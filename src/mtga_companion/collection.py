"""What cards you own.

Arena stopped reporting collection contents when PlayerInventory.GetPlayerCardsV3
was removed in August 2021 and never replaced it. Everything here is therefore a
*lower bound* derived from evidence in the log:

    draft   you picked the card, so you own at least the picked count
    played  you cast it in one of your own games, so you own at least one
    grant   Arena granted it while the tracker was running (booster, reward)

A card's presence in one of your decks is deliberately NOT evidence here.
Arena's Import feature lets you paste a decklist with cards you have not
crafted -- it flags them as missing rather than blocking the paste -- and the
resulting deck is then indistinguishable from one built by hand: you can
rename it to anything, so no name- or metadata-based heuristic on the deck
itself can tell the two apart. An earlier version of this module tried
excluding decks still carrying Arena's default "Imported Deck" name, which
works only until the player renames it -- which they always eventually do.
`deck_proven_ownership` still exists, but only as a noisy anchor set for
validating a candidate region during a memory sync (memread.py); it must never
feed into card_ownership again.

Absence from this table means "no evidence", never "you don't own it". Callers
must not treat it as a complete collection -- the MCP layer says so explicitly
in every response, because an agent that reads absence as non-ownership will
recommend cards you already have and refuse ones you could play today.

An exact collection CSV, or a memory sync (scripts/sync_collection.py), when
you have one, overrides all of the above with real data instead of inference.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Rows from an exact export beat anything we inferred.
_SOURCE_PRECEDENCE = {
    "import": 5, "memory": 4, "grant": 3, "draft": 1, "played": 0,
}

# SQL form of the same ranking, for queries that must pick ONE row per
# arena_id rather than blending numbers across sources. Blending with a plain
# MAX(quantity) is the bug this exists to avoid: two inferred sources can
# disagree on a card's quantity, so a MAX across them would silently inflate
# ownership whenever the less trustworthy one's number happens to be higher.
# The fix is to always take the number from the single highest-precedence
# source for that card, never to combine numbers across sources.
_PRECEDENCE_CASE_SQL = """
    CASE source
        WHEN 'import' THEN 5
        WHEN 'memory' THEN 4
        WHEN 'grant' THEN 3
        WHEN 'draft' THEN 1
        ELSE 0
    END
"""

# One row per arena_id: whichever source ranks highest for that card. Callers
# join against this instead of aggregating card_ownership directly.
BEST_OWNERSHIP_SQL = f"""
    SELECT arena_id, quantity, source FROM (
        SELECT arena_id, quantity, source,
               ROW_NUMBER() OVER (
                   PARTITION BY arena_id ORDER BY {_PRECEDENCE_CASE_SQL} DESC
               ) AS rn
        FROM card_ownership
    ) WHERE rn = 1
"""


def _record(
    conn: sqlite3.Connection, arena_id: int, source: str, quantity: int, confidence: str
) -> None:
    """Upsert one ownership claim, keeping the highest quantity seen."""
    conn.execute(
        "INSERT INTO card_ownership(arena_id, source, quantity, confidence, updated_at) "
        "VALUES(?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(arena_id, source) DO UPDATE SET "
        "  quantity = MAX(quantity, excluded.quantity), "
        "  confidence = excluded.confidence, "
        "  updated_at = excluded.updated_at",
        (arena_id, source, quantity, confidence),
    )


def deck_proven_ownership(conn: sqlite3.Connection) -> dict[int, int]:
    """arena_id -> max quantity CLAIMED by a card's presence in a player deck.

    NOT reliable enough to be actual ownership evidence -- see this module's
    docstring for why deck membership was retired as a card_ownership source.
    The only remaining caller is memread.py, which uses this purely as a noisy
    anchor set to help pick out the right candidate region during a memory
    sync: a wrong or unowned card here just lowers that scan's validated
    fraction, it does not get written down as fact. Do not feed this into
    card_ownership.

    Still excludes Arena's own precon/starter decks, and decks still carrying
    Arena's default "Imported Deck" name -- cheap noise reduction for the
    anchor set even though neither filter is trustworthy enough for
    card_ownership itself.
    """
    rows = conn.execute(
        "SELECT dc.arena_id, MAX(dc.quantity) AS q FROM deck_cards dc "
        "JOIN decks d ON d.deck_id = dc.deck_id "
        "WHERE d.deck_kind = 'player' AND d.name NOT LIKE 'Imported Deck%' "
        "GROUP BY dc.arena_id"
    )
    return {r["arena_id"]: r["q"] for r in rows}


def rebuild_inferred(conn: sqlite3.Connection) -> dict[str, int]:
    """Recompute the inferred ownership rows from drafts, grants and matches.

    Import rows are left untouched -- they are ground truth and this function
    must never clobber them. Deck contents are deliberately NOT a source here
    -- see this module's docstring for why, and deck_proven_ownership for the
    one place deck-derived numbers are still allowed to matter.
    """
    # 'import' and 'memory' are ground truth (an exact export, or read
    # straight from the game's own memory) and must survive a rebuild of the
    # merely-inferred sources.
    conn.execute("DELETE FROM card_ownership WHERE source NOT IN ('import', 'memory')")

    counts = {"draft": 0, "played": 0, "grant": 0}

    # Each draft pick is one physical copy; the same card picked twice is two.
    for row in conn.execute(
        "SELECT arena_id, COUNT(*) AS q FROM draft_picks "
        "WHERE arena_id IS NOT NULL GROUP BY arena_id"
    ):
        _record(conn, row["arena_id"], "draft", row["q"], "lower_bound")
        counts["draft"] += 1

    # Cards Arena granted us while the tracker was running -- booster openings,
    # rewards, draft payouts. Summed, not maxed: two boosters with the same card
    # is two copies. This is the only source that grows toward the true
    # collection rather than merely proving what a deck already revealed.
    for row in conn.execute(
        "SELECT arena_id, SUM(quantity) AS q FROM card_grants GROUP BY arena_id"
    ):
        _record(conn, row["arena_id"], "grant", row["q"], "lower_bound")
        counts["grant"] = counts.get("grant", 0) + 1

    # Casting a card in your own game proves at least one copy.
    for row in conn.execute(
        "SELECT DISTINCT arena_id FROM match_cards_seen WHERE is_self = 1"
    ):
        _record(conn, row["arena_id"], "played", 1, "lower_bound")
        counts["played"] += 1

    conn.commit()
    log.info("Rebuilt inferred ownership: %s", counts)
    return counts


def owned_quantity(conn: sqlite3.Connection, arena_id: int) -> tuple[int, str]:
    """Best-known quantity for one card and how certain it is."""
    rows = conn.execute(
        "SELECT source, quantity, confidence FROM card_ownership WHERE arena_id = ?",
        (arena_id,),
    ).fetchall()
    if not rows:
        return 0, "unknown"
    best = max(rows, key=lambda r: _SOURCE_PRECEDENCE.get(r["source"], -1))
    if best["source"] in ("import", "memory"):
        return best["quantity"], "exact"
    # Below memory/import precedence, take the largest quantity among the
    # remaining (inferred) sources -- those are independent pieces of lower-
    # bound evidence and combining them is fine; only a *trusted* source may
    # never be outvoted by a numerically larger untrusted one.
    return max(
        r["quantity"] for r in rows if r["source"] not in ("import", "memory")
    ), "lower_bound"


def get_collection(
    conn: sqlite3.Connection,
    colors: str | None = None,
    rarity: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Known-owned cards, always paired with an explicit coverage statement."""
    # Grouped by name, not arena_id: Arena gives every printing its own grpId,
    # but deck legality and "do I have a playset" are per card name, so a
    # per-printing list would both duplicate rows and understate copies held.
    sql = [
        f"WITH best AS ({BEST_OWNERSHIP_SQL})",
        "SELECT MIN(c.arena_id) AS arena_id, c.name, c.mana_cost, c.cmc,",
        "       c.colors, c.type_line, c.rarity, c.set_code, MIN(c.image_uri) AS image_uri,",
        "       SUM(best.quantity) AS quantity,",
        "       MAX(best.source IN ('import', 'memory')) AS exact",
        "FROM best JOIN cards c ON c.arena_id = best.arena_id",
    ]
    where, params = [], []
    if rarity:
        where.append("c.rarity = ?")
        params.append(rarity)
    if colors:
        for ch in colors.upper():
            if ch in "WUBRG":
                where.append("c.colors LIKE ?")
                params.append(f"%{ch}%")
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("GROUP BY c.name ORDER BY c.name LIMIT ?")
    params.append(limit)

    rows = [dict(r) for r in conn.execute("\n".join(sql), params)]
    has_exact = conn.execute(
        "SELECT 1 FROM card_ownership WHERE source IN ('import', 'memory') LIMIT 1"
    ).fetchone()

    has_memory = conn.execute(
        "SELECT MAX(updated_at) FROM card_ownership WHERE source = 'memory'"
    ).fetchone()[0]

    if has_memory:
        caveat = (
            f"Read from MTG Arena's own memory (last synced {has_memory}). This "
            "is the real collection, not an inference -- but it is a snapshot: "
            "cards obtained after that sync won't show up until the next one."
        )
    elif has_exact:
        caveat = "Exact collection imported; this list is complete."
    else:
        caveat = (
            "MTG Arena stopped reporting collection contents in 2021. This "
            "list is a LOWER BOUND built from cards seen in your decks, draft "
            "picks and games. A card missing here may still be owned - treat "
            "absence as 'unknown', not as 'not owned'. Use import_collection "
            "with a CSV export, or scripts/sync_collection.py, for an exact list."
        )

    return {
        "cards": rows,
        "count": len(rows),
        "completeness": "exact" if has_exact else "lower_bound",
        "caveat": caveat,
    }


def _resolve_name(conn: sqlite3.Connection, name: str, set_code: str | None) -> int | None:
    """Map a card name (optionally disambiguated by set) to an Arena id."""
    name = name.strip()
    if set_code:
        row = conn.execute(
            "SELECT arena_id FROM cards WHERE name = ? AND set_code = ? COLLATE NOCASE",
            (name, set_code),
        ).fetchone()
        if row:
            return row["arena_id"]
    row = conn.execute(
        "SELECT arena_id FROM cards WHERE name = ? ORDER BY arena_id LIMIT 1", (name,)
    ).fetchone()
    return row["arena_id"] if row else None


# Column names vary between exporters; match case-insensitively on these.
_NAME_KEYS = ("name", "card", "card name", "cardname")
_QTY_KEYS = ("quantity", "qty", "count", "amount", "owned")
_SET_KEYS = ("set", "set code", "setcode", "expansion", "edition")


def _pick(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    lowered = {(k or "").strip().lower(): v for k, v in row.items()}
    for key in keys:
        if lowered.get(key):
            return lowered[key]
    return None


def import_collection(conn: sqlite3.Connection, path: str | Path) -> dict[str, Any]:
    """Load an exact collection CSV, replacing any previous import.

    Accepts the common shapes exporters emit -- a name column plus a quantity
    column, optionally a set column for disambiguation. Cards whose names do not
    resolve are reported rather than silently dropped, since a partial import
    that looked successful would be worse than a loud failure.
    """
    src = Path(path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"No such collection file: {src}")

    with src.open(newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(fh, dialect=dialect))

    if not rows:
        raise ValueError(f"{src} contains no rows")
    if _pick(rows[0], _NAME_KEYS) is None:
        raise ValueError(
            f"{src} has no recognisable card-name column "
            f"(looked for {', '.join(_NAME_KEYS)}); found: {list(rows[0])}"
        )

    conn.execute("DELETE FROM card_ownership WHERE source = 'import'")
    imported, unresolved = 0, []
    for row in rows:
        name = _pick(row, _NAME_KEYS)
        if not name:
            continue
        try:
            qty = int(float(_pick(row, _QTY_KEYS) or 1))
        except ValueError:
            qty = 1
        if qty <= 0:
            continue
        arena_id = _resolve_name(conn, name, _pick(row, _SET_KEYS))
        if arena_id is None:
            unresolved.append(name)
            continue
        _record(conn, arena_id, "import", qty, "exact")
        imported += 1
    conn.commit()

    log.info("Imported %d cards (%d unresolved) from %s", imported, len(unresolved), src)
    return {
        "imported": imported,
        "unresolved_count": len(unresolved),
        "unresolved_sample": unresolved[:20],
        "source": str(src),
    }

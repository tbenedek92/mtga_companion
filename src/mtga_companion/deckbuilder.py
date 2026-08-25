"""Deck construction support for an AI agent.

The model itself runs elsewhere -- an agent connected over MCP does the
creative work. This module supplies the parts that must be *correct* rather
than creative: which cards are legal and owned, what a suggestion would cost in
wildcards, whether a proposed list is actually legal, and how to write it in the
format Arena's importer accepts.

One rule shapes most of the code here: **Magic's four-copy limit is per card
name, not per printing.** Arena assigns a distinct grpId to every printing, so a
deck holding two printings of Shock holds four Shocks, not two different cards.
Counting by arena_id would silently allow eight.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

log = logging.getLogger(__name__)

# Formats Arena actually offers, mapped to the Scryfall legality key.
FORMATS = {
    "standard": "standard",
    "alchemy": "alchemy",
    "historic": "historic",
    "timeless": "timeless",
    "pioneer": "pioneer",
    "brawl": "brawl",
    "standardbrawl": "standardbrawl",
    "historicbrawl": "brawl",
}

# Singleton formats: one copy of everything except basic lands.
SINGLETON_FORMATS = {"brawl", "standardbrawl", "historicbrawl"}

# Arena's deck-size rules. Brawl is 100 including the commander.
MIN_DECK_SIZE = {"brawl": 100, "standardbrawl": 60, "historicbrawl": 100}
DEFAULT_MIN_DECK_SIZE = 60

BASIC_LANDS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}

_WILDCARD_COLUMN = {
    "common": "wc_common",
    "uncommon": "wc_uncommon",
    "rare": "wc_rare",
    "mythic": "wc_mythic",
}


def _legality_key(fmt: str) -> str:
    key = FORMATS.get((fmt or "").strip().lower())
    if key is None:
        raise ValueError(
            f"Unknown format {fmt!r}. Known formats: {', '.join(sorted(FORMATS))}"
        )
    return key


def owned_by_name(conn: sqlite3.Connection) -> dict[str, int]:
    """Best-known owned quantity per card name.

    Ownership is recorded per arena_id, but the four-copy rule and everything a
    deck builder cares about is per name, so printings are summed here.

    Each arena_id's own quantity comes from its single highest-precedence
    source (see collection.BEST_OWNERSHIP_SQL), never a MAX blended across
    sources: an Arena-generated "preview" deck (e.g. an Alchemy upgrade
    suggestion) can list more copies of a card than the player has actually
    crafted, so a naive MAX would let that number silently outrank a real
    memory read or CSV import.
    """
    from .collection import BEST_OWNERSHIP_SQL

    rows = conn.execute(
        f"""
        WITH best AS ({BEST_OWNERSHIP_SQL})
        SELECT c.name AS name, SUM(best.quantity) AS quantity
        FROM best JOIN cards c ON c.arena_id = best.arena_id
        GROUP BY c.name
        """
    )
    return {r["name"]: r["quantity"] for r in rows}


def candidate_pool(
    conn: sqlite3.Connection,
    fmt: str = "standard",
    colors: str | None = None,
    owned_only: bool = True,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Cards legal in `fmt` that the player can build with.

    With `owned_only` the pool is what they can sleeve up today. Without it the
    pool widens to every legal card, and each entry still reports `owned` so an
    agent can weigh an upgrade against its wildcard cost.
    """
    key = _legality_key(fmt)
    sql = [
        "SELECT MIN(c.arena_id) AS arena_id, c.name, c.mana_cost, c.cmc,",
        "       c.colors, c.color_identity, c.type_line, c.oracle_text,",
        "       c.rarity, c.set_code, c.edhrec_rank",
        "FROM cards c",
        f"WHERE json_extract(c.legalities, '$.{key}') = 'legal'",
    ]
    params: list[Any] = []
    if owned_only:
        sql.append(
            "AND c.name IN (SELECT c2.name FROM card_ownership o "
            "JOIN cards c2 ON c2.arena_id = o.arena_id)"
        )
    if colors:
        # Colour identity, not colour: a card is castable in a deck whose
        # identity covers it, which is what matters for deck legality.
        wanted = {ch for ch in colors.upper() if ch in "WUBRG"}
        if wanted:
            forbidden = set("WUBRG") - wanted
            for ch in forbidden:
                sql.append("AND c.color_identity NOT LIKE ?")
                params.append(f"%{ch}%")
    sql.append("GROUP BY c.name ORDER BY c.cmc, c.name LIMIT ?")
    params.append(limit)

    owned = owned_by_name(conn)
    pool = []
    for row in conn.execute("\n".join(sql), params):
        entry = dict(row)
        entry["owned"] = owned.get(entry["name"], 0)
        pool.append(entry)
    return pool


def wildcard_cost(
    conn: sqlite3.Connection, cards: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """What a proposed list would cost in wildcards, against real stock.

    `cards` is [{"name": str, "quantity": int}, ...]. Copies already owned are
    free; the shortfall is charged at the card's rarity. Basic lands are always
    free in Arena and are never charged.
    """
    owned = owned_by_name(conn)
    needed: dict[str, int] = defaultdict(int)
    missing: list[dict[str, Any]] = []

    for card in cards:
        name = card.get("name")
        want = int(card.get("quantity") or 0)
        if not name or want <= 0 or name in BASIC_LANDS:
            continue
        short = want - owned.get(name, 0)
        if short <= 0:
            continue
        row = conn.execute(
            "SELECT rarity FROM cards WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        rarity = (row["rarity"] if row else None) or "unknown"
        needed[rarity] += short
        missing.append(
            {"name": name, "need": short, "owned": owned.get(name, 0), "rarity": rarity}
        )

    stock_row = conn.execute(
        "SELECT wc_common, wc_uncommon, wc_rare, wc_mythic FROM inventory "
        "ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    stock = {
        rarity: (stock_row[col] if stock_row else None)
        for rarity, col in _WILDCARD_COLUMN.items()
    }

    shortfall = {
        rarity: count - (stock.get(rarity) or 0)
        for rarity, count in needed.items()
        if stock.get(rarity) is not None and count > (stock.get(rarity) or 0)
    }

    return {
        "wildcards_needed": dict(needed),
        "wildcards_available": stock,
        "shortfall": shortfall,
        "craftable_now": not shortfall,
        "missing_cards": sorted(missing, key=lambda m: -m["need"]),
    }


def check_wildcard_budget(
    cost: dict[str, Any], budget: dict[str, int] | None
) -> dict[str, Any]:
    """Compare a wildcard cost against a self-imposed spending limit.

    Distinct from `wildcard_cost`'s `craftable_now`, which checks against
    actual wildcard STOCK: this checks against how many the player is willing
    to SPEND on this one deck -- e.g. "at most 1 rare wildcard" even if they
    own five. Pass the `wildcards_needed` dict from `wildcard_cost`.
    """
    if not budget:
        return {"budget_set": False, "within_budget": True, "over_budget": {}}
    needed = cost.get("wildcards_needed", {})
    over = {
        rarity: needed[rarity] - budget.get(rarity, 0)
        for rarity in needed
        if needed[rarity] > budget.get(rarity, 0)
    }
    return {
        "budget_set": True, "budget": dict(budget),
        "within_budget": not over, "over_budget": over,
    }


def validate_deck(
    conn: sqlite3.Connection,
    cards: Iterable[dict[str, Any]],
    fmt: str = "standard",
) -> dict[str, Any]:
    """Check a proposed decklist for size, copy limits and legality.

    Returns every problem found rather than the first, so an agent can fix a
    list in one pass instead of round-tripping per error.
    """
    key = _legality_key(fmt)
    normalised = (fmt or "").strip().lower()
    singleton = normalised in SINGLETON_FORMATS
    max_copies = 1 if singleton else 4
    min_size = MIN_DECK_SIZE.get(normalised, DEFAULT_MIN_DECK_SIZE)

    totals: dict[str, int] = defaultdict(int)
    board_totals: dict[str, int] = defaultdict(int)
    for card in cards:
        name = card.get("name")
        qty = int(card.get("quantity") or 0)
        if not name or qty <= 0:
            continue
        totals[name] += qty
        board_totals[card.get("board", "main")] += qty

    errors: list[str] = []
    warnings: list[str] = []
    unknown: list[str] = []
    illegal: list[str] = []

    for name, qty in totals.items():
        row = conn.execute(
            "SELECT name, legalities FROM cards WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        if row is None:
            unknown.append(name)
            continue
        if name in BASIC_LANDS:
            continue  # unlimited copies, always legal
        if qty > max_copies:
            errors.append(f"{name}: {qty} copies, limit is {max_copies}")
        legalities = json.loads(row["legalities"] or "{}")
        if legalities and legalities.get(key) != "legal":
            illegal.append(name)

    main = board_totals.get("main", 0)
    if main < min_size:
        errors.append(f"Mainboard has {main} cards, minimum for {fmt} is {min_size}")
    side = board_totals.get("sideboard", 0)
    if side > 15:
        errors.append(f"Sideboard has {side} cards, maximum is 15")

    if unknown:
        errors.append(
            f"Not found in the card database (check spelling, or not on Arena): "
            f"{', '.join(sorted(unknown)[:10])}"
        )
    if illegal:
        errors.append(f"Not legal in {fmt}: {', '.join(sorted(illegal)[:10])}")

    lands = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE name IN (%s) AND type_line LIKE '%%Land%%'"
        % ",".join("?" * len(totals)),
        list(totals),
    ).fetchone()[0] if totals else 0
    if main >= min_size and lands == 0:
        warnings.append("No lands in the mainboard")

    return {
        "valid": not errors,
        "format": fmt,
        "mainboard_size": main,
        "sideboard_size": side,
        "distinct_cards": len(totals),
        "errors": errors,
        "warnings": warnings,
    }


def to_arena_export(
    conn: sqlite3.Connection, cards: Iterable[dict[str, Any]]
) -> str:
    """Render a decklist in the form Arena's deck importer accepts.

        Deck
        4 Lightning Strike (DMU) 137

    Cards whose printing cannot be resolved are emitted without the set suffix,
    which Arena still accepts by name.
    """
    sections: dict[str, list[str]] = {"main": [], "sideboard": [], "commander": []}
    for card in cards:
        name = card.get("name")
        qty = int(card.get("quantity") or 0)
        if not name or qty <= 0:
            continue
        row = None
        if name not in BASIC_LANDS:
            # Basic lands are emitted bare: Arena accepts "20 Mountain", and the
            # arbitrary printing we would otherwise pick can be a promo set
            # (e.g. PANA) that its importer does not recognise.
            row = conn.execute(
                "SELECT set_code, collector_number FROM cards "
                "WHERE name = ? AND set_code IS NOT NULL ORDER BY arena_id LIMIT 1",
                (name,),
            ).fetchone()
        if row and row["set_code"] and row["collector_number"]:
            line = f"{qty} {name} ({row['set_code'].upper()}) {row['collector_number']}"
        else:
            line = f"{qty} {name}"
        sections.setdefault(card.get("board", "main"), []).append(line)

    out: list[str] = []
    if sections.get("commander"):
        out += ["Commander", *sections["commander"], ""]
    out += ["Deck", *sections.get("main", [])]
    if sections.get("sideboard"):
        out += ["", "Sideboard", *sections["sideboard"]]
    return "\n".join(out)


_SECTION_HEADERS = {
    "deck": "main", "mainboard": "main", "main": "main", "maindeck": "main",
    "sideboard": "sideboard",
    "commander": "commander", "command zone": "commander",
}
# "4 Lightning Bolt (STA) 42" or a bare "4 Lightning Bolt" -- Arena accepts
# both, and this mirrors what to_arena_export() emits (bare form for basics).
_CARD_LINE = re.compile(
    r"^(\d+)\s+(.+?)(?:\s+\(([A-Za-z0-9]{2,5})\)\s+(\S+))?$"
)


def parse_arena_export(text: str) -> list[dict[str, Any]]:
    """Parse Arena-importable decklist text into [{name, quantity, board}, ...].

    The inverse of to_arena_export(). Best-effort: section headers (Deck,
    Sideboard, Commander), blank lines and // comments are recognised; a line
    that doesn't parse as "<qty> <name>" is skipped rather than raising, since
    decklists pasted from other sites carry stray headers ("About", deck name)
    this format doesn't define. Card names aren't resolved to arena_ids here --
    that happens downstream in validate_deck / wildcard_cost / save_suggestion,
    each of which already looks a card up by name.
    """
    board = "main"
    cards: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        header = line.rstrip(":").lower()
        if header in _SECTION_HEADERS:
            board = _SECTION_HEADERS[header]
            continue
        match = _CARD_LINE.match(line)
        if not match:
            continue
        qty = int(match.group(1))
        name = match.group(2).strip()
        if qty <= 0 or not name:
            continue
        cards.append({"name": name, "quantity": qty, "board": board})
    return cards


def deck_to_cards(conn: sqlite3.Connection, deck_id: str) -> list[dict[str, Any]]:
    """A stored deck as the {name, quantity, board} shape this module expects."""
    rows = conn.execute(
        "SELECT c.name, SUM(dc.quantity) AS quantity, dc.board "
        "FROM deck_cards dc JOIN cards c ON c.arena_id = dc.arena_id "
        "WHERE dc.deck_id = ? GROUP BY dc.board, c.name",
        (deck_id,),
    )
    return [dict(r) for r in rows]


def save_suggestion(
    conn: sqlite3.Connection,
    name: str,
    fmt: str,
    cards: list[dict[str, Any]],
    rationale: str | None = None,
    based_on_deck: str | None = None,
    wildcard_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Persist an agent's suggestion so the GUI can render it.

    `wildcard_budget`, if given, is re-checked and stored alongside the
    validation so the GUI can show "within budget" without the caller having
    to have called validate_deck first -- the two paths (validate then save,
    or just save) end up with the same stored record either way.
    """
    validation = validate_deck(conn, cards, fmt)
    cost = wildcard_cost(conn, cards)
    validation["wildcard_budget_check"] = check_wildcard_budget(cost, wildcard_budget)
    owned = owned_by_name(conn)

    cur = conn.execute(
        "INSERT INTO suggested_decks(created_at, name, format, rationale, "
        "based_on_deck, wildcard_cost, validation) "
        "VALUES(datetime('now'), ?, ?, ?, ?, ?, ?)",
        (name, fmt, rationale, based_on_deck,
         json.dumps(cost), json.dumps(validation)),
    )
    suggestion_id = cur.lastrowid

    for card in cards:
        card_name = card.get("name")
        qty = int(card.get("quantity") or 0)
        if not card_name or qty <= 0:
            continue
        row = conn.execute(
            "SELECT arena_id FROM cards WHERE name = ? ORDER BY arena_id LIMIT 1",
            (card_name,),
        ).fetchone()
        conn.execute(
            "INSERT INTO suggested_deck_cards(suggestion_id, arena_id, name, "
            "quantity, board, owned) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(suggestion_id, name, board) DO UPDATE SET "
            "quantity = excluded.quantity",
            (suggestion_id, row["arena_id"] if row else None, card_name, qty,
             card.get("board", "main"), owned.get(card_name, 0)),
        )
    conn.commit()

    log.info("Saved suggestion %s (%s)", suggestion_id, name)
    return {
        "suggestion_id": suggestion_id,
        "name": name,
        "format": fmt,
        "validation": validation,
        "wildcard_cost": cost,
        "arena_export": to_arena_export(conn, cards),
    }


def import_deck(
    conn: sqlite3.Connection,
    text: str,
    name: str,
    fmt: str = "standard",
    rationale: str | None = None,
    based_on_deck: str | None = None,
) -> dict[str, Any]:
    """Parse Arena-format decklist text and save it like an agent suggestion.

    This is the second way a deck gets into the app: an agent that built a
    deck outside the MCP tool loop (or the player, pasting a list they found
    elsewhere) can hand over the text directly instead of a structured
    `cards` list. Reuses save_suggestion, so imported decks show up in the
    same Deck Builder view as agent-generated ones, with the same validation,
    wildcard cost, and Arena export.
    """
    cards = parse_arena_export(text)
    if not cards:
        raise ValueError(
            "Could not parse any cards from that text. Expected lines like "
            "'4 Lightning Bolt (STA) 42' or '4 Lightning Bolt', optionally "
            "under 'Deck' / 'Sideboard' / 'Commander' headers."
        )
    return save_suggestion(
        conn, name, fmt, cards, rationale or "Imported decklist", based_on_deck
    )


def list_suggestions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT suggestion_id, created_at, name, format, rationale, based_on_deck "
        "FROM suggested_decks ORDER BY created_at DESC, suggestion_id DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def get_suggestion(conn: sqlite3.Connection, suggestion_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM suggested_decks WHERE suggestion_id = ?", (suggestion_id,)
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["wildcard_cost"] = json.loads(out.get("wildcard_cost") or "{}")
    out["validation"] = json.loads(out.get("validation") or "{}")
    cards = conn.execute(
        "SELECT s.name, s.quantity, s.board, s.owned, s.arena_id, "
        "       c.mana_cost, c.cmc, c.type_line, c.rarity, c.image_uri "
        "FROM suggested_deck_cards s LEFT JOIN cards c ON c.arena_id = s.arena_id "
        "WHERE s.suggestion_id = ? ORDER BY s.board, c.cmc, s.name",
        (suggestion_id,),
    )
    out["cards"] = [dict(r) for r in cards]
    out["arena_export"] = to_arena_export(conn, out["cards"])
    return out

"""Read-side queries shared by the MCP tools and the CLI.

Kept separate from the MCP layer so they can be tested without standing up a
server.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

_CARD_FIELDS = (
    "c.arena_id, c.name, c.mana_cost, c.cmc, c.colors, c.type_line, "
    "c.oracle_text, c.power, c.toughness, c.rarity, c.set_code, c.image_uri"
)


def list_decks(
    conn: sqlite3.Connection, include_precon: bool = False
) -> list[dict[str, Any]]:
    """Decks, player-built ones first.

    Arena includes roughly 108 starter and preconstructed decks in every
    StartHook payload. Returning them by default buries the dozen decks the
    player actually built, so they are excluded unless asked for.
    """
    rows = conn.execute(
        """
        SELECT d.deck_id, d.name, d.format, d.colors, d.last_updated,
               d.last_played, d.is_valid, d.deck_kind, d.is_favorite,
               d.description, d.playstyle,
               (SELECT COALESCE(SUM(quantity), 0) FROM deck_cards dc
                 WHERE dc.deck_id = d.deck_id AND dc.board = 'main') AS mainboard_size,
               (SELECT COALESCE(SUM(quantity), 0) FROM deck_cards dc
                 WHERE dc.deck_id = d.deck_id AND dc.board = 'sideboard') AS sideboard_size
        FROM decks d
        WHERE ? OR d.deck_kind = 'player'
        ORDER BY (d.deck_kind = 'player') DESC,
                 COALESCE(d.last_played, d.last_updated) DESC, d.name
        """,
        (1 if include_precon else 0,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_deck(conn: sqlite3.Connection, deck_id: str) -> dict[str, Any] | None:
    deck = conn.execute(
        "SELECT deck_id, name, format, colors, last_updated, last_played, is_valid, "
        "description, playstyle, comments, recommendations, notes_updated_at "
        "FROM decks WHERE deck_id = ?",
        (deck_id,),
    ).fetchone()
    if deck is None:
        return None

    # Summed per card *name*, not per arena_id. A deck can hold two printings
    # of the same card (Arena gives each its own grpId), which would otherwise
    # show up as "1x Shock" and "3x Shock" -- two entries an agent reads as two
    # different cards rather than a playset.
    cards = conn.execute(
        f"""
        SELECT dc.board, SUM(dc.quantity) AS quantity,
               MIN(c.arena_id) AS arena_id, c.name, c.mana_cost, c.cmc,
               c.colors, c.type_line, c.oracle_text, c.power, c.toughness,
               c.rarity, c.set_code,
               c.image_uri, GROUP_CONCAT(dc.arena_id) AS printings
        FROM deck_cards dc
        LEFT JOIN cards c ON c.arena_id = dc.arena_id
        WHERE dc.deck_id = ?
        GROUP BY dc.board, COALESCE(c.name, dc.arena_id)
        ORDER BY dc.board, c.cmc, c.name
        """,
        (deck_id,),
    ).fetchall()

    boards: dict[str, list[dict[str, Any]]] = {}
    for row in cards:
        entry = dict(row)
        printings = (entry.pop("printings") or "").split(",")
        # Only surface the extra grpIds when there actually are several.
        if len(printings) > 1:
            entry["printings"] = [int(x) for x in printings if x]
        boards.setdefault(entry.pop("board"), []).append(entry)

    result = dict(deck)
    result["mainboard"] = boards.get("main", [])
    result["sideboard"] = boards.get("sideboard", [])
    for extra, items in boards.items():
        if extra not in ("main", "sideboard"):
            result[extra] = items
    return result


_NOTE_FIELDS = ("description", "playstyle", "comments", "recommendations")


def update_deck_notes(
    conn: sqlite3.Connection,
    deck_id: str,
    description: str | None = None,
    playstyle: str | None = None,
    comments: str | None = None,
    recommendations: str | None = None,
) -> dict[str, Any]:
    """Set player- or agent-written annotations on one of the player's decks.

    Arena has no concept of these fields, so they live entirely in our own
    database and are never touched by log ingestion -- re-syncing decks from
    the log only ever updates name/format/cards, never these columns.

    Partial update: a field left as None is unchanged, not cleared. To erase
    a field, pass an empty string explicitly.
    """
    updates = {
        field: value
        for field, value in zip(
            _NOTE_FIELDS, (description, playstyle, comments, recommendations)
        )
        if value is not None
    }
    if not updates:
        raise ValueError(
            "Provide at least one of description, playstyle, comments, "
            "recommendations to update."
        )
    if conn.execute(
        "SELECT 1 FROM decks WHERE deck_id = ?", (deck_id,)
    ).fetchone() is None:
        raise ValueError(f"No deck with id {deck_id!r}.")

    set_clause = ", ".join(f"{field} = ?" for field in updates)
    conn.execute(
        f"UPDATE decks SET {set_clause}, notes_updated_at = datetime('now') "
        "WHERE deck_id = ?",
        (*updates.values(), deck_id),
    )
    conn.commit()
    return get_deck(conn, deck_id)


def search_cards(
    conn: sqlite3.Connection,
    query: str = "",
    owned_only: bool = False,
    colors: str | None = None,
    rarity: str | None = None,
    max_cmc: float | None = None,
    limit: int = 50,
    all_printings: bool = False,
) -> list[dict[str, Any]]:
    """Substring search over name and rules text, with the usual filters.

    Collapsed to one row per card name by default. Arena assigns a distinct
    grpId to every printing, so an un-collapsed search for "Sheoldred" returns
    the same card several times and pushes genuinely different matches off the
    end of the result -- wasteful for an agent and misleading for a human. Set
    all_printings to see each grpId separately.
    """
    sql = [f"SELECT {_CARD_FIELDS} FROM cards c"]
    if owned_only:
        sql.append("JOIN card_ownership o ON o.arena_id = c.arena_id")
    where, params = [], []
    if query:
        where.append("(c.name LIKE ? OR c.oracle_text LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if rarity:
        where.append("c.rarity = ?")
        params.append(rarity)
    if max_cmc is not None:
        where.append("c.cmc <= ?")
        params.append(max_cmc)
    if colors:
        for ch in colors.upper():
            if ch in "WUBRG":
                where.append("c.colors LIKE ?")
                params.append(f"%{ch}%")
    if where:
        sql.append("WHERE " + " AND ".join(where))
    if all_printings:
        sql.append("GROUP BY c.arena_id")
    else:
        # Prefer the printing that actually carries oracle text as the
        # representative row; a bare fallback row would be the less useful pick.
        sql.append("GROUP BY c.name HAVING c.oracle_text IS NOT NULL "
                   "OR MAX(c.oracle_text IS NOT NULL) = 0")
    sql.append("ORDER BY c.name LIMIT ?")
    params.append(limit)
    return [dict(r) for r in conn.execute("\n".join(sql), params)]


def get_inventory(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT captured_at, gold, gems, wc_common, wc_uncommon, wc_rare, "
        "wc_mythic, vault_progress FROM inventory ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_rank(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ranks ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out.pop("raw", None)
    return out


def get_match_history(
    conn: sqlite3.Connection, limit: int = 20, deck_id: str | None = None
) -> list[dict[str, Any]]:
    sql = [
        "SELECT m.match_id, m.started_at, m.ended_at, m.event_name, m.format, m.deck_id,",
        "       d.name AS deck_name, m.opponent_name, m.opponent_colors,",
        "       m.result, m.games_won, m.games_lost, m.on_play",
        "FROM matches m LEFT JOIN decks d ON d.deck_id = m.deck_id",
    ]
    params: list[Any] = []
    if deck_id:
        sql.append("WHERE m.deck_id = ?")
        params.append(deck_id)
    sql.append("ORDER BY m.started_at DESC LIMIT ?")
    params.append(limit)
    return [dict(r) for r in conn.execute("\n".join(sql), params)]


def get_match_plays(conn: sqlite3.Connection, match_id: str) -> list[dict[str, Any]]:
    """Cards cast or played as a land during one match, in order, self vs
    opponent. Empty for a match recorded before match_plays existed -- see
    parse._extract_gre_event's docstring for what this table can and can't
    tell you (no counterspells, no life totals). For combat, see
    get_match_combat."""
    rows = conn.execute(
        "SELECT mp.seq, mp.game_number, mp.is_self, mp.action, mp.arena_id, "
        "       c.name, c.mana_cost, c.type_line "
        "FROM match_plays mp LEFT JOIN cards c ON c.arena_id = mp.arena_id "
        "WHERE mp.match_id = ? ORDER BY mp.seq",
        (match_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_match_combat(conn: sqlite3.Connection, match_id: str) -> list[dict[str, Any]]:
    """Attacks and blocks during one match, in turn order, self vs opponent.

    Not merged into get_match_plays' timeline: plays are ordered by a GRE
    annotation id, combat by turn number and the enclosing message's own
    gameStateId -- close cousins, not the same numbering, so interleaving
    them exactly isn't attempted. A block's target_arena_id is the attacker
    it blocked; an attack's is what it attacked, if not the opponent
    directly (target_is_player tells you which). Either can resolve to
    nothing for a token creature -- tokens aren't in the card database.
    """
    rows = conn.execute(
        "SELECT mc.game_number, mc.turn_number, mc.is_self, mc.action, "
        "       mc.arena_id, c.name, "
        "       mc.target_arena_id, t.name AS target_name, mc.target_is_player "
        "FROM match_combat mc "
        "LEFT JOIN cards c ON c.arena_id = mc.arena_id "
        "LEFT JOIN cards t ON t.arena_id = mc.target_arena_id "
        "WHERE mc.match_id = ? ORDER BY mc.turn_number, mc.seq",
        (match_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_deck_stats(conn: sqlite3.Connection, deck_id: str) -> dict[str, Any] | None:
    deck = get_deck(conn, deck_id)
    if deck is None:
        return None

    record = conn.execute(
        "SELECT COUNT(*) AS played,"
        " SUM(result = 'win') AS wins,"
        " SUM(result = 'loss') AS losses,"
        " SUM(result = 'draw') AS draws"
        " FROM matches WHERE deck_id = ?",
        (deck_id,),
    ).fetchone()

    played = record["played"] or 0
    wins = record["wins"] or 0
    losses = record["losses"] or 0

    curve: Counter[int] = Counter()
    colors: Counter[str] = Counter()
    types: Counter[str] = Counter()
    lands = 0
    for card in deck["mainboard"]:
        qty = card["quantity"]
        type_line = card.get("type_line") or ""
        if "Land" in type_line:
            lands += qty
        else:
            # X spells and missing data both bucket at 0 rather than vanishing.
            curve[int(card["cmc"] or 0)] += qty
        for ch in (card.get("colors") or "").split(","):
            if ch:
                colors[ch] += qty
        primary = type_line.split("—")[0].strip().split()
        if primary:
            types[primary[-1]] += qty

    return {
        "deck_id": deck_id,
        "name": deck["name"],
        "format": deck["format"],
        "matches_played": played,
        "wins": wins,
        "losses": losses,
        "draws": record["draws"] or 0,
        "win_rate": round(wins / played, 3) if played else None,
        "mainboard_size": sum(c["quantity"] for c in deck["mainboard"]),
        "lands": lands,
        "mana_curve": {str(k): curve[k] for k in sorted(curve)},
        "color_distribution": dict(colors.most_common()),
        "type_distribution": dict(types.most_common()),
    }


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Health summary: what data we actually hold, and why it might be empty."""
    from . import paths

    def count(table: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    detailed = paths.detailed_logs_enabled()
    counts = {
        "cards": count("cards"),
        "decks": count("decks"),
        "matches": count("matches"),
        "draft_picks": count("draft_picks"),
        "owned_cards": conn.execute(
            "SELECT COUNT(DISTINCT arena_id) FROM card_ownership"
        ).fetchone()[0],
        "unparsed_events": count("raw_events"),
    }
    out: dict[str, Any] = {
        "detailed_logs_enabled": detailed,
        "log_path": str(paths.PLAYER_LOG),
        "log_exists": paths.PLAYER_LOG.exists(),
        **counts,
    }
    if detailed is False:
        out["action_required"] = (
            "MTG Arena is not writing game data. Enable Settings -> Account -> "
            "'Detailed Logs (Plugin Support)' and restart Arena; decks, matches "
            "and collection cannot be read until you do."
        )

    return out

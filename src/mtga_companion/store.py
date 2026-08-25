"""SQLite schema and connection handling for our own database.

Everything Arena gives us is keyed by its own integer ids (grpId for cards,
deck ids, match ids), so every write is an upsert on those. Re-reading the same
log is therefore idempotent, which matters because we backfill Player-prev.log
on every startup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import paths

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Card reference data. `source` records where the row came from so callers can
-- tell full Scryfall oracle data from the thinner local-Arena fallback.
CREATE TABLE IF NOT EXISTS cards (
    arena_id       INTEGER PRIMARY KEY,
    scryfall_id    TEXT,
    oracle_id      TEXT,
    name           TEXT NOT NULL,
    mana_cost      TEXT,
    cmc            REAL,
    colors         TEXT,
    color_identity TEXT,
    type_line      TEXT,
    oracle_text    TEXT,
    power          TEXT,
    toughness      TEXT,
    rarity         TEXT,
    set_code       TEXT,
    collector_number TEXT,
    legalities     TEXT,
    edhrec_rank    INTEGER,
    image_uri      TEXT,
    source         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_set ON cards(set_code);

-- Decks as reported by Arena's StartHook/DeckSummaries payloads.
CREATE TABLE IF NOT EXISTS decks (
    deck_id      TEXT PRIMARY KEY,
    name         TEXT,
    format       TEXT,
    colors       TEXT,
    last_updated TEXT,
    last_played  TEXT,
    is_valid     INTEGER,
    -- 'player' for decks you built or edited, 'precon' for the ~100 starter
    -- and preconstructed decks Arena ships in every StartHook payload.
    deck_kind    TEXT,
    is_favorite  INTEGER,
    raw          TEXT,
    -- Player- or agent-written annotations. Arena has no concept of these, so
    -- they are never touched by log ingestion (_extract_decks only updates
    -- the columns above) and survive every resync untouched.
    description     TEXT,   -- what the deck's plan/concept is
    playstyle       TEXT,   -- e.g. "Aggro", "Midrange", "Control", or free text
    comments        TEXT,   -- free-form notes
    recommendations TEXT,   -- what to change/improve, often agent-written
    notes_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS deck_cards (
    deck_id     TEXT NOT NULL REFERENCES decks(deck_id) ON DELETE CASCADE,
    arena_id    INTEGER NOT NULL,
    quantity    INTEGER NOT NULL,
    board       TEXT NOT NULL DEFAULT 'main',   -- main | sideboard | commander
    PRIMARY KEY (deck_id, arena_id, board)
);

CREATE TABLE IF NOT EXISTS matches (
    match_id        TEXT PRIMARY KEY,
    started_at      TEXT,
    ended_at        TEXT,
    event_name      TEXT,
    deck_id         TEXT,
    opponent_name   TEXT,
    opponent_colors TEXT,
    result          TEXT,          -- win | loss | draw
    games_won       INTEGER,
    games_lost      INTEGER,
    on_play         INTEGER,
    raw             TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_deck ON matches(deck_id);
CREATE INDEX IF NOT EXISTS idx_matches_started ON matches(started_at);

CREATE TABLE IF NOT EXISTS match_games (
    match_id   TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    game_number INTEGER NOT NULL,
    result     TEXT,
    on_play    INTEGER,
    turns      INTEGER,
    PRIMARY KEY (match_id, game_number)
);

-- Cards we saw the local player cast/play, per match. Feeds ownership inference.
CREATE TABLE IF NOT EXISTS match_cards_seen (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    arena_id INTEGER NOT NULL,
    is_self  INTEGER NOT NULL,
    PRIMARY KEY (match_id, arena_id, is_self)
);

CREATE TABLE IF NOT EXISTS draft_picks (
    draft_id    TEXT NOT NULL,
    pack_number INTEGER NOT NULL,
    pick_number INTEGER NOT NULL,
    arena_id    INTEGER,
    pack_cards  TEXT,
    PRIMARY KEY (draft_id, pack_number, pick_number)
);

-- Single-row-per-snapshot wallet/wildcard state from StartHook InventoryInfo.
CREATE TABLE IF NOT EXISTS inventory (
    captured_at    TEXT PRIMARY KEY,
    gold           INTEGER,
    gems           INTEGER,
    wc_common      INTEGER,
    wc_uncommon    INTEGER,
    wc_rare        INTEGER,
    wc_mythic      INTEGER,
    vault_progress REAL,
    raw            TEXT
);

CREATE TABLE IF NOT EXISTS ranks (
    captured_at  TEXT PRIMARY KEY,
    constructed_class TEXT,
    constructed_level INTEGER,
    constructed_step  INTEGER,
    limited_class     TEXT,
    limited_level     INTEGER,
    limited_step      INTEGER,
    constructed_won   INTEGER,
    constructed_lost  INTEGER,
    limited_won       INTEGER,
    limited_lost      INTEGER,
    raw          TEXT
);

-- Ownership is NOT in the log any more (GetPlayerCardsV3 was removed in 2021).
-- These rows are a derived lower bound unless source='import'.
CREATE TABLE IF NOT EXISTS card_ownership (
    arena_id   INTEGER NOT NULL,
    source     TEXT NOT NULL,     -- deck | draft | played | import
    quantity   INTEGER NOT NULL,
    confidence TEXT NOT NULL,     -- lower_bound | exact
    updated_at TEXT,
    PRIMARY KEY (arena_id, source)
);

-- Lines we recognised as game data but could not parse. The log format is
-- undocumented and shifts with patches; this makes drift diagnosable without
-- replaying a whole session.
CREATE TABLE IF NOT EXISTS raw_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seen_at    TEXT,
    label      TEXT,
    reason     TEXT,
    payload    TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_events_label ON raw_events(label);

-- Byte offset per log file so restarts resume instead of re-reading.
CREATE TABLE IF NOT EXISTS ingest_state (
    path       TEXT PRIMARY KEY,
    offset     INTEGER NOT NULL,
    size       INTEGER NOT NULL,
    updated_at TEXT
);

-- Cards granted to the player over time: booster openings, draft rewards,
-- quest and daily rewards. Arena has not reported collection *contents* since
-- 2021, but it does report inventory *changes* as they happen -- so a tracker
-- that is running accumulates an increasingly accurate collection. This is an
-- append-only event log; quantities are summed, not maxed, because opening two
-- boosters containing the same card grants two copies.
CREATE TABLE IF NOT EXISTS card_grants (
    grant_key  TEXT PRIMARY KEY,   -- dedupes replayed log lines
    seen_at    TEXT,
    arena_id   INTEGER NOT NULL,
    quantity   INTEGER NOT NULL,
    context    TEXT
);
CREATE INDEX IF NOT EXISTS idx_grants_card ON card_grants(arena_id);

-- Decks produced by an AI agent through the MCP tools, kept so the GUI can
-- display a suggestion the agent generated in a separate session.
CREATE TABLE IF NOT EXISTS suggested_decks (
    suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    name          TEXT NOT NULL,
    format        TEXT,
    rationale     TEXT,
    based_on_deck TEXT,
    wildcard_cost TEXT,
    validation    TEXT
);

CREATE TABLE IF NOT EXISTS suggested_deck_cards (
    suggestion_id INTEGER NOT NULL
        REFERENCES suggested_decks(suggestion_id) ON DELETE CASCADE,
    arena_id      INTEGER,
    name          TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    board         TEXT NOT NULL DEFAULT 'main',
    owned         INTEGER,
    PRIMARY KEY (suggestion_id, name, board)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# Columns added after the first release. `CREATE TABLE IF NOT EXISTS` silently
# leaves an existing table alone, so new columns need an explicit ALTER on
# databases that already exist.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("decks", "deck_kind", "TEXT"),
    ("decks", "is_favorite", "INTEGER"),
    ("ranks", "constructed_won", "INTEGER"),
    ("ranks", "constructed_lost", "INTEGER"),
    ("ranks", "limited_won", "INTEGER"),
    ("ranks", "limited_lost", "INTEGER"),
    ("decks", "description", "TEXT"),
    ("decks", "playstyle", "TEXT"),
    ("decks", "comments", "TEXT"),
    ("decks", "recommendations", "TEXT"),
    ("decks", "notes_updated_at", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        existing = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if not existing:
            continue  # table not created yet; SCHEMA will handle it
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def connect(
    path: Path | None = None, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open our database, creating and migrating the schema as needed.

    `check_same_thread=False` is needed by the HTTP server, which serves
    requests from a worker thread pool. Writes still go through one connection,
    and SQLite's own locking plus WAL mode covers concurrent access.
    """
    target = path or paths.db_path()
    conn = sqlite3.connect(target, timeout=30.0, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def record_raw_event(
    conn: sqlite3.Connection, label: str, reason: str, payload: str
) -> None:
    """Park an unparseable-but-interesting line for later diagnosis."""
    conn.execute(
        "INSERT INTO raw_events(seen_at, label, reason, payload) "
        "VALUES(datetime('now'), ?, ?, ?)",
        (label, reason, payload[:20000]),
    )

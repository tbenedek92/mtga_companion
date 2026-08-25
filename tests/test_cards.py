"""Card layer, with regression coverage for two bugs found against real data."""

from __future__ import annotations

import sqlite3

import pytest

from mtga_companion import cards, store


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.sqlite")
    yield c
    c.close()


def make_arena_db(path, rows, locs):
    """Build a minimal stand-in for Arena's Raw_CardDatabase file."""
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE Cards (GrpId INT PRIMARY KEY, TitleId INT, ExpansionCode TEXT,"
        " Rarity INT, OldSchoolManaText TEXT, Power TEXT, Toughness TEXT,"
        " CollectorNumber TEXT, IsPrimaryCard BOOLEAN, IsToken BOOLEAN)"
    )
    db.execute("CREATE TABLE Localizations_enUS (LocId INT, Formatted INT, Loc TEXT)")
    db.executemany("INSERT INTO Cards VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO Localizations_enUS VALUES (?,?,?)", locs)
    db.commit()
    db.close()
    return path


def test_arena_mana_notation_becomes_symbols():
    assert cards._arena_mana_to_symbols("o2oUoU") == "{2}{U}{U}"
    assert cards._arena_mana_to_symbols("o5oB") == "{5}{B}"
    assert cards._arena_mana_to_symbols("") is None
    assert cards._arena_mana_to_symbols(None) is None


def test_strip_markup_removes_formatted_tags():
    assert cards._strip_markup("<i>Flavor</i>") == "Flavor"
    assert cards._strip_markup("<nobr>+1/+1</nobr>") == "+1/+1"
    assert cards._strip_markup("Plain") == "Plain"
    assert cards._strip_markup(None) is None


def test_fallback_keeps_cards_with_only_a_formatted_1_title(tmp_path, conn):
    """Regression: ~1,250 real Arena cards have no Formatted=0 title row.

    Eternal Witness, Mana Crypt and Trinket Mage among them. An inner join on
    Formatted = 0 dropped every one of them.
    """
    arena = make_arena_db(
        tmp_path / "arena.mtga",
        rows=[
            (100, 1, "2X2", 3, "o1oGoG", "2", "1", "5", 1, 0),   # Formatted=1 only
            (200, 2, "DMU", 5, "o2oBoB", "4", "5", "107", 1, 0), # Formatted=0
        ],
        locs=[
            (1, 1, "<i>Eternal Witness</i>"),
            (2, 0, "Sheoldred, the Apocalypse"),
            (2, 1, "<nobr>Sheoldred</nobr>"),
        ],
    )

    assert cards.load_mtga_fallback(conn, arena) == 2
    names = {r["name"] for r in conn.execute("SELECT name FROM cards")}
    # Present at all, and with the markup stripped.
    assert names == {"Eternal Witness", "Sheoldred, the Apocalypse"}


def test_fallback_prefers_plain_title_over_markup_variant(tmp_path, conn):
    arena = make_arena_db(
        tmp_path / "arena.mtga",
        rows=[(300, 7, "SET", 2, "oR", None, None, "1", 1, 0)],
        locs=[(7, 1, "<i>Marked Up</i>"), (7, 0, "Plain Name"), (7, 2, "Plain Name")],
    )
    cards.load_mtga_fallback(conn, arena)
    assert conn.execute("SELECT name FROM cards").fetchone()["name"] == "Plain Name"


def test_fallback_skips_tokens_and_non_primary(tmp_path, conn):
    arena = make_arena_db(
        tmp_path / "arena.mtga",
        rows=[
            (1, 1, "S", 2, "oR", None, None, "1", 1, 0),  # keep
            (2, 2, "S", 2, "oR", None, None, "2", 1, 1),  # token
            (3, 3, "S", 2, "oR", None, None, "3", 0, 0),  # non-primary
        ],
        locs=[(1, 0, "Real Card"), (2, 0, "A Token"), (3, 0, "Alt Printing")],
    )
    assert cards.load_mtga_fallback(conn, arena) == 1
    assert conn.execute("SELECT name FROM cards").fetchone()["name"] == "Real Card"


def test_fallback_does_not_overwrite_scryfall_rows(tmp_path, conn):
    conn.execute(
        "INSERT INTO cards (arena_id, name, oracle_text, source) VALUES (?,?,?,?)",
        (100, "Scryfall Version", "Real oracle text", "scryfall"),
    )
    conn.commit()
    arena = make_arena_db(
        tmp_path / "arena.mtga",
        rows=[(100, 1, "X", 2, "oR", None, None, "1", 1, 0)],
        locs=[(1, 0, "Arena Version")],
    )
    assert cards.load_mtga_fallback(conn, arena) == 0
    row = conn.execute("SELECT name, source FROM cards").fetchone()
    assert row["name"] == "Scryfall Version"
    assert row["source"] == "scryfall"


def test_enrichment_updates_every_card_sharing_a_name(tmp_path, conn, monkeypatch):
    """Regression: name->id collapsed duplicates, so only one Swamp got text.

    Arena has a distinct grpId per printing, so basic lands and Secret Lair
    alt-arts repeat names many times over.
    """
    import gzip
    import json

    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(cards.paths, "scryfall_cache_dir", lambda: cache)
    with gzip.open(cache / "default_cards.jsonl.gz", "wt") as fh:
        fh.write(json.dumps({
            "name": "Swamp", "oracle_id": "abc", "cmc": 0.0, "colors": [],
            "color_identity": ["B"], "type_line": "Basic Land — Swamp",
            "oracle_text": "({T}: Add {B}.)", "legalities": {},
        }) + "\n")

    for arena_id in (11809, 28193, 28577):
        conn.execute(
            "INSERT INTO cards (arena_id, name, source) VALUES (?,?,?)",
            (arena_id, "Swamp", "mtga_local"),
        )
    conn.commit()

    assert cards.enrich_local_from_scryfall(conn) == 3
    rows = conn.execute("SELECT oracle_text FROM cards").fetchall()
    assert all(r["oracle_text"] == "({T}: Add {B}.)" for r in rows)


def test_get_card_returns_none_when_absent(conn):
    assert cards.get_card(conn, 999999) is None

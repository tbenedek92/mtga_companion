"""Read-side queries and deck statistics."""

from __future__ import annotations

import pytest

from mtga_companion import queries, store


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.sqlite")
    c.executemany(
        "INSERT INTO cards (arena_id, name, mana_cost, cmc, colors, type_line,"
        " oracle_text, rarity, set_code, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "Lightning Bolt", "{R}", 1, "R", "Instant", "Deals 3 damage.",
             "rare", "sta", "scryfall"),
            # Same name, different printing -- Arena gives each its own grpId.
            (2, "Lightning Bolt", "{R}", 1, "R", "Instant", "Deals 3 damage.",
             "rare", "vma", "scryfall"),
            (3, "Mountain", "", 0, "", "Basic Land — Mountain", "({T}: Add {R}.)",
             "basic", "m19", "scryfall"),
            (4, "Goblin Guide", "{R}", 1, "R", "Creature — Goblin Scout", "Haste.",
             "rare", "zen", "scryfall"),
            (5, "Counterspell", "{U}{U}", 2, "U", "Instant", "Counter target spell.",
             "uncommon", "sta", "scryfall"),
        ],
    )
    c.execute(
        "INSERT INTO decks (deck_id, name, format, colors, deck_kind) "
        "VALUES ('d1','Burn','Standard','R','player')"
    )
    c.executemany(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) VALUES (?,?,?,?)",
        [("d1", 1, 4, "main"), ("d1", 4, 4, "main"), ("d1", 3, 20, "main"),
         ("d1", 5, 2, "sideboard")],
    )
    c.commit()
    yield c
    c.close()


def test_search_collapses_printings_by_name(conn):
    """Regression: three printings of one card crowded out real matches."""
    results = queries.search_cards(conn, query="Lightning Bolt")
    assert [r["name"] for r in results] == ["Lightning Bolt"]


def test_search_can_show_every_printing(conn):
    results = queries.search_cards(conn, query="Lightning Bolt", all_printings=True)
    assert sorted(r["set_code"] for r in results) == ["sta", "vma"]


def test_search_matches_rules_text(conn):
    assert [r["name"] for r in queries.search_cards(conn, query="Counter target")] == [
        "Counterspell"
    ]


def test_search_filters_combine(conn):
    results = queries.search_cards(conn, colors="R", max_cmc=1, rarity="rare")
    assert sorted(r["name"] for r in results) == ["Goblin Guide", "Lightning Bolt"]


def test_search_owned_only_uses_ownership_table(conn):
    assert queries.search_cards(conn, query="Lightning", owned_only=True) == []
    conn.execute(
        "INSERT INTO card_ownership (arena_id, source, quantity, confidence) "
        "VALUES (1,'deck',4,'lower_bound')"
    )
    conn.commit()
    assert len(queries.search_cards(conn, query="Lightning", owned_only=True)) == 1


def test_list_decks_reports_board_sizes(conn):
    deck = queries.list_decks(conn)[0]
    assert deck["name"] == "Burn"
    assert deck["mainboard_size"] == 28
    assert deck["sideboard_size"] == 2


def test_list_decks_hides_precons_by_default(conn):
    """Arena ships ~108 starter decks; they must not bury the player's own."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('p1','Starter','precon')"
    )
    conn.commit()

    assert [d["name"] for d in queries.list_decks(conn)] == ["Burn"]
    assert sorted(d["name"] for d in queries.list_decks(conn, include_precon=True)) == [
        "Burn", "Starter"
    ]


def test_list_decks_puts_player_decks_first(conn):
    conn.execute(
        "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('p1','Starter','precon')"
    )
    conn.commit()
    assert queries.list_decks(conn, include_precon=True)[0]["name"] == "Burn"


def test_get_deck_splits_boards_and_resolves_cards(conn):
    deck = queries.get_deck(conn, "d1")
    assert {c["name"] for c in deck["mainboard"]} == {
        "Lightning Bolt", "Goblin Guide", "Mountain"
    }
    assert [c["name"] for c in deck["sideboard"]] == ["Counterspell"]


def test_get_deck_merges_printings_of_the_same_card(conn):
    """A deck holding two printings of Lightning Bolt is a playset, not two cards."""
    conn.execute(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
        "VALUES ('d1', 2, 1, 'main')"
    )
    conn.commit()

    mainboard = queries.get_deck(conn, "d1")["mainboard"]
    bolts = [c for c in mainboard if c["name"] == "Lightning Bolt"]
    assert len(bolts) == 1
    assert bolts[0]["quantity"] == 5          # 4 of grpId 1 + 1 of grpId 2
    assert sorted(bolts[0]["printings"]) == [1, 2]


def test_get_deck_single_printing_has_no_printings_field(conn):
    goblin = next(
        c for c in queries.get_deck(conn, "d1")["mainboard"]
        if c["name"] == "Goblin Guide"
    )
    assert "printings" not in goblin


def test_get_deck_unknown_id_returns_none(conn):
    assert queries.get_deck(conn, "nope") is None


def test_deck_stats_curve_excludes_lands(conn):
    stats = queries.get_deck_stats(conn, "d1")
    assert stats["lands"] == 20
    assert stats["mana_curve"] == {"1": 8}
    assert stats["mainboard_size"] == 28


def test_deck_stats_win_rate(conn):
    conn.executemany(
        "INSERT INTO matches (match_id, deck_id, result) VALUES (?,?,?)",
        [("m1", "d1", "win"), ("m2", "d1", "win"), ("m3", "d1", "loss")],
    )
    conn.commit()
    stats = queries.get_deck_stats(conn, "d1")
    assert (stats["wins"], stats["losses"], stats["win_rate"]) == (2, 1, 0.667)


def test_deck_stats_win_rate_is_none_without_matches(conn):
    assert queries.get_deck_stats(conn, "d1")["win_rate"] is None


def test_match_history_filters_by_deck(conn):
    conn.execute("INSERT INTO decks (deck_id, name) VALUES ('d2','Other')")
    conn.executemany(
        "INSERT INTO matches (match_id, deck_id, started_at, result) VALUES (?,?,?,?)",
        [("m1", "d1", "2026-01-01", "win"), ("m2", "d2", "2026-01-02", "loss")],
    )
    conn.commit()
    assert [m["match_id"] for m in queries.get_match_history(conn, deck_id="d1")] == ["m1"]
    # Newest first when unfiltered.
    assert [m["match_id"] for m in queries.get_match_history(conn)] == ["m2", "m1"]


def test_status_flags_disabled_logging(conn, monkeypatch):
    monkeypatch.setattr(queries_paths := __import__(
        "mtga_companion.paths", fromlist=["x"]), "detailed_logs_enabled", lambda: False)
    result = queries.status(conn)
    assert result["detailed_logs_enabled"] is False
    assert "Detailed Logs" in result["action_required"]


def test_status_has_no_action_when_logging_enabled(conn, monkeypatch):
    monkeypatch.setattr(__import__(
        "mtga_companion.paths", fromlist=["x"]), "detailed_logs_enabled", lambda: True)
    assert "action_required" not in queries.status(conn)

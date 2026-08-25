"""Ownership inference and CSV import."""

from __future__ import annotations

import pytest

from mtga_companion import collection, store


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.sqlite")
    c.executemany(
        "INSERT INTO cards (arena_id, name, rarity, colors, set_code, source) "
        "VALUES (?,?,?,?,?,'scryfall')",
        [
            (1, "Lightning Bolt", "rare", "R", "sta"),
            (2, "Counterspell", "uncommon", "U", "sta"),
            (3, "Llanowar Elves", "common", "G", "m19"),
            (4, "Lightning Bolt", "rare", "R", "vma"),
        ],
    )
    c.execute(
        "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('d1','Burn','player')"
    )
    c.commit()
    yield c
    c.close()


def test_deck_membership_implies_ownership(conn):
    conn.executemany(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) VALUES (?,?,?,?)",
        [("d1", 1, 4, "main"), ("d1", 2, 2, "sideboard")],
    )
    conn.commit()

    collection.rebuild_inferred(conn)

    assert collection.owned_quantity(conn, 1) == (4, "lower_bound")
    assert collection.owned_quantity(conn, 2) == (2, "lower_bound")
    assert collection.owned_quantity(conn, 3) == (0, "unknown")


def test_precon_decks_confer_no_ownership(conn):
    """Arena reports the contents of the ~108 decks it gives every account."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('p1','Starter','precon')"
    )
    conn.execute(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
        "VALUES ('p1', 3, 4, 'main')"
    )
    conn.commit()

    collection.rebuild_inferred(conn)

    assert collection.owned_quantity(conn, 3) == (0, "unknown")


def test_draft_picks_accumulate(conn):
    conn.executemany(
        "INSERT INTO draft_picks (draft_id, pack_number, pick_number, arena_id) "
        "VALUES (?,?,?,?)",
        [("dr1", 1, 1, 3), ("dr1", 1, 2, 3), ("dr1", 2, 1, 2)],
    )
    conn.commit()

    collection.rebuild_inferred(conn)

    assert collection.owned_quantity(conn, 3) == (2, "lower_bound")
    assert collection.owned_quantity(conn, 2) == (1, "lower_bound")


def test_only_our_own_played_cards_count(conn):
    """Seeing the opponent cast something proves nothing about our collection."""
    conn.execute("INSERT INTO matches (match_id) VALUES ('m1')")
    conn.executemany(
        "INSERT INTO match_cards_seen (match_id, arena_id, is_self) VALUES (?,?,?)",
        [("m1", 1, 1), ("m1", 3, 0)],
    )
    conn.commit()

    collection.rebuild_inferred(conn)

    assert collection.owned_quantity(conn, 1) == (1, "lower_bound")
    assert collection.owned_quantity(conn, 3) == (0, "unknown")


def test_highest_evidence_wins(conn):
    conn.execute(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
        "VALUES ('d1', 1, 4, 'main')"
    )
    conn.execute("INSERT INTO matches (match_id) VALUES ('m1')")
    conn.execute(
        "INSERT INTO match_cards_seen (match_id, arena_id, is_self) VALUES ('m1',1,1)"
    )
    conn.commit()

    collection.rebuild_inferred(conn)

    # Deck evidence (4) beats played evidence (1).
    assert collection.owned_quantity(conn, 1) == (4, "lower_bound")


def test_rebuild_is_idempotent(conn):
    conn.execute(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
        "VALUES ('d1', 1, 4, 'main')"
    )
    conn.commit()

    collection.rebuild_inferred(conn)
    first = conn.execute("SELECT COUNT(*) FROM card_ownership").fetchone()[0]
    collection.rebuild_inferred(conn)
    second = conn.execute("SELECT COUNT(*) FROM card_ownership").fetchone()[0]

    assert first == second == 1


def test_collection_states_it_is_a_lower_bound(conn):
    conn.execute(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
        "VALUES ('d1', 1, 4, 'main')"
    )
    conn.commit()
    collection.rebuild_inferred(conn)

    result = collection.get_collection(conn)

    assert result["completeness"] == "lower_bound"
    assert "LOWER BOUND" in result["caveat"]
    assert result["count"] == 1


def test_import_overrides_inference_and_reports_exact(tmp_path, conn):
    conn.execute(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
        "VALUES ('d1', 1, 4, 'main')"
    )
    conn.commit()
    collection.rebuild_inferred(conn)

    csv_file = tmp_path / "collection.csv"
    csv_file.write_text("Name,Quantity\nLightning Bolt,2\nLlanowar Elves,4\n")

    result = collection.import_collection(conn, csv_file)

    assert result["imported"] == 2
    # Exact import wins over the deck-derived lower bound of 4.
    assert collection.owned_quantity(conn, 1) == (2, "exact")
    assert collection.get_collection(conn)["completeness"] == "exact"


def test_rebuild_preserves_imported_rows(tmp_path, conn):
    csv_file = tmp_path / "c.csv"
    csv_file.write_text("Name,Quantity\nCounterspell,3\n")
    collection.import_collection(conn, csv_file)

    collection.rebuild_inferred(conn)

    assert collection.owned_quantity(conn, 2) == (3, "exact")


def test_import_reports_unresolved_names(tmp_path, conn):
    csv_file = tmp_path / "c.csv"
    csv_file.write_text("Name,Quantity\nLightning Bolt,1\nNot A Real Card,2\n")

    result = collection.import_collection(conn, csv_file)

    assert result["imported"] == 1
    assert result["unresolved_count"] == 1
    assert "Not A Real Card" in result["unresolved_sample"]


def test_import_accepts_alternative_column_names(tmp_path, conn):
    csv_file = tmp_path / "c.csv"
    csv_file.write_text("Card Name,Count,Set\nCounterspell,3,sta\n")

    assert collection.import_collection(conn, csv_file)["imported"] == 1
    assert collection.owned_quantity(conn, 2) == (3, "exact")


def test_set_column_disambiguates_reprints(tmp_path, conn):
    """Lightning Bolt exists twice; the set column must pick the right grpId."""
    csv_file = tmp_path / "c.csv"
    csv_file.write_text("Name,Quantity,Set\nLightning Bolt,1,vma\n")

    collection.import_collection(conn, csv_file)

    assert collection.owned_quantity(conn, 4) == (1, "exact")
    assert collection.owned_quantity(conn, 1) == (0, "unknown")


def test_import_rejects_file_without_name_column(tmp_path, conn):
    csv_file = tmp_path / "c.csv"
    csv_file.write_text("foo,bar\n1,2\n")

    with pytest.raises(ValueError, match="card-name column"):
        collection.import_collection(conn, csv_file)


def test_import_rejects_missing_file(conn):
    with pytest.raises(FileNotFoundError):
        collection.import_collection(conn, "/nonexistent/path.csv")


def test_reimport_replaces_previous_import(tmp_path, conn):
    first = tmp_path / "a.csv"
    first.write_text("Name,Quantity\nLightning Bolt,4\n")
    collection.import_collection(conn, first)

    second = tmp_path / "b.csv"
    second.write_text("Name,Quantity\nCounterspell,1\n")
    collection.import_collection(conn, second)

    assert collection.owned_quantity(conn, 1) == (0, "unknown")
    assert collection.owned_quantity(conn, 2) == (1, "exact")


def test_collection_filters_by_rarity_and_color(tmp_path, conn):
    csv_file = tmp_path / "c.csv"
    csv_file.write_text("Name,Quantity\nLightning Bolt,1\nCounterspell,1\nLlanowar Elves,1\n")
    collection.import_collection(conn, csv_file)

    assert {c["name"] for c in collection.get_collection(conn, rarity="rare")["cards"]} == {
        "Lightning Bolt"
    }
    assert {c["name"] for c in collection.get_collection(conn, colors="U")["cards"]} == {
        "Counterspell"
    }

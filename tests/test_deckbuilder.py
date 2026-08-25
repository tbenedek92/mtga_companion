"""Deck construction support: pools, wildcard costing, validation, export."""

from __future__ import annotations

import pytest

from mtga_companion import collection, deckbuilder as db, store

LEGAL_ALL = '{"standard":"legal","alchemy":"legal","historic":"legal","brawl":"legal"}'
NOT_STANDARD = '{"standard":"not_legal","historic":"legal","brawl":"legal"}'


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.sqlite")
    c.executemany(
        "INSERT INTO cards (arena_id, name, mana_cost, cmc, colors, color_identity,"
        " type_line, rarity, set_code, collector_number, legalities, source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,'scryfall')",
        [
            (1, "Lightning Bolt", "{R}", 1, "R", "R", "Instant", "rare", "sta", "42", LEGAL_ALL),
            (2, "Lightning Bolt", "{R}", 1, "R", "R", "Instant", "rare", "vma", "99", LEGAL_ALL),
            (3, "Mountain", "", 0, "", "", "Basic Land — Mountain", "basic", "pana", "219", LEGAL_ALL),
            (4, "Counterspell", "{U}{U}", 2, "U", "U", "Instant", "uncommon", "sta", "12", LEGAL_ALL),
            (5, "Sheoldred", "{2}{B}{B}", 4, "B", "B", "Creature", "mythic", "dmu", "107", LEGAL_ALL),
            (6, "Old Card", "{G}", 1, "G", "G", "Creature", "rare", "old", "1", NOT_STANDARD),
        ],
    )
    c.execute(
        "INSERT INTO inventory (captured_at, gold, gems, wc_common, wc_uncommon,"
        " wc_rare, wc_mythic) VALUES ('2026-01-01', 250, 100, 20, 26, 5, 6)"
    )
    c.commit()
    yield c
    c.close()


def own(conn, arena_id, qty, source="deck"):
    conn.execute(
        "INSERT INTO card_ownership (arena_id, source, quantity, confidence) "
        "VALUES (?,?,?,'lower_bound')",
        (arena_id, source, qty),
    )
    conn.commit()


class TestOwnership:
    def test_printings_of_one_card_sum_by_name(self, conn):
        """Four copies across two printings is a playset, not two cards."""
        own(conn, 1, 3)
        own(conn, 2, 1)
        assert db.owned_by_name(conn)["Lightning Bolt"] == 4

    def test_precon_decks_do_not_confer_ownership(self, conn):
        """Regression: Arena reports the contents of ~108 precon decks it gives
        every account. Counting them claimed 2,394 owned cards where only 238
        were real, including four Sheoldreds the player had never owned."""
        conn.execute(
            "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('p1','WC Deck','precon')"
        )
        conn.execute(
            "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('u1','Mine','player')"
        )
        conn.executemany(
            "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) VALUES (?,?,?,'main')",
            [("p1", 5, 4), ("u1", 1, 4)],
        )
        conn.commit()

        collection.rebuild_inferred(conn)
        owned = db.owned_by_name(conn)

        assert owned.get("Lightning Bolt") == 4
        assert owned.get("Sheoldred") is None


class TestCandidatePool:
    def test_pool_is_format_legal_and_owned(self, conn):
        own(conn, 1, 4)
        own(conn, 6, 4)  # legal in historic, not standard
        names = {c["name"] for c in db.candidate_pool(conn, "standard")}
        assert names == {"Lightning Bolt"}
        assert "Old Card" in {c["name"] for c in db.candidate_pool(conn, "historic")}

    def test_pool_collapses_printings(self, conn):
        own(conn, 1, 3)
        own(conn, 2, 1)
        pool = db.candidate_pool(conn, "standard")
        assert [c["name"] for c in pool] == ["Lightning Bolt"]
        assert pool[0]["owned"] == 4

    def test_colors_filter_uses_color_identity(self, conn):
        own(conn, 1, 4)
        own(conn, 4, 4)
        assert {c["name"] for c in db.candidate_pool(conn, "standard", colors="R")} == {
            "Lightning Bolt"
        }

    def test_unowned_pool_still_reports_ownership(self, conn):
        pool = db.candidate_pool(conn, "standard", owned_only=False)
        assert {c["name"] for c in pool} >= {"Lightning Bolt", "Sheoldred"}
        assert all(c["owned"] == 0 for c in pool)

    def test_unknown_format_is_rejected_loudly(self, conn):
        with pytest.raises(ValueError, match="Unknown format"):
            db.candidate_pool(conn, "commander-but-typo")


class TestWildcardCost:
    def test_owned_cards_cost_nothing(self, conn):
        own(conn, 1, 4)
        cost = db.wildcard_cost(conn, [{"name": "Lightning Bolt", "quantity": 4}])
        assert cost["wildcards_needed"] == {}
        assert cost["craftable_now"] is True

    def test_shortfall_is_charged_at_card_rarity(self, conn):
        own(conn, 1, 1)
        cost = db.wildcard_cost(conn, [{"name": "Lightning Bolt", "quantity": 4}])
        assert cost["wildcards_needed"] == {"rare": 3}
        assert cost["missing_cards"][0] == {
            "name": "Lightning Bolt", "need": 3, "owned": 1, "rarity": "rare"
        }

    def test_cost_is_compared_against_real_stock(self, conn):
        cost = db.wildcard_cost(conn, [{"name": "Sheoldred", "quantity": 4}])
        assert cost["wildcards_needed"] == {"mythic": 4}
        assert cost["wildcards_available"]["mythic"] == 6
        assert cost["craftable_now"] is True

    def test_shortfall_reported_when_stock_is_too_low(self, conn):
        cost = db.wildcard_cost(conn, [{"name": "Sheoldred", "quantity": 8}])
        assert cost["shortfall"] == {"mythic": 2}
        assert cost["craftable_now"] is False

    def test_basic_lands_are_free(self, conn):
        cost = db.wildcard_cost(conn, [{"name": "Mountain", "quantity": 24}])
        assert cost["wildcards_needed"] == {}


class TestValidation:
    def test_a_legal_deck_passes(self, conn):
        cards = [{"name": "Lightning Bolt", "quantity": 4, "board": "main"},
                 {"name": "Mountain", "quantity": 56, "board": "main"}]
        result = db.validate_deck(conn, cards, "standard")
        assert result["valid"] is True
        assert result["mainboard_size"] == 60

    def test_copy_limit_counts_by_name_not_printing(self, conn):
        """Two printings of Bolt at 4 each is eight copies, not two legal sets."""
        cards = [{"name": "Lightning Bolt", "quantity": 4, "board": "main"},
                 {"name": "Lightning Bolt", "quantity": 4, "board": "sideboard"},
                 {"name": "Mountain", "quantity": 56, "board": "main"}]
        result = db.validate_deck(conn, cards, "standard")
        assert result["valid"] is False
        assert any("limit is 4" in e for e in result["errors"])

    def test_basic_lands_are_exempt_from_the_copy_limit(self, conn):
        result = db.validate_deck(
            conn, [{"name": "Mountain", "quantity": 60, "board": "main"}], "standard"
        )
        assert result["valid"] is True

    def test_undersized_deck_fails(self, conn):
        result = db.validate_deck(
            conn, [{"name": "Mountain", "quantity": 40, "board": "main"}], "standard"
        )
        assert any("minimum" in e for e in result["errors"])

    def test_format_illegal_cards_are_named(self, conn):
        cards = [{"name": "Old Card", "quantity": 4, "board": "main"},
                 {"name": "Mountain", "quantity": 56, "board": "main"}]
        result = db.validate_deck(conn, cards, "standard")
        assert any("Not legal in standard" in e for e in result["errors"])

    def test_unknown_card_names_are_reported(self, conn):
        cards = [{"name": "Definitely Not A Card", "quantity": 4, "board": "main"},
                 {"name": "Mountain", "quantity": 56, "board": "main"}]
        result = db.validate_deck(conn, cards, "standard")
        assert any("Not found" in e for e in result["errors"])

    def test_brawl_is_singleton_and_100_cards(self, conn):
        cards = [{"name": "Lightning Bolt", "quantity": 2, "board": "main"},
                 {"name": "Mountain", "quantity": 98, "board": "main"}]
        result = db.validate_deck(conn, cards, "historicbrawl")
        assert any("limit is 1" in e for e in result["errors"])

    def test_all_problems_reported_together(self, conn):
        """One pass should surface every fault, not just the first."""
        cards = [{"name": "Lightning Bolt", "quantity": 8, "board": "main"},
                 {"name": "Old Card", "quantity": 4, "board": "main"}]
        errors = db.validate_deck(conn, cards, "standard")["errors"]
        assert len(errors) >= 3  # copy limit, size, illegal card


class TestArenaExport:
    def test_lines_carry_set_and_collector_number(self, conn):
        text = db.to_arena_export(conn, [{"name": "Lightning Bolt", "quantity": 4}])
        assert text == "Deck\n4 Lightning Bolt (STA) 42"

    def test_basic_lands_are_emitted_without_a_set(self, conn):
        """Arena accepts a bare basic; the printing we would otherwise pick can
        be a promo set (PANA) its importer rejects."""
        text = db.to_arena_export(conn, [{"name": "Mountain", "quantity": 20}])
        assert text == "Deck\n20 Mountain"

    def test_sideboard_gets_its_own_section(self, conn):
        text = db.to_arena_export(conn, [
            {"name": "Lightning Bolt", "quantity": 4, "board": "main"},
            {"name": "Counterspell", "quantity": 2, "board": "sideboard"},
        ])
        assert "Sideboard" in text
        assert text.index("Deck") < text.index("Sideboard")

    def test_unknown_card_falls_back_to_bare_name(self, conn):
        text = db.to_arena_export(conn, [{"name": "Mystery Card", "quantity": 1}])
        assert "1 Mystery Card" in text


class TestSuggestions:
    def test_saving_a_suggestion_records_validation_and_cost(self, conn):
        own(conn, 1, 4)
        cards = [{"name": "Lightning Bolt", "quantity": 4, "board": "main"},
                 {"name": "Sheoldred", "quantity": 2, "board": "main"},
                 {"name": "Mountain", "quantity": 54, "board": "main"}]
        saved = db.save_suggestion(conn, "Test Burn", "standard", cards, "because")

        assert saved["validation"]["valid"] is True
        assert saved["wildcard_cost"]["wildcards_needed"] == {"mythic": 2}

        full = db.get_suggestion(conn, saved["suggestion_id"])
        assert full["name"] == "Test Burn"
        assert full["rationale"] == "because"
        assert "Deck" in full["arena_export"]
        bolt = next(c for c in full["cards"] if c["name"] == "Lightning Bolt")
        assert bolt["owned"] == 4

    def test_suggestions_are_listed_newest_first(self, conn):
        db.save_suggestion(conn, "First", "standard", [{"name": "Mountain", "quantity": 60}])
        db.save_suggestion(conn, "Second", "standard", [{"name": "Mountain", "quantity": 60}])
        assert [s["name"] for s in db.list_suggestions(conn)] == ["Second", "First"]

    def test_missing_suggestion_returns_none(self, conn):
        assert db.get_suggestion(conn, 999) is None

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

    def test_deck_membership_does_not_confer_ownership(self, conn):
        """Regression: Arena reports the contents of ~108 precon decks it gives
        every account; counting them once claimed 2,394 owned cards where only
        238 were real, including four Sheoldreds the player had never owned.
        A second regression (Arena's Import feature lets a player deck list
        cards it never owned, flagged as missing rather than blocked, and the
        deck is then indistinguishable from a hand-built one once renamed)
        showed that even excluding precons wasn't enough -- so deck contents
        are not ownership evidence at all, precon or player."""
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

        assert owned.get("Lightning Bolt") is None
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


class TestWildcardBudget:
    def test_no_budget_is_always_within_budget(self, conn):
        cost = db.wildcard_cost(conn, [{"name": "Sheoldred", "quantity": 4}])
        result = db.check_wildcard_budget(cost, None)
        assert result == {"budget_set": False, "within_budget": True, "over_budget": {}}

    def test_within_budget(self, conn):
        cost = db.wildcard_cost(conn, [{"name": "Sheoldred", "quantity": 2}])
        result = db.check_wildcard_budget(cost, {"mythic": 5})
        assert result["budget_set"] is True
        assert result["within_budget"] is True
        assert result["over_budget"] == {}

    def test_over_budget_reports_the_shortfall(self, conn):
        cost = db.wildcard_cost(conn, [{"name": "Sheoldred", "quantity": 8}])
        result = db.check_wildcard_budget(cost, {"mythic": 1})
        assert result["within_budget"] is False
        assert result["over_budget"] == {"mythic": 7}

    def test_rarities_absent_from_the_budget_default_to_zero_allowance(self, conn):
        """A budget of {"rare": 1} with no mention of mythic means zero
        mythic wildcards are acceptable, not unlimited."""
        cost = db.wildcard_cost(conn, [{"name": "Sheoldred", "quantity": 1}])
        result = db.check_wildcard_budget(cost, {"rare": 5})
        assert result["within_budget"] is False
        assert result["over_budget"] == {"mythic": 1}

    def test_free_cards_never_violate_a_budget(self, conn):
        own(conn, 1, 4)  # Lightning Bolt, fully owned
        cost = db.wildcard_cost(conn, [{"name": "Lightning Bolt", "quantity": 4}])
        result = db.check_wildcard_budget(cost, {"rare": 0})
        assert result["within_budget"] is True


class TestParseArenaExport:
    def test_round_trips_through_to_arena_export(self, conn):
        original = [
            {"name": "Lightning Bolt", "quantity": 4, "board": "main"},
            {"name": "Mountain", "quantity": 20, "board": "main"},
            {"name": "Counterspell", "quantity": 2, "board": "sideboard"},
        ]
        text = db.to_arena_export(conn, original)
        parsed = db.parse_arena_export(text)
        assert {(c["name"], c["quantity"], c["board"]) for c in parsed} == {
            (c["name"], c["quantity"], c["board"]) for c in original
        }

    def test_bare_lines_without_set_info_are_accepted(self):
        cards = db.parse_arena_export("Deck\n4 Lightning Bolt\n20 Mountain\n")
        assert cards == [
            {"name": "Lightning Bolt", "quantity": 4, "board": "main"},
            {"name": "Mountain", "quantity": 20, "board": "main"},
        ]

    def test_section_headers_switch_the_board(self):
        text = "Deck\n4 Lightning Bolt\n\nSideboard\n2 Counterspell\n\nCommander\n1 Sheoldred"
        cards = db.parse_arena_export(text)
        assert [(c["name"], c["board"]) for c in cards] == [
            ("Lightning Bolt", "main"), ("Counterspell", "sideboard"),
            ("Sheoldred", "commander"),
        ]

    def test_comments_and_blank_lines_are_ignored(self):
        text = "// my favorite deck\nDeck\n\n4 Lightning Bolt\n// good card\n20 Mountain"
        cards = db.parse_arena_export(text)
        assert len(cards) == 2

    def test_unparseable_lines_are_skipped_not_fatal(self):
        text = "Deck\nAbout\nName: My Cool Deck\n4 Lightning Bolt\n"
        cards = db.parse_arena_export(text)
        assert cards == [{"name": "Lightning Bolt", "quantity": 4, "board": "main"}]

    def test_empty_text_yields_no_cards(self):
        assert db.parse_arena_export("") == []
        assert db.parse_arena_export("Deck\n\nSideboard\n") == []

    def test_card_names_with_punctuation_and_dfcs(self):
        cards = db.parse_arena_export("Deck\n2 Jace, the Mind Sculptor\n1 Fire // Ice (STA) 42\n")
        assert cards[0]["name"] == "Jace, the Mind Sculptor"
        assert cards[1]["name"] == "Fire // Ice"


class TestImportDeck:
    def test_import_saves_a_playable_suggestion(self, conn):
        text = "Deck\n4 Lightning Bolt (STA) 42\n56 Mountain\n"
        saved = db.import_deck(conn, text, "Pasted Burn", "standard")

        assert saved["name"] == "Pasted Burn"
        assert saved["validation"]["valid"] is True
        assert "Deck" in saved["arena_export"]

        full = db.get_suggestion(conn, saved["suggestion_id"])
        assert full["rationale"] == "Imported decklist"
        assert sum(c["quantity"] for c in full["cards"]) == 60

    def test_import_respects_a_custom_rationale(self, conn):
        text = "Deck\n4 Lightning Bolt\n56 Mountain\n"
        saved = db.import_deck(conn, text, "X", rationale="From a forum post")
        full = db.get_suggestion(conn, saved["suggestion_id"])
        assert full["rationale"] == "From a forum post"

    def test_import_rejects_text_with_no_parseable_cards(self, conn):
        with pytest.raises(ValueError, match="Could not parse"):
            db.import_deck(conn, "not a decklist at all", "X")

    def test_import_rejects_empty_text(self, conn):
        with pytest.raises(ValueError):
            db.import_deck(conn, "", "X")


class TestSaveSuggestionWithBudget:
    def test_budget_check_is_stored_alongside_validation(self, conn):
        cards = [{"name": "Sheoldred", "quantity": 4, "board": "main"},
                 {"name": "Mountain", "quantity": 56, "board": "main"}]
        saved = db.save_suggestion(
            conn, "Budgeted", "standard", cards, wildcard_budget={"mythic": 1}
        )
        full = db.get_suggestion(conn, saved["suggestion_id"])
        check = full["validation"]["wildcard_budget_check"]
        assert check["budget_set"] is True
        assert check["within_budget"] is False
        assert check["over_budget"] == {"mythic": 3}

    def test_no_budget_given_is_recorded_as_unset(self, conn):
        cards = [{"name": "Mountain", "quantity": 60, "board": "main"}]
        saved = db.save_suggestion(conn, "Free", "standard", cards)
        full = db.get_suggestion(conn, saved["suggestion_id"])
        assert full["validation"]["wildcard_budget_check"]["budget_set"] is False


class TestSaveSuggestionUpdateInPlace:
    def test_passing_suggestion_id_revises_instead_of_duplicating(self, conn):
        first = db.save_suggestion(
            conn, "V1", "standard", [{"name": "Mountain", "quantity": 60, "board": "main"}]
        )
        second = db.save_suggestion(
            conn, "V2", "standard",
            [{"name": "Mountain", "quantity": 58, "board": "main"},
             {"name": "Lightning Bolt", "quantity": 2, "board": "main"}],
            suggestion_id=first["suggestion_id"],
        )
        assert second["suggestion_id"] == first["suggestion_id"]
        assert len(db.list_suggestions(conn)) == 1

        full = db.get_suggestion(conn, first["suggestion_id"])
        assert full["name"] == "V2"
        names = {c["name"] for c in full["cards"]}
        assert names == {"Mountain", "Lightning Bolt"}

    def test_stale_cards_are_removed_on_revision(self, conn):
        """Cards dropped from the new list must not linger from the old one."""
        first = db.save_suggestion(
            conn, "V1", "standard",
            [{"name": "Mountain", "quantity": 56, "board": "main"},
             {"name": "Lightning Bolt", "quantity": 4, "board": "main"}],
        )
        db.save_suggestion(
            conn, "V2", "standard",
            [{"name": "Mountain", "quantity": 60, "board": "main"}],
            suggestion_id=first["suggestion_id"],
        )
        full = db.get_suggestion(conn, first["suggestion_id"])
        assert {c["name"] for c in full["cards"]} == {"Mountain"}

    def test_notes_are_partial_updates_across_revisions(self, conn):
        first = db.save_suggestion(
            conn, "V1", "standard", [{"name": "Mountain", "quantity": 60}],
            description="Original plan", playstyle="Aggro",
        )
        db.save_suggestion(
            conn, "V1", "standard", [{"name": "Mountain", "quantity": 60}],
            suggestion_id=first["suggestion_id"], comments="New note",
        )
        full = db.get_suggestion(conn, first["suggestion_id"])
        assert full["description"] == "Original plan"  # untouched
        assert full["playstyle"] == "Aggro"             # untouched
        assert full["comments"] == "New note"

    def test_updating_an_unknown_suggestion_id_raises(self, conn):
        with pytest.raises(ValueError, match="No saved suggestion"):
            db.save_suggestion(
                conn, "X", "standard", [{"name": "Mountain", "quantity": 60}],
                suggestion_id=999,
            )

    def test_rationale_and_based_on_deck_are_also_partial_on_revision(self, conn):
        first = db.save_suggestion(
            conn, "V1", "standard", [{"name": "Mountain", "quantity": 60}],
            rationale="First reason",
        )
        db.save_suggestion(
            conn, "V1", "standard", [{"name": "Mountain", "quantity": 60}],
            suggestion_id=first["suggestion_id"],
        )
        full = db.get_suggestion(conn, first["suggestion_id"])
        assert full["rationale"] == "First reason"


class TestUpdateSuggestionNotes:
    def test_updates_notes_without_touching_cards(self, conn):
        saved = db.save_suggestion(
            conn, "X", "standard", [{"name": "Mountain", "quantity": 60}]
        )
        updated = db.update_suggestion_notes(
            conn, saved["suggestion_id"], recommendations="Add removal"
        )
        assert updated["recommendations"] == "Add removal"
        assert len(updated["cards"]) == 1

    def test_partial_update(self, conn):
        saved = db.save_suggestion(
            conn, "X", "standard", [{"name": "Mountain", "quantity": 60}],
            description="A", playstyle="B",
        )
        db.update_suggestion_notes(conn, saved["suggestion_id"], comments="C")
        full = db.get_suggestion(conn, saved["suggestion_id"])
        assert (full["description"], full["playstyle"], full["comments"]) == ("A", "B", "C")

    def test_no_fields_is_rejected(self, conn):
        saved = db.save_suggestion(
            conn, "X", "standard", [{"name": "Mountain", "quantity": 60}]
        )
        with pytest.raises(ValueError, match="at least one"):
            db.update_suggestion_notes(conn, saved["suggestion_id"])

    def test_unknown_suggestion_is_rejected(self, conn):
        with pytest.raises(ValueError, match="No saved suggestion"):
            db.update_suggestion_notes(conn, 999, comments="x")


class TestDuplicateDeck:
    def test_duplicate_from_a_real_deck(self, conn):
        conn.execute(
            "INSERT INTO decks (deck_id, name, format, deck_kind) "
            "VALUES ('d1', 'Original', 'standard', 'player')"
        )
        conn.execute(
            "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) "
            "VALUES ('d1', 1, 4, 'main')"
        )
        conn.commit()

        dup = db.duplicate_deck(conn, "Variant", deck_id="d1")
        full = db.get_suggestion(conn, dup["suggestion_id"])
        assert full["format"] == "standard"
        assert full["cards"][0]["name"] == "Lightning Bolt"
        assert "Original" in full["rationale"]

    def test_duplicate_from_a_suggestion(self, conn):
        original = db.save_suggestion(
            conn, "Base", "standard", [{"name": "Mountain", "quantity": 60}]
        )
        dup = db.duplicate_deck(conn, "Fork", suggestion_id=original["suggestion_id"])
        assert dup["suggestion_id"] != original["suggestion_id"]
        assert len(db.list_suggestions(conn)) == 2

    def test_notes_are_not_carried_over(self, conn):
        original = db.save_suggestion(
            conn, "Base", "standard", [{"name": "Mountain", "quantity": 60}],
            description="Should not copy", playstyle="Control",
        )
        dup = db.duplicate_deck(conn, "Fork", suggestion_id=original["suggestion_id"])
        full = db.get_suggestion(conn, dup["suggestion_id"])
        assert full["description"] is None
        assert full["playstyle"] is None

    def test_requires_exactly_one_source(self, conn):
        with pytest.raises(ValueError, match="exactly one"):
            db.duplicate_deck(conn, "X")
        with pytest.raises(ValueError, match="exactly one"):
            db.duplicate_deck(conn, "X", deck_id="d1", suggestion_id=1)

    def test_unknown_deck_id_is_rejected(self, conn):
        with pytest.raises(ValueError, match="No deck"):
            db.duplicate_deck(conn, "X", deck_id="nope")

    def test_unknown_suggestion_id_is_rejected(self, conn):
        with pytest.raises(ValueError, match="No saved suggestion"):
            db.duplicate_deck(conn, "X", suggestion_id=999)

    def test_format_can_be_overridden(self, conn):
        conn.execute(
            "INSERT INTO decks (deck_id, name, format, deck_kind) "
            "VALUES ('d1', 'Original', 'standard', 'player')"
        )
        conn.commit()
        dup = db.duplicate_deck(conn, "Variant", deck_id="d1", fmt="historic")
        assert db.get_suggestion(conn, dup["suggestion_id"])["format"] == "historic"


class TestListSuggestionsIncludesPreview:
    def test_playstyle_and_description_are_listed(self, conn):
        db.save_suggestion(
            conn, "X", "standard", [{"name": "Mountain", "quantity": 60}],
            playstyle="Aggro", description="Fast deck",
        )
        listed = db.list_suggestions(conn)[0]
        assert listed["playstyle"] == "Aggro"
        assert listed["description"] == "Fast deck"

"""Parser framing and extraction, checked against real captured payloads.

The shapes used here were taken from an actual Detailed-Logs session, including
the awkward parts: responses put their JSON on the line *after* an unprefixed
header, deck metadata and deck contents live in separate top-level keys, and
deck attributes arrive as a name/value list with JSON-quoted timestamps.
"""

from __future__ import annotations

import json

import pytest

from mtga_companion import parse, store


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.sqlite")
    yield c
    c.close()


RANK_PAYLOAD = {
    "constructedSeasonOrdinal": 92, "constructedLevel": 2,
    "constructedMatchesWon": 16, "constructedMatchesLost": 7,
    "limitedSeasonOrdinal": 92, "limitedLevel": 4,
}


class TestFraming:
    """Response bodies arrive on the line after an unprefixed header."""

    def test_response_body_follows_header_line(self, conn):
        p = parse.LogParser(conn)
        assert p.feed("<== RankGetCombinedRankInfo(940afb39-d4e7)") is False
        assert p.feed(json.dumps(RANK_PAYLOAD)) is True
        assert conn.execute("SELECT constructed_level FROM ranks").fetchone()[0] == 2

    def test_response_header_carries_no_logger_prefix(self, conn):
        """Real headers are bare; requiring the prefix drops every response."""
        p = parse.LogParser(conn)
        p.feed("<== RankGetCombinedRankInfo(x)")
        p.feed(json.dumps(RANK_PAYLOAD))
        assert conn.execute("SELECT COUNT(*) FROM ranks").fetchone()[0] == 1

    def test_blank_line_between_header_and_body_is_tolerated(self, conn):
        p = parse.LogParser(conn)
        p.feed("<== RankGetCombinedRankInfo(x)")
        p.feed("")
        assert p.feed(json.dumps(RANK_PAYLOAD)) is True

    def test_interrupted_header_does_not_capture_a_later_payload(self, conn):
        """If the body never arrives, the pending label must be dropped."""
        p = parse.LogParser(conn)
        p.feed("<== RankGetCombinedRankInfo(x)")
        p.feed("FrontDoorConnectionAWS:ProcessMessages()")
        assert p.feed(json.dumps(RANK_PAYLOAD)) is False
        assert conn.execute("SELECT COUNT(*) FROM ranks").fetchone()[0] == 0

    def test_prefixed_request_is_single_line(self, conn):
        p = parse.LogParser(conn)
        assert p.feed(
            '[UnityCrossThreadLogger]==> GraphGetGraphState {"id":"x","request":"{}"}'
        ) is False

    def test_non_logger_lines_ignored(self, conn):
        p = parse.LogParser(conn)
        assert p.feed("Initialize engine version: 2022.3") is False
        assert p.feed("") is False


class TestRobustness:
    """Whatever the payloads become, ingestion must not crash or fabricate."""

    def test_garbage_lines_are_survivable(self, conn):
        for line in [
            "",
            "not a log line",
            "[UnityCrossThreadLogger]",
            "[UnityCrossThreadLogger]Label {not json}",
            "[UnityCrossThreadLogger]<== Deck.Foo(x) {",
            "[UnityCrossThreadLogger]==> Deck.Bar null",
        ]:
            assert parse.handle_line(conn, line) is False

    def test_unrecognised_response_is_recorded_not_dropped(self, conn):
        p = parse.LogParser(conn)
        p.feed("<== DeckMysteryNewThing(x)")
        p.feed('{"surprise":1}')
        row = conn.execute("SELECT label, reason FROM raw_events").fetchone()
        assert row["label"] == "DeckMysteryNewThing"
        assert row["reason"] == "no extractor matched"

    def test_unrecognised_request_is_not_recorded(self, conn):
        """Our own outgoing chatter is noise; only server responses matter."""
        parse.LogParser(conn).feed(
            '[UnityCrossThreadLogger]==> DeckMysteryNewThing '
            '{"id":"x","request":"{\\"CacheVersion\\":0}"}'
        )
        assert conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 0

    def test_telemetry_is_ignored_without_recording(self, conn):
        assert parse.handle_line(
            conn, '[UnityCrossThreadLogger]==> LogBusinessEvents {"a":1}'
        ) is False
        assert conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 0

    def test_extractor_exception_is_contained(self, conn, monkeypatch):
        def boom(_conn, _payload):
            raise RuntimeError("shape changed")

        monkeypatch.setattr(parse, "_ROUTES", [(("Deck",), (boom,))])
        assert parse.handle_line(conn, '[UnityCrossThreadLogger]<== Deck.X(y) {"a":1}') is False
        assert "shape changed" in conn.execute(
            "SELECT reason FROM raw_events"
        ).fetchone()["reason"]


class TestHelpers:
    def test_walk_finds_nested_keys(self):
        payload = {"outer": {"middle": [{"InventoryInfo": {"gold": 5}}]}}
        assert parse._walk(payload, "InventoryInfo") == {"gold": 5}

    def test_first_is_case_insensitive_across_spellings(self):
        assert parse._first({"DeckId": "x"}, "deckId") == "x"
        assert parse._first({"deckid": "x"}, "DeckId") == "x"
        assert parse._first({"a": 1}, "missing") is None

    def test_double_encoded_json_is_unwrapped(self):
        assert parse._loads(json.dumps(json.dumps({"a": 1}))) == {"a": 1}

    def test_deck_entries_accept_object_form(self):
        entries = [{"cardId": 111, "quantity": 4}, {"cardId": 222, "quantity": 2}]
        assert list(parse._iter_deck_entries(entries)) == [(111, 4), (222, 2)]

    def test_deck_entries_accept_flat_run_length_form(self):
        assert list(parse._iter_deck_entries([111, 4, 222, 2])) == [(111, 4), (222, 2)]

    def test_deck_entries_tolerate_empty_and_none(self):
        assert list(parse._iter_deck_entries(None)) == []
        assert list(parse._iter_deck_entries([])) == []


class TestExtraction:
    """Payload shapes below are copied from a real StartHook response."""

    @staticmethod
    def start_hook(conn, payload):
        p = parse.LogParser(conn)
        p.feed("<== StartHook(940afb39-d4e7-4a22-9e4e-15d207d755f2)")
        return p.feed(json.dumps(payload))

    def test_decks_join_summaries_to_separate_deck_lists(self, conn):
        """Metadata and card lists live in two sibling keys, joined by id.

        Neither is usable alone: DeckSummaries has no cards, Decks has no name.
        """
        payload = {
            "DeckSummaries": [{
                "DeckId": "abc", "Name": "Mono-Red Burn", "Description": "",
                "Attributes": [
                    {"name": "Format", "value": "Standard"},
                    {"name": "Version", "value": "11"},
                    {"name": "LastPlayed", "value": '"2026-08-25T10:09:31+02:00"'},
                    {"name": "LastUpdated", "value": '"2026-08-24T12:00:00+02:00"'},
                    {"name": "IsFavorite", "value": "true"},
                ],
            }],
            "Decks": {"abc": {
                "MainDeck": [{"cardId": 111, "quantity": 4}],
                "Sideboard": [{"cardId": 222, "quantity": 2}],
                "CommandZone": [], "Companions": [],
            }},
        }
        assert self.start_hook(conn, payload) is True

        deck = conn.execute("SELECT * FROM decks").fetchone()
        assert deck["name"] == "Mono-Red Burn"
        assert deck["format"] == "Standard"
        assert deck["deck_kind"] == "player"
        assert deck["is_favorite"] == 1
        # Quotes stripped from the JSON-encoded timestamp.
        assert deck["last_played"].startswith("2026-08-25T10:09:31")
        assert dict(
            conn.execute("SELECT board, quantity FROM deck_cards ORDER BY board")
        ) == {"main": 4, "sideboard": 2}

    def test_never_played_sentinel_becomes_null(self, conn):
        """Arena writes .NET DateTime.MinValue for 'never', not a real date."""
        payload = {
            "DeckSummaries": [{
                "DeckId": "abc", "Name": "D",
                "Attributes": [
                    {"name": "Version", "value": "1"},
                    {"name": "LastPlayed", "value": '"0001-01-01T00:00:00+00:00"'},
                ],
            }],
            "Decks": {"abc": {"MainDeck": [{"cardId": 111, "quantity": 4}]}},
        }
        self.start_hook(conn, payload)
        assert conn.execute("SELECT last_played FROM decks").fetchone()[0] is None

    def test_precon_decks_are_flagged_separately(self, conn):
        """Arena ships ~108 precons in every payload; they aren't user decks."""
        payload = {
            "DeckSummaries": [
                {"DeckId": "p1", "Name": "Starter", "Attributes": [],
                 "Description": "Decks/Precon/CC_ANB_W_Desc"},
                {"DeckId": "u1", "Name": "Mine", "Description": "",
                 "Attributes": [{"name": "LastUpdated", "value": '"2026-08-24T00:00:00Z"'}]},
            ],
            "Decks": {"p1": {"MainDeck": []}, "u1": {"MainDeck": []}},
        }
        self.start_hook(conn, payload)
        kinds = dict(conn.execute("SELECT name, deck_kind FROM decks"))
        assert kinds == {"Starter": "precon", "Mine": "player"}

    def test_deck_colors_are_derived_from_cards(self, conn):
        """Arena reports no deck colors, so they come from the card table."""
        conn.executemany(
            "INSERT INTO cards (arena_id, name, colors, source) VALUES (?,?,?,'scryfall')",
            [(111, "Bolt", "R"), (222, "Counterspell", "U")],
        )
        payload = {
            "DeckSummaries": [{"DeckId": "abc", "Name": "Izzet", "Attributes": []}],
            "Decks": {"abc": {"MainDeck": [
                {"cardId": 111, "quantity": 4}, {"cardId": 222, "quantity": 4}
            ]}},
        }
        self.start_hook(conn, payload)
        assert conn.execute("SELECT colors FROM decks").fetchone()[0] == "UR"

    def test_reparsing_the_same_deck_is_idempotent(self, conn):
        payload = {
            "DeckSummaries": [{"DeckId": "abc", "Name": "D", "Attributes": []}],
            "Decks": {"abc": {"MainDeck": [{"cardId": 1, "quantity": 4}]}},
        }
        self.start_hook(conn, payload)
        self.start_hook(conn, payload)
        assert conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0] == 1

    def test_deck_edit_replaces_rather_than_accumulates(self, conn):
        """Removing a card from a deck must remove it here too."""
        base = {"DeckSummaries": [{"DeckId": "abc", "Name": "D", "Attributes": []}]}
        first = {**base, "Decks": {"abc": {"MainDeck": [
            {"cardId": 1, "quantity": 4}, {"cardId": 2, "quantity": 4}]}}}
        second = {**base, "Decks": {"abc": {"MainDeck": [
            {"cardId": 1, "quantity": 4}]}}}
        self.start_hook(conn, first)
        self.start_hook(conn, second)
        assert [r[0] for r in conn.execute("SELECT arena_id FROM deck_cards")] == [1]

    def test_inventory_snapshot(self, conn):
        payload = {"InventoryInfo": {
            "Gold": 5000, "Gems": 900, "WildCardCommons": 12,
            "WildCardUnCommons": 8, "WildCardRares": 3, "WildCardMythics": 1,
            "TotalVaultProgress": 42.5,
        }}
        assert self.start_hook(conn, payload) is True

        row = conn.execute("SELECT * FROM inventory").fetchone()
        assert (row["gold"], row["gems"], row["wc_mythic"]) == (5000, 900, 1)
        assert row["vault_progress"] == 42.5

    def test_rank_snapshot_without_a_class_field(self, conn):
        """The live payload has no rank class at all -- only levels and record."""
        p = parse.LogParser(conn)
        p.feed("<== RankGetCombinedRankInfo(x)")
        assert p.feed(json.dumps(RANK_PAYLOAD)) is True

        row = conn.execute("SELECT * FROM ranks").fetchone()
        assert row["constructed_class"] is None
        assert row["constructed_level"] == 2
        assert (row["constructed_won"], row["constructed_lost"]) == (16, 7)
        assert row["limited_level"] == 4

    def test_draft_pick_with_comma_separated_pack(self, conn):
        payload = {"DraftId": "d1", "PackNumber": 1, "PickNumber": 2,
                   "CardId": 555, "PackCards": "111,222,555"}
        p = parse.LogParser(conn)
        p.feed("<== Draft.Notify(x)")
        assert p.feed(json.dumps(payload)) is True

        row = conn.execute("SELECT * FROM draft_picks").fetchone()
        assert row["arena_id"] == 555
        assert row["pack_cards"] == "111,222,555"


class TestCardGrants:
    """Arena reports inventory *changes* even though it no longer reports
    contents, so a running tracker accumulates the real collection over time.

    Shapes are provisional: no booster has been opened into a captured log yet.
    """

    def test_flat_grpid_list_counts_repeats_as_quantity(self, conn):
        payload = {"Changes": [{"Id": "c1", "Context": "BoosterOpen",
                                "CardsAdded": [111, 222, 111]}]}
        assert parse._extract_card_grants(conn, payload) is True
        rows = dict(conn.execute("SELECT arena_id, quantity FROM card_grants"))
        assert rows == {111: 2, 222: 1}

    def test_object_form_with_explicit_quantity(self, conn):
        payload = {"Changes": [{"Id": "c2", "CardsAdded": [
            {"grpId": 111, "quantity": 3}]}]}
        parse._extract_card_grants(conn, payload)
        assert conn.execute(
            "SELECT quantity FROM card_grants WHERE arena_id=111"
        ).fetchone()[0] == 3

    def test_replaying_the_same_log_does_not_double_count(self, conn):
        """Player-prev.log is re-read on startup; grants must not accumulate."""
        payload = {"Changes": [{"Id": "c1", "CardsAdded": [111, 111]}]}
        parse._extract_card_grants(conn, payload)
        parse._extract_card_grants(conn, payload)
        assert conn.execute(
            "SELECT SUM(quantity) FROM card_grants WHERE arena_id=111"
        ).fetchone()[0] == 2

    def test_distinct_openings_of_the_same_card_do_accumulate(self, conn):
        """Two boosters containing the same card is genuinely two copies."""
        parse._extract_card_grants(conn, {"Changes": [{"Id": "a", "CardsAdded": [111]}]})
        parse._extract_card_grants(conn, {"Changes": [{"Id": "b", "CardsAdded": [111]}]})
        assert conn.execute(
            "SELECT SUM(quantity) FROM card_grants WHERE arena_id=111"
        ).fetchone()[0] == 2

    def test_empty_changes_is_not_a_match(self, conn):
        assert parse._extract_card_grants(conn, {"Changes": []}) is False
        assert parse._extract_card_grants(conn, {"InventoryInfo": {"Gold": 1}}) is False


def test_grants_feed_the_collection(tmp_path):
    """A granted card becomes owned without ever appearing in a deck."""
    from mtga_companion import collection

    c = store.connect(tmp_path / "g.sqlite")
    c.execute(
        "INSERT INTO cards (arena_id, name, source) VALUES (111,'Opened Card','scryfall')"
    )
    parse._extract_card_grants(
        c, {"Changes": [{"Id": "b1", "Context": "BoosterOpen", "CardsAdded": [111, 111]}]}
    )
    c.commit()

    collection.rebuild_inferred(c)

    assert collection.owned_quantity(c, 111) == (2, "lower_bound")
    c.close()

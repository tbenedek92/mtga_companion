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

    def test_draft_pick_records_full_list_on_completion(self, conn):
        """Real QuickDraft shape: fields are JSON-encoded under `Payload`, and
        only the terminal "Completed" event's cumulative `PickedCards` is
        trustworthy -- Arena never reports a single chosen card per pick."""
        inner = {"EventName": "QuickDraft_HOB_20260820", "DraftStatus": "Completed",
                  "PackNumber": 2, "PickNumber": 13,
                  "PickedCards": ["103541", "103464", "103415"]}
        payload = {"CurrentModule": "BotDraft", "Payload": json.dumps(inner)}
        p = parse.LogParser(conn)
        p.feed("<== BotDraft(x)")
        assert p.feed(json.dumps(payload)) is True

        rows = conn.execute(
            "SELECT pick_number, arena_id FROM draft_picks ORDER BY pick_number"
        ).fetchall()
        assert [(r["pick_number"], r["arena_id"]) for r in rows] == [
            (0, 103541), (1, 103464), (2, 103415)
        ]

    def test_draft_pick_ignores_in_progress_events(self, conn):
        """PickNext events never reveal which card was chosen -- only the
        final Completed event's PickedCards is authoritative."""
        inner = {"EventName": "QuickDraft_HOB_20260820", "DraftStatus": "PickNext",
                  "PackNumber": 0, "PickNumber": 1, "DraftPack": ["1", "2"],
                  "PickedCards": ["103541"]}
        payload = {"CurrentModule": "BotDraft", "Payload": json.dumps(inner)}
        p = parse.LogParser(conn)
        p.feed("<== BotDraft(x)")
        assert p.feed(json.dumps(payload)) is False

        assert conn.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0] == 0


class TestMatchExtraction:
    """Shapes trimmed from two real completed matches captured live: one won
    by the opponent conceding, one lost normally. Both confirmed that match
    traffic uses a fourth line shape entirely -- see _MATCH_HEADER."""

    ME = "TNOMMPVRQZDODPW2LOP67R24FQ"
    OPPONENT = "E6G5EMXF4VH4PGRIMT4GNRTTH4"

    def room_event(self, state_type, extra=None):
        room = {
            "gameRoomInfo": {
                "gameRoomConfig": {
                    "reservedPlayers": [
                        {"userId": self.ME, "playerName": "igor", "systemSeatId": 1,
                         "teamId": 1, "eventId": "Play"},
                        {"userId": self.OPPONENT, "playerName": "DanitoRasen91",
                         "systemSeatId": 2, "teamId": 2, "eventId": "Play"},
                    ],
                    "matchId": "45189e2a-2761-456f-9a09-24619f9997b5",
                },
                "stateType": state_type,
            }
        }
        if extra:
            room["gameRoomInfo"].update(extra)
        return {"matchGameRoomStateChangedEvent": room}

    def feed_match(self, conn, header, body):
        p = parse.LogParser(conn)
        assert p.feed(header) is False
        result = p.feed(json.dumps(body))
        return p, result

    def test_match_header_line_is_recognised(self, conn):
        _, result = self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: "
            "MatchGameRoomStateChangedEvent",
            self.room_event("MatchGameRoomStateType_Playing"),
        )
        assert result is True
        row = conn.execute("SELECT * FROM matches").fetchone()
        assert row["match_id"] == "45189e2a-2761-456f-9a09-24619f9997b5"
        assert row["opponent_name"] == "DanitoRasen91"
        assert row["event_name"] == "Play"
        assert row["result"] is None

    def test_client_to_match_direction_is_also_recognised(self, conn):
        """The header also appears as "<id> to Match: <label>" for
        client-originated traffic -- same id, reversed order."""
        p = parse.LogParser(conn)
        assert p.feed(
            f"[UnityCrossThreadLogger]8/26/2026 9:57:11 AM: {self.ME} to Match: "
            "ClientToGremessage"
        ) is False
        # Not a shape we model; recognising the header must not itself crash
        # or misfire just because the body doesn't match any route.
        assert p.feed(json.dumps({"requestId": 1})) is False

    def test_win_by_concession_is_recorded_from_the_players_own_seat(self, conn):
        """Regression: finalMatchResult only ever names a winningTeamId, never
        "you" -- without threading the account id from the header, there is
        no way to tell this was a win rather than a loss."""
        self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: "
            "MatchGameRoomStateChangedEvent",
            self.room_event("MatchGameRoomStateType_Playing"),
        )
        self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 10:02:52 AM: Match to {self.ME}: "
            "MatchGameRoomStateChangedEvent",
            self.room_event("MatchGameRoomStateType_MatchCompleted", {
                "finalMatchResult": {
                    "matchId": "45189e2a-2761-456f-9a09-24619f9997b5",
                    "resultList": [
                        {"scope": "MatchScope_Game", "result": "ResultType_WinLoss",
                         "winningTeamId": 1, "reason": "ResultReason_Concede"},
                        {"scope": "MatchScope_Match", "result": "ResultType_WinLoss",
                         "winningTeamId": 1, "reason": "ResultReason_Concede"},
                    ],
                },
            }),
        )
        row = conn.execute("SELECT * FROM matches").fetchone()
        assert row["result"] == "win"
        assert (row["games_won"], row["games_lost"]) == (1, 0)
        assert row["ended_at"] is not None

    def test_loss_is_recorded_when_the_other_team_wins(self, conn):
        me_second_seat = {
            "gameRoomInfo": {
                "gameRoomConfig": {
                    "reservedPlayers": [
                        {"userId": self.ME, "playerName": "igor", "systemSeatId": 1,
                         "teamId": 1, "eventId": "Play"},
                        {"userId": "KQGBB2B3AZDIJELK3SGYMCQDFE", "playerName": "YuZu",
                         "systemSeatId": 2, "teamId": 2, "eventId": "Play"},
                    ],
                    "matchId": "cefb539e-7eb8-4d5f-a197-8c9b65a85262",
                },
                "stateType": "MatchGameRoomStateType_MatchCompleted",
                "finalMatchResult": {
                    "matchId": "cefb539e-7eb8-4d5f-a197-8c9b65a85262",
                    "resultList": [
                        {"scope": "MatchScope_Game", "result": "ResultType_WinLoss",
                         "winningTeamId": 2, "reason": "ResultReason_Game"},
                        {"scope": "MatchScope_Match", "result": "ResultType_WinLoss",
                         "winningTeamId": 2, "reason": "ResultReason_Game"},
                    ],
                },
            }
        }
        self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 10:12:53 AM: Match to {self.ME}: "
            "MatchGameRoomStateChangedEvent",
            {"matchGameRoomStateChangedEvent": me_second_seat},
        )
        row = conn.execute("SELECT * FROM matches").fetchone()
        assert row["result"] == "loss"
        assert (row["games_won"], row["games_lost"]) == (0, 1)
        assert row["opponent_name"] == "YuZu"

    def test_format_is_pulled_from_gre_events_not_room_state(self, conn):
        """superFormat never appears in MatchGameRoomStateChangedEvent -- only
        inside the GRE message stream's gameInfo."""
        self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: "
            "MatchGameRoomStateChangedEvent",
            self.room_event("MatchGameRoomStateType_Playing"),
        )
        gre_body = {
            "greToClientEvent": {
                "greToClientMessages": [
                    {"type": "GREMessageType_GameStateMessage", "gameStateMessage": {
                        "gameInfo": {
                            "matchID": "45189e2a-2761-456f-9a09-24619f9997b5",
                            "superFormat": "SuperFormat_Constructed",
                        }
                    }},
                ]
            }
        }
        p, result = self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: "
            "GreToClientEvent",
            gre_body,
        )
        assert result is True
        assert conn.execute("SELECT format FROM matches").fetchone()["format"] == "Constructed"

    def test_gre_traffic_without_gameinfo_does_not_flood_raw_events(self, conn):
        """Most GreToClientEvent messages (card taps, hover state, timers) carry
        no gameInfo at all -- deliberately unmodeled, not unrecognised, so they
        must not spam raw_events with one row per message."""
        p, result = self.feed_match(
            conn,
            f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: "
            "GreToClientEvent",
            {"greToClientEvent": {"greToClientMessages": [
                {"type": "GREMessageType_TimerStateMessage", "timerStateMessage": {}}
            ]}},
        )
        assert result is True
        assert conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 0


class TestGrePlays:
    """Shapes trimmed from the same real matches: what card left whose hand,
    and in what order. Arena has no "X played card Y" event -- only a
    zone-transfer annotation naming an object id and a source zone id, both
    of which are only resolved to a real card/owner via caches built from
    earlier, easy-to-miss messages. See _extract_gre_event."""

    ME = "TNOMMPVRQZDODPW2LOP67R24FQ"
    OPPONENT = "E6G5EMXF4VH4PGRIMT4GNRTTH4"
    MATCH_ID = "45189e2a-2761-456f-9a09-24619f9997b5"

    def room_playing(self):
        return {"matchGameRoomStateChangedEvent": {"gameRoomInfo": {
            "gameRoomConfig": {
                "reservedPlayers": [
                    {"userId": self.ME, "playerName": "igor", "systemSeatId": 1,
                     "teamId": 1, "eventId": "Play"},
                    {"userId": self.OPPONENT, "playerName": "DanitoRasen91",
                     "systemSeatId": 2, "teamId": 2, "eventId": "Play"},
                ],
                "matchId": self.MATCH_ID,
            },
            "stateType": "MatchGameRoomStateType_Playing",
        }}}

    def zone_transfer(self, ann_id, instance_id, zone_src, category):
        return {"id": ann_id, "affectedIds": [instance_id],
                "type": ["AnnotationType_ZoneTransfer"],
                "details": [
                    {"key": "zone_src", "type": "KeyValuePairValueType_int32",
                     "valueInt32": [zone_src]},
                    {"key": "zone_dest", "type": "KeyValuePairValueType_int32",
                     "valueInt32": [28]},
                    {"key": "category", "type": "KeyValuePairValueType_string",
                     "valueString": [category]},
                ]}

    @pytest.fixture
    def parser(self, conn):
        """A match already under way: room seen (my_seat known), zones and
        the player's own opening-hand object already established -- the
        state every later diff in these tests builds on."""
        p = parse.LogParser(conn)
        header = (f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: ")
        p.feed(header + "MatchGameRoomStateChangedEvent")
        p.feed(json.dumps(self.room_playing()))
        full = {"greToClientEvent": {"greToClientMessages": [{
            "gameStateMessage": {
                "type": "GameStateType_Full",
                "gameInfo": {"matchID": self.MATCH_ID, "gameNumber": 1,
                             "superFormat": "SuperFormat_Constructed"},
                "zones": [
                    {"zoneId": 31, "type": "ZoneType_Hand", "ownerSeatId": 1},
                    {"zoneId": 35, "type": "ZoneType_Hand", "ownerSeatId": 2},
                    {"zoneId": 28, "type": "ZoneType_Battlefield"},
                    {"zoneId": 27, "type": "ZoneType_Stack"},
                ],
                # My own Mountain is visible to me from the start; the
                # opponent's hand is hidden, so no gameObjects entry for it
                # exists yet -- that only arrives when they play it.
                "gameObjects": [
                    {"instanceId": 279, "grpId": 73514, "zoneId": 31},
                ],
            }
        }]}}
        p.feed(header + "GreToClientEvent")
        p.feed(json.dumps(full))
        return p

    def test_my_land_is_recorded_as_self(self, conn, parser):
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "annotations": [self.zone_transfer(154, 279, zone_src=31, category="PlayLand")],
        }}]}}
        header = f"[UnityCrossThreadLogger]8/26/2026 9:57:12 AM: Match to {self.ME}: "
        parser.feed(header + "GreToClientEvent")
        assert parser.feed(json.dumps(diff)) is True

        row = conn.execute("SELECT * FROM match_plays").fetchone()
        assert (row["is_self"], row["action"], row["arena_id"]) == (1, "land", 73514)
        assert row["game_number"] == 1
        assert conn.execute(
            "SELECT is_self FROM match_cards_seen WHERE arena_id = 73514"
        ).fetchone()["is_self"] == 1

    def test_opponents_card_is_revealed_and_recorded_as_opponent(self, conn, parser):
        """The opponent's card only becomes knowable at the exact moment they
        cast it -- its gameObjects entry and its zone-transfer annotation
        arrive together, in the same diff."""
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "gameObjects": [{"instanceId": 400, "grpId": 90492, "zoneId": 27}],
            "annotations": [self.zone_transfer(196, 400, zone_src=35, category="CastSpell")],
        }}]}}
        header = f"[UnityCrossThreadLogger]8/26/2026 9:57:22 AM: Match to {self.ME}: "
        parser.feed(header + "GreToClientEvent")
        parser.feed(json.dumps(diff))

        row = conn.execute("SELECT * FROM match_plays").fetchone()
        assert (row["is_self"], row["action"], row["arena_id"]) == (0, "cast", 90492)

    def test_non_play_zone_transfers_are_not_recorded(self, conn, parser):
        """Resolve (stack -> battlefield) and Draw are zone transfers too but
        do not mean "a card was played"."""
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "annotations": [
                self.zone_transfer(175, 279, zone_src=27, category="Resolve"),
                self.zone_transfer(188, 279, zone_src=32, category="Draw"),
            ],
        }}]}}
        header = f"[UnityCrossThreadLogger]8/26/2026 9:57:12 AM: Match to {self.ME}: "
        parser.feed(header + "GreToClientEvent")
        parser.feed(json.dumps(diff))

        assert conn.execute("SELECT COUNT(*) FROM match_plays").fetchone()[0] == 0

    def test_replaying_the_same_line_does_not_duplicate(self, conn, parser):
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "annotations": [self.zone_transfer(154, 279, zone_src=31, category="PlayLand")],
        }}]}}
        header = f"[UnityCrossThreadLogger]8/26/2026 9:57:12 AM: Match to {self.ME}: "
        parser.feed(header + "GreToClientEvent")
        parser.feed(json.dumps(diff))
        parser.feed(header + "GreToClientEvent")
        parser.feed(json.dumps(diff))

        assert conn.execute("SELECT COUNT(*) FROM match_plays").fetchone()[0] == 1

    def test_a_new_match_clears_the_previous_match_object_cache(self, conn, parser):
        """Regression: Arena reuses small instance ids across different
        matches (confirmed from two real captures), so a stale cache would
        resolve a new match's instance 279 to the previous match's card."""
        other_room = {"matchGameRoomStateChangedEvent": {"gameRoomInfo": {
            "gameRoomConfig": {
                "reservedPlayers": [
                    {"userId": self.ME, "playerName": "igor", "systemSeatId": 2,
                     "teamId": 2, "eventId": "Play"},
                ],
                "matchId": "cefb539e-7eb8-4d5f-a197-8c9b65a85262",
            },
            "stateType": "MatchGameRoomStateType_Playing",
        }}}
        header = f"[UnityCrossThreadLogger]8/26/2026 10:12:53 AM: Match to {self.ME}: "
        parser.feed(header + "MatchGameRoomStateChangedEvent")
        parser.feed(json.dumps(other_room))

        # Instance 279 was never re-established in the new match, so a
        # zone transfer naming it must resolve to nothing, not the old card.
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "annotations": [self.zone_transfer(999, 279, zone_src=31, category="PlayLand")],
        }}]}}
        parser.feed(header + "GreToClientEvent")
        parser.feed(json.dumps(diff))

        assert conn.execute("SELECT COUNT(*) FROM match_plays").fetchone()[0] == 0


class TestGreCombat:
    """Shapes trimmed from a real captured combat: an attack that went
    unblocked, and a separate creature blocked over several turns. Arena has
    no "X attacked Y" event -- combat lives entirely in a creature's own
    attackState/blockState fields, resent across several diffs while combat
    resolves. See _extract_gre_event."""

    ME = "TNOMMPVRQZDODPW2LOP67R24FQ"
    OPPONENT = "E6G5EMXF4VH4PGRIMT4GNRTTH4"
    MATCH_ID = "45189e2a-2761-456f-9a09-24619f9997b5"

    @pytest.fixture
    def parser(self, conn):
        p = parse.LogParser(conn)
        header = f"[UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to {self.ME}: "
        room = {"matchGameRoomStateChangedEvent": {"gameRoomInfo": {
            "gameRoomConfig": {
                "reservedPlayers": [
                    {"userId": self.ME, "playerName": "igor", "systemSeatId": 1,
                     "teamId": 1, "eventId": "Play"},
                    {"userId": self.OPPONENT, "playerName": "DanitoRasen91",
                     "systemSeatId": 2, "teamId": 2, "eventId": "Play"},
                ],
                "matchId": self.MATCH_ID,
            },
            "stateType": "MatchGameRoomStateType_Playing",
        }}}
        p.feed(header + "MatchGameRoomStateChangedEvent")
        p.feed(json.dumps(room))
        full = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Full",
            "gameInfo": {"matchID": self.MATCH_ID, "gameNumber": 1,
                         "superFormat": "SuperFormat_Constructed"},
            "turnInfo": {"turnNumber": 3},
        }}]}}
        p.feed(header + "GreToClientEvent")
        p.feed(json.dumps(full))
        return p

    def feed_gre(self, parser, at, body):
        header = f"[UnityCrossThreadLogger]8/26/2026 9:57:{at} AM: Match to {self.ME}: "
        parser.feed(header + "GreToClientEvent")
        return parser.feed(json.dumps(body))

    def test_my_attacker_targeting_the_player_is_recorded(self, conn, parser):
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "gameObjects": [{
                "instanceId": 280, "grpId": 94051, "ownerSeatId": 1,
                "attackState": "AttackState_Declared", "attackInfo": {"targetId": 2},
            }],
        }}]}}
        assert self.feed_gre(parser, "58", diff) is True

        row = conn.execute("SELECT * FROM match_combat").fetchone()
        assert (row["action"], row["is_self"], row["arena_id"]) == ("attack", 1, 94051)
        assert (row["target_is_player"], row["target_arena_id"]) == (1, None)
        assert row["turn_number"] == 3

    def test_repeated_attacking_state_across_several_diffs_is_not_duplicated(
        self, conn, parser
    ):
        """Real captures show the same attacker resent Declared, then
        Attacking, then Attacking+Unblocked as combat resolves -- one
        creature attacking once, not three attacks."""
        for state in ("AttackState_Declared", "AttackState_Attacking", "AttackState_Attacking"):
            diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
                "type": "GameStateType_Diff",
                "gameObjects": [{
                    "instanceId": 280, "grpId": 94051, "ownerSeatId": 1,
                    "attackState": state, "attackInfo": {"targetId": 2},
                }],
            }}]}}
            self.feed_gre(parser, "58", diff)

        assert conn.execute("SELECT COUNT(*) FROM match_combat").fetchone()[0] == 1

    def test_opponents_blocker_records_which_attacker_it_blocked(self, conn, parser):
        """Trimmed from a real block: the blocker names the attacker's
        instanceId in blockInfo.attackerIds, resolved via the same object
        cache attack tracking uses."""
        reveal_attacker = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "gameObjects": [{"instanceId": 353, "grpId": 90492, "ownerSeatId": 1}],
        }}]}}
        self.feed_gre(parser, "20", reveal_attacker)

        block = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "gameObjects": [{
                "instanceId": 358, "grpId": 104963, "ownerSeatId": 2,
                "blockState": "BlockState_Declared", "blockInfo": {"attackerIds": [353]},
            }],
        }}]}}
        self.feed_gre(parser, "25", block)

        row = conn.execute("SELECT * FROM match_combat WHERE action = 'block'").fetchone()
        assert (row["is_self"], row["arena_id"], row["target_arena_id"]) == (0, 104963, 90492)

    def test_a_new_game_lets_a_reused_instance_id_attack_again(self, conn, parser):
        """Regression: a Bo3's game 2 reuses small instance ids for entirely
        different creatures -- without game_number in the key, game 2's
        first attack would silently collide with game 1's and be dropped."""
        diff = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "gameObjects": [{
                "instanceId": 280, "grpId": 94051, "ownerSeatId": 1,
                "attackState": "AttackState_Declared", "attackInfo": {"targetId": 2},
            }],
        }}]}}
        self.feed_gre(parser, "58", diff)

        new_game = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Full",
            "gameInfo": {"matchID": self.MATCH_ID, "gameNumber": 2,
                         "superFormat": "SuperFormat_Constructed"},
            "turnInfo": {"turnNumber": 1},
        }}]}}
        self.feed_gre(parser, "58", new_game)

        game2_attack = {"greToClientEvent": {"greToClientMessages": [{"gameStateMessage": {
            "type": "GameStateType_Diff",
            "gameObjects": [{
                # Same instanceId (280) and turnNumber (3) as game 1's attack,
                # but a different card and a different game.
                "instanceId": 280, "grpId": 12345, "ownerSeatId": 1,
                "attackState": "AttackState_Declared", "attackInfo": {"targetId": 2},
            }],
        }}]}}
        self.feed_gre(parser, "59", {"greToClientEvent": {"greToClientMessages": [{
            "gameStateMessage": {"type": "GameStateType_Diff", "turnInfo": {"turnNumber": 3}},
        }]}})
        self.feed_gre(parser, "60", game2_attack)

        rows = conn.execute(
            "SELECT game_number, arena_id FROM match_combat ORDER BY game_number"
        ).fetchall()
        assert [(r["game_number"], r["arena_id"]) for r in rows] == [(1, 94051), (2, 12345)]


class TestCardGrants:
    """The theory was that Arena reports inventory *changes* even though it no
    longer reports contents, so a running tracker could accumulate the real
    collection over time. Confirmed false: a real booster opened on this
    machine left no trace anywhere in the log. These shapes are kept and
    tested defensively in case a future payload proves them right, but do not
    expect this extractor to ever fire -- see its docstring in parse.py.
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

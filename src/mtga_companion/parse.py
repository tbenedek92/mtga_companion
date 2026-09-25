"""Turn Player.log lines into database rows.

Written against a real Detailed-Logs sample captured on this machine. The three
line shapes Arena actually emits are:

    [UnityCrossThreadLogger]==> Label {json}          request, single line
    [UnityCrossThreadLogger]8/25/2026 11:46:47 AM     timestamp header
    <== Label(uuid)                                   response header, NO prefix
    {json}                                            payload, its own line

The response payload is *not* on the header line, and the header carries no
`[UnityCrossThreadLogger]` prefix -- both differ from the request shape and from
what most published descriptions of this format say. Parsing responses therefore
needs one line of lookahead, which is what `LogParser` holds.

Extractors are defensive by design. Wizards has been reducing what the log
exposes since 2021, so anything that no longer matches is written to
`raw_events` rather than dropped or guessed at, and nothing here raises.

.. warning::

   **A fourth line shape exists, used only for match traffic**, found by
   capturing a real live game::

       [UnityCrossThreadLogger]8/26/2026 9:57:09 AM: Match to <id>: <Label>
       {json, on the next line}

   or the same with `<id> to Match:` for client-originated messages. `<id>` is
   the player's own persistent Arena account id -- not a per-request
   transaction id like the `<== Label(uuid)` shape uses -- and it is the only
   place in the whole log that says which seat is "me", so `LogParser`
   threads it into the payload as `_my_user_id` for the two match extractors
   that need it. See `_MATCH_HEADER`, `_extract_match_room` and
   `_extract_gre_event`.

   Deck, inventory, rank, draft and match extraction are now all verified
   against real sessions. `GreToClientEvent` carries the full game-rules-engine
   protocol -- board state, hands, the stack, hundreds of messages per match --
   and none of that is modeled here beyond pulling out the match format;
   full play-by-play reconstruction was deliberately out of scope.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from typing import Any, Callable, Iterable

from . import store

log = logging.getLogger(__name__)

# Extractors that have never seen a real payload. Surfaced through
# queries.status() so the gap is visible in the GUI and to agents, rather than
# living only in comments.
UNVERIFIED_EXTRACTORS = ("card_grants",)

_PREFIX = "[UnityCrossThreadLogger]"
# Bare response header, e.g. "<== StartHook(940afb39-...)"
_RESPONSE_HEADER = re.compile(r"^<==\s*([A-Za-z0-9_.]+)\s*\(([^)]*)\)\s*$")
# Prefixed request, e.g. "[UnityCrossThreadLogger]==> GraphGetGraphState {json}"
_REQUEST = re.compile(r"^==>\s*([A-Za-z0-9_.]+)\s*(\{.*)$", re.S)
# Older/simple prefixed form that still carries a payload on one line.
_LABEL_JSON = re.compile(r"^([^{]*?)\s*(\{.*)$", re.S)
# Match traffic only, JSON on the next line, e.g.:
#   "...9:57:09 AM: Match to <id>: MatchGameRoomStateChangedEvent"
#   "...9:57:11 AM: <id> to Match: ClientToGremessage"
# <id> is the player's own persistent account id, not a transaction id.
_MATCH_HEADER = re.compile(
    r"^\[UnityCrossThreadLogger\]\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M: "
    r"(?:Match to (?P<to_id>[A-Za-z0-9]+)|(?P<from_id>[A-Za-z0-9]+) to Match): "
    r"(?P<label>[A-Za-z0-9_]+)\s*$"
)


def _loads(text: str | None) -> Any:
    """Parse JSON, tolerating the double-encoded strings Arena emits."""
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _first(payload: Any, *names: str) -> Any:
    """Read the first present key, trying each spelling case-insensitively."""
    if not isinstance(payload, dict):
        return None
    lowered = {k.lower(): v for k, v in payload.items()}
    for name in names:
        if name in payload:
            return payload[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _walk(payload: Any, *names: str) -> Any:
    """Depth-first search for the first matching key anywhere in the payload."""
    found = _first(payload, *names)
    if found is not None:
        return found
    if isinstance(payload, dict):
        children: Iterable[Any] = payload.values()
    elif isinstance(payload, list):
        children = payload
    else:
        return None
    for child in children:
        result = _walk(child, *names)
        if result is not None:
            return result
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# .NET's DateTime.MinValue. Arena writes it for "never happened", and left as a
# literal it sorts as the oldest real date and reads as a genuine timestamp.
_NEVER = "0001-01-01"


def _attributes(summary: dict[str, Any]) -> dict[str, str | None]:
    """Flatten Arena's [{name, value}] attribute list into a dict.

    Deck metadata -- Format, LastPlayed, LastUpdated, IsFavorite -- lives here
    rather than as top-level fields. Timestamp values arrive JSON-quoted
    (`'"2026-08-23T21:12:53+02:00"'`), so the quotes are stripped, and the
    DateTime.MinValue sentinel becomes None.
    """
    out: dict[str, str | None] = {}
    for attr in summary.get("Attributes") or []:
        if not isinstance(attr, dict):
            continue
        name, value = attr.get("name"), attr.get("value")
        if name is None:
            continue
        if isinstance(value, str):
            if len(value) > 1 and value[0] == value[-1] == '"':
                value = value[1:-1]
            if value.startswith(_NEVER) or not value:
                value = None
        out[name] = value
    return out


def _iter_deck_entries(entries: Any) -> Iterable[tuple[int, int]]:
    """Yield (arena_id, quantity) from either deck-list encoding Arena uses.

    Observed: [{"cardId": 75472, "quantity": 1}, ...]. The flat run-length form
    is also accepted because older payloads used it.
    """
    if isinstance(entries, list) and entries and isinstance(entries[0], dict):
        for entry in entries:
            arena_id = _as_int(_first(entry, "cardId", "CardId", "grpId", "GrpId", "id"))
            qty = _as_int(_first(entry, "quantity", "Quantity", "count", "Count")) or 1
            if arena_id:
                yield arena_id, qty
    elif isinstance(entries, list):
        for i in range(0, len(entries) - 1, 2):
            arena_id, qty = _as_int(entries[i]), _as_int(entries[i + 1])
            if arena_id and qty:
                yield arena_id, qty


def _deck_colors(conn: sqlite3.Connection, deck_id: str) -> str:
    """Derive a deck's colors from its cards; Arena does not report them."""
    rows = conn.execute(
        "SELECT DISTINCT c.colors FROM deck_cards dc JOIN cards c "
        "ON c.arena_id = dc.arena_id WHERE dc.deck_id = ? AND dc.board = 'main'",
        (deck_id,),
    )
    found = {ch for (colors,) in rows if colors for ch in colors.split(",") if ch}
    return "".join(ch for ch in "WUBRG" if ch in found)


# --------------------------------------------------------------------------
# Extractors. Each returns True if it wrote something, False to fall through.
# --------------------------------------------------------------------------


def _extract_decks(conn: sqlite3.Connection, payload: Any) -> bool:
    """Decks come from two sibling keys that must be joined on deck id.

    `DeckSummaries` holds name and attributes; `Decks` is a dict keyed by the
    same ids holding MainDeck/Sideboard card lists. Neither is usable alone.
    """
    summaries = _first(payload, "DeckSummaries", "DeckSummariesV2")
    lists = _first(payload, "Decks")
    if not isinstance(summaries, list) or not summaries:
        return False
    if not isinstance(lists, dict):
        lists = {}

    written = 0
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        deck_id = _first(summary, "DeckId", "deckId", "id")
        if deck_id is None:
            continue
        deck_id = str(deck_id)
        attrs = _attributes(summary)

        # Arena ships ~100 starter/precon decks in every payload. Ones the
        # player has actually built or edited carry edit-tracking attributes.
        description = str(_first(summary, "Description") or "")
        is_player = bool(attrs.get("LastUpdated") or attrs.get("Version"))
        if description.startswith("Decks/Precon"):
            is_player = False

        # The deck row must exist before its cards: deck_cards.deck_id is a
        # foreign key. Colors are derived from the cards, so they are filled in
        # afterwards rather than computed up front.
        conn.execute(
            "INSERT INTO decks(deck_id, name, format, last_updated, "
            "last_played, is_valid, deck_kind, is_favorite, raw) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(deck_id) DO UPDATE SET name=excluded.name, "
            "format=excluded.format, "
            "last_updated=excluded.last_updated, last_played=excluded.last_played, "
            "deck_kind=excluded.deck_kind, is_favorite=excluded.is_favorite, "
            "raw=excluded.raw",
            (
                deck_id,
                _first(summary, "Name", "name"),
                attrs.get("Format") or None,
                attrs.get("LastUpdated"),
                attrs.get("LastPlayed"),
                None,
                "player" if is_player else "precon",
                1 if str(attrs.get("IsFavorite", "")).lower() == "true" else 0,
                json.dumps(summary)[:20000],
            ),
        )

        contents = lists.get(deck_id) or {}
        boards = {
            "main": _first(contents, "MainDeck", "mainDeck"),
            "sideboard": _first(contents, "Sideboard", "sideboard"),
            "commander": _first(contents, "CommandZone", "commandZone"),
        }
        if any(v is not None for v in boards.values()):
            conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
            for board, entries in boards.items():
                for arena_id, qty in _iter_deck_entries(entries):
                    conn.execute(
                        "INSERT INTO deck_cards(deck_id, arena_id, quantity, board) "
                        "VALUES(?,?,?,?) ON CONFLICT(deck_id, arena_id, board) "
                        "DO UPDATE SET quantity = excluded.quantity",
                        (deck_id, arena_id, qty, board),
                    )

        conn.execute(
            "UPDATE decks SET colors = ? WHERE deck_id = ?",
            (_deck_colors(conn, deck_id), deck_id),
        )
        written += 1

    log.info("Parsed %d decks", written)
    return written > 0


def _extract_inventory(conn: sqlite3.Connection, payload: Any) -> bool:
    inv = _walk(payload, "InventoryInfo", "inventoryInfo")
    if not isinstance(inv, dict):
        return False
    conn.execute(
        "INSERT OR REPLACE INTO inventory(captured_at, gold, gems, wc_common, "
        "wc_uncommon, wc_rare, wc_mythic, vault_progress, raw) "
        "VALUES(datetime('now'),?,?,?,?,?,?,?,?)",
        (
            _as_int(_first(inv, "Gold")),
            _as_int(_first(inv, "Gems")),
            _as_int(_first(inv, "WildCardCommons")),
            _as_int(_first(inv, "WildCardUnCommons")),
            _as_int(_first(inv, "WildCardRares")),
            _as_int(_first(inv, "WildCardMythics")),
            _first(inv, "TotalVaultProgress", "vaultProgress"),
            json.dumps({k: v for k, v in inv.items()
                        if not isinstance(v, (list, dict))})[:20000],
        ),
    )
    log.info("Parsed inventory snapshot")
    return True


def _extract_rank(conn: sqlite3.Connection, payload: Any) -> bool:
    """Rank info. The observed payload no longer carries a rank *class*
    (Bronze/Silver/Gold) at all -- only levels and season match records -- so
    presence of a level, not a class, is what marks this payload as rank data."""
    if not isinstance(payload, dict):
        return False
    con_level = _as_int(_walk(payload, "constructedLevel", "ConstructedLevel"))
    lim_level = _as_int(_walk(payload, "limitedLevel", "LimitedLevel"))
    if con_level is None and lim_level is None:
        return False
    conn.execute(
        "INSERT OR REPLACE INTO ranks(captured_at, constructed_class, "
        "constructed_level, constructed_step, limited_class, limited_level, "
        "limited_step, constructed_won, constructed_lost, limited_won, "
        "limited_lost, raw) VALUES(datetime('now'),?,?,?,?,?,?,?,?,?,?,?)",
        (
            _walk(payload, "constructedClass", "ConstructedClass"),
            con_level,
            _as_int(_walk(payload, "constructedStep", "ConstructedStep")),
            _walk(payload, "limitedClass", "LimitedClass"),
            lim_level,
            _as_int(_walk(payload, "limitedStep", "LimitedStep")),
            _as_int(_walk(payload, "constructedMatchesWon")),
            _as_int(_walk(payload, "constructedMatchesLost")),
            _as_int(_walk(payload, "limitedMatchesWon")),
            _as_int(_walk(payload, "limitedMatchesLost")),
            json.dumps(payload)[:20000],
        ),
    )
    log.info("Parsed rank snapshot")
    return True


def _extract_card_grants(conn: sqlite3.Connection, payload: Any) -> bool:
    """Record cards Arena grants us: boosters, rewards, draft payouts.

    Arena stopped reporting collection *contents* in 2021; the theory was that
    it still reports inventory *changes*, so a tracker that is running could
    build an increasing accurate collection over time via `InventoryInfo.Changes`
    or reward payloads shaped like `CardsAdded`/`GrantedCards`.

    .. note:: **Confirmed dead, not just unverified.** A real booster opened on
       this machine (2026-08-26) produced no `InventoryInfo.Changes`, no
       `CardsAdded`/`GrantedCards`, and no request/response of any kind whose
       label contains "card", "pack", "open", "store", "reward", or "grant" --
       checked across both `Player.log` and `Player-prev.log`. The card the
       booster granted appears nowhere in either file. Wizards does not log
       booster contents at all anymore, so this extractor has nothing to read
       and cannot be fixed by correcting its shape. The only real source for
       newly acquired cards is the memory sync (`memread.sync_collection`, run
       via `scripts/sync_collection.py`) -- re-run it after opening boosters.
       This function is kept in case a future payload shape proves it wrong,
       but do not expect it to ever fire.
    """
    changes = _first(payload, "Changes", "changes")
    if not isinstance(changes, list) or not changes:
        # Reward payloads carry their own card lists.
        for key in ("CardsAdded", "cardsAdded", "GrantedCards", "grantedCards"):
            found = _walk(payload, key)
            if isinstance(found, list) and found:
                changes = [{"CardsAdded": found}]
                break
        else:
            return False

    context = _first(payload, "Context", "context", "source") or "inventory_change"
    written = 0
    for change in changes:
        if not isinstance(change, dict):
            continue
        added = None
        for key in ("CardsAdded", "cardsAdded", "GrantedCards", "grantedCards"):
            candidate = _first(change, key)
            if isinstance(candidate, list):
                added = candidate
                break
        if not added:
            continue
        change_ctx = str(_first(change, "Context", "context", "source") or context)
        # Arena sends a flat list of grpIds with repeats meaning quantity.
        counted: dict[int, int] = {}
        for entry in added:
            arena_id = (
                _as_int(entry)
                if not isinstance(entry, dict)
                else _as_int(_first(entry, "grpId", "GrpId", "cardId", "CardId"))
            )
            if arena_id is None:
                continue
            qty = 1
            if isinstance(entry, dict):
                qty = _as_int(_first(entry, "quantity", "Quantity", "count")) or 1
            counted[arena_id] = counted.get(arena_id, 0) + qty

        for arena_id, qty in counted.items():
            # Keyed on the change's own identity so replaying a log -- which
            # happens on every startup via Player-prev.log -- cannot double-count.
            key_src = json.dumps(
                [_first(change, "Id", "id", "SeqId"), change_ctx, arena_id, qty],
                sort_keys=True,
            )
            grant_key = hashlib.sha256(key_src.encode()).hexdigest()[:32]
            conn.execute(
                "INSERT INTO card_grants(grant_key, seen_at, arena_id, quantity, "
                "context) VALUES(?, datetime('now'), ?, ?, ?) "
                "ON CONFLICT(grant_key) DO NOTHING",
                (grant_key, arena_id, qty, change_ctx),
            )
            written += 1

    if written:
        log.info("Recorded %d card grants", written)
    return written > 0


def _extract_match_room(conn: sqlite3.Connection, payload: Any) -> bool:
    """Match room state: who's in the match, and -- once it ends -- who won.

    Verified against two real completed matches (one won by concede, one lost
    normally). Arena never says "which seat is me" inside this payload -- the
    only place it says so at all is the log line's own header, threaded in as
    payload["_my_user_id"] by LogParser (see _MATCH_HEADER). Without it there
    is no way to tell a win from a loss, since `finalMatchResult` is phrased
    as "team N won", not "you won".
    """
    room = _first(payload, "matchGameRoomStateChangedEvent")
    if not isinstance(room, dict):
        return False
    info = _first(room, "gameRoomInfo")
    if not isinstance(info, dict):
        return False
    config = _first(info, "gameRoomConfig") or {}
    match_id = _first(config, "matchId")
    if match_id is None:
        return False
    match_id = str(match_id)

    my_user_id = payload.get("_my_user_id") if isinstance(payload, dict) else None
    reserved = [p for p in (_first(config, "reservedPlayers") or []) if isinstance(p, dict)]
    me = next((p for p in reserved if p.get("userId") == my_user_id), None)
    opponent = next((p for p in reserved if p.get("userId") != my_user_id), None)
    my_team = me.get("teamId") if me else None
    my_seat = me.get("systemSeatId") if me else None

    # The GRE cache tracks exactly one match at a time (Arena never runs two
    # concurrently); a differing match_id means a new match has started, so
    # its per-match object/zone caches must not carry over.
    cache = payload.get("_gre_cache") if isinstance(payload, dict) else None
    if isinstance(cache, dict):
        if cache.get("match_id") != match_id:
            cache.clear()
            cache["match_id"] = match_id
        if my_seat is not None:
            cache["my_seat"] = my_seat

    conn.execute(
        "INSERT INTO matches(match_id, started_at, event_name, opponent_name, my_seat, raw) "
        "VALUES(?, datetime('now'), ?, ?, ?, ?) "
        "ON CONFLICT(match_id) DO UPDATE SET "
        "event_name = COALESCE(matches.event_name, excluded.event_name), "
        "opponent_name = COALESCE(matches.opponent_name, excluded.opponent_name), "
        "my_seat = COALESCE(matches.my_seat, excluded.my_seat), "
        "raw = excluded.raw",
        (
            match_id,
            (me or {}).get("eventId") or _first(config, "eventId"),
            (opponent or {}).get("playerName"),
            my_seat,
            json.dumps(room)[:20000],
        ),
    )

    if _first(info, "stateType") == "MatchGameRoomStateType_MatchCompleted":
        # resultList holds one MatchScope_Game entry per game played plus one
        # MatchScope_Match entry for the overall winner -- each names a
        # winningTeamId, never "you", so my_team is what turns it into
        # win/loss/draw from the player's own point of view.
        results = _first(_first(info, "finalMatchResult") or {}, "resultList") or []
        games_won = games_lost = 0
        match_result = None
        if my_team is not None:
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                winner = entry.get("winningTeamId")
                if entry.get("scope") == "MatchScope_Game":
                    if winner == my_team:
                        games_won += 1
                    elif winner is not None:
                        games_lost += 1
                elif entry.get("scope") == "MatchScope_Match":
                    match_result = "win" if winner == my_team else (
                        "draw" if winner is None else "loss"
                    )
        conn.execute(
            "UPDATE matches SET ended_at = datetime('now'), "
            "result = COALESCE(?, result), games_won = ?, games_lost = ? "
            "WHERE match_id = ?",
            (match_result, games_won, games_lost, match_id),
        )
    return True


def _annotation_detail(ann: dict[str, Any], key: str) -> Any:
    """Pull one value out of a GRE annotation's `details` list.

    Each entry is `{"key": ..., "type": "KeyValuePairValueType_<T>", "value<T>": [...]}`
    -- a typed key/value pair with the value wrapped in a single-element list
    regardless of type, apparently to share one schema across scalar and list
    values.
    """
    for detail in ann.get("details") or []:
        if not isinstance(detail, dict) or detail.get("key") != key:
            continue
        for field, value in detail.items():
            if field.startswith("value") and isinstance(value, list) and value:
                return value[0]
    return None


# The two GRE annotation categories that mean "a card left hand for real" --
# Resolve/Draw/etc. are zone transfers too but not what "played a card" means.
_PLAY_ACTIONS = {"CastSpell": "cast", "PlayLand": "land"}


def _extract_gre_event(conn: sqlite3.Connection, payload: Any) -> bool:
    """Track the match format, what was cast or played, and combat.

    `GreToClientEvent` carries the full GRE protocol -- board state, hands,
    the stack, hundreds of messages per match -- and almost none of that is
    modeled here. What is: `superFormat`, which never appears in the room
    state `_extract_match_room` reads; `AnnotationType_ZoneTransfer`
    annotations with category `CastSpell` or `PlayLand`, which is how Arena
    reports "a card left hand" -- there is no more direct "X played card Y"
    event anywhere in the protocol; and each creature's own `attackState` /
    `blockState` fields, which is where combat lives instead -- there is no
    "X attacked Y" annotation the way there is for casting.

    Three things only make sense with real captured matches in hand:

    - Zone transfers and combat both name an object's `instanceId`, not its
      card. `instanceId -> grpId` is only sent once, in a `gameObjects`
      entry, the first time an object becomes known to us -- for our own
      cards that is turn 1 (they start in a zone we can already see), for
      the opponent's it is the moment they reveal it, in the very same
      message as whatever revealed it. Either way the mapping must be
      cached (payload["_gre_cache"], threaded in by LogParser) across many
      calls, since it is never repeated afterwards.
    - A zone transfer names the source zone's *id*, not its owner. Zone
      ownership (`ownerSeatId`) is likewise sent once, in a `zones` list,
      and only for per-seat zones -- shared zones like the battlefield or
      stack have none, which is exactly why category matters:
      CastSpell/PlayLand always originate in a hand, a per-seat zone, so the
      owner is always knowable. Combat objects carry `ownerSeatId` directly,
      no zone lookup needed.
    - Combat has no discrete "declared" event to key off of the way a zone
      transfer's annotation id does -- Arena just resends the same
      attacking/blocking creature's full state across several diffs while
      combat resolves. The natural key is (game, turn, instanceId, action):
      re-declaring within one combat collides into the same row via
      ON CONFLICT DO NOTHING, and a later turn or game does not, because
      turnNumber and gameNumber are cached the same way as everything else
      here -- neither is resent on every message either.

    Always returns True once the envelope matches, even when nothing in this
    particular batch was new -- most GRE traffic (taps, hovers, timers) is
    deliberately unmodeled, not unrecognised, and treating it as "no
    extractor matched" would flood raw_events with hundreds of rows per match.
    """
    event = _first(payload, "greToClientEvent")
    if not isinstance(event, dict):
        return False
    cache = payload.get("_gre_cache") if isinstance(payload, dict) else None
    if not isinstance(cache, dict):
        cache = {}

    for msg in _first(event, "greToClientMessages") or []:
        gsm = _first(msg, "gameStateMessage")
        if not isinstance(gsm, dict):
            continue

        info = _first(gsm, "gameInfo")
        if isinstance(info, dict):
            match_id = _first(info, "matchID", "matchId")
            fmt = _first(info, "superFormat")
            if match_id is not None and fmt:
                conn.execute(
                    "UPDATE matches SET format = ? WHERE match_id = ? AND format IS NULL",
                    (str(fmt).removeprefix("SuperFormat_"), str(match_id)),
                )
            game_number = _first(info, "gameNumber")
            if game_number is not None:
                cache["game_number"] = game_number

        turn_info = _first(gsm, "turnInfo")
        if isinstance(turn_info, dict) and turn_info.get("turnNumber") is not None:
            cache["turn_number"] = turn_info["turnNumber"]

        if _first(gsm, "type") == "GameStateType_Full":
            # A fresh full state means a new game -- Bo3's game 2 reuses
            # small instance/zone ids for entirely different objects.
            cache["objects"] = {}
            cache["zones"] = {}
        objects = cache.setdefault("objects", {})
        zones = cache.setdefault("zones", {})

        for zone in _first(gsm, "zones") or []:
            if isinstance(zone, dict) and zone.get("zoneId") is not None \
                    and zone.get("ownerSeatId") is not None:
                zones[zone["zoneId"]] = zone["ownerSeatId"]

        for obj in _first(gsm, "gameObjects") or []:
            if isinstance(obj, dict) and obj.get("instanceId") is not None \
                    and obj.get("grpId") is not None:
                objects[obj["instanceId"]] = obj["grpId"]

        match_id = cache.get("match_id")
        my_seat = cache.get("my_seat")
        opponent_seat = 3 - my_seat if my_seat in (1, 2) else None
        game_number = cache.get("game_number") or 0
        turn_number = cache.get("turn_number") or 0

        # A second pass over the same list: a creature's own gameObjects
        # entry and the object it's attacking/blocking can both arrive in
        # this one message, so the objects cache above must be fully warm
        # before either is resolved.
        for obj in _first(gsm, "gameObjects") or []:
            if not isinstance(obj, dict) or match_id is None:
                continue
            instance_id = obj.get("instanceId")
            grp_id = obj.get("grpId") or objects.get(instance_id)
            if instance_id is None or grp_id is None:
                continue
            owner_seat = obj.get("ownerSeatId")
            is_self = None if my_seat is None or owner_seat is None else (
                1 if owner_seat == my_seat else 0
            )

            attack_state = obj.get("attackState")
            if attack_state in ("AttackState_Declared", "AttackState_Attacking"):
                target_id = (obj.get("attackInfo") or {}).get("targetId")
                target_arena_id = objects.get(target_id) if target_id is not None else None
                target_is_player = (
                    1 if target_id is not None and target_id in (my_seat, opponent_seat)
                    else 0 if target_arena_id is not None else None
                )
                conn.execute(
                    "INSERT INTO match_combat(match_id, game_number, turn_number, "
                    "instance_id, seq, action, arena_id, is_self, target_arena_id, "
                    "target_is_player) VALUES(?,?,?,?,?,'attack',?,?,?,?) "
                    "ON CONFLICT(match_id, game_number, turn_number, instance_id, action) "
                    "DO NOTHING",
                    (match_id, game_number, turn_number, instance_id,
                     gsm.get("gameStateId"), grp_id, is_self, target_arena_id,
                     target_is_player),
                )

            block_state = obj.get("blockState")
            if block_state in ("BlockState_Declared", "BlockState_Blocking"):
                attacker_ids = (obj.get("blockInfo") or {}).get("attackerIds") or []
                target_arena_id = objects.get(attacker_ids[0]) if attacker_ids else None
                conn.execute(
                    "INSERT INTO match_combat(match_id, game_number, turn_number, "
                    "instance_id, seq, action, arena_id, is_self, target_arena_id, "
                    "target_is_player) VALUES(?,?,?,?,?,'block',?,?,?,0) "
                    "ON CONFLICT(match_id, game_number, turn_number, instance_id, action) "
                    "DO NOTHING",
                    (match_id, game_number, turn_number, instance_id,
                     gsm.get("gameStateId"), grp_id, is_self, target_arena_id),
                )
        for ann in _first(gsm, "annotations") or []:
            if not isinstance(ann, dict):
                continue
            if "AnnotationType_ZoneTransfer" not in (ann.get("type") or []):
                continue
            action = _PLAY_ACTIONS.get(_annotation_detail(ann, "category"))
            if action is None or match_id is None:
                continue
            affected = ann.get("affectedIds") or []
            if not affected:
                continue
            grp_id = objects.get(affected[0])
            if grp_id is None:
                continue
            zone_src = _annotation_detail(ann, "zone_src")
            owner_seat = zones.get(zone_src) if zone_src is not None else None
            is_self = None if my_seat is None or owner_seat is None else (
                1 if owner_seat == my_seat else 0
            )
            conn.execute(
                "INSERT INTO match_plays(match_id, seq, game_number, arena_id, "
                "is_self, action) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(match_id, seq) DO NOTHING",
                (match_id, ann.get("id"), cache.get("game_number"), grp_id,
                 is_self, action),
            )
            if is_self is not None:
                # Feeds collection.py's 'played' ownership source: casting a
                # card proves we own it, distinct from just having seen it
                # (which proves nothing -- the opponent's card is theirs).
                conn.execute(
                    "INSERT INTO match_cards_seen(match_id, arena_id, is_self) "
                    "VALUES(?,?,?) ON CONFLICT(match_id, arena_id, is_self) DO NOTHING",
                    (match_id, grp_id, is_self),
                )
    return True


def _extract_draft_pick(conn: sqlite3.Connection, payload: Any) -> bool:
    """Draft picks, corrected against a real QuickDraft (bot draft) session.

    The response's real fields are JSON-encoded as a string under `Payload`,
    not delivered as a nested object. Arena never reports which single card a
    given pick chose -- only `PickedCards`, the cumulative list so far -- and
    that list is only complete once `DraftStatus` reaches `"Completed"`, so
    that is the one moment this records from: one row per entry of the final
    `PickedCards`, keyed by its index so re-feeding the same line (Arena
    replays `Player-prev.log` on every startup) does not double-count.
    """
    raw = _first(payload, "Payload", "payload")
    inner = _loads(raw) if isinstance(raw, str) else payload
    if not isinstance(inner, dict):
        return False
    if str(_first(inner, "DraftStatus", "draftStatus") or "") != "Completed":
        return False
    picked = _first(inner, "PickedCards", "pickedCards")
    if not isinstance(picked, list) or not picked:
        return False
    draft_id = str(_first(inner, "EventName", "eventName") or "draft")
    written = 0
    for i, card in enumerate(picked):
        arena_id = _as_int(card)
        if arena_id is None:
            continue
        conn.execute(
            "INSERT INTO draft_picks(draft_id, pack_number, pick_number, "
            "arena_id, pack_cards) VALUES(?,0,?,?,'') "
            "ON CONFLICT(draft_id, pack_number, pick_number) DO UPDATE SET "
            "arena_id = excluded.arena_id",
            (draft_id, i, arena_id),
        )
        written += 1
    return written > 0


# Label substrings mapped to extractors. StartHook is one payload carrying
# inventory, decks and more, so several extractors run against it.
_ROUTES: list[tuple[tuple[str, ...], tuple[Callable[..., bool], ...]]] = [
    (("StartHook",), (_extract_inventory, _extract_decks, _extract_rank,
                      _extract_card_grants)),
    (("Inventory", "PostMatchUpdate", "Rewards", "Booster", "OpenBooster",
      "Quest"), (_extract_card_grants,)),
    (("Deck", "DeckSummaries", "DeckList"), (_extract_decks,)),
    (("Rank", "CombinedRankInfo"), (_extract_rank,)),
    (("GreToClient", "MatchGameRoom", "matchGameRoom"),
     (_extract_match_room, _extract_gre_event)),
    (("Draft", "BotDraft"), (_extract_draft_pick,)),
]

# Payload-bearing labels we deliberately ignore: telemetry, UI and store chatter.
_IGNORE = (
    "Analytics", "BIEvent", "LogBusinessEvents", "Telemetry", "PerfEvent",
    "GraphGetGraphState", "GetFormats",
    # Deliberately skipped: season start/end metadata, and the precon catalogue
    # which duplicates the decks StartHook already delivers. Listing them keeps
    # raw_events meaningful -- anything left there is genuinely unexpected.
    "RankGetSeasonAndRankDetails", "DeckGetAllPreconDecksV3",
    "EventGetCoursesV2", "EventGetActiveMatches",
)


class LogParser:
    """Feeds log lines in order, holding the one line of state responses need."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._pending: str | None = None
        self._match_pending: tuple[str, str] | None = None
        # Running state for the currently active match's GRE stream (object
        # instance ids and zone ownership are only sent once, when first
        # seen -- see _extract_gre_event). Reset per match, since Arena
        # reuses small instance/zone ids across different matches.
        self._gre_cache: dict[str, Any] = {}

    def feed(self, line: str) -> bool:
        """Consume one line. Returns True if it produced a database write."""
        header = _RESPONSE_HEADER.match(line)
        if header:
            # Response header; its JSON body is on a following line.
            self._pending = header.group(1)
            return False

        if self._pending is not None:
            if not line.strip():
                return False  # blank line between header and body
            if line.startswith("{"):
                label, self._pending = self._pending, None
                return self._dispatch(label, line, is_response=True)
            self._pending = None  # body never arrived; drop the expectation

        match_header = _MATCH_HEADER.match(line)
        if match_header:
            # Match traffic; JSON body is on a following line too, but the
            # header itself carries the player's own account id, not just a
            # label -- see _MATCH_HEADER.
            my_id = match_header.group("to_id") or match_header.group("from_id")
            self._match_pending = (match_header.group("label"), my_id)
            return False

        if self._match_pending is not None:
            if not line.strip():
                return False
            if line.startswith("{"):
                label, my_id = self._match_pending
                self._match_pending = None
                return self._dispatch(label, line, is_response=True, my_user_id=my_id)
            self._match_pending = None

        if line.startswith(_PREFIX):
            body = line[len(_PREFIX):].strip()
            request = _REQUEST.match(body)
            if request:
                return self._dispatch(*request.groups(), is_response=False)
            same_line = _LABEL_JSON.match(body)
            if same_line:
                label, payload = same_line.groups()
                return self._dispatch(
                    label.strip() or "unknown", payload.strip(), is_response=True
                )
        return False

    def _dispatch(
        self,
        label: str,
        payload_text: str,
        is_response: bool = True,
        my_user_id: str | None = None,
    ) -> bool:
        if any(skip in label for skip in _IGNORE):
            return False
        payload = _loads(payload_text)
        if payload is None:
            return False

        # Outgoing requests are `{"id": ..., "request": "<json string>"}`
        # envelopes. Unwrap to the real body; if that body is empty there is
        # nothing to extract and nothing worth flagging as unparsed either.
        if isinstance(payload, dict) and set(payload) <= {"id", "request"}:
            inner = _loads(payload.get("request"))
            if not isinstance(inner, dict) or not inner:
                return False
            payload = inner

        if my_user_id and isinstance(payload, dict):
            # Neither key is a field Arena sends -- injected so the match
            # extractors can tell which seat is the player's own (see
            # _MATCH_HEADER) and share running per-match state across many
            # calls (object/zone caches only arrive once each; see
            # _extract_gre_event). The cache is the same dict every time, by
            # reference, so extractors can mutate it in place.
            payload = {**payload, "_my_user_id": my_user_id, "_gre_cache": self._gre_cache}

        for needles, extractors in _ROUTES:
            if not any(needle in label for needle in needles):
                continue
            wrote = False
            for extractor in extractors:
                try:
                    wrote |= extractor(self.conn, payload)
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("%s failed on %s: %s", extractor.__name__, label, exc)
                    store.record_raw_event(self.conn, label, f"error: {exc}", payload_text)
            if not wrote and is_response:
                # An unrecognised *response* means the server sent something we
                # no longer understand -- worth surfacing. An unrecognised
                # request is just our own client chatter, so it is not recorded.
                store.record_raw_event(
                    self.conn, label, "no extractor matched", payload_text
                )
            return wrote
        return False


def handle_line(conn: sqlite3.Connection, line: str) -> bool:
    """Stateless single-line entry point, kept for callers that don't need
    response bodies (which span two lines and require `LogParser`)."""
    return LogParser(conn).feed(line)

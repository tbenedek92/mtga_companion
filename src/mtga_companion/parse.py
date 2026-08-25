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

   **Match and draft extraction is UNVERIFIED.** `_extract_match_room` and
   `_extract_draft_pick` were written from the documented format, not from an
   observed payload -- no game or draft has been captured yet. Deck, inventory
   and rank extraction *is* verified against a real session.

   To finish them: play a match (or do a draft), run ``mtga-companion ingest``,
   then inspect the ``raw_events`` table for rows with reason
   ``no extractor matched``. Those rows hold the real payloads, so the
   extractors can be corrected without replaying the session.
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
UNVERIFIED_EXTRACTORS = ("match", "draft", "card_grants")

_PREFIX = "[UnityCrossThreadLogger]"
# Bare response header, e.g. "<== StartHook(940afb39-...)"
_RESPONSE_HEADER = re.compile(r"^<==\s*([A-Za-z0-9_.]+)\s*\(([^)]*)\)\s*$")
# Prefixed request, e.g. "[UnityCrossThreadLogger]==> GraphGetGraphState {json}"
_REQUEST = re.compile(r"^==>\s*([A-Za-z0-9_.]+)\s*(\{.*)$", re.S)
# Older/simple prefixed form that still carries a payload on one line.
_LABEL_JSON = re.compile(r"^([^{]*?)\s*(\{.*)$", re.S)


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

    Arena stopped reporting collection *contents* in 2021 but still reports
    inventory *changes*, so a tracker that is running builds an increasingly
    accurate collection over time. `InventoryInfo.Changes` is the delta feed;
    reward payloads use `CardsAdded`/`GrantedCards` shapes.

    .. note:: The exact shape is **unverified** -- no booster has been opened
       into a captured log yet. Anything unrecognised is left for `raw_events`.
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
    """Match room state. Shapes here are still provisional -- no match has been
    played into a captured log yet, so this is written from the documented
    format and will be corrected against a real game."""
    room = _walk(payload, "matchGameRoomStateChangedEvent")
    if not isinstance(room, dict):
        return False
    state = _walk(room, "gameRoomInfo", "GameRoomInfo") or room
    config = _walk(state, "gameRoomConfig", "GameRoomConfig") or {}
    match_id = _first(config, "matchId", "MatchId") or _walk(state, "matchId", "MatchId")
    if match_id is None:
        return False
    match_id = str(match_id)
    conn.execute(
        "INSERT INTO matches(match_id, started_at, event_name, raw) "
        "VALUES(?, datetime('now'), ?, ?) "
        "ON CONFLICT(match_id) DO UPDATE SET raw = excluded.raw",
        (match_id, _first(config, "eventId", "EventId"), json.dumps(room)[:20000]),
    )
    if _walk(state, "stateType", "StateType") == "MatchGameRoomStateType_MatchCompleted":
        conn.execute(
            "UPDATE matches SET ended_at = datetime('now') WHERE match_id = ?",
            (match_id,),
        )
    return True


def _extract_draft_pick(conn: sqlite3.Connection, payload: Any) -> bool:
    """Draft picks. Provisional until a draft appears in a captured log."""
    pack = _walk(payload, "PackCards", "packCards")
    pick = _as_int(_walk(payload, "PickNumber", "pickNumber", "SelfPick"))
    packno = _as_int(_walk(payload, "PackNumber", "packNumber", "SelfPack"))
    if pack is None or pick is None or packno is None:
        return False
    draft_id = str(_walk(payload, "DraftId", "draftId", "EventName", "eventName") or "draft")
    chosen = _as_int(_walk(payload, "CardId", "cardId", "GrpId", "grpId"))
    if isinstance(pack, str):
        pack_list = [p for p in pack.split(",") if p]
    elif isinstance(pack, list):
        pack_list = [str(p) for p in pack]
    else:
        pack_list = []
    conn.execute(
        "INSERT INTO draft_picks(draft_id, pack_number, pick_number, arena_id, "
        "pack_cards) VALUES(?,?,?,?,?) "
        "ON CONFLICT(draft_id, pack_number, pick_number) DO UPDATE SET "
        "arena_id = COALESCE(excluded.arena_id, draft_picks.arena_id), "
        "pack_cards = excluded.pack_cards",
        (draft_id, packno, pick, chosen, ",".join(pack_list)),
    )
    return True


# Label substrings mapped to extractors. StartHook is one payload carrying
# inventory, decks and more, so several extractors run against it.
_ROUTES: list[tuple[tuple[str, ...], tuple[Callable[..., bool], ...]]] = [
    (("StartHook",), (_extract_inventory, _extract_decks, _extract_rank,
                      _extract_card_grants)),
    (("Inventory", "PostMatchUpdate", "Rewards", "Booster", "OpenBooster",
      "Quest"), (_extract_card_grants,)),
    (("Deck", "DeckSummaries", "DeckList"), (_extract_decks,)),
    (("Rank", "CombinedRankInfo"), (_extract_rank,)),
    (("GreToClient", "MatchGameRoom", "matchGameRoom"), (_extract_match_room,)),
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
        self, label: str, payload_text: str, is_response: bool = True
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

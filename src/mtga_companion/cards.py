"""Card reference data.

Primary source is Scryfall's `default_cards` bulk export, filtered to objects
that carry an `arena_id` -- that field is the join key to the `grpId` values
Arena writes into Player.log.

Fallback is Arena's own card database, a plain SQLite file shipped with the
game. It covers rebalanced/Alchemy and digital-only printings that Scryfall may
not map to an arena_id, but its type/subtype columns are numeric enum ids and
rules text needs an Abilities join, so it is deliberately second choice.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

from . import paths, store

log = logging.getLogger(__name__)

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
# Scryfall asks API consumers to identify themselves and set Accept explicitly.
_HEADERS = {
    "User-Agent": "mtga-companion/0.1 (local personal deck tool)",
    "Accept": "application/json",
}
_META_UPDATED_AT = "scryfall_updated_at"
_MIN_REFRESH = timedelta(hours=20)


def _bulk_entry(client: httpx.Client, kind: str = "default_cards") -> dict[str, Any]:
    resp = client.get(BULK_INDEX_URL, headers=_HEADERS, timeout=30.0)
    resp.raise_for_status()
    for entry in resp.json()["data"]:
        if entry["type"] == kind:
            return entry
    raise RuntimeError(f"Scryfall bulk export {kind!r} not found")


def _download(client: httpx.Client, url: str, dest: Path) -> Path:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url, headers=_HEADERS, timeout=None) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    return dest


def _iter_arena_cards(bulk_file: Path) -> Iterator[dict[str, Any]]:
    """Stream the gzipped JSONL export, yielding printings with an arena_id.

    Decompressed the export is hundreds of MB, so it is read a line at a time
    rather than loaded into memory.
    """
    with gzip.open(bulk_file, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                card = json.loads(line)
            except json.JSONDecodeError:
                continue
            if card.get("arena_id") is not None:
                yield card


def _face(card: dict[str, Any], key: str) -> Any:
    """Read a field that lives on the card or, for DFCs, on its first face."""
    if card.get(key) is not None:
        return card[key]
    faces = card.get("card_faces") or []
    if faces and faces[0].get(key) is not None:
        return faces[0][key]
    return None


def _row_from_scryfall(card: dict[str, Any]) -> tuple:
    faces = card.get("card_faces") or []
    oracle_text = card.get("oracle_text")
    if oracle_text is None and faces:
        oracle_text = "\n//\n".join(f.get("oracle_text", "") for f in faces)
    image = (card.get("image_uris") or {}).get("normal")
    if image is None and faces:
        image = (faces[0].get("image_uris") or {}).get("normal")
    return (
        card["arena_id"],
        card.get("id"),
        card.get("oracle_id"),
        card.get("name"),
        _face(card, "mana_cost"),
        card.get("cmc"),
        ",".join(card.get("colors") or _face(card, "colors") or []),
        ",".join(card.get("color_identity") or []),
        card.get("type_line"),
        oracle_text,
        _face(card, "power"),
        _face(card, "toughness"),
        card.get("rarity"),
        card.get("set"),
        card.get("collector_number"),
        json.dumps(card.get("legalities") or {}),
        card.get("edhrec_rank"),
        image,
        "scryfall",
    )


_UPSERT = """
INSERT INTO cards (
    arena_id, scryfall_id, oracle_id, name, mana_cost, cmc, colors,
    color_identity, type_line, oracle_text, power, toughness, rarity,
    set_code, collector_number, legalities, edhrec_rank, image_uri, source
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(arena_id) DO UPDATE SET
    scryfall_id=excluded.scryfall_id, oracle_id=excluded.oracle_id,
    name=excluded.name, mana_cost=excluded.mana_cost, cmc=excluded.cmc,
    colors=excluded.colors, color_identity=excluded.color_identity,
    type_line=excluded.type_line, oracle_text=excluded.oracle_text,
    power=excluded.power, toughness=excluded.toughness, rarity=excluded.rarity,
    set_code=excluded.set_code, collector_number=excluded.collector_number,
    legalities=excluded.legalities, edhrec_rank=excluded.edhrec_rank,
    image_uri=excluded.image_uri, source=excluded.source
"""


def sync_scryfall(conn: sqlite3.Connection, force: bool = False) -> int:
    """Refresh the card table from Scryfall. Returns rows written."""
    last = store.get_meta(conn, _META_UPDATED_AT)
    if last and not force:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
            if age < _MIN_REFRESH:
                log.info("Scryfall data is %s old; skipping refresh", age)
                return 0
        except ValueError:
            pass

    with httpx.Client(follow_redirects=True) as client:
        entry = _bulk_entry(client)
        dest = paths.scryfall_cache_dir() / "default_cards.jsonl.gz"
        log.info(
            "Downloading Scryfall bulk export (%s compressed bytes, updated %s)",
            entry.get("compressed_size"),
            entry.get("updated_at"),
        )
        _download(client, entry["jsonl_download_uri"], dest)

    written = 0
    batch: list[tuple] = []
    for card in _iter_arena_cards(dest):
        batch.append(_row_from_scryfall(card))
        if len(batch) >= 1000:
            conn.executemany(_UPSERT, batch)
            written += len(batch)
            batch.clear()
    if batch:
        conn.executemany(_UPSERT, batch)
        written += len(batch)
    conn.commit()
    store.set_meta(conn, _META_UPDATED_AT, datetime.now(timezone.utc).isoformat())
    log.info("Wrote %d Arena-mapped cards from Scryfall", written)
    return written


_MARKUP = re.compile(r"<[^>]+>")


def _strip_markup(text: str | None) -> str | None:
    """Drop the HTML tags Arena's Formatted=1 localisation rows carry."""
    return _MARKUP.sub("", text) if text else text


# Arena stores rarity as an int and mana as its own "oNoR" notation.
_ARENA_RARITY = {0: None, 1: "basic", 2: "common", 3: "uncommon", 4: "rare", 5: "mythic"}


def _arena_mana_to_symbols(text: str | None) -> str | None:
    """Convert Arena's 'o2oUoU' notation to Scryfall-style '{2}{U}{U}'."""
    if not text:
        return None
    parts = [p for p in text.split("o") if p]
    return "".join("{" + p + "}" for p in parts)


def load_mtga_fallback(conn: sqlite3.Connection, db_file: Path | None = None) -> int:
    """Add cards from Arena's own database that Scryfall did not supply.

    Opened read-only -- this is a live game file and we never write to it.
    """
    src = db_file or paths.find_mtga_card_database()
    if src is None:
        log.warning("No local Arena card database found; skipping fallback")
        return 0

    known = {r[0] for r in conn.execute("SELECT arena_id FROM cards")}
    uri = f"file:{src}?mode=ro"
    added = 0
    with sqlite3.connect(uri, uri=True) as arena:
        arena.row_factory = sqlite3.Row
        # Titles are stored per Formatted variant: 0 and 2 are plain text, 1
        # carries HTML markup (<i>, <nobr>). Around 1,250 cards -- Eternal
        # Witness, Mana Crypt and friends -- have *only* a Formatted=1 row, so
        # an inner join on Formatted = 0 silently drops them. Prefer 0, then 2,
        # then 1, via a subquery that cannot drop rows.
        rows = arena.execute(
            """
            SELECT c.GrpId, c.ExpansionCode, c.Rarity, c.OldSchoolManaText,
                   c.Power, c.Toughness, c.CollectorNumber,
                   (SELECT l.Loc FROM Localizations_enUS l
                     WHERE l.LocId = c.TitleId AND l.Loc IS NOT NULL
                     ORDER BY CASE l.Formatted WHEN 0 THEN 0 WHEN 2 THEN 1 ELSE 2 END
                     LIMIT 1) AS name
            FROM Cards c
            WHERE c.IsPrimaryCard = 1 AND c.IsToken = 0
            """
        )
        batch: list[tuple] = []
        for r in rows:
            if r["GrpId"] in known or not r["name"]:
                continue
            batch.append(
                (
                    r["GrpId"], None, None, _strip_markup(r["name"]),
                    _arena_mana_to_symbols(r["OldSchoolManaText"]), None, "", "",
                    None, None,
                    r["Power"] or None, r["Toughness"] or None,
                    _ARENA_RARITY.get(r["Rarity"]),
                    r["ExpansionCode"], r["CollectorNumber"],
                    "{}", None, None, "mtga_local",
                )
            )
            if len(batch) >= 1000:
                conn.executemany(_UPSERT, batch)
                added += len(batch)
                batch.clear()
        if batch:
            conn.executemany(_UPSERT, batch)
            added += len(batch)
    conn.commit()
    log.info("Added %d cards from the local Arena database", added)
    return added


def enrich_local_from_scryfall(conn: sqlite3.Connection) -> int:
    """Fill in oracle data for fallback cards by matching on name.

    Cards that reach us via `mtga_local` have no rules text, type line or CMC,
    because Arena stores those as enum ids and ability joins. Most of them do
    exist on Scryfall -- just under a printing that carries no arena_id (e.g.
    Eternal Witness in 2X2). Matching by name recovers the oracle data while
    keeping Arena's grpId as the key, so deck advice has text to reason about.
    """
    # Keyed name -> [arena_id]: many Arena grpIds share a name (every basic
    # land printing, Secret Lair alt-arts), so a plain name->id dict would
    # silently drop all but one of them.
    wanted: dict[str, list[int]] = {}
    for r in conn.execute(
        "SELECT arena_id, name FROM cards "
        "WHERE source = 'mtga_local' AND oracle_text IS NULL"
    ):
        wanted.setdefault(r["name"], []).append(r["arena_id"])
    if not wanted:
        return 0

    bulk = paths.scryfall_cache_dir() / "default_cards.jsonl.gz"
    if not bulk.exists():
        log.warning("No cached Scryfall export; run sync_scryfall first")
        return 0

    updates: list[tuple] = []
    seen: set[str] = set()
    with gzip.open(bulk, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                card = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = card.get("name")
            if name not in wanted or name in seen:
                continue
            seen.add(name)
            faces = card.get("card_faces") or []
            oracle_text = card.get("oracle_text")
            if oracle_text is None and faces:
                oracle_text = "\n//\n".join(f.get("oracle_text", "") for f in faces)
            image = (card.get("image_uris") or {}).get("normal")
            if image is None and faces:
                image = (faces[0].get("image_uris") or {}).get("normal")
            shared = (
                card.get("oracle_id"),
                card.get("cmc"),
                ",".join(card.get("colors") or _face(card, "colors") or []),
                ",".join(card.get("color_identity") or []),
                card.get("type_line"),
                oracle_text,
                json.dumps(card.get("legalities") or {}),
                card.get("edhrec_rank"),
                image,
            )
            updates.extend(shared + (arena_id,) for arena_id in wanted[name])

    conn.executemany(
        "UPDATE cards SET oracle_id=?, cmc=?, colors=?, color_identity=?, "
        "type_line=?, oracle_text=?, legalities=?, edhrec_rank=?, image_uri=?, "
        "source='mtga_local+scryfall' WHERE arena_id=?",
        updates,
    )
    conn.commit()
    log.info("Enriched %d fallback cards with Scryfall oracle data", len(updates))
    return len(updates)


def sync_all(conn: sqlite3.Connection, force: bool = False) -> dict[str, int]:
    result = {
        "scryfall": sync_scryfall(conn, force=force),
        "mtga_local": load_mtga_fallback(conn),
    }
    result["enriched"] = enrich_local_from_scryfall(conn)
    return result


def get_card(conn: sqlite3.Connection, arena_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cards WHERE arena_id = ?", (arena_id,)).fetchone()
    return dict(row) if row else None

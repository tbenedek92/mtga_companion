"""Follow Arena's Player.log.

Two behaviours drive the design:

* Arena truncates and rewrites Player.log on every launch, moving the previous
  session to Player-prev.log. A tailer that only ever seeks forward will sit at
  a stale offset and miss the whole next session, so shrinkage is detected and
  the file re-read from zero.
* The file grows while the game runs and can end mid-line, so a partial trailing
  line is held back rather than handed to the parser.

Everything here is read-only. Arena is never touched, and running alongside
another tracker is safe.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from . import paths

log = logging.getLogger(__name__)


@dataclass
class Cursor:
    """Where we have read up to in one file."""

    path: Path
    offset: int = 0
    size: int = 0


def load_cursor(conn: sqlite3.Connection, path: Path) -> Cursor:
    row = conn.execute(
        "SELECT offset, size FROM ingest_state WHERE path = ?", (str(path),)
    ).fetchone()
    if row is None:
        return Cursor(path)
    return Cursor(path, offset=row["offset"], size=row["size"])


def save_cursor(conn: sqlite3.Connection, cursor: Cursor) -> None:
    conn.execute(
        "INSERT INTO ingest_state(path, offset, size, updated_at) "
        "VALUES(?, ?, ?, datetime('now')) "
        "ON CONFLICT(path) DO UPDATE SET offset=excluded.offset, "
        "size=excluded.size, updated_at=excluded.updated_at",
        (str(cursor.path), cursor.offset, cursor.size),
    )
    conn.commit()


def read_new_lines(cursor: Cursor) -> tuple[list[str], Cursor]:
    """Return complete lines written since the cursor, and the advanced cursor.

    A trailing partial line (no newline yet) is left unconsumed so the next call
    picks it up whole.
    """
    path = cursor.path
    try:
        size = path.stat().st_size
    except OSError:
        return [], cursor

    offset = cursor.offset
    if size < offset:
        # File shrank: Arena restarted and rewrote the log. Start over.
        log.info("%s was truncated (%d -> %d); re-reading from start",
                 path.name, offset, size)
        offset = 0
    if size == offset:
        return [], Cursor(path, offset, size)

    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read(size - offset)

    consumed = len(chunk)
    tail_break = chunk.rfind(b"\n")
    if tail_break == -1:
        # No complete line yet; wait for more bytes.
        return [], Cursor(path, offset, size)
    if tail_break + 1 != consumed:
        chunk = chunk[: tail_break + 1]
        consumed = tail_break + 1

    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines, Cursor(path, offset + consumed, size)


def iter_lines(conn: sqlite3.Connection, path: Path) -> Iterator[str]:
    """Yield unread lines from one file and persist the new cursor."""
    cursor = load_cursor(conn, path)
    lines, advanced = read_new_lines(cursor)
    for line in lines:
        yield line
    if advanced.offset != cursor.offset or advanced.size != cursor.size:
        save_cursor(conn, advanced)


def catch_up(
    conn: sqlite3.Connection,
    handler: Callable[[str], None],
    include_previous: bool = True,
) -> int:
    """Read everything new in the previous and current logs. Returns line count.

    Player-prev.log is included so a session that ended before we started is
    still ingested; its cursor is tracked separately, so it is only read once.
    """
    count = 0
    targets: list[Path] = []
    if include_previous and paths.PLAYER_PREV_LOG.exists():
        targets.append(paths.PLAYER_PREV_LOG)
    if paths.PLAYER_LOG.exists():
        targets.append(paths.PLAYER_LOG)

    for target in targets:
        for line in iter_lines(conn, target):
            handler(line)
            count += 1
    return count


def follow(
    conn: sqlite3.Connection,
    handler: Callable[[str], None],
    interval: float = 1.0,
    stop: Callable[[], bool] | None = None,
    on_idle: Callable[[], None] | None = None,
) -> None:
    """Catch up, then poll the live log forever (or until `stop()` is true).

    Polling rather than watching by inode: Arena rewrites the file in place, so
    a stat-based size check is both simpler and more reliable here.

    `on_idle` runs each time the log goes quiet, which is the natural point to
    commit and recompute derived tables -- doing that per line would thrash.
    """
    catch_up(conn, handler)
    if on_idle is not None:
        on_idle()
    while stop is None or not stop():
        try:
            moved = catch_up(conn, handler, include_previous=False)
        except Exception:
            log.exception("Log ingestion error; continuing")
            moved = 0
        if moved == 0:
            if on_idle is not None:
                try:
                    on_idle()
                except Exception:
                    log.exception("on_idle failed; continuing")
            time.sleep(interval)

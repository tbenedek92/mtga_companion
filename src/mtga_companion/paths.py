"""Filesystem locations for Arena's data and our own."""

from __future__ import annotations

import os
from pathlib import Path

# Arena's Unity log. Detailed Logs (Plugin Support) must be enabled in
# Settings -> Account or this file carries no game data.
MTGA_LOG_DIR = Path.home() / "Library/Logs/Wizards Of The Coast/MTGA"
PLAYER_LOG = MTGA_LOG_DIR / "Player.log"
PLAYER_PREV_LOG = MTGA_LOG_DIR / "Player-prev.log"

# Arena ships its card database as a plain SQLite file. Several may be present
# after an update; the newest by mtime is the live one.
_MTGA_INSTALL_CANDIDATES = (
    Path.home() / "Library/Application Support/Steam/steamapps/common/MTGA/MTGA_Data",
    Path("/Applications/MTGA.app/Contents/Resources/Data"),
)


def data_dir() -> Path:
    """Where we keep our own database and caches."""
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    path = root / "mtga_companion"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "db.sqlite"


def scryfall_cache_dir() -> Path:
    path = data_dir() / "scryfall-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_mtga_card_database() -> Path | None:
    """Newest Raw_CardDatabase_*.mtga, or None if Arena isn't installed here."""
    newest: Path | None = None
    for base in _MTGA_INSTALL_CANDIDATES:
        raw = base / "Downloads/Raw"
        if not raw.is_dir():
            continue
        for candidate in raw.glob("Raw_CardDatabase_*.mtga"):
            if newest is None or candidate.stat().st_mtime > newest.stat().st_mtime:
                newest = candidate
    return newest


def detailed_logs_enabled(log: Path | None = None) -> bool | None:
    """True/False from the log's own banner, or None if the log is unreadable.

    Arena writes 'DETAILED LOGS: ENABLED' or 'DISABLED' near the top of every
    session. Without ENABLED the log contains no decks, matches or card ids.
    """
    log = log or PLAYER_LOG
    try:
        head = log.read_text(errors="replace")[:20000]
    except OSError:
        return None
    if "DETAILED LOGS: ENABLED" in head:
        return True
    if "DETAILED LOGS: DISABLED" in head:
        return False
    return None

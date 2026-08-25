#!/usr/bin/env python3
"""Read MTGA's real collection out of the running game's memory and write it
into our database.

Must run as root -- task_for_pid on another user's process requires it, and
MTGA is not hardened-runtime so root is sufficient (no special entitlement
needed). Read-only against the game; the only write is to our own SQLite file,
whose ownership is restored to the invoking user afterward (root would
otherwise leave it root-owned and break every subsequent non-sudo run).

    sudo .venv/bin/python scripts/sync_collection.py

The actual work lives in memread.sync_collection() -- see that function and
find_dictionary_entries()'s docstring for how the table is located and why the
result is trusted or not before being written.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from mtga_companion import collection, memread, paths, store


def restore_ownership(path: pathlib.Path) -> None:
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if not (uid and gid):
        return
    for target in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if target.exists():
            try:
                os.chown(target, int(uid), int(gid))
            except OSError as exc:
                print(f"  (warning: could not restore ownership of {target}: {exc})")


def main() -> None:
    conn = store.connect()
    anchors = collection.deck_proven_ownership(conn)
    print(f"Anchors: {len(anchors)} known-owned cards from your decks")

    pid = memread.find_mtga_pid()
    if pid is None:
        print("MTGA is not running.")
        return
    print(f"MTGA pid: {pid}")

    try:
        mem = memread.ProcessMemory(pid)
    except memread.AccessDenied as exc:
        print(f"Cannot attach: {exc}")
        return

    print("Scanning...")
    result = memread.sync_collection(conn, mem=mem)

    if not result.found:
        print("No candidate dictionary found. Nothing written.")
        return

    print(f"\nBest candidate: {hex(result.region_address)}, "
          f"{result.entry_count} distinct entries")
    print(f"  Anchors present: {result.anchors_present}/{result.anchors_total}")
    print(f"  Anchors validated: {result.anchors_validated}/{result.anchors_total} "
          f"({result.validation_fraction:.0%})")

    if result.written:
        print(f"\nValidation passed. Wrote entries to card_ownership "
              "(source='memory', confidence='exact').")
        db_path = paths.db_path()
        restore_ownership(db_path)
        print(f"Restored ownership of {db_path} to the invoking user.")
    else:
        print(
            f"\nValidation rate below threshold. NOT written -- this region "
            "may be the wrong table, or your proven-owned anchor set (from "
            "decks you've built) is too small yet to tell confidently. "
            "Run scan_memory.py to see every candidate region's numbers, or "
            "build a few more decks so there's more to validate against."
        )


if __name__ == "__main__":
    main()

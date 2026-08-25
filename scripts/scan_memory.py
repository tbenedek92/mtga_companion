#!/usr/bin/env python3
"""Diagnostic: report on the candidate collection-table region without writing
anything to the database. Use this if sync_collection.py's validation rate
looks low and you want to see the raw numbers before trusting it.

Must run as root. Entirely read-only against the game.

    sudo .venv/bin/python scripts/scan_memory.py

See memread.py's module docstring and find_dictionary_entries() for how this
works: it looks for the `hashCode == key` signature of a .NET/IL2CPP
Dictionary<int,int> entry, which needs no prior knowledge of Arena's object
layout, then scores candidate regions against cards independently known to be
owned (from decks the player built).
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from mtga_companion import collection, memread, store

OUTPUT = pathlib.Path(__file__).parent.parent / "scan_memory_results.json"


def main() -> None:
    conn = store.connect()
    anchors = collection.deck_proven_ownership(conn)
    lo, hi = conn.execute("SELECT MIN(arena_id), MAX(arena_id) FROM cards").fetchone()
    print(f"Anchors: {len(anchors)} known-owned cards from your decks")
    print(f"Valid grpId range: {lo}-{hi}")

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

    regions = list(mem.heap_like_regions())
    print(f"Scanning {len(regions)} private RW regions...")
    t0 = time.time()

    candidates = []
    for region in regions:
        data = mem.read_all(region.address, region.size)
        if not data:
            continue
        entries = memread.find_dictionary_entries(data, lo, hi)
        if len(entries) < 5:
            continue
        table = {e.key: e.value for e in entries}
        present = sum(1 for k in anchors if k in table)
        validated = sum(
            1 for k, v in anchors.items()
            if k in table and 0 <= table[k] < 1000 and table[k] >= v
        )
        candidates.append({
            "address": hex(region.address), "size": region.size,
            "distinct_keys": len(table),
            "anchor_hits": present, "anchor_validated": validated,
            "stride_guess_bytes": memread.guess_stride([e.word_offset for e in entries]),
        })

    elapsed = time.time() - t0
    candidates.sort(key=lambda c: (-c["anchor_validated"], -c["anchor_hits"]))
    print(f"\nScan complete in {elapsed:.1f}s. {len(candidates)} candidate regions.\n")
    print("Top candidates:")
    for c in candidates[:10]:
        print(
            f"  {c['address']}  size={c['size'] / 1e6:.1f}MB  "
            f"distinct={c['distinct_keys']}  "
            f"anchors={c['anchor_hits']}/{len(anchors)}  "
            f"validated={c['anchor_validated']}  stride~{c['stride_guess_bytes']}"
        )

    OUTPUT.write_text(json.dumps({
        "pid": pid, "elapsed_seconds": elapsed, "anchor_count": len(anchors),
        "grpid_range": [lo, hi], "regions_scanned": len(regions),
        "candidates": candidates[:50],
    }, indent=2))
    print(f"\nFull results written to {OUTPUT}")
    print("\nTo actually write a validated collection to the database, run "
          "sync_collection.py instead.")


if __name__ == "__main__":
    main()

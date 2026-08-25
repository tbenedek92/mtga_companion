"""Read MTG Arena's collection out of the running game's memory.

Arena stopped reporting collection contents in its log in 2021. It is still in
the client's memory, which is how other trackers (Untapped's "Scry") obtain it:
they attach to the MTGA process and walk the runtime's object graph.

Two things make this tractable here:

* MTGA is signed **without hardened runtime** (`codesign` reports `flags=0x0`),
  so `task_for_pid` is permitted for root. No entitlement or SIP change needed --
  but it does mean the probe must run under sudo.
* Everything below is **read-only**. `mach_vm_read_overwrite` copies bytes out
  of the target task without suspending it, and nothing here writes to, injects
  into, or otherwise modifies the game.

Arena uses IL2CPP (`il2cpp_data/Metadata/global-metadata.dat`), not Mono, so
class/field offsets are not introspectable the way they are in a Mono build.
Rather than parse IL2CPP metadata -- which changes shape between Unity versions
-- this module anchors on data we already know: the grpIds of cards the player
demonstrably owns. A region of memory densely packed with known grpIds next to
small integers is the collection table, whatever the surrounding structure is
called. That approach survives Arena patches that would break a hard-coded
offset walk.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import dataclasses
import logging
import struct
import subprocess
from collections import Counter
from typing import Iterator, NamedTuple

import numpy as np


@dataclasses.dataclass(frozen=True)
class Region:
    address: int
    size: int
    protection: int
    shared: bool

    @property
    def end(self) -> int:
        return self.address + self.size

log = logging.getLogger(__name__)

KERN_SUCCESS = 0
VM_PROT_READ = 1
VM_PROT_WRITE = 2
VM_PROT_EXECUTE = 4
VM_REGION_BASIC_INFO_64 = 9

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

task_t = ctypes.c_uint32
mach_port_t = ctypes.c_uint32
vm_size_t = ctypes.c_uint64
mach_vm_address_t = ctypes.c_uint64

_libc.mach_task_self.restype = mach_port_t
_libc.task_for_pid.argtypes = [mach_port_t, ctypes.c_int, ctypes.POINTER(task_t)]
_libc.task_for_pid.restype = ctypes.c_int
_libc.mach_vm_read_overwrite.argtypes = [
    task_t, mach_vm_address_t, vm_size_t, mach_vm_address_t,
    ctypes.POINTER(vm_size_t),
]
_libc.mach_vm_read_overwrite.restype = ctypes.c_int
_libc.mach_vm_region.argtypes = [
    task_t, ctypes.POINTER(mach_vm_address_t), ctypes.POINTER(vm_size_t),
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(mach_port_t),
]
_libc.mach_vm_region.restype = ctypes.c_int


class _RegionInfo(ctypes.Structure):
    _fields_ = [
        ("protection", ctypes.c_int), ("max_protection", ctypes.c_int),
        ("inheritance", ctypes.c_uint32), ("shared", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32), ("offset", ctypes.c_uint64),
        ("behavior", ctypes.c_int), ("user_wired_count", ctypes.c_ushort),
    ]


class AccessDenied(RuntimeError):
    """task_for_pid refused. Almost always: not running as root."""


def find_mtga_pid() -> int | None:
    """PID of the running MTGA client, if any."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "MTGA.app/Contents/MacOS/MTGA"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out[0]) if out else None


class ProcessMemory:
    """Read-only handle on another process's address space."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        task = task_t()
        kr = _libc.task_for_pid(_libc.mach_task_self(), pid, ctypes.byref(task))
        if kr != KERN_SUCCESS:
            raise AccessDenied(
                f"task_for_pid({pid}) failed with kern_return {kr}. "
                "MTGA is not hardened-runtime, so this should succeed as root: "
                "re-run under sudo."
            )
        self.task = task

    def read(self, address: int, size: int) -> bytes | None:
        buf = (ctypes.c_char * size)()
        got = vm_size_t(0)
        kr = _libc.mach_vm_read_overwrite(
            self.task, address, size,
            ctypes.cast(buf, ctypes.c_void_p).value, ctypes.byref(got),
        )
        if kr != KERN_SUCCESS or got.value == 0:
            return None
        return bytes(buf)[: got.value]

    def regions(self, max_regions: int = 200_000) -> Iterator[tuple[int, int]]:
        """Yield (address, size) for every readable region."""
        for r in self.regions_detailed(max_regions):
            yield r.address, r.size

    def regions_detailed(self, max_regions: int = 200_000) -> Iterator["Region"]:
        """Yield every region with its protection and shared flag.

        The collection table is IL2CPP-managed heap: private (not shared with
        another process, so not a mapped framebuffer or shared library),
        read+write, and not executable. Filtering on that up front turns a
        multi-gigabyte address space into something scannable in seconds
        instead of minutes.
        """
        addr = mach_vm_address_t(0)
        size = vm_size_t(0)
        info = _RegionInfo()
        count = ctypes.c_uint32(ctypes.sizeof(info) // 4)
        obj = mach_port_t()
        seen = 0
        while seen < max_regions:
            kr = _libc.mach_vm_region(
                self.task, ctypes.byref(addr), ctypes.byref(size),
                VM_REGION_BASIC_INFO_64, ctypes.byref(info),
                ctypes.byref(count), ctypes.byref(obj),
            )
            if kr != KERN_SUCCESS:
                return
            seen += 1
            if info.protection & VM_PROT_READ:
                yield Region(
                    address=addr.value, size=size.value,
                    protection=info.protection, shared=bool(info.shared),
                )
            addr = mach_vm_address_t(addr.value + size.value)

    def heap_like_regions(
        self, min_size: int = 1 << 14, max_size: int = 512 << 20
    ) -> Iterator["Region"]:
        """Private RW, non-executable regions in a plausible heap size range.

        This is the search space for anything the game allocated itself, as
        opposed to mapped files, shared libraries, or GPU-visible buffers.
        """
        for r in self.regions_detailed():
            if r.shared:
                continue
            if r.protection & VM_PROT_EXECUTE:
                continue
            if r.protection & VM_PROT_WRITE == 0:
                continue
            if not (min_size <= r.size <= max_size):
                continue
            yield r

    def read_all(self, address: int, size: int, chunk: int = 8 << 20) -> bytes | None:
        """Read a whole region, chunked so no single mach call is huge."""
        parts = []
        offset = 0
        while offset < size:
            piece = self.read(address + offset, min(chunk, size - offset))
            if piece is None:
                if not parts:
                    return None
                break  # partial region (e.g. it shrank mid-scan); use what we got
            parts.append(piece)
            offset += len(piece)
        return b"".join(parts)


class DictEntry(NamedTuple):
    """One decoded slot from a .NET/IL2CPP `Dictionary<int, int>`."""

    word_offset: int  # index into the region's 4-byte words, at entry.hashCode
    key: int
    value: int


def find_dictionary_entries(
    data: bytes, key_min: int, key_max: int
) -> list[DictEntry]:
    """Locate `Dictionary<int, int>` entries in a raw memory buffer.

    The trick this relies on: .NET's `int.GetHashCode()` returns the int
    itself, and a dictionary's internal Entry struct stores the computed hash
    next to the key --

        struct Entry { int hashCode; int next; TKey key; TValue value; }

    so for every real entry, `entry.hashCode == entry.key`. Two words matching
    exactly, purely by chance, is roughly a 1-in-4-billion coincidence per
    position -- so scanning every 4-byte-aligned offset for `word[i] ==
    word[i+2]` finds candidate entries with almost no false positives, without
    needing to know the surrounding object layout at all. `key_min`/`key_max`
    then filters those candidates to ones that look like a real card id, which
    also discards the true-but-irrelevant coincidental dictionaries elsewhere
    in the process (Arena has more than one int-keyed table in memory).

    The value is read from word_offset + 3, i.e. byte offset +12 from the
    entry start -- valid when TValue is itself a plain int, as a card-count
    dictionary would be.
    """
    n = len(data) // 4
    if n < 4:
        return []
    arr = np.frombuffer(data[: n * 4], dtype="<u4")
    eq = arr[: n - 2] == arr[2:n]
    in_range = (arr[: n - 2] >= key_min) & (arr[: n - 2] <= key_max)
    hit = np.nonzero(eq & in_range)[0]
    hit = hit[hit + 3 < n]
    keys = arr[hit]
    values = arr[hit + 3]
    return [
        DictEntry(int(w), int(k), int(v))
        for w, k, v in zip(hit.tolist(), keys.tolist(), values.tolist())
    ]


def guess_stride(word_offsets: list[int], max_gap: int = 4096) -> int | None:
    """Most common byte gap between candidate entries in one region.

    A real backing array holds entries at a constant stride (Arena's chosen
    initial capacity, then doubled on growth); empty buckets between real
    entries create gaps that are still exact multiples of that stride, so the
    single most common gap is a reliable estimate of the true entry size.
    """
    if len(word_offsets) < 3:
        return None
    byte_offsets = np.sort(np.asarray(word_offsets, dtype=np.int64)) * 4
    diffs = np.diff(byte_offsets)
    diffs = diffs[(diffs > 0) & (diffs < max_gap)]
    if len(diffs) == 0:
        return None
    counts = Counter(diffs.tolist())
    return counts.most_common(1)[0][0]


class SyncResult(NamedTuple):
    """Outcome of a memory sync attempt, whether or not it was trusted enough
    to act on."""

    found: bool
    written: bool
    region_address: int | None
    entry_count: int
    anchors_total: int
    anchors_present: int
    anchors_validated: int
    validation_fraction: float
    collection: dict[int, int]  # arena_id -> quantity, only when `found`


def find_collection_dictionary(
    mem: ProcessMemory,
    key_min: int,
    key_max: int,
    anchors: dict[int, int],
    min_entries: int = 50,
) -> SyncResult:
    """Search the process for the region holding the card-collection table.

    Every private, writable, non-executable region in a plausible heap-size
    range is decoded with `find_dictionary_entries`; the region whose decoded
    entries validate the most `anchors` (arena_id -> a quantity the player is
    independently known to own, e.g. from decks they built) wins. Structural
    plausibility (the hashCode==key signature) narrows candidates to real
    dictionaries; anchor validation then picks the *right* dictionary among
    however many int-keyed tables Arena happens to have in memory, since nothing
    about the byte pattern alone says which one is the collection.
    """
    best: SyncResult | None = None
    for region in mem.heap_like_regions():
        data = mem.read_all(region.address, region.size)
        if not data:
            continue
        entries = find_dictionary_entries(data, key_min, key_max)
        if len(entries) < min_entries:
            continue
        table = {e.key: e.value for e in entries}  # last write wins; rare dupes

        present = sum(1 for k in anchors if k in table)
        validated = sum(
            1 for k, v in anchors.items()
            if k in table and 0 <= table[k] < 1000 and table[k] >= v
        )
        if best is None or validated > best.anchors_validated:
            best = SyncResult(
                found=True, written=False, region_address=region.address,
                entry_count=len(table), anchors_total=len(anchors),
                anchors_present=present, anchors_validated=validated,
                validation_fraction=validated / len(anchors) if anchors else 0.0,
                collection=table,
            )

    if best is None:
        return SyncResult(
            found=False, written=False, region_address=None, entry_count=0,
            anchors_total=len(anchors), anchors_present=0, anchors_validated=0,
            validation_fraction=0.0, collection={},
        )
    return best


def sync_collection(
    conn, min_validation: float = 0.5, mem: "ProcessMemory | None" = None
) -> SyncResult:
    """Find, decode and (if trustworthy) write the real collection from memory.

    Requires root -- ProcessMemory(pid) will raise AccessDenied otherwise, same
    as everything else in this module. `conn` needs write access, which is why
    this whole call runs as root: splitting "read as root, write as user"
    across two processes is possible but not worth the plumbing for a script
    the player runs by hand.

    Entries are written to card_ownership as source='memory', confidence=
    'exact', REPLACING any previous memory-sourced rows -- but only if
    `validation_fraction` clears `min_validation`. Below that, nothing is
    written and the caller should treat the result as informational: either
    the wrong region was found, or the player's proven-owned anchor set is too
    small yet to tell.
    """
    from . import collection  # deferred: avoids a hard import-time dependency

    if mem is None:
        pid = find_mtga_pid()
        if pid is None:
            return SyncResult(False, False, None, 0, 0, 0, 0, 0.0, {})
        mem = ProcessMemory(pid)

    anchors = collection.deck_proven_ownership(conn)
    lo, hi = conn.execute(
        "SELECT MIN(arena_id), MAX(arena_id) FROM cards"
    ).fetchone()

    result = find_collection_dictionary(mem, lo, hi, anchors)
    if not result.found or result.validation_fraction < min_validation:
        return result

    conn.execute("DELETE FROM card_ownership WHERE source = 'memory'")
    written = 0
    for arena_id, qty in result.collection.items():
        if not (0 < qty < 1000):
            continue  # implausible as a real copy count; a hash collision, not a card
        exists = conn.execute(
            "SELECT 1 FROM cards WHERE arena_id = ?", (arena_id,)
        ).fetchone()
        if exists is None:
            continue
        conn.execute(
            "INSERT INTO card_ownership(arena_id, source, quantity, confidence, "
            "updated_at) VALUES(?, 'memory', ?, 'exact', datetime('now'))",
            (arena_id, qty),
        )
        written += 1
    conn.commit()
    log.info("Wrote %d cards from memory sync", written)
    return result._replace(written=True)


def probe(pid: int | None = None) -> dict:
    """Report whether memory reading is possible, without decoding anything."""
    pid = pid or find_mtga_pid()
    if pid is None:
        return {"ok": False, "reason": "MTGA is not running"}
    try:
        mem = ProcessMemory(pid)
    except AccessDenied as exc:
        return {"ok": False, "reason": str(exc), "pid": pid}

    regions = 0
    readable = 0
    sample = None
    for base, size in mem.regions():
        regions += 1
        readable += size
        if sample is None:
            data = mem.read(base, 16)
            if data:
                sample = f"0x{base:x}: {data.hex()}"
    return {
        "ok": True, "pid": pid, "readable_regions": regions,
        "readable_bytes": readable, "sample": sample,
    }

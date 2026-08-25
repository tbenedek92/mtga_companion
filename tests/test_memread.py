"""The memory-scanning decode logic, tested against synthetic byte buffers.

Everything that touches an actual process (ProcessMemory, task_for_pid) can't
run in CI without root and a live MTGA -- what's tested here is the part that
matters for correctness regardless of platform: given raw bytes shaped like a
.NET Dictionary<int,int>, does the decoder find the right entries and not
find things that only coincidentally look like them.
"""

from __future__ import annotations

import struct

from mtga_companion import memread


def pack_entry(hash_code: int, next_: int, key: int, value: int) -> bytes:
    """One 16-byte Dictionary<int,int> Entry: {hashCode, next, key, value}."""
    return struct.pack("<iiii", hash_code, next_, key, value)


def real_entry(key: int, value: int, next_: int = -1) -> bytes:
    """A genuine entry: hashCode == key, as int.GetHashCode() guarantees."""
    return pack_entry(key, next_, key, value)


def empty_slot() -> bytes:
    """An unused Dictionary bucket: hashCode -1, no key/value to trust."""
    return pack_entry(-1, -1, 0, 0)


class TestFindDictionaryEntries:
    def test_finds_a_single_real_entry(self):
        data = real_entry(key=12345, value=4)
        found = memread.find_dictionary_entries(data, key_min=0, key_max=1 << 20)
        assert len(found) == 1
        assert (found[0].key, found[0].value) == (12345, 4)

    def test_finds_multiple_entries_with_gaps(self):
        """Empty buckets between real entries must not break detection."""
        data = (
            real_entry(100, 4) + empty_slot() + empty_slot()
            + real_entry(200, 2) + real_entry(300, 1)
        )
        found = memread.find_dictionary_entries(data, key_min=0, key_max=1000)
        assert sorted((e.key, e.value) for e in found) == [
            (100, 4), (200, 2), (300, 1)
        ]

    def test_key_range_filters_out_of_range_hashcode_key_matches(self):
        """A hashCode==key coincidence outside the plausible id range is noise,
        not a card -- e.g. another Dictionary<int,int> entirely."""
        data = real_entry(key=999_999, value=1) + real_entry(key=500, value=2)
        found = memread.find_dictionary_entries(data, key_min=100, key_max=1000)
        assert [(e.key, e.value) for e in found] == [(500, 2)]

    def test_near_miss_does_not_match(self):
        """hashCode off by one from key must not be treated as a real entry --
        the whole point of this signature is that it is an exact match."""
        data = pack_entry(hash_code=100, next_=-1, key=101, value=4)
        found = memread.find_dictionary_entries(data, key_min=0, key_max=1000)
        assert found == []

    def test_random_noise_does_not_produce_matches(self):
        """Bytes with no dictionary structure at all -- distinct, unrelated
        32-bit values -- must not coincidentally satisfy hashCode==key."""
        data = struct.pack("<20I", *range(1, 21))
        found = memread.find_dictionary_entries(data, key_min=0, key_max=100)
        assert found == []

    def test_too_short_a_buffer_is_handled(self):
        assert memread.find_dictionary_entries(b"", 0, 100) == []
        assert memread.find_dictionary_entries(b"\x00" * 8, 0, 100) == []

    def test_entry_at_the_very_end_needs_a_value_word_in_bounds(self):
        """A hashCode==key match with no room for byte offset+12 (the value)
        must be dropped rather than reading past the buffer."""
        # hashCode(0) next(4) key(8) -- no value word follows.
        data = struct.pack("<iii", 42, -1, 42)
        assert memread.find_dictionary_entries(data, 0, 100) == []

    def test_word_offset_points_at_the_entry_start(self):
        # key_min=1 excludes the leading zero padding: an all-zero region
        # trivially satisfies hashCode(0) == key(0), which is real memory's
        # single most common false-positive source and exactly what a
        # positive key_min (real grpIds start well above 0) is for.
        data = b"\x00" * 16 + real_entry(key=50, value=3)
        found = memread.find_dictionary_entries(data, 1, 100)
        assert found[0].word_offset == 4  # 16 bytes in = word index 4

    def test_zero_padding_is_excluded_by_a_positive_key_min(self):
        """Real memory is mostly zero padding, which trivially satisfies
        hashCode(0) == key(0). A positive key_min (real grpIds never reach
        down to 0) is what keeps that from swamping the results with noise."""
        data = b"\x00" * 64 + real_entry(key=50, value=3)
        found = memread.find_dictionary_entries(data, 1, 100)
        assert [(e.key, e.value) for e in found] == [(50, 3)]


class TestGuessStride:
    def test_constant_stride_is_detected(self):
        offsets = [0, 4, 8, 12]  # word indices; entries every 16 bytes
        assert memread.guess_stride(offsets) == 16

    def test_gaps_from_empty_buckets_are_still_multiples_of_the_stride(self):
        # word offsets 0, 8, 20 -> byte offsets 0, 32, 80 -> gaps 32, 48
        # (both multiples of 16); mode should still recover something sane.
        offsets = [0, 4, 8, 20, 24]
        stride = memread.guess_stride(offsets)
        assert stride is not None and stride % 4 == 0

    def test_too_few_points_returns_none(self):
        assert memread.guess_stride([0, 4]) is None
        assert memread.guess_stride([]) is None

    def test_huge_gaps_are_excluded_from_the_estimate(self):
        # Two entries close together (stride 16), one far-off outlier that
        # should not dominate the mode.
        offsets = [0, 4, 8, 12, 100_000]
        assert memread.guess_stride(offsets) == 16

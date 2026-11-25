"""The order a Java ``HashMap`` iterates in, so Pipit writes checklists exactly as Scythebill
does after it rebuilds one (``Maps.newHashMapWithExpectedSize`` then
``ImmutableMap.copyOf``, which keeps the hash order).

Ported from the JDK and Guava:
- ``String.hashCode``: s[0]*31^(n-1) + ... + s[n-1], in 32-bit arithmetic;
- ``List.hashCode``: 31*h + e.hashCode(), starting from 1;
- ``SightingTaxons``: a single taxon hashes as its ID, one with a subspecies as
  31*hash(id) + hash(subspecies), a sp. or hybrid as its sorted ID list;
- ``HashMap``: bucket = (h ^ (h >>> 16)) & (table size - 1); the table size is the next
  power of two of the requested capacity; buckets iterate in index order and, within one,
  in insertion order. (A bucket of 8 or more entries in a table of 64+ becomes a tree,
  which can reorder it; with taxon IDs that never happens in practice, and the oracle
  tests would show it.)
- ``Maps.capacity`` (Guava): expected < 3 -> expected + 1, else expected / 0.75 + 1.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence

_MASK = 0xFFFFFFFF


def _int32(value: int) -> int:
    value &= _MASK
    return value - (1 << 32) if value & 0x80000000 else value


def string_hash(text: str) -> int:
    """``String.hashCode`` (over UTF-16 code units)."""
    result = 0
    for unit in text.encode("utf-16-be").hex(" ", 2).split():
        result = (31 * result + int(unit, 16)) & _MASK
    return _int32(result)


def list_hash(hashes: Iterable[int]) -> int:
    result = 1
    for value in hashes:
        result = (31 * result + value) & _MASK
    return _int32(result)


def sighting_taxon_hash(kind: str, ids: Sequence[str], subspecies: str | None = None) -> int:
    """``SightingTaxon.hashCode`` for "single", "ssp", "sp" or "hybrid"."""
    if kind == "single":
        return string_hash(ids[0])
    if kind == "ssp":
        return _int32(31 * string_hash(ids[0]) + string_hash(subspecies or ""))
    return list_hash(string_hash(taxon_id) for taxon_id in sorted(set(ids)))


def guava_capacity(expected: int) -> int:
    """``Maps.capacity``: the initial capacity of ``newHashMapWithExpectedSize``."""
    if expected < 3:
        return expected + 1
    return int(expected / 0.75 + 1.0)


def table_size(capacity: int) -> int:
    """``HashMap.tableSizeFor``: the next power of two (at least 1)."""
    size = 1
    while size < capacity:
        size <<= 1
    return size


def hashmap_order[K: Hashable](keys: Sequence[K], hashes: Sequence[int], capacity: int) -> list[K]:
    """The iteration order of a ``HashMap`` built with ``capacity`` after putting ``keys``
    (distinct, in this order). Growth while filling keeps this order: a resize splits each
    bucket into two, each keeping its entries' relative order, so the final table size
    decides everything."""
    size = table_size(capacity)
    while len(keys) > size * 0.75:  # the map grows as it fills
        size <<= 1
    buckets: dict[int, list[K]] = {}
    for key, value in zip(keys, hashes, strict=True):
        spread = value ^ ((value & _MASK) >> 16)
        buckets.setdefault(spread & (size - 1), []).append(key)
    return [key for index in sorted(buckets) for key in buckets[index]]

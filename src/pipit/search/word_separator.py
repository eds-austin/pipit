"""Ways to split one typed string into several word prefixes ("wiwa" -> "wi" + "wa").

Ported from Scythebill ``model/src/commonMain/kotlin/.../util/WordSeparator.kt``. Pipit's
indexer does not enumerate splits (it searches them all at once), but this is kept as the
reference definition and is used by tests to check the indexer against Scythebill.
"""

from __future__ import annotations

from functools import cache, cmp_to_key

#: Above this, splitting gets very slow (it is 2^N); longer input is cut to this length.
MAX_LENGTH_TO_SPLIT = 15


def _product(boundaries: tuple[int, ...]) -> int:
    product = 1
    previous = 0
    for value in boundaries:
        product *= value - previous
        previous = value
    return product


def _prefer_shorter_and_balanced(first: tuple[int, ...], second: tuple[int, ...]) -> int:
    """Fewer words first; then more balanced splits (higher product of lengths); then
    more characters in the earlier words."""
    if len(first) != len(second):
        return len(first) - len(second)
    product_difference = _product(second) - _product(first)
    if product_difference:
        return product_difference
    for a, b in zip(first, second, strict=True):
        if a != b:
            return b - a
    return 0


@cache
def boundaries(length: int, max_words: int = 5) -> tuple[tuple[int, ...], ...]:
    """Each split as end offsets; the last is always the (capped) length."""
    length = min(length, MAX_LENGTH_TO_SPLIT)
    if length <= 0:
        return ()
    splits: list[tuple[int, ...]] = []
    for mask in range(1 << (length - 1)):
        if mask.bit_count() + 1 > max_words:
            continue
        cuts = [bit + 1 for bit in range(length - 1) if mask >> bit & 1]
        splits.append((*cuts, length))
    return tuple(sorted(splits, key=cmp_to_key(_prefer_shorter_and_balanced)))

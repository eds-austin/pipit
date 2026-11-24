"""Word-prefix type-ahead index with Scythebill's matching rules, built for speed.

Semantics (Scythebill ``model/src/commonMain/kotlin/.../util/Indexer.kt``):

- A name is indexed word by word: word *i* (up to five) goes into position *i*.
- A query with separators ("he gu") is a list of tokens; token *k* must be a prefix of a
  word at a position strictly after token *k-1*'s position.
- A query without separators ("wiwa") is also tried split into up to five pieces ("wi" +
  "wa", "w" + "iwa", ...); the result is the union over every split. Input beyond 15
  characters is ignored for this, as in Scythebill.

Scythebill enumerates the splits and walks a trie per position. Here each position is a
sorted word list with a bitset (a Python int) of entries per word, and one memoized
recursion covers all splits at once, so a keystroke costs well under a millisecond.
Results are sets of entry numbers; ranking is the caller's job.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator
from functools import lru_cache

from pipit.search.normalize import index_words, query_text, split_words
from pipit.search.word_separator import MAX_LENGTH_TO_SPLIT

MAX_WORDS = 5
_HIGHEST = "\U0010ffff"


def bits_of(bitset: int) -> Iterator[int]:
    """Entry numbers in a bitset, ascending."""
    while bitset:
        lowest = bitset & -bitset
        yield lowest.bit_length() - 1
        bitset ^= lowest


class _Position:
    """All words at one word position: sorted, with the entries that have each word."""

    __slots__ = ("_bitsets", "_words", "lookup")

    def __init__(self, words: dict[str, int]) -> None:
        self._words = sorted(words)
        self._bitsets = [words[word] for word in self._words]
        self.lookup = lru_cache(maxsize=8192)(self._lookup)

    def _lookup(self, prefix: str) -> int:
        start = bisect_left(self._words, prefix)
        end = bisect_left(self._words, prefix + _HIGHEST, start)
        result = 0
        for bitset in self._bitsets[start:end]:
            result |= bitset
        return result

    def warm(self) -> None:
        """Precompute one- and two-letter prefixes, the broadest (slowest) lookups."""
        for word in self._words:
            self.lookup(word[:1])
            self.lookup(word[:2])


class Indexer:
    """Add names with ``add`` (entry numbers are assigned in order), then ``freeze``."""

    def __init__(self, max_words: int = MAX_WORDS) -> None:
        self._max_words = max_words
        self._building: list[dict[str, int]] = []
        self._positions: tuple[_Position, ...] = ()
        self._count = 0
        self._frozen = False

    def __len__(self) -> int:
        return self._count

    def add(self, name: str, alternates: dict[str, list[str]] | None = None) -> int:
        """Index ``name``; returns its entry number. ``alternates`` maps a normalized word
        to extra words indexed at the same position (word-level synonyms)."""
        if self._frozen:
            raise RuntimeError("indexer is frozen")
        entry = self._count
        self._count += 1
        bit = 1 << entry
        for position, word in enumerate(index_words(name, self._max_words)):
            if position == len(self._building):
                self._building.append({})
            words = self._building[position]
            for indexed in (word, *(alternates or {}).get(word, ())):
                words[indexed] = words.get(indexed, 0) | bit
        return entry

    def freeze(self, warm: bool = True) -> Indexer:
        self._positions = tuple(_Position(words) for words in self._building)
        self._building = []
        self._frozen = True
        if warm:
            for position in self._positions:
                position.warm()
        return self

    @property
    def all(self) -> int:
        return (1 << self._count) - 1

    def find(self, query: str) -> int:
        """Entries matching ``query`` as a bitset."""
        if not self._frozen:
            raise RuntimeError("freeze() the indexer before searching")
        entry = query_text(query)
        tokens = split_words(entry)
        if len(tokens) > 1:
            return self._find_tokens(tokens)
        if not entry:
            return 0
        return self._find_splits(entry[:MAX_LENGTH_TO_SPLIT])

    def _find_tokens(self, tokens: list[str]) -> int:
        positions = self._positions
        token_count = len(tokens)
        if token_count > len(positions):
            return 0
        # following[i] = entries where tokens k+1.. match at positions > i (for token k).
        following: list[int] | None = None
        for k in range(token_count - 1, -1, -1):
            last = len(positions) - (token_count - k)
            matches = [0] * len(positions)
            for i in range(k, last + 1):
                found = positions[i].lookup(tokens[k])
                if found and following is not None:
                    found &= following[i]
                matches[i] = found
            # suffix OR so following[i] = OR of matches[j] for j > i
            suffix = [0] * len(positions)
            running = 0
            for i in range(len(positions) - 1, -1, -1):
                suffix[i] = running
                running |= matches[i]
            if k == 0:
                return running
            following = suffix
        return 0  # pragma: no cover

    def _find_splits(self, entry: str) -> int:
        positions = self._positions
        position_count = len(positions)
        length = len(entry)
        memo: dict[tuple[int, int, int], int] = {}

        def rest(start: int, first_position: int, pieces_left: int) -> int:
            """Entries where entry[start:] splits into <= pieces_left pieces matched at
            increasing positions >= first_position."""
            key = (start, first_position, pieces_left)
            if key in memo:
                return memo[key]
            result = 0
            for position in range(first_position, position_count):
                lookup = positions[position].lookup
                for end in range(start + 1, length + 1):
                    found = lookup(entry[start:end])
                    if not found:
                        break  # longer pieces can't match at this position either
                    if end < length:
                        if pieces_left == 1:
                            continue
                        found &= rest(end, position + 1, pieces_left - 1)
                    result |= found
            memo[key] = result
            return result

        return rest(0, 0, self._max_words)

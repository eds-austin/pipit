"""A literal, slow port of Scythebill's Indexer.find, used to check the fast bitset engine.

It follows ``Indexer.kt`` step by step: enumerate every split from ``WordSeparator``,
then recurse token by token through the per-position word lists.
"""

from __future__ import annotations

from pipit.search.normalize import index_words, query_text, split_words
from pipit.search.word_separator import boundaries


class ReferenceIndexer:
    def __init__(self, max_words: int = 5) -> None:
        self.max_words = max_words
        self.positions: list[dict[str, set[int]]] = []
        self.count = 0

    def add(self, name: str) -> int:
        value = self.count
        self.count += 1
        for i, word in enumerate(index_words(name, self.max_words)):
            if i == len(self.positions):
                self.positions.append({})
            self.positions[i].setdefault(word, set()).add(value)
        return value

    def _matches(self, position: int, prefix: str) -> set[int]:
        found: set[int] = set()
        for word, values in self.positions[position].items():
            if word.startswith(prefix):
                found |= values
        return found

    def find(self, query: str) -> set[int]:
        entry = query_text(query)
        tokens = split_words(entry)
        if len(tokens) > 1:
            return self.find_tokens(tokens)
        results: set[int] = set()
        for split in boundaries(len(entry), self.max_words):
            start = 0
            pieces = []
            for end in split:
                pieces.append(entry[start:end])
                start = end
            results |= self.find_tokens(pieces)
        return results

    def find_tokens(self, tokens: list[str]) -> set[int]:
        if len(tokens) > len(self.positions):
            return set()
        return self._find(tokens, 0, 0, None)

    def _find(
        self, tokens: list[str], number: int, minimum: int, within: set[int] | None
    ) -> set[int]:
        results: set[int] = set()
        last = len(self.positions) - (len(tokens) - number)
        for i in range(minimum, last + 1):
            found = self._matches(i, tokens[number])
            if within is not None:
                found &= within
            if found and number + 1 < len(tokens):
                found = self._find(tokens, number + 1, i + 1, found)
            results |= found
        return results

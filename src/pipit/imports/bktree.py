"""A BK-tree of names, for finding names within an edit distance.

Ported from Scythebill ``model/.../util/BKTree.java`` with ``Metrics.levenshteinDistance``.
The search order matters (importers take the first match, or treat the first two as equals),
so it is kept exactly: a node, then its children by increasing distance from it.
"""

from __future__ import annotations

from collections.abc import Callable

from rapidfuzz.distance import Levenshtein


def levenshtein(first: str, second: str) -> int:
    """Commons Text ``LevenshteinDistance``: insertions, deletions and substitutions."""
    return int(Levenshtein.distance(first, second))


class _Node[V]:
    __slots__ = ("children", "key", "value")

    def __init__(self, key: str, value: V) -> None:
        self.key = key
        self.value = value
        self.children: dict[int, _Node[V]] = {}


class BKTree[V]:
    """Build with ``add`` in order; the first key added is the root."""

    def __init__(self, transform: Callable[[str], str] | None = None) -> None:
        self._root: _Node[V] | None = None
        self._transform = transform or (lambda key: key)

    def add(self, key: str, value: V) -> None:
        node = _Node(self._transform(key), value)
        if self._root is None:
            self._root = node
            return
        current = self._root
        while True:
            distance = levenshtein(current.key, node.key)
            child = current.children.get(distance)
            if child is None:
                current.children[distance] = node
                return
            current = child

    def search(self, query: str, maximum_distance: int) -> list[V]:
        found: list[V] = []
        if self._root is None:
            return found
        key = self._transform(query)
        stack = [self._root]
        # Depth-first, children by increasing distance: a stack of reversed child lists.
        while stack:
            node = stack.pop()
            distance = levenshtein(node.key, key)
            if distance <= maximum_distance:
                found.append(node.value)
            if not node.children:
                continue
            nearby = [node.children[i]
                      for i in range(max(0, distance - maximum_distance),
                                     distance + maximum_distance + 1)
                      if i in node.children]  # fmt: skip
            stack.extend(reversed(nearby))
        return found

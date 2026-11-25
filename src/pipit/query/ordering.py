"""Guava's ``Ordering.greatestOf`` exactly, as Scythebill uses it to pick a species' best
sightings: including which of several tied sightings it keeps (``TopKSelector``'s
quickselect), since that decides what Print and the spreadsheet show."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from functools import cmp_to_key
from typing import Any

type Comparator[T] = Callable[[T, T], int]


def greatest_of[T](items: Sequence[T], comparator: Comparator[T], k: int) -> list[T]:
    """``Ordering.greatestOf(collection, k)``: the ``k`` greatest, greatest first."""

    def reverse(a: T, b: T) -> int:
        return comparator(b, a)

    return _least_of(items, reverse, k)


def _least_of[T](items: Sequence[T], comparator: Comparator[T], k: int) -> list[T]:
    if len(items) <= 2 * k:
        return sorted(items, key=cmp_to_key(comparator))[:k]
    if k == 0:
        return []
    return _TopK(comparator, k).run(items)


class _TopK:
    """Guava's ``TopKSelector.least``."""

    def __init__(self, comparator: Comparator[Any], k: int) -> None:
        self.comparator = comparator
        self.k = k
        self.buffer: list[object] = [None] * (2 * k)
        self.size = 0
        self.threshold: object = None

    def run(self, items: Sequence[Any]) -> list[Any]:
        for item in items:
            self.offer(item)
        ordered = sorted(self.buffer[: self.size], key=cmp_to_key(self.comparator))
        return ordered[: self.k]

    def offer(self, item: object) -> None:
        k = self.k
        if self.size == 0:
            self.buffer[0] = item
            self.threshold = item
            self.size = 1
        elif self.size < k:
            self.buffer[self.size] = item
            self.size += 1
            if self.comparator(item, self.threshold) > 0:
                self.threshold = item
        elif self.comparator(item, self.threshold) < 0:
            self.buffer[self.size] = item
            self.size += 1
            if self.size == 2 * k:
                self._trim()

    def _trim(self) -> None:
        k = self.k
        left = 0
        right = 2 * k - 1
        min_threshold_position = 0
        iterations = 0
        max_iterations = math.ceil(math.log2(right - left)) * 3 if right > left else 0
        while left < right:
            pivot_index = (left + right + 1) >> 1
            pivot_new_index = self._partition(left, right, pivot_index)
            if pivot_new_index > k:
                right = pivot_new_index - 1
            elif pivot_new_index < k:
                left = max(pivot_new_index, left + 1)
                min_threshold_position = pivot_new_index
            else:
                break
            iterations += 1
            if iterations >= max_iterations:
                self.buffer[left : right + 1] = sorted(
                    self.buffer[left : right + 1], key=cmp_to_key(self.comparator)
                )
                break
        self.size = k
        self.threshold = self.buffer[min_threshold_position]
        for i in range(min_threshold_position + 1, k):
            if self.comparator(self.buffer[i], self.threshold) > 0:
                self.threshold = self.buffer[i]

    def _partition(self, left: int, right: int, pivot_index: int) -> int:
        buffer = self.buffer
        pivot = buffer[pivot_index]
        buffer[pivot_index] = buffer[right]
        new_index = left
        for i in range(left, right):
            if self.comparator(buffer[i], pivot) < 0:
                buffer[new_index], buffer[i] = buffer[i], buffer[new_index]
                new_index += 1
        buffer[right] = buffer[new_index]
        buffer[new_index] = pivot
        return new_index

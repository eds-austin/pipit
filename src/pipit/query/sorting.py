"""Scythebill's sighting orderings and species sorts.

- ``SightingComparators`` and ``SortType``: each sort is an ordering of sightings in which the
  "best" sighting (the one shown first, or the one a species is placed by) is the greatest.
- ``greatest_of`` (``pipit.query.ordering``) picks a species' best sightings.
- ``ResolvedComparator`` and ``SortedTaxa``: species placed by their best sighting.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cmp_to_key

from pipit.domain.partial_date import PartialField
from pipit.domain.values import ApproximateNumber
from pipit.query.model import QSighting
from pipit.query.ordering import Comparator
from pipit.query.results import QueryResults, taxonomy_index
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType

#: ``SightingComparators.SIGHTING_STATUS_VALUES``: higher is "worse".
_STATUS_VALUES = {"none": 0, "notAccepted": 1, "intro": 2, "provisional": 3, "bvd": 4,
                  "notEstablished": 5, "restrained": 6, "unsatisfactoryViews": 7,
                  "idUncertain": 8, "signs": 9, "dead": 10, "notByMe": 11,
                  "domestic": 12}  # fmt: skip


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _compare(left: object, right: object) -> int:
    return int(left > right) - int(left < right)  # type: ignore[operator]


def prefer_not_heard_only(a: QSighting, b: QSighting) -> int:
    return int(b.heard_only) - int(a.heard_only)


def prefer_not_introduced(a: QSighting, b: QSighting) -> int:
    return _STATUS_VALUES.get(b.status, 0) - _STATUS_VALUES.get(a.status, 0)


def more_recent(a: QSighting, b: QSighting) -> int:
    """``MoreRecentComparator`` (``recency`` sorts exactly as it does)."""
    return _compare(a.recency, b.recency)


def prefer_earlier(a: QSighting, b: QSighting) -> int:
    return -more_recent(a, b)


def _year_key(sighting: QSighting) -> tuple[object, ...]:
    date = sighting.end_date
    if date is None:
        return (0,)
    fields = tuple((-int(field), 1988 if field is PartialField.YEAR else number)
                   for field, number in date.fields)  # fmt: skip
    time_value = sighting.time
    return (1, fields, (0,) if time_value is None else (1, time_value.hour, time_value.minute))


def prefer_earlier_in_the_year(a: QSighting, b: QSighting) -> int:
    """``LaterInTheYearComparator`` reversed: end dates compared as if in 1988."""
    return -_compare(_year_key(a), _year_key(b))


def _count(sighting: QSighting) -> int:
    number = ApproximateNumber.parse(sighting.count) if sighting.count else None
    return 0 if number is None else number.number


def prefer_higher_counts(a: QSighting, b: QSighting) -> int:
    return _count(a) - _count(b)


def compound(*comparators: Comparator[QSighting]) -> Comparator[QSighting]:
    def compare(a: QSighting, b: QSighting) -> int:
        for comparator in comparators:
            result = comparator(a, b)
            if result:
                return result
        return 0

    return compare


#: ``SortType``: each sort's ordering of sightings. Its labels for sorting species and
#: sightings, and whether species sorted by it are numbered.
SORT_TYPES: dict[str, Comparator[QSighting]] = {
    "DEFAULT": compound(prefer_not_heard_only, prefer_not_introduced, prefer_earlier),
    "BY_DATE": prefer_earlier,
    "BY_DATE_DESCENDING": more_recent,
    "BY_DAY_OF_YEAR": prefer_earlier_in_the_year,
    "BY_DAY_OF_YEAR_DESCENDING": lambda a, b: -prefer_earlier_in_the_year(a, b),
    "BY_SIGHTING_COUNT": prefer_higher_counts,
}
SPECIES_SORT_LABELS = {"DEFAULT": "Taxonomic order", "BY_DATE": "Newest additions",
                       "BY_DATE_DESCENDING": "Longest since seen",
                       "BY_DAY_OF_YEAR": "Day of year",
                       "BY_DAY_OF_YEAR_DESCENDING": "Day of year (descending)",
                       "BY_SIGHTING_COUNT": "Number recorded"}  # fmt: skip
NUMBERED_SORTS = ("BY_DATE", "BY_DATE_DESCENDING")


# ------------------------------------------------------------------ taxa


def resolved_comparator(results: QueryResults) -> Comparator[Resolved]:
    """``ResolvedComparator``: taxonomic order, a sp. or hybrid after its last taxon."""
    index = taxonomy_index(results.taxonomy)

    def max_index(resolved: Resolved) -> int:
        return max(index[t.id] for t in resolved.taxa)

    def compare(left: Resolved, right: Resolved) -> int:
        single = SightingTaxonType.SINGLE
        if left.type is single:
            if right.type is single:
                return index[left.taxon.id] - index[right.taxon.id]
            return -1 if index[left.taxon.id] <= max_index(right) else 1
        if right.type is single:
            return -1 if max_index(left) < index[right.taxon.id] else 1
        left_max, right_max = max_index(left), max_index(right)
        if left_max != right_max:
            return left_max - right_max
        left_taxa = sorted(left.taxa, key=lambda taxon: index[taxon.id])
        right_taxa = sorted(right.taxa, key=lambda taxon: index[taxon.id])
        for a, b in zip(left_taxa, right_taxa, strict=False):
            if a is not b:
                return index[a.id] - index[b.id]
        if len(left.taxa) != len(right.taxa):
            return 1 if len(left.taxa) > len(right.taxa) else -1
        return _TYPE_ORDER[left.type] - _TYPE_ORDER[right.type]

    return compare


_TYPE_ORDER = {kind: i for i, kind in enumerate(SightingTaxonType)}


@dataclass(frozen=True, slots=True)
class SortedRow:
    taxon: Resolved
    sighting: QSighting
    number: int  # 0: none


def sorted_rows(results: QueryResults, taxa: list[Resolved], sort_type: str,
                sightings_per_taxon: int, omit: Callable[[Resolved], bool]
                ) -> list[SortedRow]:  # fmt: skip
    """``SortedTaxa.rows``."""
    ordering = SORT_TYPES[sort_type]
    numbered = sort_type in NUMBERED_SORTS
    rows: list[SortedRow] = []
    numbered_by: dict[Resolved, QSighting] = {}
    for taxon in taxa:
        if taxon.smallest_type is TaxonType.FAMILY or omit(taxon):
            continue
        best = results.best_sightings(taxon, ordering, max(1, sightings_per_taxon))
        if not best:
            continue
        if numbered and taxon.type is SightingTaxonType.SINGLE and results.is_countable(taxon):
            numbered_by[taxon] = best[0]
        rows.extend(SortedRow(taxon, sighting, 0) for sighting in best)
    taxonomic = resolved_comparator(results)
    if numbered:

        def row_order(a: SortedRow, b: SortedRow) -> int:
            return ordering(a.sighting, b.sighting) or -taxonomic(a.taxon, b.taxon)
    else:

        def row_order(a: SortedRow, b: SortedRow) -> int:
            return -ordering(a.sighting, b.sighting) or taxonomic(a.taxon, b.taxon)

    rows.sort(key=cmp_to_key(row_order))
    if not numbered_by:
        return rows
    number = len(numbered_by)
    result = []
    for row in rows:
        if numbered_by.get(row.taxon) is row.sighting:
            result.append(SortedRow(row.taxon, row.sighting, number))
            number -= 1
        else:
            result.append(row)
    return result

"""Year comparison: for each species the query finds, its sightings year by year (and half
year by half year), with each year's earliest and latest dates, and the species counted per
year.

Ported from Scythebill ``ui/.../panels/reports/YearComparisonProcessor.java`` and the year
range and sorts of ``YearComparisonPanel``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from pipit.domain.partial_date import (
    PartialDate,
    PartialField,
    after_or_equals,
    before_or_equals,
    compare_partial_dates,
)
from pipit.query.engine import EngineContext, StoredQuery, run_query
from pipit.query.model import QSighting
from pipit.query.results import QueryResults
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType

#: At most a century of years is compared.
MAXIMUM_YEAR_SPAN = 100


class Half(Enum):
    """``SplitYearKey``: the whole year or one of its halves."""

    WHOLE_YEAR = ""
    H1 = "H1"
    H2 = "H2"


def sighting_year(sighting: QSighting) -> int | None:
    """``sightingYear``: the year of a sighting whose dates are in one year, else None."""
    start = sighting.start_date
    end = sighting.end_date
    if start is None or end is None:
        return None
    start_year = start.get(PartialField.YEAR)
    end_year = end.get(PartialField.YEAR)
    if start_year is None or end_year is None or start_year != end_year:
        return None
    return start_year


def half_of(start: PartialDate | None, end: PartialDate | None) -> Half | None:
    """``splitYearKey``: the half of the year a sighting is in, if it has months in one."""
    start_month = None if start is None else start.get(PartialField.MONTH)
    end_month = None if end is None else end.get(PartialField.MONTH)
    if start_month is None or end_month is None:
        return None
    if start_month <= 6 and end_month <= 6:
        return Half.H1
    if start_month > 6 and end_month > 6:
        return Half.H2
    return None


def day_of_year(when: PartialDate, year: int, *, at_end: bool = False) -> int:
    """``dayOfYear``: a date with a month; with no day, the 1st (or the last with
    ``at_end``)."""
    month = when.get(PartialField.MONTH)
    assert month is not None
    day = when.get(PartialField.DAY)
    first = date(year, month, 1)
    if day is not None:
        return first.replace(day=day).timetuple().tm_yday
    if at_end:
        following = date(year + (month == 12), month % 12 + 1, 1)
        return (following.toordinal() - 1) - date(year, 1, 1).toordinal() + 1
    return first.timetuple().tm_yday


def _day_or_mid_month(when: PartialDate, year: int) -> int:
    month = when.get(PartialField.MONTH)
    assert month is not None
    day = when.get(PartialField.DAY) or 14
    return date(year, month, day).timetuple().tm_yday


def sighting_day(start: PartialDate, end: PartialDate | None, year: int) -> int:
    """``sightingDay``: the day of the year a sighting is drawn on, midway between its dates
    (the 14th for a month with no day); 0 with no month."""
    if start.get(PartialField.MONTH) is None:
        return 0
    last = end if end is not None and end.get(PartialField.MONTH) is not None else start
    return (_day_or_mid_month(start, year) + _day_or_mid_month(last, year)) // 2


def _same_month(sighting: QSighting) -> bool:
    start = sighting.start_date
    end = sighting.end_date
    assert start is not None and end is not None
    month = start.get(PartialField.MONTH)
    return month is not None and month == end.get(PartialField.MONTH)


@dataclass(slots=True)
class YearResult:
    """One year (or half): its sightings, and the earliest and latest dates of those in one
    month."""

    earliest: PartialDate | None = None
    latest: PartialDate | None = None
    frequency: int = 0

    def add(self, sighting: QSighting) -> None:
        first = self.frequency == 0
        self.frequency += 1
        if not _same_month(sighting):
            return
        when = sighting.start_date
        assert when is not None
        if first or self.earliest is None or compare_partial_dates(when, self.earliest) < 0:
            self.earliest = when
        if first or self.latest is None or compare_partial_dates(when, self.latest) > 0:
            self.latest = when


def _fields(when: PartialDate, missing_month: int, missing_day: int) -> tuple[int, int]:
    month = when.get(PartialField.MONTH)
    day = when.get(PartialField.DAY)
    return (missing_month if month is None else month, missing_day if day is None else day)


def _less_ignoring_year(a: PartialDate, b: PartialDate) -> bool:
    """``lessThanIgnoringYear``: a missing month or day is never less."""
    return _fields(a, 13, 32) < _fields(b, 13, 32)


def _greater_ignoring_year(a: PartialDate, b: PartialDate) -> bool:
    """``greaterThanIgnoringYear``: a missing month or day is never greater."""
    return _fields(a, -1, -1) > _fields(b, -1, -1)


@dataclass
class SpeciesResult:
    resolved: Resolved
    first_year: int
    last_year: int
    years: dict[Half, dict[int, YearResult]] = field(default_factory=dict)
    days: dict[int, list[int]] = field(default_factory=dict)  # year -> days drawn
    first_year_ever: int | None = None

    def year(self, half: Half, year: int) -> YearResult | None:
        return self.years.get(half, {}).get(year)

    def _add(self, half: Half, year: int, sighting: QSighting) -> None:
        self.years.setdefault(half, {}).setdefault(year, YearResult()).add(sighting)

    def add(self, sighting: QSighting) -> None:
        year = sighting_year(sighting)
        if year is None or not self.first_year <= year <= self.last_year:
            return
        start = sighting.start_date
        end = sighting.end_date
        assert start is not None
        self._add(Half.WHOLE_YEAR, year, sighting)
        half = half_of(start, end)
        if half is not None:
            self._add(half, year, sighting)
        day = sighting_day(start, end, year)
        if day > 0:
            self.days.setdefault(year, []).append(day)

    def total(self, half: Half) -> YearResult:
        """``total``: every year's sightings, earliest and latest by month and day."""
        total = YearResult()
        for _year, result in sorted(self.years.get(half, {}).items()):
            total.frequency += result.frequency
            if total.earliest is None or (
                result.earliest is not None and _less_ignoring_year(result.earliest, total.earliest)
            ):
                total.earliest = result.earliest
            if total.latest is None or (
                result.latest is not None and _greater_ignoring_year(result.latest, total.latest)
            ):
                total.latest = result.latest
        return total

    @property
    def years_present(self) -> int:
        return len(self.years.get(Half.WHOLE_YEAR, {}))

    @property
    def total_sightings(self) -> int:
        return self.total(Half.WHOLE_YEAR).frequency

    @property
    def first_seen(self) -> int | None:
        """``firstYear``: the first year in range with a sighting."""
        seen = self.years.get(Half.WHOLE_YEAR, {})
        return min(seen) if seen else None

    @property
    def last_seen(self) -> int | None:
        seen = self.years.get(Half.WHOLE_YEAR, {})
        return max(seen) if seen else None


@dataclass
class YearComparison:
    first_year: int
    last_year: int
    species: list[SpeciesResult] = field(default_factory=list)  # taxonomic order

    @property
    def years(self) -> range:
        return range(self.first_year, self.last_year + 1)

    def _counted(self, present: Callable[[SpeciesResult], bool]) -> list[SpeciesResult]:
        """``countedSpecies``: single species only (sp.s and hybrids never count)."""
        return [s for s in self.species
                if s.resolved.type is SightingTaxonType.SINGLE and present(s)]  # fmt: skip

    def species_count(self, half: Half, year: int) -> int:
        return len(self._counted(lambda s: s.year(half, year) is not None))

    def species_count_all_years(self, half: Half) -> int:
        return len(self._counted(lambda s: s.total(half).frequency > 0))

    def first_seen_days(self) -> list[list[int]]:
        """``firstSeenDaysByYear``: per year, the sorted days each counted species was first
        seen (left out when that first sighting has no month)."""
        found = []
        for year in self.years:
            days = []
            for species in self.species:
                result = species.year(Half.WHOLE_YEAR, year)
                if (species.resolved.type is SightingTaxonType.SINGLE and result is not None
                        and result.earliest is not None):  # fmt: skip
                    days.append(day_of_year(result.earliest, year))
            found.append(sorted(days))
        return found


def year_range(from_year: int | None, to_year: int | None) -> Callable[[QSighting], bool] | None:
    """``yearRangePredicate``: starting in or after ``from_year`` and ending in or before
    ``to_year``."""
    if from_year is None and to_year is None:
        return None
    start_base = None if from_year is None else PartialDate.of(year=from_year)
    end_base = None if to_year is None else PartialDate.of(year=to_year)

    def accepts(sighting: QSighting) -> bool:
        if start_base is not None:
            start = sighting.start_date
            if start is None or not after_or_equals(start_base, start):
                return False
        if end_base is not None:
            end = sighting.end_date
            if end is None or not before_or_equals(end_base, end):
                return False
        return True

    return accepts


def compare_years(context: EngineContext, query: StoredQuery, *, from_year: int | None = None,
                  to_year: int | None = None, today: date | None = None,
                  ) -> YearComparison:  # fmt: skip
    """``process``: ``context`` at species depth. A species' first year ever comes from the
    query alone, so one seen before the range isn't new in its first year within it."""
    additional = year_range(from_year, to_year)
    results = _run(context, query, additional)
    years = [y for s in results.all_sightings() if (y := sighting_year(s)) is not None]
    if not years:
        current = (today or date.today()).year
        return YearComparison(current, current)
    first = min(years)
    last = min(max(years), first + MAXIMUM_YEAR_SPAN)
    comparison = YearComparison(first, last)
    countable = results.countable
    for resolved in results.taxa:
        species = SpeciesResult(resolved, first, last)
        comparison.species.append(species)
        for sighting in results.sightings_of(resolved):
            if countable is None or countable(sighting):
                species.add(sighting)
    if additional is None:
        for species in comparison.species:
            species.first_year_ever = species.first_seen
        return comparison
    everything = _run(context, query, None)
    for species in comparison.species:
        earliest = species.first_seen
        for sighting in everything.sightings_of(species.resolved):
            year = sighting_year(sighting)
            if year is not None and (everything.countable is None
                                     or everything.countable(sighting)):  # fmt: skip
                earliest = year if earliest is None else min(earliest, year)
        species.first_year_ever = earliest
    return comparison


def _run(context: EngineContext, query: StoredQuery,
         additional: Callable[[QSighting], bool] | None) -> QueryResults:  # fmt: skip
    return run_query(query, context, include_families=False, only_countable=True,
                     additional=additional)  # fmt: skip


#: ``YearComparisonPreferences.Sort``: (key, label); ties keep taxonomic order.
SORTS = (
    ("MOST_SIGHTINGS", "Most sightings"),
    ("MOST_YEARS", "Most years"),
    ("NEWEST", "Newest"),
    ("LONGEST_UNSEEN", "Longest unseen"),
    ("TAXONOMIC", "Taxonomic order"),
)


def sorted_species(comparison: YearComparison, sort: str) -> list[SpeciesResult]:
    """The panel's sorts (stable, so ties stay in taxonomic order). Years missing (no
    sighting) sort as Scythebill's ``Integer.MAX_VALUE`` and ``MIN_VALUE`` do."""
    rows = list(comparison.species)
    if sort == "MOST_YEARS":
        rows.sort(key=lambda s: -s.years_present)
    elif sort == "MOST_SIGHTINGS":
        rows.sort(key=lambda s: -s.total_sightings)
    elif sort == "NEWEST":
        rows.sort(key=lambda s: -(s.first_year_ever if s.first_year_ever is not None
                                  else 2**31 - 1))  # fmt: skip
    elif sort == "LONGEST_UNSEEN":
        rows.sort(key=lambda s: s.last_seen if s.last_seen is not None else -(2**31))
    return rows

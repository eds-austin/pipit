"""Timeline: the life list growing day by day, each year's and each day's species and lifers,
decades, and milestones (every 100th or 1,000th species).

Ported from Scythebill ``ui/.../panels/reports/TimelineData.java`` and the query and sorts of
``TimelinePanel``.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from pipit.domain.partial_date import PartialDate, PartialField
from pipit.query.engine import EngineContext, StoredQuery, run_query
from pipit.query.model import QSighting, QueryList
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import SightingTaxonType


@dataclass(frozen=True, slots=True)
class Lifer:
    species_id: str
    day: date


@dataclass(frozen=True, slots=True)
class Milestone:
    number: int
    lifer: Lifer


@dataclass(frozen=True, slots=True)
class Decade:
    start_year: int
    count: int
    lifers: int


@dataclass(frozen=True, slots=True)
class Period:
    """A year or a day: the species seen, the place they all share (None if any was
    unplaced), and the lifers among them."""

    when: PartialDate
    species: tuple[str, ...]
    place: str | None
    lifers: int

    @property
    def count(self) -> int:
        return len(self.species)

    @property
    def is_day(self) -> bool:
        return self.when.get(PartialField.DAY) is not None

    @property
    def first_day(self) -> date:
        return first_possible_day(self.when)

    @property
    def last_day(self) -> date:
        found = last_possible_day(self.when, self.when)
        assert found is not None
        return found


def last_possible_day(start: PartialDate | None, end: PartialDate | None) -> date | None:
    """``lastPossibleDay``: the end date's (else the start's) last day."""
    when = end if end is not None else start
    if when is None:
        return None
    year = when.get(PartialField.YEAR)
    if year is None:
        return None
    month = when.get(PartialField.MONTH)
    if month is None or not 1 <= month <= 12:
        month = 12
    length = calendar.monthrange(year, month)[1]
    day = length
    given = when.get(PartialField.DAY)
    if when.get(PartialField.MONTH) is not None and given is not None:
        day = max(1, min(length, given))
    return date(year, month, day)


def first_possible_day(when: PartialDate) -> date:
    year = when.get(PartialField.YEAR)
    assert year is not None
    return date(year, when.get(PartialField.MONTH) or 1, when.get(PartialField.DAY) or 1)


def year_bucket(start: PartialDate | None, end: PartialDate | None) -> PartialDate | None:
    if start is None or end is None:
        return None
    year = start.get(PartialField.YEAR)
    if year is None or year != end.get(PartialField.YEAR):
        return None
    return PartialDate.of(year=year)


def day_bucket(start: PartialDate | None, end: PartialDate | None) -> PartialDate | None:
    if start is None or start != end:
        return None
    if any(start.get(f) is None for f in (PartialField.DAY, PartialField.MONTH,
                                          PartialField.YEAR)):  # fmt: skip
        return None
    return start


def decade_of(year: int) -> int:
    return year // 10 * 10


@dataclass
class _PeriodBuilder:
    when: PartialDate
    species: dict[str, None] = field(default_factory=dict)
    place: str | None = None
    common_ancestor: Callable[[str, str], str | None] = lambda first, _second: first

    def add(self, species_id: str, place: str | None) -> None:
        if not self.species:
            self.place = place
        elif self.place is not None:
            if place is None:
                self.place = None
            elif place != self.place:
                self.place = self.common_ancestor(self.place, place)
        self.species[species_id] = None

    def build(self, life_list_days: dict[str, date]) -> Period:
        first = first_possible_day(self.when)
        last = last_possible_day(self.when, self.when)
        assert last is not None
        lifers = sum(1 for species in self.species
                     if (day := life_list_days.get(species)) is not None
                     and first <= day <= last)  # fmt: skip
        return Period(self.when, tuple(self.species), self.place, lifers)


@dataclass
class Timeline:
    lifers: list[Lifer]  # by day, then species ID
    life_list_days: dict[str, date]
    years: list[Period]  # by first day
    days: list[Period]
    decades: dict[int, Decade]
    undated_species: int
    sightings_in_no_year: int
    sightings_on_no_day: int
    latest_day: date | None

    def decade(self, start_year: int) -> Decade:
        return self.decades.get(start_year, Decade(start_year, 0, 0))

    @property
    def life_list_total(self) -> int:
        return len(self.lifers)

    def life_list_on(self, day: date) -> int:
        """The life list's size at the end of ``day``."""
        low, high = 0, len(self.lifers)
        while low < high:
            middle = (low + high) // 2
            if self.lifers[middle].day <= day:
                low = middle + 1
            else:
                high = middle
        return low

    def milestones(self) -> list[Milestone]:
        """Every 100th species (every 1,000th from 1,000 species on)."""
        step = 100 if len(self.lifers) < 1000 else 1000
        return [Milestone(number, self.lifers[number - 1])
                for number in range(step, len(self.lifers) + 1, step)]  # fmt: skip

    @property
    def first_day(self) -> date | None:
        return self.lifers[0].day if self.lifers else None


def build_timeline(sightings: list[QSighting], resolve: Callable[[QSighting], str | None],
                   query_list: QueryList) -> Timeline:  # fmt: skip
    """``fromSightings``: each sighting as its species (``resolve``: None for a sp. or
    hybrid of several species, which are left out)."""
    all_species: set[str] = set()
    life_list_days: dict[str, date] = {}
    years: dict[PartialDate, _PeriodBuilder] = {}
    days: dict[PartialDate, _PeriodBuilder] = {}
    decade_species: dict[int, set[str]] = {}
    latest: date | None = None
    in_no_year = 0
    on_no_day = 0

    def ancestor(first: str, second: str) -> str | None:
        return _common_ancestor(query_list, first, second)

    for sighting in sightings:
        species = resolve(sighting)
        if species is None:
            continue
        start = sighting.start_date
        end = sighting.end_date
        all_species.add(species)
        last = last_possible_day(start, end)
        if last is not None:
            known = life_list_days.get(species)
            if known is None or last < known:
                life_list_days[species] = last
            if latest is None or last > latest:
                latest = last
        place = sighting.location_xml_id
        year = year_bucket(start, end)
        if year is not None:
            year_builder = years.setdefault(year, _PeriodBuilder(year, common_ancestor=ancestor))
            year_builder.add(species, place)
        elif last is not None:
            in_no_year += 1
        start_year = None if start is None else start.get(PartialField.YEAR)
        end_year = None if end is None else end.get(PartialField.YEAR)
        if (start_year is not None and end_year is not None
                and decade_of(start_year) == decade_of(end_year)):  # fmt: skip
            decade_species.setdefault(decade_of(start_year), set()).add(species)
        day = day_bucket(start, end)
        if day is not None:
            days.setdefault(day, _PeriodBuilder(day, common_ancestor=ancestor)).add(species, place)
        elif last is not None:
            on_no_day += 1
    lifers = sorted((Lifer(species, seen) for species, seen in life_list_days.items()),
                    key=lambda lifer: (lifer.day, lifer.species_id))  # fmt: skip
    decades = {}
    for start_year, species_set in decade_species.items():
        new = sum(1 for species in species_set
                  if (seen := life_list_days.get(species)) is not None
                  and decade_of(seen.year) == start_year)  # fmt: skip
        decades[start_year] = Decade(start_year, len(species_set), new)

    def periods(builders: dict[PartialDate, _PeriodBuilder]) -> list[Period]:
        built = [builder.build(life_list_days) for builder in builders.values()]
        return sorted(built, key=lambda period: period.first_day)

    return Timeline(lifers, life_list_days, periods(years), periods(days), decades,
                    len(all_species) - len(life_list_days), in_no_year, on_no_day,
                    latest)  # fmt: skip


def _common_ancestor(query_list: QueryList, first: str, second: str) -> str | None:
    """``Locations.getCommonAncestor`` of two places."""
    above: set[str] = set()
    current: str | None = first
    while current is not None:
        above.add(current)
        current = query_list.parent.get(current)
    current = second
    while current is not None:
        if current in above:
            return current
        current = query_list.parent.get(current)
    return None


def timeline(context: EngineContext, query: StoredQuery) -> Timeline:
    """``showQueryInList``: the query's countable sightings (``context`` at species
    depth)."""
    results = run_query(query, context, include_families=False, only_countable=True)
    resolver = context.resolve

    def species_of(sighting: QSighting) -> str | None:
        resolved = resolver.sighting(sighting)
        if resolved is None:
            return None
        species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
        if species.type in (SightingTaxonType.SP, SightingTaxonType.HYBRID):
            return None
        return species.ids[0]

    return build_timeline(results.all_sightings(), species_of, context.query_list)


#: ``TimelinePreferences.Sort``: (key, label).
SORTS = (("MOST_SPECIES", "Most species"), ("MOST_NEW", "Most new"),
         ("NEWEST_FIRST", "Newest first"))  # fmt: skip

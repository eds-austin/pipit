"""Trips from imported rows: an existing trip the row's dates fall in (at its place or a place
above), else a new one.

Ported from Scythebill ``ui/.../imports/TripImporter.java`` with ``TripUtils.dateRange`` and
``rangeToUserString``, ``PartialDateRanges`` and ``Trips.newId``. The existing trips are put
in Guava ``TreeRangeMap``s by place (every place above a trip's, and "no place"), later
trips taking over the dates they share with earlier ones; a row's trip is the one holding
both its start and end dates, or the only one within them (then taking the row's dates).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import time

from pipit.domain.partial_date import PartialDate, compare_partial_dates
from pipit.domain.report import Link, Location, Photo, ReportSet, Trip
from pipit.imports.places import Places, is_descendent

_ID_LENGTH = 6
_ID_SPLIT = re.compile(r"[ \t\n\x0b\f\r/]+")  # Java's \s is ASCII


def start_to_int(date: PartialDate) -> int:
    """``startPartialDateToInt``: missing fields as early as can be."""
    return ((date.day or 1) + 100 * (date.month or 1)
            + 1200 * (date.year if date.year is not None else 1))  # fmt: skip


def end_to_int(date: PartialDate) -> int:
    """``endPartialDateToInt``: missing fields as late as can be."""
    return ((date.day or 31) + 100 * (date.month or 12)
            + 1200 * (date.year if date.year is not None else 2200))  # fmt: skip


@dataclass(frozen=True, slots=True)
class _Bound:
    value: int
    closed: bool


@dataclass(slots=True)
class _Piece:
    low: _Bound
    high: _Bound
    trip: Trip

    def contains(self, point: int) -> bool:
        above = point > self.low.value or (point == self.low.value and self.low.closed)
        below = point < self.high.value or (point == self.high.value and self.high.closed)
        return above and below


def _below(point: _Bound, low: _Bound) -> bool:
    """Whether an upper bound ``point`` ends before a lower bound ``low`` starts."""
    return point.value < low.value or (point.value == low.value
                                       and not (point.closed and low.closed))  # fmt: skip


class RangeMap:
    """Guava ``TreeRangeMap`` of closed integer ranges (pieces may end up open)."""

    def __init__(self) -> None:
        self.pieces: list[_Piece] = []

    def put(self, low: int, high: int, trip: Trip) -> None:
        new_low, new_high = _Bound(low, True), _Bound(high, True)
        kept: list[_Piece] = []
        for piece in self.pieces:
            if _below(piece.high, new_low) or _below(new_high, piece.low):
                kept.append(piece)
                continue
            if piece.low.value < low:
                kept.append(_Piece(piece.low, _Bound(low, False), piece.trip))
            if piece.high.value > high:
                kept.append(_Piece(_Bound(high, False), piece.high, piece.trip))
        kept.append(_Piece(new_low, new_high, trip))
        kept.sort(key=lambda piece: (piece.low.value, not piece.low.closed))
        self.pieces = kept

    def get(self, point: int) -> Trip | None:
        return next((piece.trip for piece in self.pieces if piece.contains(point)), None)

    def within(self, low: int, high: int) -> list[Trip]:
        """``subRangeMap(range).asMapOfRanges().values()``: a trip per piece meeting it."""
        query_low, query_high = _Bound(low, True), _Bound(high, True)
        return [
            piece.trip
            for piece in self.pieces
            if not (_below(piece.high, query_low) or _below(query_high, piece.low))
        ]


@dataclass(slots=True)
class TripInfo:
    start_date: PartialDate
    end_date: PartialDate
    location_id: str | None
    start_time: time | None = None
    name: str | None = None
    notes: str | None = None
    links: list[Link] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)


class TripImporter:
    def __init__(self, report: ReportSet, places: Places) -> None:
        self.report = report
        self.places = places
        self._maps: dict[str | None, RangeMap] = {}
        for trip in report.trips:
            location = places.by_id.get(trip.location_id) if trip.location_id else None
            while True:
                key = None if location is None else location.id
                self._maps.setdefault(key, RangeMap()).put(
                    start_to_int(trip.start_date), end_to_int(trip.end_date), trip
                )
                if location is None:
                    break
                location = location.parent

    def create(self, info: TripInfo) -> Trip:
        """``createTrip``: an existing trip (maybe changed) or a new one."""
        location = self.places.by_id.get(info.location_id) if info.location_id else None
        low, high = start_to_int(info.start_date), end_to_int(info.end_date)
        trip: Trip | None = None
        current = location
        while True:
            found = self._maps.get(None if current is None else current.id)
            if found is not None:
                trip = self._existing(found, low, high, info)
            if current is None or trip is not None:
                break
            current = current.parent
        if trip is not None:
            return trip
        return self._new(info, location)

    def _existing(self, found: RangeMap, low: int, high: int, info: TripInfo) -> Trip | None:
        at_start, at_end = found.get(low), found.get(high)
        existing: Trip | None = None
        new_dates = False
        if at_start is not None and at_start is at_end:
            existing = at_start
        else:
            inside = found.within(low, high)
            if len(inside) == 1:
                existing = inside[0]
                new_dates = True
        if existing is None:
            return None
        trip: Trip | None = None
        moved_to: str | None = None
        if info.location_id == existing.location_id:
            trip = existing
        elif info.location_id is not None and existing.location_id is not None:
            existing_place = self.places.by_id[existing.location_id]
            new_place = self.places.by_id[info.location_id]
            if is_descendent(existing_place, new_place):
                trip = existing
            elif is_descendent(new_place, existing_place):
                trip = existing
                moved_to = info.location_id
        if trip is None:
            return None
        if not trip.name:
            trip.name = info.name
        if new_dates:
            if compare_partial_dates(info.start_date, info.end_date) > 0:
                raise ValueError("startDate must be before endDate")
            trip.start_date, trip.end_date = info.start_date, info.end_date
        if moved_to is not None:
            trip.location_id = moved_to
        trip.links = _merge_by_uri(trip.links, info.links)
        trip.photos = _merge_by_uri(trip.photos, info.photos)
        if info.notes:
            if not trip.notes:
                trip.notes = info.notes
            elif trip.notes != info.notes:
                trip.notes = f"{trip.notes}\n{info.notes}"
        return trip

    def _new(self, info: TripInfo, location: Location | None) -> Trip:
        name = info.name
        if not name:
            # Scythebill names it after its place, but by then has walked that place up to
            # nothing, so it always fails: the row isn't imported. (Its name would have been
            # "<place>, <range_to_user_string>".)
            raise ValueError("Scythebill can't make a trip without a name")
        if compare_partial_dates(info.start_date, info.end_date) > 0:
            raise ValueError("startDate must be before endDate")
        if location is not None:
            self.places.ensure_added(location)
        trip = Trip(
            new_trip_id(name, {trip.id for trip in self.report.trips}),
            info.start_date,
            info.end_date,
            info.location_id,
            info.start_time,
            name or None,
            info.notes or None,
            list(info.links),
            list(info.photos),
        )
        self.report.trips.append(trip)
        return trip


def _merge_by_uri[T: Link | Photo](existing: list[T], added: list[T]) -> list[T]:
    """``mergeByUri``: the existing ones, then those added with other URIs."""
    merged: list[T] = []
    seen: set[str] = set()
    for item in [*existing, *added]:
        if item.uri not in seen:
            seen.add(item.uri)
            merged.append(item)
    return merged


def _year(year: int) -> str:
    """``PartialDateIO.formatYear``."""
    return f"0{year}" if year < 10 else str(year)


def _year_month(year: int, month: int) -> str:
    """``PartialDateDisplay.toShortUserString`` of a month: "4/2024"."""
    return f"{month}/{_year(year)}"


def range_to_user_string(start: PartialDate, end: PartialDate) -> str | None:
    """``TripUtils.rangeToUserString``: "2024", "2023-2024", "4/2024" or "4/2024-5/2024"."""
    if start.year is None or end.year is None:
        return None
    if start.year != end.year:
        return f"{start.year}-{end.year}"
    if start.month is None or end.month is None:
        return str(start.year)
    if start.month == end.month:
        return _year_month(start.year, start.month)
    return f"{_year_month(start.year, start.month)}-{_year_month(end.year, end.month)}"


def new_trip_id(name: str | None, taken: set[str]) -> str:
    """``Trips.newId``: up to six characters spread over the name's words (digits from the
    end of all-digit words), then 1, 2, ... until unused."""
    built = ""
    if name is not None:
        parts = [part for part in _ID_SPLIT.split(name) if part]
        for i, part in enumerate(parts):
            remaining = _ID_LENGTH - len(built)
            per_word = max(1, math.ceil(remaining / (len(parts) - i)))
            if part.isdigit():
                built += part[max(0, len(part) - per_word) :]
            else:
                built += part[:per_word].lower()
    else:
        built = "t"
    if built not in taken:
        return built
    count = 1
    while f"{built}{count}" in taken:
        count += 1
    return f"{built}{count}"

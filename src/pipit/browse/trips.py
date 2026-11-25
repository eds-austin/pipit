"""The Trips screen's data: trips newest first, and which sightings belong to a trip.

A trip's sightings are, as in Scythebill's Trips screen (``SightingPredicates.isPartOfTrip``),
those attached to it, plus any sighting inside its place (anywhere, if it has none) whose
dates fall within the trip's (``afterOrEquals`` its start and ``beforeOrEquals`` its end,
comparing only the fields the trip's dates have). An undated sighting on a trip takes that
trip's dates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from functools import cmp_to_key

from pipit.browse.dates import display_date
from pipit.domain.partial_date import (
    PartialDate,
    after_or_equals,
    before_or_equals,
    compare_partial_dates,
    parse_partial_date,
)


@dataclass(frozen=True, slots=True)
class TripRow:
    row: int
    xml_id: str
    name: str
    start: PartialDate
    end: PartialDate
    start_text: str
    end_text: str
    start_time: str
    location_xml_id: str | None
    notes: str
    links: int
    photos: int


def _shown(date: PartialDate) -> str:
    return display_date(date.year, date.month, date.day)


def trip_rows(connection: sqlite3.Connection, query: str = "") -> list[TripRow]:
    """Trips by start date, newest first (Scythebill's order: ``comparePartialDates``
    reversed, ties in list order). ``query`` keeps trips whose name or notes contain it."""
    needle = query.strip().casefold()
    rows = []
    for (row, xml_id, name, start, end, start_time, location, notes, links,
         photos) in connection.execute(
        "SELECT t.id, t.xml_id, t.name, t.start_date, t.end_date, t.start_time, "
        "t.location_xml_id, t.notes, (SELECT count(*) FROM links l WHERE l.trip_id = t.id), "
        "(SELECT count(*) FROM photos p WHERE p.trip_id = t.id) FROM trips t ORDER BY t.ord"
    ):  # fmt: skip
        if (
            needle
            and needle not in (name or "").casefold()
            and needle not in (notes or "").casefold()
        ):
            continue
        start_date = parse_partial_date(start)
        end_date = parse_partial_date(end)
        rows.append(TripRow(row, xml_id, name or "", start_date, end_date, _shown(start_date),
                            _shown(end_date), start_time or "", location, notes or "", links,
                            photos))  # fmt: skip
    return sorted(rows, key=cmp_to_key(_by_start), reverse=True)


def _by_start(left: TripRow, right: TripRow) -> int:
    return compare_partial_dates(left.start, right.start)


def trip_sighting_ids(connection: sqlite3.Connection, trip: TripRow) -> list[int]:
    """The trip's sightings in list order (see the module docstring)."""
    trip_dates = {
        xml_id: (parse_partial_date(start), parse_partial_date(end))
        for xml_id, start, end in connection.execute(
            "SELECT xml_id, start_date, end_date FROM trips"
        )
    }
    if trip.location_xml_id is None:
        candidates = connection.execute(
            "SELECT s.id, s.date, s.trip_xml_id FROM sightings s ORDER BY s.ord"
        )
    else:
        candidates = connection.execute(
            "SELECT s.id, s.date, s.trip_xml_id FROM sightings s "
            "WHERE s.trip_xml_id = ? OR s.location_xml_id IN ("
            " SELECT l.xml_id FROM location_closure c JOIN locations l ON l.id = c.descendant"
            " JOIN locations a ON a.id = c.ancestor WHERE a.xml_id = ?) ORDER BY s.ord",
            (trip.xml_id, trip.location_xml_id),
        )
    parsed: dict[str, PartialDate] = {}
    found = []
    for sighting, date, own_trip in candidates:
        if own_trip == trip.xml_id:
            found.append(sighting)
            continue
        if date is not None:
            start = end = parsed.setdefault(date, parse_partial_date(date))
        elif own_trip is not None and own_trip in trip_dates:
            start, end = trip_dates[own_trip]
        else:
            continue
        if after_or_equals(trip.start, start) and before_or_equals(trip.end, end):
            found.append(sighting)
    return found

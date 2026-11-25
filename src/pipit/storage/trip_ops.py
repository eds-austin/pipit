"""Changing trips, with Scythebill's exact rules (each call runs inside the caller's
``ListDatabase.action``, so it is one undo step).

Ported from Scythebill:
- ``TripInfoBrowsePanel.save`` (edit): name, dates and notes as typed (empty notes are
  removed); a new place moves the trip's sightings that were at its old place to the new
  one (Scythebill removes and re-adds them, so they go to the end of the list); sightings
  elsewhere stay where they are. The end date may not come before the start date.
- ``ReportSet.deleteTrips`` (delete): no sighting is deleted. Each of the trip's sightings
  loses the trip and goes to the end of the list; one without its own date gets the date
  the trip's start and end share (``getCommonPartialDate``), else the start year.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pipit.domain.partial_date import (
    PartialDate,
    PartialField,
    common_partial_date,
    compare_partial_dates,
    format_partial_date,
    parse_partial_date,
)


class TripError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Trip:
    row: int
    xml_id: str
    location_xml_id: str | None
    start: PartialDate
    end: PartialDate
    name: str
    notes: str


def _trip(connection: sqlite3.Connection, row: int) -> _Trip:
    found = connection.execute(
        "SELECT id, xml_id, location_xml_id, start_date, end_date, name, notes FROM trips "
        "WHERE id = ?",
        (row,),
    ).fetchone()
    if found is None:
        raise TripError("That trip no longer exists.")
    return _Trip(found[0], found[1], found[2], parse_partial_date(found[3]),
                 parse_partial_date(found[4]), found[5] or "", found[6] or "")  # fmt: skip


def _to_end(connection: sqlite3.Connection, sighting_ids: list[int]) -> None:
    """Scythebill's remove-and-add: the sightings go to the end, in their order."""
    order: int = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM sightings").fetchone()[
        0
    ]
    for offset, sighting in enumerate(sighting_ids):
        connection.execute("UPDATE sightings SET ord = ? WHERE id = ?", (order + offset, sighting))


def update_trip(
    connection: sqlite3.Connection,
    row: int,
    *,
    name: str,
    start: str,
    end: str,
    location_xml_id: str | None,
    notes: str,
) -> None:
    trip = _trip(connection, row)
    if not name.strip():
        raise TripError("A trip needs a name.")
    try:
        start_date = parse_partial_date(start.strip())
        end_date = parse_partial_date(end.strip())
    except ValueError as error:
        raise TripError(f"Invalid date: {error}") from error
    if not start_date.fields or not end_date.fields:
        raise TripError("A trip needs a start and an end date.")
    if compare_partial_dates(start_date, end_date) > 0:
        raise TripError("The end date must not come before the start date.")
    if (
        location_xml_id is not None
        and not connection.execute(
            "SELECT 1 FROM locations WHERE xml_id = ?", (location_xml_id,)
        ).fetchone()
    ):
        raise TripError("That place no longer exists.")
    if name != trip.name:
        connection.execute("UPDATE trips SET name = ? WHERE id = ?", (name, row))
    if start_date != trip.start or end_date != trip.end:
        connection.execute(
            "UPDATE trips SET start_date = ?, end_date = ? WHERE id = ?",
            (format_partial_date(start_date), format_partial_date(end_date), row),
        )
    if notes != trip.notes:
        connection.execute("UPDATE trips SET notes = ? WHERE id = ?", (notes or None, row))
    if location_xml_id != trip.location_xml_id:
        if location_xml_id is not None:
            moving = [
                sighting
                for (sighting,) in connection.execute(
                    "SELECT id FROM sightings WHERE trip_xml_id = ? AND location_xml_id IS ? "
                    "ORDER BY ord",
                    (trip.xml_id, trip.location_xml_id),
                )
            ]
            for sighting in moving:
                connection.execute(
                    "UPDATE sightings SET location_xml_id = ? WHERE id = ?",
                    (location_xml_id, sighting),
                )
            _to_end(connection, moving)
        connection.execute(
            "UPDATE trips SET location_xml_id = ? WHERE id = ?", (location_xml_id, row)
        )


def delete_trip(connection: sqlite3.Connection, row: int) -> int:
    """Delete the trip, keeping its sightings; returns how many sightings it had."""
    trip = _trip(connection, row)
    fallback = common_partial_date(trip.start, trip.end)
    if fallback is None and trip.start.get(PartialField.YEAR) is not None:
        fallback = PartialDate.of(trip.start.get(PartialField.YEAR))
    sightings = connection.execute(
        "SELECT id, date FROM sightings WHERE trip_xml_id = ? ORDER BY ord", (trip.xml_id,)
    ).fetchall()
    for sighting, date in sightings:
        if date is None and fallback is not None:
            connection.execute(
                "UPDATE sightings SET trip_xml_id = NULL, date = ?, date_y = ?, date_m = ?, "
                "date_d = ? WHERE id = ?",
                (format_partial_date(fallback), fallback.year, fallback.month, fallback.day,
                 sighting),
            )  # fmt: skip
        else:
            connection.execute("UPDATE sightings SET trip_xml_id = NULL WHERE id = ?", (sighting,))
    _to_end(connection, [sighting for sighting, _ in sightings])
    connection.execute("DELETE FROM trips WHERE id = ?", (row,))
    return len(sightings)

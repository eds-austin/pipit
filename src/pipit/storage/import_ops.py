"""Storing an import: what an import made of the list in memory, written into the list
database as the changes it amounts to.

An import (``pipit.imports``) only adds to a list, apart from overwritten duplicates: it adds
places (and moves places it gave coordinates or a hotspot to the end of their parent's, as
Scythebill does), adds sightings at the end, removes overwritten ones, and adds or replaces
checklists' details. Called inside one ``ListDatabase.action``, so the import is one undo
step; the caller checks the stored list exports as the result does.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pipit.domain.partial_date import format_partial_date
from pipit.domain.report import Location, ReportSet, Sighting, Visit
from pipit.storage.repository import float_text as _float_text
from pipit.storage.repository import save_sightings


@dataclass(frozen=True, slots=True)
class _StoredPlace:
    row: int
    parent: int | None
    order: int
    latitude: str | None
    longitude: str | None
    hotspot: str | None
    description: str | None


def store_import(connection: sqlite3.Connection, report: ReportSet,
                 original: list[Sighting], removed: list[Sighting],
                 added: list[Sighting]) -> None:  # fmt: skip
    """``original``: the sightings as loaded (in stored order), of which ``removed`` go;
    ``added`` are appended; places and visits as in ``report``."""
    _store_places(connection, report.roots)
    if removed:
        rows = [row for (row,) in connection.execute("SELECT id FROM sightings ORDER BY ord")]
        position = {id(sighting): i for i, sighting in enumerate(original)}
        connection.executemany(
            "DELETE FROM sightings WHERE id = ?",
            [(rows[position[id(sighting)]],) for sighting in removed],
        )
    first = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM sightings").fetchone()[0]
    save_sightings(connection, added, first_order=first)
    _store_visits(connection, report.visits)


def _store_places(connection: sqlite3.Connection, roots: list[Location]) -> None:
    stored = {
        xml_id: _StoredPlace(row, parent, order, latitude, longitude, hotspot, description)
        for xml_id, row, parent, order, latitude, longitude, hotspot, description
        in connection.execute(
            "SELECT xml_id, id, parent_id, ord, latitude, longitude, ebird_hotspot_id, "
            "description FROM locations")
    }  # fmt: skip
    rows: dict[str, int] = {}

    def store(location: Location, parent: int | None, order: int) -> None:
        latitude = location.lat_long.latitude if location.lat_long else None
        longitude = location.lat_long.longitude if location.lat_long else None
        found = stored.get(location.id)
        if found is None:
            cursor = connection.execute(
                "INSERT INTO locations(xml_id, parent_id, ord, type, name, ebird_code, "
                "ebird_hotspot_id, latitude, longitude, private, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (location.id, parent, order, location.type, location.name, location.ebird_code,
                 location.ebird_hotspot_id, latitude, longitude, int(location.private),
                 location.description),
            )  # fmt: skip
            assert cursor.lastrowid is not None
            rows[location.id] = cursor.lastrowid
        else:
            rows[location.id] = found.row
            if found.parent != parent:
                raise ValueError(f"an import moved {location.id} to another parent")
            if (found.order, found.latitude, found.longitude, found.hotspot, found.description) != (
                order,
                latitude,
                longitude,
                location.ebird_hotspot_id,
                location.description,
            ):
                connection.execute(
                    "UPDATE locations SET ord = ?, latitude = ?, longitude = ?, "
                    "ebird_hotspot_id = ?, description = ? WHERE id = ?",
                    (order, latitude, longitude, location.ebird_hotspot_id,
                     location.description, found.row),
                )  # fmt: skip
        for child_order, child in enumerate(location.children):
            store(child, rows[location.id], child_order)

    for order, root in enumerate(roots):
        store(root, None, order)
    missing = set(stored) - set(rows)
    if missing:
        raise ValueError(f"an import would remove places: {sorted(missing)[:5]}")


def _store_visits(connection: sqlite3.Connection, visits: list[Visit]) -> None:
    stored = {
        (location, date, start): (row, order)
        for row, order, location, date, start in connection.execute(
            "SELECT id, ord, location_xml_id, date, start_time FROM visits")
    }  # fmt: skip
    next_order = max((order for _, order in stored.values()), default=-1) + 1
    for visit in visits:
        key = visit.key
        date = format_partial_date(key.date)
        start = "" if key.start_time is None else f"{key.start_time:%H:%M}"
        values = (visit.observation_type.type_id, _float_text(visit.area_hectares),
                  _float_text(visit.distance_km), visit.duration_minutes or None, visit.party_size,
                  visit.comments, int(visit.complete))  # fmt: skip
        found = stored.get((key.location_id, date, start))
        if found is None:
            connection.execute(
                "INSERT INTO visits(ord, location_xml_id, date, date_y, date_m, date_d, "
                "start_time, observation_type, area_hectares, distance_km, duration_minutes, "
                "party_size, comments, complete) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (next_order, key.location_id, date, key.date.year, key.date.month, key.date.day,
                 start, *values),
            )  # fmt: skip
            next_order += 1
            continue
        current = connection.execute(
            "SELECT observation_type, area_hectares, distance_km, duration_minutes, "
            "party_size, comments, complete FROM visits WHERE id = ?", (found[0],),
        ).fetchone()  # fmt: skip
        if tuple(current) != values:
            connection.execute(
                "UPDATE visits SET observation_type = ?, area_hectares = ?, distance_km = ?, "
                "duration_minutes = ?, party_size = ?, comments = ?, complete = ? WHERE id = ?",
                (*values, found[0]),
            )
        photos = [(photo.uri, photo.name, int(photo.favorite)) for photo in visit.photos]
        if _photos(connection, found[0]) != photos:
            # A replaced visit (Scythebill replaces it whole) has the import's photos: none.
            connection.execute("DELETE FROM photos WHERE visit_id = ?", (found[0],))
            connection.executemany(
                "INSERT INTO photos(visit_id, ord, uri, name, favorite) VALUES (?, ?, ?, ?, ?)",
                [(found[0], i, *photo) for i, photo in enumerate(photos)],
            )


def _photos(connection: sqlite3.Connection, visit_row: int) -> list[tuple[str, str | None, int]]:
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT uri, name, favorite FROM photos WHERE visit_id = ? ORDER BY ord", (visit_row,)
        )
    ]

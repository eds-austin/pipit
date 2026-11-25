"""Changing the location tree, with Scythebill's exact rules (each call runs inside the
caller's transaction, normally ``ListDatabase.action``, so every change is undoable).

Ported from Scythebill:
- ``ReportSet.deleteLocation``: only a location without children; built-in ones only if
  they have no eBird code or are on Scythebill's short allowlist. Its sightings move to the
  parent (appended at the end of the list, as Scythebill re-adds them); its visits move to
  the parent unless the parent already has a visit at that date and time (then they are
  dropped); trips move to the parent; its custom checklist is removed.
- ``LocationReplacements.replaceLocation`` (merge): the old location is renamed
  "~~~~~<name>" and loses its eBird code, its children move into the new one (merging
  any that clash by name), it moves inside the new one, and is deleted as above.
- ``LocationReplacements.reparentReplacingIfNeeded`` (move): a clash by name with a child
  of the new parent is merged first.
- ``ReassignNewBuiltInLocations``: a user location under a built-in one that matches a
  built-in place not yet created is replaced by that built-in place.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pipit.domain.locations import (
    PREDEFINED_PREFIX,
    PredefinedLocations,
    create_id,
    is_built_in,
    names_equal,
)
from pipit.domain.report import LOCATION_TYPES, Location
from pipit.domain.values import LatLong
from pipit.storage.repository import load_locations

#: ReportSet.DELETEABLE_BUILT_IN_LOCATIONS: built-in places Scythebill lets you delete.
DELETABLE_BUILT_IN_CODES = frozenset({
    "CU-02", "FI-AL", "FI-ES", "FI-IS", "FI-LL", "FI-LS", "FI-OL", "LV-AI", "LV-AL", "LV-BL",
    "LV-BU", "LV-CE", "LV-DA", "LV-DGV", "LV-DO", "LV-GU", "LV-JEL", "LV-JK", "LV-JL",
    "LV-JUR", "LV-KR", "LV-KU", "LV-LE", "LV-LM", "LV-LPX", "LV-LU", "LV-MA", "LV-OG",
    "LV-PR", "LV-RE", "LV-REZ", "LV-RI", "LV-RIX", "LV-SA",
})  # fmt: skip
_MERGED_PREFIX = "~~~~~"


class LocationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Row:
    row: int
    xml_id: str
    parent: int | None
    name: str
    ebird_code: str | None


def _row(connection: sqlite3.Connection, row: int) -> _Row:
    found = connection.execute(
        "SELECT id, xml_id, parent_id, name, ebird_code FROM locations WHERE id = ?", (row,)
    ).fetchone()
    if found is None:
        raise LocationError(f"no location {row}")
    return _Row(*found)


def row_of(connection: sqlite3.Connection, xml_id: str) -> int:
    found = connection.execute("SELECT id FROM locations WHERE xml_id = ?", (xml_id,)).fetchone()
    if found is None:
        raise LocationError(f"no location {xml_id}")
    return int(found[0])


def _children(connection: sqlite3.Connection, row: int) -> list[_Row]:
    return [
        _Row(*found)
        for found in connection.execute(
            "SELECT id, xml_id, parent_id, name, ebird_code FROM locations WHERE parent_id = ? "
            "ORDER BY ord",
            (row,),
        )
    ]


def _child_named(connection: sqlite3.Connection, parent: int, name: str) -> _Row | None:
    found = connection.execute(
        "SELECT id, xml_id, parent_id, name, ebird_code FROM locations "
        "WHERE parent_id = ? AND name = ?",
        (parent, name),
    ).fetchone()
    return None if found is None else _Row(*found)


def _next_order(connection: sqlite3.Connection, parent: int | None) -> int:
    value: int = connection.execute(
        "SELECT coalesce(max(ord), -1) + 1 FROM locations WHERE parent_id IS ?", (parent,)
    ).fetchone()[0]
    return value


def _is_inside(connection: sqlite3.Connection, row: int, ancestor: int) -> bool:
    current: int | None = row
    while current is not None:
        if current == ancestor:
            return True
        current = connection.execute(
            "SELECT parent_id FROM locations WHERE id = ?", (current,)
        ).fetchone()[0]
    return False


def _reparent(connection: sqlite3.Connection, row: int, parent: int) -> None:
    """``setParent``: appended at the end of the new parent's children."""
    connection.execute(
        "UPDATE locations SET parent_id = ?, ord = ? WHERE id = ?",
        (parent, _next_order(connection, parent), row),
    )


# ------------------------------------------------------------------ delete


def can_delete(connection: sqlite3.Connection, row: int) -> str | None:
    """Why the location can't be deleted, or None."""
    location = _row(connection, row)
    if (
        location.xml_id.startswith("_")
        and location.ebird_code
        and (location.ebird_code not in DELETABLE_BUILT_IN_CODES)
    ):
        return "Built-in places can't be deleted."
    if _children(connection, row):
        return "Delete or move the places inside it first."
    return None


def delete_location(connection: sqlite3.Connection, row: int) -> None:
    reason = can_delete(connection, row)
    if reason is not None:
        raise LocationError(reason)
    location = _row(connection, row)
    parent = None if location.parent is None else _row(connection, location.parent)
    parent_id = None if parent is None else parent.xml_id
    # Sightings move to the parent and are re-added at the end, in their order.
    moved = [
        sighting
        for (sighting,) in connection.execute(
            "SELECT id FROM sightings WHERE location_xml_id = ? ORDER BY ord", (location.xml_id,)
        )
    ]
    order: int = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM sightings").fetchone()[
        0
    ]
    for offset, sighting in enumerate(moved):
        connection.execute(
            "UPDATE sightings SET location_xml_id = ?, ord = ? WHERE id = ?",
            (parent_id, order + offset, sighting),
        )
    # Visits move to the parent unless it already has one at that date and time.
    for visit, date, start_time in connection.execute(
        "SELECT id, date, start_time FROM visits WHERE location_xml_id = ? ORDER BY ord",
        (location.xml_id,),
    ).fetchall():
        occupied = (
            parent_id is None
            or connection.execute(
                "SELECT 1 FROM visits WHERE location_xml_id = ? AND date = ? AND start_time = ?",
                (parent_id, date, start_time),
            ).fetchone()
        )
        if occupied:
            connection.execute("DELETE FROM visits WHERE id = ?", (visit,))
        else:
            visit_order = connection.execute(
                "SELECT coalesce(max(ord), -1) + 1 FROM visits"
            ).fetchone()[0]
            connection.execute(
                "UPDATE visits SET location_xml_id = ?, ord = ? WHERE id = ?",
                (parent_id, visit_order, visit),
            )
    connection.execute(
        "UPDATE trips SET location_xml_id = ? WHERE location_xml_id = ?",
        (parent_id, location.xml_id),
    )
    connection.execute("DELETE FROM checklists WHERE location_xml_id = ?", (location.xml_id,))
    connection.execute("DELETE FROM locations WHERE id = ?", (row,))


# ------------------------------------------------------------------ merge and move


def merge_location(connection: sqlite3.Connection, old: int, new: int) -> None:
    """``replaceLocation(new, old)``: everything in ``old`` ends up in ``new``."""
    if old == new or _is_inside(connection, new, old):
        raise LocationError("A place can't be merged into itself or a place inside it.")
    source = _row(connection, old)
    connection.execute(
        "UPDATE locations SET name = ?, ebird_code = NULL WHERE id = ?",
        (_MERGED_PREFIX + source.name, old),
    )
    for child in _children(connection, old):
        clash = _child_named(connection, new, child.name)
        if clash is not None:
            merge_location(connection, child.row, clash.row)
        else:
            _reparent(connection, child.row, new)
    _reparent(connection, old, new)
    delete_location(connection, old)


def move_location(connection: sqlite3.Connection, row: int, new_parent: int) -> None:
    """``reparentReplacingIfNeeded``: a same-named child of the new parent is merged into
    the moving location first."""
    location = _row(connection, row)
    if location.parent == new_parent:
        return
    if _is_inside(connection, new_parent, row):
        raise LocationError("A place can't be moved inside itself.")
    clash = _child_named(connection, new_parent, location.name)
    if clash is not None:
        merge_location(connection, clash.row, row)
    _reparent(connection, row, new_parent)


# ------------------------------------------------------------------ create and edit


def add_location(
    connection: sqlite3.Connection,
    parent: int,
    name: str,
    location_type: str | None = None,
    *,
    latitude: str | None = None,
    longitude: str | None = None,
) -> str:
    name = name.strip()
    if not name:
        raise LocationError("A place needs a name.")
    if location_type is not None and location_type not in LOCATION_TYPES:
        raise LocationError(f"Unknown location type {location_type}.")
    if _child_named(connection, parent, name) is not None:
        raise LocationError(f"There is already a place called {name} there.")
    lat_long = LatLong.parse(latitude, longitude) if latitude and longitude else None
    ids = {xml_id for (xml_id,) in connection.execute("SELECT xml_id FROM locations")}
    xml_id = create_id(name, ids)
    connection.execute(
        "INSERT INTO locations(xml_id, parent_id, ord, type, name, latitude, longitude) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (xml_id, parent, _next_order(connection, parent), location_type, name,
         lat_long.latitude if lat_long else None, lat_long.longitude if lat_long else None),
    )  # fmt: skip
    return xml_id


def rename_location(connection: sqlite3.Connection, row: int, name: str) -> None:
    location = _row(connection, row)
    name = name.strip()
    if not name:
        raise LocationError("A place needs a name.")
    if location.xml_id.startswith("_"):
        raise LocationError("Built-in places keep their names.")
    if name == location.name:
        return
    if location.parent is not None and _child_named(connection, location.parent, name):
        raise LocationError(f"There is already a place called {name} there.")
    connection.execute("UPDATE locations SET name = ? WHERE id = ?", (name, row))


def edit_location(
    connection: sqlite3.Connection,
    row: int,
    *,
    latitude: str = "",
    longitude: str = "",
    description: str = "",
    private: bool = False,
    hotspot: str = "",
) -> None:
    """Coordinates (both or neither), description, private flag, eBird hotspot ID."""
    lat_long = None
    if latitude.strip() or longitude.strip():
        try:
            lat_long = LatLong.parse(latitude.strip(), longitude.strip())
        except ValueError as error:
            raise LocationError(f"Invalid coordinates: {error}") from error
    connection.execute(
        "UPDATE locations SET latitude = ?, longitude = ?, description = ?, private = ?, "
        "ebird_hotspot_id = ? WHERE id = ?",
        (lat_long.latitude if lat_long else None, lat_long.longitude if lat_long else None,
         description.strip() or None, int(private), hotspot.strip() or None, row),
    )  # fmt: skip


# ------------------------------------------------------------------ built-in reassignment


def reassign_new_built_in_locations(
    connection: sqlite3.Connection, predefined: PredefinedLocations
) -> list[str]:
    """``ReassignNewBuiltInLocations``; returns the codes of the built-in places created."""
    created: list[str] = []
    for root in load_locations(connection):
        _reassign(connection, predefined, root, created)
    return created


def _reassign(
    connection: sqlite3.Connection,
    predefined: PredefinedLocations,
    location: Location,
    created: list[str],
) -> None:
    parent = location.parent
    current_xml_id = location.id
    # The parent may itself have been replaced (re-read children carry the new parent).
    if not is_built_in(location) and parent is not None and is_built_in(parent):
        name = (
            location.name.removesuffix(" County")
            if location.name.endswith(" County")
            else location.name
        )
        match = None
        for candidate in predefined.children(parent):
            if names_equal(name, candidate.name):
                match = candidate
                break
        codes_present = connection.execute(
            "SELECT 1 FROM locations WHERE ebird_code = ?", (match.code if match else None,)
        ).fetchone()
        if match is not None and not codes_present:
            parent_row = row_of(connection, parent.id)
            same = _child_named(connection, parent_row, match.name)
            if same is None or same.xml_id == location.id:
                ids = {xml_id for (xml_id,) in connection.execute("SELECT xml_id FROM locations")}
                new_id = create_id(match.name, ids, PREDEFINED_PREFIX, match.code)
                old_row = row_of(connection, location.id)
                # replaceLocation: rename the old one first so the new name is free.
                connection.execute(
                    "UPDATE locations SET name = ?, ebird_code = NULL WHERE id = ?",
                    (_MERGED_PREFIX + location.name, old_row),
                )
                connection.execute(
                    "INSERT INTO locations(xml_id, parent_id, ord, type, name, ebird_code) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id, parent_row, _next_order(connection, parent_row), match.type,
                     match.name, match.code),
                )  # fmt: skip
                merge_location(connection, old_row, row_of(connection, new_id))
                created.append(match.code)
                current_xml_id = new_id
    children = list(location.children)
    if current_xml_id != location.id:  # replaced: its children now live in the new place
        children = _current_children(connection, current_xml_id)
    for child in children:
        _reassign(connection, predefined, child, created)


def _current_children(connection: sqlite3.Connection, xml_id: str) -> list[Location]:
    stack = load_locations(connection)
    while stack:
        candidate = stack.pop()
        if candidate.id == xml_id:
            return list(candidate.children)
        stack.extend(candidate.children)
    return []

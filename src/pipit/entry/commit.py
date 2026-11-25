"""Save an Enter Sightings session into a list, as one undoable action.

Follows Scythebill's ``SingleLocationEdit.apply`` for each slot:

- the slot's location is created first if it is a built-in place not yet in the list
  (ID "_scyco_<code>") or a new place (ID from its name), appended to its parent;
- each species is stored with the slot's location, the date and the start time; new
  sightings are appended to the list in taxonomic order;
- a slot loaded from a recorded visit (``pipit.entry.existing``) replaces exactly the
  sightings it loaded, as Scythebill does: those still in the grid are re-added at the end
  of the list in taxonomic order (keeping their database rows, so observers and photos
  stay attached), the rest are deleted;
- a slot that loaded nothing deletes nothing: a species already recorded at that visit
  (same place, date and start time) is updated in place, everything else is added;
- the visit record is stored when it has data (``VisitInfo.hasData``), else removed;
  fields hidden by the protocol are dropped.

Everything happens in one transaction, so one undo takes back the whole day.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cmp_to_key

from pipit.domain.locations import PREDEFINED_PREFIX, create_id
from pipit.domain.partial_date import PartialDate, format_partial_date
from pipit.domain.report import ObservationType, VisitField
from pipit.domain.values import LatLong, float32, format_time
from pipit.entry.session import EntrySession, LocationKind, Slot, SlotSighting
from pipit.storage.database import ListDatabase
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

#: Maps (taxonomy id, taxon id) chosen in the session to the base sighting taxon to store
#: and its taxonomic position; None for taxa that cannot be stored.
TaxonResolver = Callable[[str, str], "StoredTaxon | None"]


@dataclass(frozen=True, slots=True)
class StoredTaxon:
    taxon: SightingTaxon
    extended_taxonomy_id: str | None  # None: the base taxonomy
    order: int  # taxonomic position, for the saved order
    # As shown in the display taxonomy, for Scythebill's ``ResolvedComparator``: the
    # position of each taxon (in the row's order) and "single", "sp" or "hybrid". Empty
    # for another taxonomy (mammals), which Scythebill saves after the display taxa.
    positions: tuple[int, ...] = ()
    display_type: str = "single"


def _compare_items(
    left: tuple[StoredTaxon, SlotSighting], right: tuple[StoredTaxon, SlotSighting]
) -> int:
    return compare_stored(left[0], right[0])


_TYPE_ORDER = {"single": 0, "sp": 1, "hybrid": 2}


def compare_stored(left: StoredTaxon, right: StoredTaxon) -> int:
    """``ResolvedComparator.compare``: the order Scythebill saves a visit's sightings in.
    A single taxon goes before a sp. or hybrid unless it comes after all of its taxa."""
    if not left.positions or not right.positions:
        if bool(left.positions) != bool(right.positions):
            return -1 if left.positions else 1
        return (left.order > right.order) - (left.order < right.order)
    if left.display_type == "single":
        if right.display_type == "single":
            return left.positions[0] - right.positions[0]
        return -1 if left.positions[0] <= max(right.positions) else 1
    if right.display_type == "single":
        return -1 if max(left.positions) < right.positions[0] else 1
    if max(left.positions) != max(right.positions):
        return max(left.positions) - max(right.positions)
    for left_position, right_position in zip(left.positions, right.positions, strict=False):
        if left_position != right_position:
            return left_position - right_position
    if len(left.positions) != len(right.positions):
        return 1 if len(left.positions) > len(right.positions) else -1
    return _TYPE_ORDER[left.display_type] - _TYPE_ORDER[right.display_type]


class CommitError(ValueError):
    pass


@dataclass
class CommitResult:
    visits: int = 0
    sightings: int = 0
    updated: int = 0
    removed: int = 0
    locations_created: list[str] = field(default_factory=list)


def _label(session: EntrySession) -> str:
    date = format_partial_date(session.date) if session.date else "no date"
    used = len({letter for row in session.rows for letter in row.seen})
    return f"Enter sightings {date}" + (f" ({used} locations)" if used > 1 else "")


def commit_session(
    database: ListDatabase, session: EntrySession, resolve: TaxonResolver
) -> CommitResult:
    problems = [p.message for p in session.problems() if p.kind.value == "error"]
    if problems:
        raise CommitError(" ".join(problems))
    assert session.date is not None
    result = CommitResult()
    with database.action(_label(session)) as connection:
        for letter, slot in zip(session.letters(), session.slots, strict=True):
            rows = [row for row in session.rows if letter in row.seen]
            replacing = slot.replaces is not None
            if not rows and not replacing:
                continue
            location_id = _ensure_location(connection, slot, result)
            stored: list[tuple[StoredTaxon, SlotSighting]] = []
            for row in rows:
                taxon = resolve(row.taxonomy_id, row.taxon_id)
                if taxon is None:
                    raise CommitError(f"{row.taxon_id} cannot be stored")
                stored.append((taxon, row.seen[letter]))
            stored.sort(key=cmp_to_key(_compare_items))
            leftover = set(slot.replaces or ())
            date = session.date
            for taxon, sighting in stored:
                if (
                    replacing
                    and sighting.source_id in leftover
                    and _exists(connection, sighting.source_id)
                ):
                    leftover.discard(sighting.source_id)
                    _readd(connection, taxon, sighting=sighting, location_id=location_id,
                           date=date, slot=slot)  # fmt: skip
                    result.updated += 1
                elif not replacing and _update_existing(
                    connection, taxon, sighting=sighting, location_id=location_id, date=date,
                    slot=slot,
                ):  # fmt: skip
                    result.updated += 1
                else:
                    _insert_sighting(connection, taxon, sighting=sighting,
                                     location_id=location_id, date=date, slot=slot)  # fmt: skip
                    result.sightings += 1
            for sighting_id in sorted(leftover):
                connection.execute("DELETE FROM sightings WHERE id = ?", (sighting_id,))
                result.removed += 1
            if _store_visit(connection, location_id, session.date, slot):
                result.visits += 1
    return result


# ------------------------------------------------------------------ locations


def _ensure_location(connection: sqlite3.Connection, slot: Slot, result: CommitResult) -> str:
    choice = slot.location
    if choice is None:
        raise CommitError("a location is missing")
    if choice.kind is LocationKind.EXISTING:
        assert choice.xml_id is not None
        if not connection.execute(
            "SELECT 1 FROM locations WHERE xml_id = ?", (choice.xml_id,)
        ).fetchone():
            raise CommitError(f"location {choice.label} no longer exists")
        return choice.xml_id
    parent = connection.execute(
        "SELECT id FROM locations WHERE xml_id = ?", (choice.parent_xml_id,)
    ).fetchone()
    if parent is None:
        raise CommitError(f"the parent of {choice.label} no longer exists")
    parent_row = parent[0]
    if choice.kind is LocationKind.PREDEFINED:
        existing = connection.execute(
            "SELECT xml_id FROM locations WHERE ebird_code = ?", (choice.code,)
        ).fetchone()
        if existing is not None:  # created meanwhile (possibly moved elsewhere)
            return str(existing[0])
    same_name = connection.execute(
        "SELECT xml_id FROM locations WHERE parent_id = ? AND name = ?", (parent_row, choice.name)
    ).fetchone()
    if same_name is not None:
        return str(same_name[0])
    ids = {xml_id for (xml_id,) in connection.execute("SELECT xml_id FROM locations")}
    predefined = choice.kind is LocationKind.PREDEFINED
    xml_id = create_id(
        choice.name,
        ids,
        PREDEFINED_PREFIX if predefined else None,
        choice.code if predefined else None,
    )
    lat_long = None
    if choice.latitude and choice.longitude:
        lat_long = LatLong.parse(choice.latitude, choice.longitude)
    order = connection.execute(
        "SELECT coalesce(max(ord), -1) + 1 FROM locations WHERE parent_id = ?", (parent_row,)
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO locations(xml_id, parent_id, ord, type, name, ebird_code, latitude, "
        "longitude) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (xml_id, parent_row, order, choice.type, choice.name, choice.code if predefined else None,
         lat_long.latitude if lat_long else None, lat_long.longitude if lat_long else None),
    )  # fmt: skip
    result.locations_created.append(xml_id)
    return xml_id


# ------------------------------------------------------------------ sightings


def _time_text(slot: Slot) -> str | None:
    return None if slot.start_time is None else format_time(slot.start_time)


def _existing_ids(
    connection: sqlite3.Connection,
    stored: StoredTaxon,
    location_id: str,
    date: PartialDate,
    slot: Slot,
) -> list[int]:
    """Sightings of the same taxon at the same visit (place, date and start time)."""
    taxon = stored.taxon
    rows = connection.execute(
        "SELECT id, kind, taxon_id, subspecies FROM sightings WHERE location_xml_id = ? "
        "AND date = ? AND time IS ? AND trip_xml_id IS NULL AND taxonomy_id IS ?",
        (location_id, format_partial_date(date), _time_text(slot), stored.extended_taxonomy_id),
    ).fetchall()
    matching = []
    for sighting_id, kind, taxon_id, subspecies in rows:
        if kind != _KIND[taxon.type] or subspecies != taxon.subspecies:
            continue
        if taxon_id is not None:
            ids: tuple[str, ...] = (taxon_id,)
        else:
            ids = tuple(
                t for (t,) in connection.execute(
                    "SELECT taxon_id FROM sighting_taxa WHERE sighting_id = ? ORDER BY ord",
                    (sighting_id,),
                )
            )  # fmt: skip
        if ids == taxon.ids:
            matching.append(sighting_id)
    return matching


def _update_existing(
    connection: sqlite3.Connection,
    stored: StoredTaxon,
    *,
    sighting: SlotSighting,
    location_id: str,
    date: PartialDate,
    slot: Slot,
) -> bool:
    ids = _existing_ids(connection, stored, location_id, date, slot)
    if not ids:
        return False
    connection.execute(
        "UPDATE sightings SET count = ?, male = ?, female = ?, immature = ?, adult = ?, "
        "heard_only = ?, photographed = ?, status = ?, breeding = ?, "
        "description = coalesce(?, description) WHERE id = ?",
        (None if sighting.count is None else str(sighting.count), int(sighting.male),
         int(sighting.female), int(sighting.immature), int(sighting.adult),
         int(sighting.heard_only), int(sighting.photographed), sighting.status,
         sighting.breeding, sighting.notes.rstrip() or None, ids[0]),
    )  # fmt: skip
    return True


def _exists(connection: sqlite3.Connection, sighting_id: int | None) -> bool:
    """Loaded sightings may be gone since (an undo): then they are added afresh."""
    return (
        connection.execute("SELECT 1 FROM sightings WHERE id = ?", (sighting_id,)).fetchone()
        is not None
    )


def _readd(
    connection: sqlite3.Connection,
    stored: StoredTaxon,
    *,
    sighting: SlotSighting,
    location_id: str,
    date: PartialDate,
    slot: Slot,
) -> None:
    """Scythebill removes a loaded sighting and adds it again at the end of the list. Same
    result, but the row (and its observers and photos) is kept: it gets the new place,
    date, time, taxon and details, and the next position in the list."""
    assert sighting.source_id is not None
    taxon = stored.taxon
    single = taxon.type in (
        SightingTaxonType.SINGLE,
        SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES,
    )
    order = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM sightings").fetchone()[0]
    connection.execute(
        "UPDATE sightings SET ord = ?, taxonomy_id = ?, kind = ?, taxon_id = ?, subspecies = ?, "
        "location_xml_id = ?, date = ?, date_y = ?, date_m = ?, date_d = ?, time = ?, "
        "trip_xml_id = NULL, count = ?, male = ?, female = ?, immature = ?, adult = ?, "
        "heard_only = ?, photographed = ?, status = ?, breeding = ?, description = ? "
        "WHERE id = ?",
        (order, stored.extended_taxonomy_id, _KIND[taxon.type],
         taxon.ids[0] if single else None, taxon.subspecies, location_id,
         format_partial_date(date), date.year, date.month, date.day, _time_text(slot),
         None if sighting.count is None else str(sighting.count), int(sighting.male),
         int(sighting.female), int(sighting.immature), int(sighting.adult),
         int(sighting.heard_only), int(sighting.photographed), sighting.status,
         sighting.breeding, sighting.notes.rstrip() or None, sighting.source_id),
    )  # fmt: skip
    parts = [] if single else list(taxon.ids)
    current = [
        taxon_id
        for (taxon_id,) in connection.execute(
            "SELECT taxon_id FROM sighting_taxa WHERE sighting_id = ? ORDER BY ord",
            (sighting.source_id,),
        )
    ]
    if current != parts:
        connection.execute("DELETE FROM sighting_taxa WHERE sighting_id = ?", (sighting.source_id,))
        connection.executemany(
            "INSERT INTO sighting_taxa(sighting_id, ord, taxon_id) VALUES (?, ?, ?)",
            [(sighting.source_id, i, taxon_id) for i, taxon_id in enumerate(parts)],
        )


_KIND = {
    SightingTaxonType.SINGLE: "single",
    SightingTaxonType.SP: "sp",
    SightingTaxonType.HYBRID: "hybrid",
    SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES: "ssp",
}


def _insert_sighting(
    connection: sqlite3.Connection,
    stored: StoredTaxon,
    *,
    sighting: SlotSighting,
    location_id: str,
    date: PartialDate,
    slot: Slot,
) -> None:
    taxon = stored.taxon
    single = taxon.type in (
        SightingTaxonType.SINGLE,
        SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES,
    )
    order = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM sightings").fetchone()[0]
    cursor = connection.execute(
        "INSERT INTO sightings(ord, taxonomy_id, kind, taxon_id, subspecies, location_xml_id, "
        "date, date_y, date_m, date_d, time, count, male, female, immature, adult, heard_only, "
        "photographed, status, breeding, description) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (order, stored.extended_taxonomy_id, _KIND[taxon.type], taxon.ids[0] if single else None,
         taxon.subspecies, location_id, format_partial_date(date), date.year, date.month,
         date.day, _time_text(slot), None if sighting.count is None else str(sighting.count),
         int(sighting.male), int(sighting.female), int(sighting.immature), int(sighting.adult),
         int(sighting.heard_only), int(sighting.photographed), sighting.status, sighting.breeding,
         sighting.notes.rstrip() or None),
    )  # fmt: skip
    if not single:
        connection.executemany(
            "INSERT INTO sighting_taxa(sighting_id, ord, taxon_id) VALUES (?, ?, ?)",
            [(cursor.lastrowid, i, taxon_id) for i, taxon_id in enumerate(taxon.ids)],
        )


# ------------------------------------------------------------------ visits


def visit_has_data(slot: Slot) -> bool:
    """``VisitInfo.hasData``: worth keeping (incidental is always kept)."""
    return (
        slot.area_hectares is not None
        or slot.distance_km is not None
        or slot.duration_minutes is not None
        or bool(slot.comments.strip())
        or slot.party_size is not None
        or slot.complete
        or slot.observation_type is ObservationType.INCIDENTAL
    )


def _store_visit(
    connection: sqlite3.Connection, location_id: str, date: PartialDate, slot: Slot
) -> bool:
    date_text = format_partial_date(date)
    start = _time_text(slot) or ""
    existing = connection.execute(
        "SELECT id FROM visits WHERE location_xml_id = ? AND date = ? AND start_time = ?",
        (location_id, date_text, start),
    ).fetchone()
    if not visit_has_data(slot):
        if existing is not None:
            connection.execute("DELETE FROM visits WHERE id = ?", (existing[0],))
        return False
    hidden = slot.observation_type.hidden

    def shown(visit_field: VisitField, value: object) -> object:
        return None if visit_field in hidden else value

    area = shown(VisitField.AREA, slot.area_hectares)
    distance = shown(VisitField.DISTANCE, slot.distance_km)
    values = (
        slot.observation_type.type_id,
        None if area is None else repr(float32(float(area))),  # type: ignore[arg-type]
        None if distance is None else repr(float32(float(distance))),  # type: ignore[arg-type]
        shown(VisitField.DURATION, slot.duration_minutes),
        shown(VisitField.PARTY_SIZE, slot.party_size),
        slot.comments.strip() or None,
        int(slot.complete),
    )
    if existing is not None:
        connection.execute(
            "UPDATE visits SET observation_type = ?, area_hectares = ?, distance_km = ?, "
            "duration_minutes = ?, party_size = ?, comments = ?, complete = ? WHERE id = ?",
            (*values, existing[0]),
        )
    else:
        order = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM visits").fetchone()[0]
        connection.execute(
            "INSERT INTO visits(ord, location_xml_id, date, date_y, date_m, date_d, start_time, "
            "observation_type, area_hectares, distance_km, duration_minutes, party_size, "
            "comments, complete) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order, location_id, date_text, date.year, date.month, date.day, start, *values),
        )
    return True

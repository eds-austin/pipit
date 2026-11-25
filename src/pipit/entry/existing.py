"""What is already recorded for a visit, loaded into Enter Sightings so it can be edited.

Ported from Scythebill ``SingleLocationEdit.snapshotExistingSightings``:

- the sightings at the place on the date whose time equals the start time; if there are
  none, those at the place on the date with no time (so a start time can be added to an
  untimed visit);
- each is shown in the display taxonomy (sightings of another taxonomy, such as mammals,
  in their own); when two sightings show as the same taxon, only the first (in list order)
  is loaded, and the others are left alone;
- the visit record (eBird checklist details) for that place, date and start time.

Saving such a slot replaces exactly the loaded sightings (see ``commit``), as Scythebill
does.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import time

from pipit.domain.partial_date import PartialDate, format_partial_date
from pipit.domain.report import ObservationType
from pipit.domain.values import ApproximateNumber, format_time, parse_float32
from pipit.entry.commit import visit_has_data
from pipit.entry.session import EntrySession, Slot, SlotSighting
from pipit.entry.taxa import EntryTaxa
from pipit.taxa.sighting_taxon import SightingTaxon


@dataclass(frozen=True, slots=True)
class LoadedRow:
    taxonomy_id: str  # the display taxonomy, or the sighting's own extended taxonomy
    taxon_id: str  # as a row of that taxonomy ("a/b" for a sp., "a+b" for a hybrid)
    sighting: SlotSighting  # with ``source_id`` set


@dataclass(frozen=True, slots=True)
class LoadedVisitInfo:
    observation_type: ObservationType
    duration_minutes: int | None
    distance_km: float | None
    area_hectares: float | None
    party_size: int | None
    complete: bool
    comments: str


@dataclass(frozen=True, slots=True)
class ExistingVisit:
    sighting_ids: list[int]  # exactly the sightings saving will replace
    rows: list[LoadedRow]
    visit: LoadedVisitInfo | None


def visit_key(location_id: str, date: PartialDate, start: time | None) -> str:
    return "|".join((location_id, format_partial_date(date), format_time(start) if start else ""))


_COLUMNS = (
    "id, taxonomy_id, kind, taxon_id, subspecies, count, male, female, immature, adult, "
    "heard_only, photographed, status, breeding, description"
)


def load_existing(
    connection: sqlite3.Connection,
    taxa: EntryTaxa,
    location_id: str,
    date: PartialDate,
    start: time | None,
) -> ExistingVisit:
    date_text = format_partial_date(date)
    time_text = format_time(start) if start else None
    found = connection.execute(
        f"SELECT {_COLUMNS} FROM sightings WHERE location_xml_id = ? AND date = ? "
        "AND time IS ? ORDER BY ord",
        (location_id, date_text, time_text),
    ).fetchall()
    if not found and time_text is not None:
        found = connection.execute(
            f"SELECT {_COLUMNS} FROM sightings WHERE location_xml_id = ? AND date = ? "
            "AND time IS NULL ORDER BY ord",
            (location_id, date_text),
        ).fetchall()
    ids: list[int] = []
    rows: list[LoadedRow] = []
    seen_keys: set[tuple[str, str]] = set()
    for (sighting_id, taxonomy_id, kind, taxon_id, subspecies, count, male, female, immature,
         adult, heard_only, photographed, status, breeding, description) in found:  # fmt: skip
        parts = (
            (taxon_id,) if taxon_id is not None else tuple(
                part for (part,) in connection.execute(
                    "SELECT taxon_id FROM sighting_taxa WHERE sighting_id = ? ORDER BY ord",
                    (sighting_id,),
                )
            )
        )  # fmt: skip
        if taxonomy_id is not None:
            # Another taxonomy (mammals): shown in its own taxonomy, single taxa only.
            if kind not in ("single", "ssp"):
                continue
            row_taxonomy, row_id = taxonomy_id, parts[0]
        else:
            stored = _stored(kind, parts, subspecies)
            shown = taxa.row_id(stored)
            if shown is None:
                continue  # can't be shown: left alone
            row_taxonomy, row_id = taxa.display.id, shown
        key = (row_taxonomy, _canonical(row_id))
        if key in seen_keys:
            continue  # a second sighting of the same taxon stays as it is
        seen_keys.add(key)
        ids.append(sighting_id)
        rows.append(
            LoadedRow(
                row_taxonomy, row_id,
                SlotSighting(
                    count=None if count is None else ApproximateNumber.parse(count),
                    heard_only=bool(heard_only), male=bool(male), female=bool(female),
                    adult=bool(adult), immature=bool(immature),
                    photographed=bool(photographed), status=status, breeding=breeding,
                    notes=description or "", source_id=sighting_id,
                ),
            )
        )  # fmt: skip
    return ExistingVisit(ids, rows, _visit(connection, location_id, date_text, time_text))


def _stored(kind: str, parts: tuple[str, ...], subspecies: str | None) -> SightingTaxon:
    if kind == "ssp":
        return SightingTaxon.with_secondary_subspecies(parts[0], subspecies or "")
    if kind == "sp":
        return SightingTaxon.sp(parts)
    if kind == "hybrid":
        return SightingTaxon.hybrid(parts)
    return SightingTaxon.single(parts[0])


def _canonical(row_id: str) -> str:
    """Rows equal as taxa ("b/a" is "a/b")."""
    for separator in ("/", "+"):
        if separator in row_id:
            return separator.join(sorted(row_id.split(separator)))
    return row_id


def _visit(
    connection: sqlite3.Connection, location_id: str, date_text: str, time_text: str | None
) -> LoadedVisitInfo | None:
    found = connection.execute(
        "SELECT observation_type, duration_minutes, distance_km, area_hectares, party_size, "
        "complete, comments FROM visits WHERE location_xml_id = ? AND date = ? "
        "AND start_time = ?",
        (location_id, date_text, time_text or ""),
    ).fetchone()
    if found is None:
        return None
    kind, duration, distance, area, party, complete, comments = found
    observation_type = ObservationType.from_id(kind) or ObservationType.HISTORICAL
    return LoadedVisitInfo(
        observation_type, duration,
        None if distance is None else parse_float32(distance),
        None if area is None else parse_float32(area),
        party, bool(complete), comments or "",
    )  # fmt: skip


# ------------------------------------------------------------------ into a session


def load_into(session: EntrySession, letter: str, existing: ExistingVisit, key: str) -> int:
    """Put a recorded visit into slot ``letter``: its sightings as ticks of that slot and,
    if the slot has no visit details yet, its visit record (as Scythebill keeps typed visit
    details). Returns the number of sightings loaded."""
    slot = session.slot(letter)
    typed = any(letter in row.seen for row in session.rows)
    for loaded in existing.rows:
        index, _ = session.add_species(loaded.taxonomy_id, loaded.taxon_id)
        current = session.rows[index].seen.get(letter)
        if current is None:
            session.rows[index].seen[letter] = replace(loaded.sighting)
        else:  # typed before the place was chosen: what was typed wins
            current.source_id = loaded.sighting.source_id
    visit = existing.visit
    if visit is not None and not visit_has_data(slot):
        slot.observation_type = visit.observation_type
        slot.duration_minutes = visit.duration_minutes
        slot.distance_km = visit.distance_km
        slot.area_hectares = visit.area_hectares
        slot.party_size = visit.party_size
        slot.complete = visit.complete
        slot.comments = visit.comments
    slot.replaces = list(existing.sighting_ids)
    slot.loaded_key = key
    # Merged into typed sightings, it counts as edited (never taken back out unseen).
    slot.loaded_signature = None if typed else session.slot_signature(letter)
    return len(existing.sighting_ids)


def sync_slot(
    connection: sqlite3.Connection, taxa: EntryTaxa, session: EntrySession, letter: str
) -> int:
    """Keep slot ``letter`` in step with the recorded visit at its place, date and start
    time: load it when they first name one; when they change before anything loaded was
    edited, take it back out and load the new one; once edited, keep it (saving then moves
    it, and the problems list says so). Returns the number of sightings newly loaded."""
    slot = session.slot(letter)
    key = session.slot_key(letter)
    if slot.loaded_key == key:
        return 0
    if slot.loaded_key is not None:
        if not is_unedited(session, letter):
            return 0
        unload(session, letter)
    if key is None or session.date is None or slot.location is None:
        return 0
    assert slot.location.xml_id is not None
    existing = load_existing(connection, taxa, slot.location.xml_id, session.date,
                             slot.start_time)  # fmt: skip
    if not existing.sighting_ids and existing.visit is None:
        return 0
    return load_into(session, letter, existing, key)


def is_unedited(session: EntrySession, letter: str) -> bool:
    slot = session.slot(letter)
    return slot.loaded_signature is not None and (
        slot.loaded_signature == session.slot_signature(letter)
    )


def unload(session: EntrySession, letter: str) -> None:
    """Take an unedited loaded visit back out of slot ``letter`` (its place, date or start
    time changed before anything was edited)."""
    slot = session.slot(letter)
    for row in session.rows:
        row.seen.pop(letter, None)
    session.rows = [row for row in session.rows if row.seen]
    defaults = Slot()
    slot.observation_type = defaults.observation_type
    slot.duration_minutes = slot.distance_km = slot.area_hectares = slot.party_size = None
    slot.complete = False
    slot.comments = ""
    slot.replaces = slot.loaded_key = slot.loaded_signature = None

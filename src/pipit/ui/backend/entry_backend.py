"""Enter Sightings for QML: the session, its models and every keyboard action.

The QML screen only displays models and calls these slots; all rules live in
``pipit.entry`` (session, search ranking, saving). Every change is saved as a draft half a
second later, so closing the window or a crash loses nothing.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from pipit.domain.partial_date import PartialDate, format_partial_date, parse_partial_date
from pipit.domain.report import ObservationType
from pipit.domain.values import (
    java_float_to_string,
    kotlin_int_or_none,
    parse_float32,
    parse_time,
)
from pipit.entry.commit import CommitError, StoredTaxon, commit_session
from pipit.entry.context import location_label
from pipit.entry.existing import is_unedited, sync_slot
from pipit.entry.session import (
    SLOT_LETTERS,
    EntrySession,
    LocationChoice,
    LocationKind,
    ProblemKind,
    SlotSighting,
    parse_clock,
    parse_count,
    parse_duration,
    parse_species_input,
)
from pipit.entry.taxa import Match
from pipit.taxa.model import TaxonType, full_name
from pipit.taxa.sighting_taxon import SightingTaxon
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)

#: Protocol by its first letter (Scythebill's types; F and R for the two less common ones).
PROTOCOL_KEYS = {
    "T": ObservationType.TRAVELING, "S": ObservationType.STATIONARY,
    "I": ObservationType.INCIDENTAL, "H": ObservationType.HISTORICAL,
    "A": ObservationType.AREA, "P": ObservationType.PELAGIC, "N": ObservationType.NOCTURNAL,
    "B": ObservationType.BANDING, "F": ObservationType.FLIGHT_CALL, "R": ObservationType.RANDOM,
}  # fmt: skip
FLAGS = ("heard_only", "male", "female", "adult", "immature", "photographed")
_FLAG_LETTERS = {"heard_only": "H", "male": "♂", "female": "♀", "adult": "ad",
                 "immature": "im", "photographed": "📷"}  # fmt: skip
DRAFT_DELAY_MS = 500


def parse_date_input(text: str, current: PartialDate | None, today: date) -> PartialDate | None:
    """ "t"/"today", "y"/"yesterday", "+"/"-" (a day after/before the current date), or a
    full or partial date ("2026-11-24", "2026-11", "2026")."""
    stripped = text.strip().lower()
    base = today
    if current is not None and current.is_full_date:
        assert current.year and current.month and current.day
        base = date(current.year, current.month, current.day)
    if stripped in ("t", "today"):
        chosen = today
    elif stripped in ("y", "yesterday"):
        chosen = today - timedelta(days=1)
    elif re.fullmatch(r"[+-]+", stripped):
        chosen = base + timedelta(days=stripped.count("+") - stripped.count("-"))
    else:
        if not re.fullmatch(r"\d{4}(-\d{1,2}(-\d{1,2})?)?", stripped):
            return None
        parts = [int(part) for part in stripped.split("-")]
        try:
            if len(parts) == 3:
                date(*parts)  # a real day
            elif len(parts) == 2 and not 1 <= parts[1] <= 12:
                return None
        except ValueError:
            return None
        return parse_partial_date("-".join(f"{part:02d}" for part in parts))
    return PartialDate.of(chosen.year, chosen.month, chosen.day)


class EntryBackend(QObject):
    changed = Signal()  # anything in the session
    matchesChanged = Signal()
    placesChanged = Signal()
    saved = Signal(str)

    def __init__(self, app: AppController, today: date | None = None) -> None:
        super().__init__()
        self._app = app
        self._today = today
        self._session: EntrySession | None = None
        self._active = "A"
        self._query_counts: dict[str | None, str] = {}
        self._combine = ""
        self._earlier_parts: list[str] = []
        self._matches: list[Match] = []
        self._places: list[LocationChoice] = []
        self._checklist_filter = ""
        self.slots_model = DictListModel([
            "letter", "label", "hasLocation", "protocol", "protocolLabel", "startTime",
            "duration", "distance", "area", "party", "complete", "comments", "speciesCount",
            "needs", "hides", "active", "editing",
        ])  # fmt: skip
        self.rows_model = DictListModel(
            ["name", "scientific", "rank", "counts", "details", "badges", "notes"]
        )
        self.matches_model = DictListModel(["name", "scientific", "detail", "status", "seen"])
        self.places_model = DictListModel(["label", "kind"])
        self.checklist_model = DictListModel(["name", "scientific", "status", "count", "taxonId"])
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(DRAFT_DELAY_MS)
        self._draft_timer.timeout.connect(self.save_draft_now)
        app.listChanged.connect(self._list_changed)
        app.taxaReadyChanged.connect(self._list_changed)
        self._list_changed()

    # ------------------------------------------------------------ lifecycle

    def _today_date(self) -> date:
        return self._today or date.today()

    def _list_changed(self) -> None:
        self._session = None
        taxa = self._app.entry_taxa
        if self._app.hasList and taxa is not None:
            draft = self._app.load_draft()
            if draft:
                try:
                    self._session = EntrySession.from_json(draft)
                except (ValueError, KeyError, TypeError):
                    log.warning("ignoring an unreadable draft")
            if self._session is None or self._session.display_taxonomy_id != taxa.display.id:
                self._session = EntrySession(taxa.display.id, self._default_date())
        self._active = "A"
        self._refresh()

    def _default_date(self) -> PartialDate:
        today = self._today_date()
        return PartialDate.of(today.year, today.month, today.day)

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        return self._session is not None and not self._app.readOnly

    @Property(bool, notify=changed)
    def hasDraft(self) -> bool:
        return self._session is not None and bool(self._session.rows)

    def _touch(self) -> None:
        self._sync_existing()
        self._refresh()
        self._draft_timer.start()

    def _sync_existing(self) -> None:
        """Load what is already recorded for each slot's place, date and start time, so
        a recorded visit opens for editing (Scythebill's snapshot of existing sightings)."""
        session = self._session
        database = self._app.database
        taxa = self._app.entry_taxa
        if session is None or database is None or taxa is None:
            return
        for letter in session.letters():
            loaded = sync_slot(database.connection, taxa, session, letter)
            if loaded:
                slot = session.slot(letter)
                place = slot.location.name if slot.location else ""
                self._app.message.emit(
                    f"Location {letter}: {loaded} recorded sighting{'s' * (loaded != 1)} at "
                    f"{place} loaded; saving replaces them"
                )

    def _resolve(self, taxonomy_id: str, taxon_id: str) -> StoredTaxon | None:
        taxa = self._app.entry_taxa
        if taxa is None:
            return None
        if taxonomy_id != taxa.display.id:  # another taxonomy (mammals), stored as it is
            return StoredTaxon(SightingTaxon.single(taxon_id), taxonomy_id, 10**9)
        return taxa.stored(taxon_id)

    def _other_names(self, taxonomy_id: str, taxon_id: str) -> tuple[str, str]:
        database = self._app.database
        found = None if database is None else database.connection.execute(
            "SELECT common_name, name FROM ext_taxa WHERE taxonomy_id = ? AND taxon_id = ?",
            (taxonomy_id, taxon_id),
        ).fetchone()  # fmt: skip
        if found is None:
            return taxon_id, ""
        return found[0] or found[1], found[1]

    @Slot()
    def save_draft_now(self) -> None:
        if self._session is not None:
            self._app.save_draft(self._session.to_json())

    # ------------------------------------------------------------ date

    @Property(str, notify=changed)
    def dateText(self) -> str:
        session = self._session
        return "" if session is None or session.date is None else format_partial_date(session.date)

    @Slot(str, result=bool)
    def setDate(self, text: str) -> bool:
        if self._session is None:
            return False
        parsed = parse_date_input(text, self._session.date, self._today_date())
        if parsed is None:
            return False
        self._session.date = parsed
        self._touch()
        return True

    @Slot(str, str, str, result=bool)
    def openVisit(self, xml_id: str, date_text: str, start: str) -> bool:
        """Start editing a recorded visit (from the Locations screen): a fresh day with the
        visit's place, date and start time at location A, its sightings loaded. Refused
        while typed, unsaved sightings are in the grid."""
        session = self._session
        taxa = self._app.entry_taxa
        context = self._app.context
        if session is None or taxa is None or context is None or self._app.readOnly:
            return False
        if self._has_typed_work(session):
            self._app.message.emit(
                "Save (Ctrl+Enter) or clear the day being entered before opening a visit"
            )
            return False
        location = context.location(xml_id)
        if location is None:
            return False
        try:
            date_value = parse_partial_date(date_text)
        except ValueError:
            return False
        fresh = EntrySession(taxa.display.id, date_value)
        fresh.slot("A").location = LocationChoice(
            LocationKind.EXISTING, location.name, location_label(location), xml_id=xml_id
        )
        fresh.slot("A").start_time = parse_time(start) if start else None
        self._session = fresh
        self._active = "A"
        self._touch()
        return True

    @staticmethod
    def _has_typed_work(session: EntrySession) -> bool:
        """Anything in the grid besides visits loaded and left as they were."""
        for letter in session.letters():
            in_use = any(letter in row.seen for row in session.rows)
            slot = session.slot(letter)
            if in_use and not (slot.replaces is not None and is_unedited(session, letter)):
                return True
        return False

    # ------------------------------------------------------------ slots

    @Property(str, notify=changed)
    def activeSlot(self) -> str:
        return self._active

    @Property(int, notify=changed)
    def slotCount(self) -> int:
        return 0 if self._session is None else len(self._session.slots)

    @Slot(str)
    def setActiveSlot(self, letter: str) -> None:
        if self._session is not None and letter in self._session.letters():
            self._active = letter
            self._refresh()

    @Slot(result=str)
    def addSlot(self) -> str:
        if self._session is None:
            return ""
        letter = self._session.add_slot() or ""
        if letter:
            self._active = letter
            self._touch()
        return letter

    @Slot(str)
    def removeSlot(self, letter: str) -> None:
        if self._session is None:
            return
        self._session.remove_slot(letter)
        if self._active not in self._session.letters():
            self._active = self._session.letters()[-1]
        self._touch()

    @Slot(str)
    def searchPlaces(self, text: str) -> None:
        context = self._app.context
        self._places = [] if context is None else context.find_places(text)
        self.places_model.reset([
            {"label": place.label, "kind": place.kind.value} for place in self._places
        ])  # fmt: skip
        self.placesChanged.emit()

    @Slot(str, int, result=bool)
    def choosePlace(self, letter: str, index: int) -> bool:
        if self._session is None or not 0 <= index < len(self._places):
            return False
        self._session.slot(letter).location = self._places[index]
        self._active = letter
        self._touch()
        return True

    @Slot(str, str, int, result=bool)
    def newPlace(self, letter: str, name: str, parent_index: int) -> bool:
        """A new place called ``name`` inside an existing place from the last search."""
        name = name.strip()
        if self._session is None or not name or not 0 <= parent_index < len(self._places):
            return False
        parent = self._places[parent_index]
        if parent.kind is not LocationKind.EXISTING:
            return False
        self._session.slot(letter).location = LocationChoice(
            LocationKind.NEW, name, f"{name} · {parent.label} (new)", parent_xml_id=parent.xml_id
        )
        self._touch()
        return True

    @Slot(str, str, result=bool)
    def setProtocolKey(self, letter: str, key: str) -> bool:
        protocol = PROTOCOL_KEYS.get(key.upper())
        if self._session is None or protocol is None:
            return False
        self._session.slot(letter).observation_type = protocol
        self._touch()
        return True

    @Slot(str, str, str, result=bool)
    def setField(self, letter: str, field: str, text: str) -> bool:
        """Start time, duration, distance, area, party size or comments; "" clears."""
        if self._session is None:
            return False
        slot = self._session.slot(letter)
        stripped = text.strip()
        if field == "comments":
            slot.comments = text
        elif field == "startTime":
            value = parse_clock(stripped) if stripped else None
            if stripped and value is None:
                return False
            slot.start_time = value
        elif field == "duration":
            minutes = parse_duration(stripped) if stripped else None
            if stripped and minutes is None:
                return False
            slot.duration_minutes = minutes
        elif field in ("distance", "area"):
            amount = parse_float32(stripped) if stripped else None
            if stripped and (amount is None or amount <= 0):
                return False
            if field == "distance":
                slot.distance_km = amount
            else:
                slot.area_hectares = amount
        elif field == "party":
            party = kotlin_int_or_none(stripped) if stripped else None
            if stripped and (party is None or party <= 0):
                return False
            slot.party_size = party
        else:
            return False
        self._touch()
        return True

    @Slot(str)
    def toggleComplete(self, letter: str) -> None:
        if self._session is not None:
            slot = self._session.slot(letter)
            slot.complete = not slot.complete
            self._touch()

    # ------------------------------------------------------------ species

    @Slot(str)
    def searchSpecies(self, text: str) -> None:
        taxa = self._app.entry_taxa
        context = self._app.context
        session = self._session
        if taxa is None or context is None or session is None:
            return
        query, self._query_counts = parse_species_input(text)
        # "a/b" (a sp.) or "a+b" (a hybrid): suggestions are for the last part.
        self._combine = "/" if "/" in query else "+" if "+" in query else ""
        self._earlier_parts = []
        if self._combine:
            *earlier, query = query.split(self._combine)
            location_for_parts = session.slot(self._active).location
            part_checklist = context.checklist_for(location_for_parts, taxa.display.id)
            for part in earlier:
                found = taxa.search(part, part_checklist, limit=1) if part.strip() else []
                if found:
                    self._earlier_parts.append(found[0].taxon_id)
        location = session.slot(self._active).location
        checklist = context.checklist_for(location, taxa.display.id)
        self._matches = taxa.search(query, checklist, context.seen_species(taxa.display), limit=30)
        self.matches_model.reset([
            {
                "name": match.common_name,
                "scientific": match.scientific_name,
                "detail": match.matched_name or ("" if match.rank == "species" else match.rank),
                "status": _status_text(match.checklist_status, checklist is not None),
                "seen": match.seen,
            }
            for match in self._matches
        ])  # fmt: skip
        self.matchesChanged.emit()

    @Slot(int, result=int)
    def chooseSpecies(self, index: int) -> int:
        """Add (or reuse) the row for a suggestion, with the counts typed after the species
        ("mall 12", "amro a3 b1"); without counts the active slot is ticked. Returns the row."""
        session = self._session
        if session is None or not 0 <= index < len(self._matches):
            return -1
        match = self._matches[index]
        taxon_id = match.taxon_id
        if self._combine and self._earlier_parts:
            parts = sorted({*self._earlier_parts, taxon_id})
            if len(parts) > 1:
                taxon_id = self._combine.join(parts)
        row, _ = session.add_species(session.display_taxonomy_id, taxon_id)
        counts = self._query_counts or {None: ""}
        for letter, count in counts.items():
            session.set_count(row, letter or self._active, count)
        self._matches = []
        self.matches_model.reset([])
        self.matchesChanged.emit()
        self._touch()
        return row

    @Slot(int, str, str, result=bool)
    def setCount(self, row: int, letter: str, text: str) -> bool:
        if self._session is None or not 0 <= row < len(self._session.rows):
            return False
        ok = self._session.set_count(row, letter, text)
        if ok:
            self._touch()
        return ok

    @Slot(int, str)
    def untick(self, row: int, letter: str) -> None:
        if self._session is not None and 0 <= row < len(self._session.rows):
            self._session.untick(row, letter)
            self._touch()

    @Slot(int, str, str)
    def toggleFlag(self, row: int, letter: str, flag: str) -> None:
        if self._session is None or flag not in FLAGS or not 0 <= row < len(self._session.rows):
            return
        sighting = self._session.rows[row].seen.get(letter)
        if sighting is None:
            return
        setattr(sighting, flag, not getattr(sighting, flag))
        self._touch()

    @Slot(int, str, str)
    def setNotes(self, row: int, letter: str, text: str) -> None:
        if self._session is None or not 0 <= row < len(self._session.rows):
            return
        sighting = self._session.rows[row].seen.get(letter)
        if sighting is not None:
            sighting.notes = text
            self._touch()

    @Slot(int)
    def removeRow(self, row: int) -> None:
        if self._session is not None and 0 <= row < len(self._session.rows):
            self._session.remove_row(row)
            self._touch()

    # ------------------------------------------------------------ checklist mode

    @Slot(str)
    def filterChecklist(self, text: str) -> None:
        self._checklist_filter = text
        self._refresh_checklist()

    @Slot(int, str, result=bool)
    def checklistEnter(self, index: int, count: str) -> bool:
        """Tick the checklist bird at ``index`` at the active slot (with a count)."""
        session = self._session
        rows = self.checklist_model.rows()
        if session is None or not 0 <= index < len(rows):
            return False
        valid, _ = parse_count(count)
        if not valid:
            return False
        row, _ = session.add_species(session.display_taxonomy_id, rows[index]["taxonId"])
        session.set_count(row, self._active, count)
        self._touch()
        return True

    # ------------------------------------------------------------ finish

    @Property("QStringList", notify=changed)
    def problems(self) -> list[str]:
        if self._session is None:
            return []
        return [
            ("" if problem.kind is ProblemKind.ERROR else "Note: ") + problem.message
            for problem in self._session.problems()
        ]

    @Property(bool, notify=changed)
    def canSave(self) -> bool:
        return self._session is not None and self._session.can_save() and not self._app.readOnly

    @Property(str, notify=changed)
    def summary(self) -> str:
        session = self._session
        if session is None:
            return ""
        parts = []
        for letter in session.letters():
            count = sum(1 for row in session.rows if letter in row.seen)
            parts.append(f"{letter} {count}")
        species = len(session.rows)
        return " · ".join([*parts, f"{species} species"])

    @Slot(result=bool)
    def finish(self) -> bool:
        session = self._session
        database = self._app.database
        taxa = self._app.entry_taxa
        if session is None or database is None or taxa is None:
            return False
        try:
            result = commit_session(database, session, self._resolve)
        except CommitError as error:
            self._app.message.emit(str(error))
            return False
        self._app.clear_draft()
        self._session = EntrySession(taxa.display.id, session.date)
        self._active = "A"
        self._app.changed()
        visits = f"{result.visits} visit{'s' if result.visits != 1 else ''}"
        removed = f", removed {result.removed}" if result.removed else ""
        text = (
            f"Saved {result.sightings + result.updated} sightings{removed}, {visits}. "
            "Ctrl+Z undoes."
        )
        self._app.message.emit(text)
        self.saved.emit(text)
        self._refresh()
        return True

    @Slot()
    def discard(self) -> None:
        taxa = self._app.entry_taxa
        if self._session is None or taxa is None:
            return
        self._session = EntrySession(taxa.display.id, self._session.date)
        self._app.clear_draft()
        self._refresh()

    # ------------------------------------------------------------ models

    def _refresh(self) -> None:
        session = self._session
        taxa = self._app.entry_taxa
        context = self._app.context
        if session is None or taxa is None or context is None:
            self.slots_model.reset([])
            self.rows_model.reset([])
            self.checklist_model.reset([])
            self.changed.emit()
            return
        slots = []
        for letter, slot in zip(session.letters(), session.slots, strict=True):
            protocol = slot.observation_type
            slots.append({
                "letter": letter,
                "label": slot.location.label if slot.location else "",
                "hasLocation": slot.location is not None,
                "protocol": protocol.type_id,
                "protocolLabel": protocol.label,
                "startTime": "" if slot.start_time is None else slot.start_time.strftime("%H:%M"),
                "duration": _minutes_text(slot.duration_minutes),
                "distance": _float_text(slot.distance_km),
                "area": _float_text(slot.area_hectares),
                "party": "" if slot.party_size is None else str(slot.party_size),
                "complete": slot.complete,
                "comments": slot.comments,
                "speciesCount": sum(1 for row in session.rows if letter in row.seen),
                "needs": [f.value for f in protocol.required],
                "hides": [f.value for f in protocol.hidden],
                "active": letter == self._active,
                # Recorded sightings saving replaces; -1 when not editing a recorded visit.
                "editing": -1 if slot.replaces is None else len(slot.replaces),
            })  # fmt: skip
        self.slots_model.reset(slots)
        seen = context.seen_species(taxa.display)
        checklists = {
            letter: context.checklist_for(slot.location, taxa.display.id)
            for letter, slot in zip(session.letters(), session.slots, strict=True)
        }
        rows = []
        for row in session.rows:
            first_part = row.taxon_id.replace("+", "/").split("/")[0]
            taxon = taxa.display.get(first_part)
            if row.taxonomy_id != taxa.display.id or taxon is None:
                # Another taxonomy (loaded with a visit): shown, never dropped, so grid
                # rows stay in step with the session's.
                name, scientific = self._other_names(row.taxonomy_id, row.taxon_id)
                rows.append({
                    "name": name, "scientific": scientific, "rank": "",
                    "counts": [_count_text(row.seen.get(letter)) for letter in SLOT_LETTERS[:4]],
                    "details": [_details(row.seen.get(letter)) for letter in SLOT_LETTERS[:4]],
                    "badges": [],
                    "notes": " / ".join(s.notes for s in row.seen.values() if s.notes),
                })  # fmt: skip
                continue
            name, scientific = taxa.names(row.taxon_id)
            single = first_part == row.taxon_id
            species = taxon
            while species.parent is not None and species.type is not TaxonType.SPECIES:
                species = species.parent
            badges = []
            if single and species.id not in seen:
                badges.append("LIFER")
            for letter in row.seen:
                checklist = checklists.get(letter)
                if checklist is None:
                    continue
                status = checklist.get(species.id)
                if status is None:
                    badges.append(f"NOT ON CHECKLIST {letter}")
                elif status in ("rarity", "rarity-from-introduced"):
                    badges.append(f"RARE {letter}")
                elif status == "endemic" and "ENDEMIC" not in badges:
                    badges.append("ENDEMIC")
            rows.append({
                "name": name,
                "scientific": scientific,
                "rank": taxon.type.xml_name if single else "sp.",
                "counts": [_count_text(row.seen.get(letter)) for letter in SLOT_LETTERS[:4]],
                "details": [_details(row.seen.get(letter)) for letter in SLOT_LETTERS[:4]],
                "badges": badges,
                "notes": " / ".join(s.notes for s in row.seen.values() if s.notes),
            })  # fmt: skip
        self.rows_model.reset(rows)
        self._refresh_checklist()
        self.changed.emit()

    def _refresh_checklist(self) -> None:
        session = self._session
        taxa = self._app.entry_taxa
        context = self._app.context
        if session is None or taxa is None or context is None:
            self.checklist_model.reset([])
            return
        checklist = context.checklist_for(session.slot(self._active).location, taxa.display.id)
        if checklist is None:
            self.checklist_model.reset([])
            return
        wanted = None
        if self._checklist_filter.strip():
            wanted = {m.taxon_id for m in taxa.search(self._checklist_filter, checklist, limit=400)}
        entered = {row.taxon_id: row.seen.get(self._active) for row in session.rows if row.seen}
        rows: list[dict[str, Any]] = []
        for taxon_id in sorted(checklist, key=taxa.order):
            if wanted is not None and taxon_id not in wanted:
                continue
            taxon = taxa.display.get(taxon_id)
            if taxon is None or taxon.disabled:
                continue
            sighting = entered.get(taxon_id)
            rows.append({
                "name": taxon.common_name or full_name(taxon),
                "scientific": full_name(taxon),
                "status": _status_text(checklist[taxon_id], True),
                "count": _count_text(sighting),
                "taxonId": taxon_id,
            })  # fmt: skip
        self.checklist_model.reset(rows)

    @Property(QObject, constant=True)
    def slots(self) -> DictListModel:
        return self.slots_model

    @Property(QObject, constant=True)
    def rows(self) -> DictListModel:
        return self.rows_model

    @Property(QObject, constant=True)
    def matches(self) -> DictListModel:
        return self.matches_model

    @Property(QObject, constant=True)
    def places(self) -> DictListModel:
        return self.places_model

    @Property(QObject, constant=True)
    def checklist(self) -> DictListModel:
        return self.checklist_model

    @property
    def session(self) -> EntrySession | None:
        return self._session


def _float_text(value: float | None) -> str:
    return "" if value is None else java_float_to_string(value)


def _minutes_text(minutes: int | None) -> str:
    if minutes is None:
        return ""
    hours, rest = divmod(minutes, 60)
    return f"{hours}h{rest:02d}" if hours else f"{rest}m"


def _count_text(sighting: SlotSighting | None) -> str:
    if sighting is None:
        return ""
    return "x" if sighting.count is None else str(sighting.count)


def _details(sighting: SlotSighting | None) -> str:
    if sighting is None:
        return ""
    return " ".join(_FLAG_LETTERS[flag] for flag in FLAGS if getattr(sighting, flag))


def _status_text(status: str | None, has_checklist: bool) -> str:
    if not has_checklist:
        return ""
    if status is None:
        return "not on checklist"
    return {"": "", "rarity-from-introduced": "rarity"}.get(status, status)

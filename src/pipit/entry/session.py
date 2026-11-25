"""An Enter Sightings session: one date, up to four locations (slots A-D), and species rows
with a separate count (and details) for each slot the bird was seen in.

Each slot becomes its own Scythebill visit when saved: the sightings take the slot's
location, the shared date and the slot's start time, and the slot's protocol and effort
become the visit record (``SingleLocationEdit.apply``). Pure data; no Qt, no database.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import time
from enum import Enum
from typing import Any

from pipit.domain.partial_date import PartialDate, format_partial_date, parse_partial_date
from pipit.domain.report import ObservationType, VisitField
from pipit.domain.values import ApproximateNumber, format_time, parse_time

SLOT_LETTERS = "ABCD"
MAX_SLOTS = 4
DRAFT_FORMAT = 1
#: Count tokens after a species query: "3", "~20", "a3", "c~12", "bx" (present, no count).
_COUNT_TOKEN = re.compile(r"(?P<slot>[a-dA-D])?(?P<count>[~<>]?[0-9]+|x)", re.IGNORECASE)


class LocationKind(Enum):
    EXISTING = "existing"  # a location already in the list
    PREDEFINED = "predefined"  # a built-in state/county not yet in the list
    NEW = "new"  # a place the user is adding


@dataclass(frozen=True, slots=True)
class LocationChoice:
    kind: LocationKind
    name: str
    label: str  # the name with its parents, for display
    xml_id: str | None = None  # EXISTING
    parent_xml_id: str | None = None  # PREDEFINED and NEW: an existing parent
    type: str | None = None  # PREDEFINED: its type; NEW: optional
    code: str | None = None  # PREDEFINED: its eBird code
    latitude: str | None = None  # NEW, optional, as typed
    longitude: str | None = None


@dataclass(slots=True)
class Slot:
    location: LocationChoice | None = None
    observation_type: ObservationType = ObservationType.HISTORICAL
    start_time: time | None = None
    duration_minutes: int | None = None
    distance_km: float | None = None
    area_hectares: float | None = None
    party_size: int | None = None
    complete: bool = False
    comments: str = ""
    # Editing a recorded visit (``pipit.entry.existing``): the sightings saving replaces,
    # the visit they were loaded from, and the slot as loaded (to tell whether it was
    # edited). None when nothing was loaded: saving then only adds and updates.
    replaces: list[int] | None = None
    loaded_key: str | None = None
    loaded_signature: str | None = None


@dataclass(slots=True)
class SlotSighting:
    """One species at one slot."""

    count: ApproximateNumber | None = None  # None: present, no count
    heard_only: bool = False
    male: bool = False
    female: bool = False
    adult: bool = False
    immature: bool = False
    photographed: bool = False
    status: str = "none"
    breeding: str = ""
    notes: str = ""
    source_id: int | None = None  # the recorded sighting this was loaded from


@dataclass(slots=True)
class EntryRow:
    taxonomy_id: str  # the taxonomy the taxon was chosen in (display or extended)
    taxon_id: str
    seen: dict[str, SlotSighting] = field(default_factory=dict)  # slot letter -> details


class ProblemKind(Enum):
    ERROR = "error"  # blocks saving
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Problem:
    kind: ProblemKind
    message: str
    slot: str | None = None  # letter to jump to
    row: int | None = None


def parse_species_input(text: str) -> tuple[str, dict[str | None, str]]:
    """Split "wiwa a3 c~12" into the species query and counts by slot (None = the active
    slot). Count tokens are only recognized at the end, so species words are never taken
    for counts."""
    words = text.split()
    counts: dict[str | None, str] = {}
    while words:
        match = _COUNT_TOKEN.fullmatch(words[-1])
        if match is None or len(words) == 1:
            break
        slot = match.group("slot")
        counts[slot.upper() if slot else None] = match.group("count").lower()
        words.pop()
    return " ".join(words), dict(reversed(list(counts.items())))


def parse_count(text: str) -> tuple[bool, ApproximateNumber | None]:
    """(valid, count). "x" or "" means present without a count."""
    stripped = text.strip()
    if stripped.lower() in ("", "x"):
        return True, None
    parsed = ApproximateNumber.parse(stripped)
    return parsed is not None, parsed


def parse_duration(text: str) -> int | None:
    """Minutes from "90", "1h30", "1:30", "2h"; None if invalid or not positive."""
    stripped = text.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(?:(\d+)[h:])?(\d*)m?", stripped)
    if not stripped or match is None:
        return None
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    total = hours * 60 + minutes
    return total if total > 0 else None


def parse_clock(text: str) -> time | None:
    """A start time from "0730", "730", "7:30" or "07:30"."""
    stripped = text.strip()
    if re.fullmatch(r"\d{3,4}", stripped):
        stripped = f"{stripped[:-2]}:{stripped[-2:]}"
    return parse_time(stripped)


@dataclass(slots=True)
class EntrySession:
    display_taxonomy_id: str
    date: PartialDate | None = None
    slots: list[Slot] = field(default_factory=lambda: [Slot()])
    rows: list[EntryRow] = field(default_factory=list)

    # ------------------------------------------------------------ slots

    def letters(self) -> str:
        return SLOT_LETTERS[: len(self.slots)]

    def slot(self, letter: str) -> Slot:
        return self.slots[SLOT_LETTERS.index(letter)]

    def add_slot(self) -> str | None:
        """Add the next slot; returns its letter, or None when all four are in use."""
        if len(self.slots) >= MAX_SLOTS:
            return None
        self.slots.append(Slot())
        return SLOT_LETTERS[len(self.slots) - 1]

    def remove_slot(self, letter: str) -> None:
        """Remove a slot; later slots move up a letter, as do their sightings."""
        index = SLOT_LETTERS.index(letter)
        if index >= len(self.slots) or len(self.slots) == 1:
            return
        del self.slots[index]
        for row in self.rows:
            moved = {}
            for slot_letter, sighting in row.seen.items():
                position = SLOT_LETTERS.index(slot_letter)
                if position < index:
                    moved[slot_letter] = sighting
                elif position > index:
                    moved[SLOT_LETTERS[position - 1]] = sighting
            row.seen = moved
        self.rows = [row for row in self.rows if row.seen]

    # ------------------------------------------------------------ rows

    def find_row(self, taxonomy_id: str, taxon_id: str) -> int | None:
        for index, row in enumerate(self.rows):
            if row.taxonomy_id == taxonomy_id and row.taxon_id == taxon_id:
                return index
        return None

    def add_species(self, taxonomy_id: str, taxon_id: str) -> tuple[int, bool]:
        """(row index, created). An existing row is reused: never a silent duplicate."""
        existing = self.find_row(taxonomy_id, taxon_id)
        if existing is not None:
            return existing, False
        self.rows.append(EntryRow(taxonomy_id, taxon_id))
        return len(self.rows) - 1, True

    def set_count(self, row: int, letter: str, text: str) -> bool:
        """Tick ``letter`` for the row with a count ("" or "x" = present). False if the
        count is invalid (nothing changes)."""
        valid, count = parse_count(text)
        if not valid or letter not in self.letters():
            return False
        sighting = self.rows[row].seen.setdefault(letter, SlotSighting())
        sighting.count = count
        return True

    def untick(self, row: int, letter: str) -> None:
        self.rows[row].seen.pop(letter, None)

    def remove_row(self, row: int) -> None:
        del self.rows[row]

    # ------------------------------------------------------------ checks

    def problems(self) -> list[Problem]:
        found: list[Problem] = []
        error = ProblemKind.ERROR
        if self.date is None:
            found.append(Problem(error, "Enter a date."))
        elif not self.date.is_full_date and len(self.slots) > 1:
            found.append(Problem(error, "Several locations need a full date."))
        replacing = any(slot.replaces for slot in self.slots)
        if not self.rows and not replacing:
            found.append(Problem(error, "Enter at least one species."))
        used = {letter for row in self.rows for letter in row.seen}
        keys: dict[tuple[str, time | None], str] = {}
        for letter, slot in zip(self.letters(), self.slots, strict=True):
            if letter not in used and slot.location is None:
                continue
            if slot.location is None:
                found.append(Problem(error, f"Location {letter} has no place.", letter))
            else:
                if letter not in used and slot.replaces:
                    count = len(slot.replaces)
                    found.append(Problem(
                        ProblemKind.WARNING,
                        f"Saving removes the {count} recorded sighting{'s' * (count != 1)} "
                        f"at location {letter}.",
                        letter,
                    ))  # fmt: skip
                elif letter not in used:
                    found.append(
                        Problem(ProblemKind.WARNING, f"No species at location {letter}.", letter)
                    )
                if slot.replaces and slot.loaded_key != self.slot_key(letter):
                    count = len(slot.replaces)
                    found.append(Problem(
                        ProblemKind.WARNING,
                        f"Saving moves the {count} recorded sighting{'s' * (count != 1)} "
                        f"loaded at location {letter} to this place, date and time.",
                        letter,
                    ))  # fmt: skip
                choice = slot.location
                identity = choice.xml_id or f"{choice.parent_xml_id}/{choice.name}"
                key = (identity, slot.start_time)
                if key in keys:
                    message = (
                        f"Locations {keys[key]} and {letter} are the same place at the same time."
                    )
                    found.append(Problem(error, message, letter))
                keys[key] = letter
            required = slot.observation_type.required
            label = slot.observation_type.label
            for visit_field, value, name in (
                (VisitField.START_TIME, slot.start_time, "a start time"),
                (VisitField.DURATION, slot.duration_minutes, "a duration"),
                (VisitField.DISTANCE, slot.distance_km, "a distance"),
                (VisitField.AREA, slot.area_hectares, "an area"),
                (VisitField.PARTY_SIZE, slot.party_size, "a party size"),
            ):
                if visit_field in required and value is None:
                    found.append(Problem(error, f"{label} at {letter} needs {name}.", letter))
            if self.date is not None and not self.date.is_full_date and slot.start_time:
                found.append(Problem(error, "A start time needs a full date.", letter))
        for index, row in enumerate(self.rows):
            if not row.seen:
                found.append(Problem(error, "A species is not ticked at any location.", row=index))
        return found

    def slot_key(self, letter: str) -> str | None:
        """Place, date and start time of an existing place: which recorded visit the slot
        is (``existing.visit_key``); None until all are known."""
        slot = self.slot(letter)
        choice = slot.location
        if self.date is None or choice is None or choice.xml_id is None:
            return None
        start = format_time(slot.start_time) if slot.start_time else ""
        return "|".join((choice.xml_id, format_partial_date(self.date), start))

    def slot_signature(self, letter: str) -> str:
        """The slot's species and details, to tell whether loaded data was edited."""
        slot = self.slot(letter)
        visit = (slot.observation_type.type_id, slot.duration_minutes, slot.distance_km,
                 slot.area_hectares, slot.party_size, slot.complete, slot.comments)  # fmt: skip
        rows = [
            (row.taxonomy_id, row.taxon_id, repr(row.seen[letter]))
            for row in self.rows
            if letter in row.seen
        ]
        return repr((visit, rows))

    def can_save(self) -> bool:
        return not any(problem.kind is ProblemKind.ERROR for problem in self.problems())

    # ------------------------------------------------------------ drafts

    def to_json(self) -> str:
        def slot_json(slot: Slot) -> dict[str, Any]:
            data = asdict(slot)
            data["location"] = (
                None if slot.location is None
                else {**asdict(slot.location), "kind": slot.location.kind.value}
            )  # fmt: skip
            data["observation_type"] = slot.observation_type.type_id
            data["start_time"] = None if slot.start_time is None else format_time(slot.start_time)
            return data

        def row_json(row: EntryRow) -> dict[str, Any]:
            seen = {}
            for letter, sighting in row.seen.items():
                data = asdict(sighting)
                data["count"] = None if sighting.count is None else str(sighting.count)
                seen[letter] = data
            return {"taxonomy_id": row.taxonomy_id, "taxon_id": row.taxon_id, "seen": seen}

        return json.dumps(
            {
                "format": DRAFT_FORMAT,
                "display_taxonomy_id": self.display_taxonomy_id,
                "date": None if self.date is None else format_partial_date(self.date),
                "slots": [slot_json(slot) for slot in self.slots],
                "rows": [row_json(row) for row in self.rows],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(text: str) -> EntrySession:
        data = json.loads(text)
        if data.get("format") != DRAFT_FORMAT:
            raise ValueError("unknown draft format")
        slots = []
        for raw in data["slots"]:
            location = raw["location"]
            observation_type = ObservationType.from_id(raw["observation_type"])
            if observation_type is None:
                raise ValueError("unknown protocol in draft")
            slots.append(
                Slot(
                    location=None if location is None else LocationChoice(
                        **{**location, "kind": LocationKind(location["kind"])}
                    ),
                    observation_type=observation_type,
                    start_time=None if raw["start_time"] is None else parse_time(raw["start_time"]),
                    duration_minutes=raw["duration_minutes"], distance_km=raw["distance_km"],
                    area_hectares=raw["area_hectares"], party_size=raw["party_size"],
                    complete=raw["complete"], comments=raw["comments"],
                    replaces=raw.get("replaces"), loaded_key=raw.get("loaded_key"),
                    loaded_signature=raw.get("loaded_signature"),
                )
            )  # fmt: skip
        rows = []
        for raw in data["rows"]:
            seen = {}
            for letter, sighting in raw["seen"].items():
                count = sighting.pop("count")
                seen[letter] = SlotSighting(
                    count=None if count is None else ApproximateNumber.parse(count), **sighting
                )
            rows.append(EntryRow(raw["taxonomy_id"], raw["taxon_id"], seen))
        return EntrySession(
            display_taxonomy_id=data["display_taxonomy_id"],
            date=None if data["date"] is None else parse_partial_date(data["date"]),
            slots=slots or [Slot()],
            rows=rows,
        )

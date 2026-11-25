"""The Species screen for QML: the taxonomy as a list (families as headings), the sightings
of the chosen entry, and the chosen sighting's details, which can be edited or deleted
(each one undo step). A sighting's visit opens in Enter sightings for anything more.

The roll-up of the whole list is rebuilt after every change (about 0.15 s for 24,000
sightings); the taxonomy rows after a filter change (under 50 ms for all 11,000 species).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from pipit.browse.locations import SpeciesRollup, SpeciesSeen, species_at
from pipit.browse.species import SightingRow, TaxonRow, sightings_of, taxonomy_rows
from pipit.domain.report import BREEDING_CODES, SIGHTING_STATUSES
from pipit.storage import sighting_ops
from pipit.storage.sighting_ops import SightingDetails, SightingError
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)

#: Status labels, as Scythebill shows them (``Messages.getText(SightingStatus)``).
STATUS_LABELS = {
    "none": "(None)", "notAccepted": "Not accepted", "bvd": "Better view desired",
    "intro": "Introduced", "provisional": "Provisional", "notEstablished": "Not established",
    "restrained": "Restrained", "domestic": "Domestic", "idUncertain": "Uncertain ID",
    "unsatisfactoryViews": "Unsatisfactory views", "notByMe": "Not by me", "dead": "Dead",
    "signs": "Signs only",
}  # fmt: skip


class SpeciesBackend(QObject):
    listChanged = Signal()  # the taxonomy rows
    selectionChanged = Signal()
    sightingChanged = Signal()
    filterChanged = Signal()

    def __init__(self, app: AppController) -> None:
        super().__init__()
        self._app = app
        self._seen: dict[str, SpeciesSeen] = {}
        self._rows: list[TaxonRow] = []
        self._only_seen = True
        self._filter = ""
        self._selected: str | None = None
        self._sightings: list[SightingRow] = []
        self._sighting: int | None = None
        self._details: dict[str, Any] = {}
        self.taxa_model = DictListModel(
            ["key", "heading", "common", "scientific", "sightings", "first", "last",
             "isSpecies"]
        )  # fmt: skip
        self.sightings_model = DictListModel(
            ["sightingId", "date", "time", "place", "asRecorded", "count", "flags", "status",
             "breeding", "notes", "trip"]
        )  # fmt: skip
        app.listChanged.connect(self._reload)
        app.dataChanged.connect(self._reload)
        app.taxaReadyChanged.connect(self._reload)
        self._reload()

    @property
    def _connection(self) -> sqlite3.Connection | None:
        database = self._app.database
        return None if database is None else database.connection

    # ------------------------------------------------------------ the taxonomy list

    def _reload(self) -> None:
        connection = self._connection
        taxa = self._app.entry_taxa
        if connection is None or taxa is None:
            self._seen = {}
        else:
            entries = species_at(connection, taxa, None, SpeciesRollup(taxa))
            self._seen = {entry.key: entry for entry in entries}
        self._rebuild()
        selected = self._selected
        if selected is None or not any(row.key == selected for row in self._rows):
            selected = next((row.key for row in self._rows if not row.heading), None)
        self._selected = None  # refresh the panes
        self._select(selected, keep_sighting=True)

    def _rebuild(self) -> None:
        taxa = self._app.entry_taxa
        self._rows = (
            [] if taxa is None
            else taxonomy_rows(taxa, self._seen.values(), only_seen=self._only_seen,
                               query=self._filter)
        )  # fmt: skip
        self.taxa_model.replace_all([
            {"key": row.key, "heading": row.heading, "common": row.common,
             "scientific": row.scientific, "sightings": row.sightings,
             "first": row.first_text, "last": row.last_text, "isSpecies": row.is_species}
            for row in self._rows
        ])  # fmt: skip
        self.listChanged.emit()
        self.selectionChanged.emit()

    @Property(int, notify=listChanged)
    def speciesSeen(self) -> int:
        """Species of the display taxonomy with at least one sighting (any status)."""
        return sum(1 for key, entry in self._seen.items()
                   if entry.is_species and not key.startswith("ext:"))  # fmt: skip

    @Property(bool, notify=filterChanged)
    def onlySeen(self) -> bool:
        return self._only_seen

    @Slot(bool)
    def setOnlySeen(self, only: bool) -> None:
        if only != self._only_seen:
            self._only_seen = only
            self.filterChanged.emit()
            self._rebuild()
            self._keep_selection_visible()

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter

    @Slot(str)
    def setFilter(self, text: str) -> None:
        self._filter = text.strip()
        self.filterChanged.emit()
        self._rebuild()
        self._keep_selection_visible()

    def _keep_selection_visible(self) -> None:
        if self._selected is not None and any(row.key == self._selected for row in self._rows):
            return
        self._select(next((row.key for row in self._rows if not row.heading), None))

    # ------------------------------------------------------------ choosing an entry

    @Property(int, notify=selectionChanged)
    def currentIndex(self) -> int:
        for index, row in enumerate(self._rows):
            if row.key == self._selected and not row.heading:
                return index
        return -1

    @Slot(int, int)
    def selectIndex(self, index: int, step: int) -> None:
        """Choose the row at ``index``; headings are skipped in the direction of ``step``."""
        if not self._rows:
            return
        index = max(0, min(index, len(self._rows) - 1))
        direction = 1 if step >= 0 else -1
        while 0 <= index < len(self._rows) and self._rows[index].heading:
            index += direction
        if not 0 <= index < len(self._rows):  # ran off an end: search back the other way
            index = max(0, min(index, len(self._rows) - 1))
            while 0 <= index < len(self._rows) and self._rows[index].heading:
                index -= direction
        if 0 <= index < len(self._rows):
            self._select(self._rows[index].key)

    @Slot(str)
    def select(self, key: str) -> None:
        self._select(key)

    def _select(self, key: str | None, keep_sighting: bool = False) -> None:
        if key == self._selected:
            return
        previous_sighting = self._sighting
        self._selected = key
        connection = self._connection
        taxa = self._app.entry_taxa
        entry = None if key is None else self._seen.get(key)
        if connection is None or taxa is None or entry is None:
            self._sightings = []
        else:
            self._sightings = sightings_of(connection, taxa, entry)
        self.sightings_model.replace_all([
            {"sightingId": row.sighting_id, "date": row.date_text, "time": row.time_text,
             "place": row.place, "asRecorded": row.as_recorded, "count": row.count,
             "flags": row.flags, "status": STATUS_LABELS.get(row.status, row.status),
             "breeding": row.breeding, "notes": row.notes, "trip": row.trip}
            for row in self._sightings
        ])  # fmt: skip
        self.selectionChanged.emit()
        ids = [row.sighting_id for row in self._sightings]
        if keep_sighting and previous_sighting in ids:
            self._select_sighting(previous_sighting)
        else:
            self._select_sighting(ids[0] if ids else None)

    @Property("QVariantMap", notify=selectionChanged)
    def entry(self) -> dict[str, Any]:
        taxa = self._app.entry_taxa
        if self._selected is None or taxa is None:
            return {}
        seen = self._seen.get(self._selected)
        if seen is not None:
            return {"key": seen.key, "common": seen.common, "scientific": seen.scientific,
                    "sightings": seen.sightings, "first": seen.first_text,
                    "last": seen.last_text, "places": len(seen.places)}  # fmt: skip
        common, scientific = taxa.names(self._selected)
        return {"key": self._selected, "common": common, "scientific": scientific,
                "sightings": 0, "first": "", "last": "", "places": 0}  # fmt: skip

    # ------------------------------------------------------------ one sighting

    @Slot(int)
    def selectSighting(self, sighting_id: int) -> None:
        self._select_sighting(sighting_id)

    @Slot(int)
    def selectSightingIndex(self, index: int) -> None:
        if self._sightings:
            index = max(0, min(index, len(self._sightings) - 1))
            self._select_sighting(self._sightings[index].sighting_id)

    @Property(int, notify=sightingChanged)
    def sightingIndex(self) -> int:
        for index, row in enumerate(self._sightings):
            if row.sighting_id == self._sighting:
                return index
        return -1

    def _select_sighting(self, sighting_id: int | None) -> None:
        self._sighting = sighting_id
        row = next((row for row in self._sightings if row.sighting_id == sighting_id), None)
        connection = self._connection
        if row is None or connection is None:
            self._details = {}
        else:
            try:
                details = sighting_ops.read_details(connection, row.sighting_id)
            except SightingError:
                self._details = {}
            else:
                self._details = {
                    "sightingId": row.sighting_id, "date": row.date_text, "time": row.time_text,
                    "place": row.place, "asRecorded": row.as_recorded, "trip": row.trip,
                    "locationXmlId": row.location_xml_id or "", "dateRaw": row.date_raw or "",
                    "count": details.count, "heardOnly": details.heard_only,
                    "male": details.male, "female": details.female, "adult": details.adult,
                    "immature": details.immature, "photographed": details.photographed,
                    "status": details.status, "breeding": details.breeding,
                    "notes": details.notes,
                    "canOpenVisit": bool(row.location_xml_id and row.date_raw and not row.trip),
                }  # fmt: skip
        self.sightingChanged.emit()

    @Property("QVariantMap", notify=sightingChanged)
    def sighting(self) -> dict[str, Any]:
        return self._details

    @Property("QStringList", constant=True)
    def statuses(self) -> list[str]:
        return list(SIGHTING_STATUSES)

    @Property("QStringList", constant=True)
    def statusLabels(self) -> list[str]:
        return [STATUS_LABELS.get(status, status) for status in SIGHTING_STATUSES]

    @Property("QStringList", constant=True)
    def breedingCodes(self) -> list[str]:
        return list(BREEDING_CODES)

    def _apply(self, label: str, change: Callable[[sqlite3.Connection], None]) -> bool:
        database = self._app.database
        if database is None:
            return False
        if database.read_only:
            self._app.message.emit("This list is read-only")
            return False
        try:
            with database.action(label) as connection:
                change(connection)
        except SightingError as error:
            self._app.message.emit(str(error))
            return False
        except sqlite3.Error as error:
            log.exception("sighting change failed")
            self._app.message.emit(f"Could not save: {error}")
            return False
        self._app.changed()
        self._app.message.emit(f"{label} · Ctrl+Z undoes")
        return True

    def _label(self, verb: str) -> str:
        entry = self.entry
        return f"{verb} {entry.get('common', 'sighting')}, {self._details.get('date', '')}"

    @Slot(int, "QVariantMap", result=bool)
    def saveSighting(self, sighting_id: int, values: dict[str, Any]) -> bool:
        details = SightingDetails(
            count=str(values.get("count", "")),
            heard_only=bool(values.get("heardOnly")), male=bool(values.get("male")),
            female=bool(values.get("female")), adult=bool(values.get("adult")),
            immature=bool(values.get("immature")),
            photographed=bool(values.get("photographed")),
            status=str(values.get("status", "none")), breeding=str(values.get("breeding", "")),
            notes=str(values.get("notes", "")),
        )  # fmt: skip
        return self._apply(
            self._label("Edit"),
            lambda c: sighting_ops.update_details(c, sighting_id, details),
        )

    @Slot(int, result=bool)
    def deleteSighting(self, sighting_id: int) -> bool:
        return self._apply(
            self._label("Delete"), lambda c: sighting_ops.delete_sighting(c, sighting_id)
        )

    # ------------------------------------------------------------ models

    @Property(QObject, constant=True)
    def taxaList(self) -> DictListModel:
        return self.taxa_model

    @Property(QObject, constant=True)
    def sightings(self) -> DictListModel:
        return self.sightings_model

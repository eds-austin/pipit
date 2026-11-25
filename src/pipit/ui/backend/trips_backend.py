"""The Trips screen for QML: trips newest first, the species seen on the chosen trip, and
the trip itself to edit (name, dates, place, notes) or delete, each one undo step with
Scythebill's rules (``pipit.storage.trip_ops``).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from pipit.browse.locations import SpeciesRollup, species_at
from pipit.browse.species import place_labels
from pipit.browse.trips import TripRow, trip_rows, trip_sighting_ids
from pipit.storage import trip_ops
from pipit.storage.trip_ops import TripError
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)
CHOICE_LIMIT = 60
DATE_RANGE = " \u2013 "  # an en dash between two dates


def _dates(trip: TripRow) -> str:
    return trip.start_text if trip.start_text == trip.end_text else (
        f"{trip.start_text}{DATE_RANGE}{trip.end_text}"
    )  # fmt: skip


class TripsBackend(QObject):
    listChanged = Signal()
    selectionChanged = Signal()
    filterChanged = Signal()

    def __init__(self, app: AppController) -> None:
        super().__init__()
        self._app = app
        self._trips: list[TripRow] = []
        self._places: dict[str, str] = {}
        self._filter = ""
        self._selected: int | None = None
        self._details: dict[str, Any] = {}
        self._sightings = 0
        self._species = 0
        self.trips_model = DictListModel(["row", "name", "dates", "place", "notes"])
        self.species_model = DictListModel(
            ["key", "common", "scientific", "sightings", "first", "last", "heardOnly", "places"]
        )
        self.choices_model = DictListModel(["xmlId", "name", "path"])
        self._choices: list[str | None] = []
        app.listChanged.connect(self._reload)
        app.dataChanged.connect(self._reload)
        app.taxaReadyChanged.connect(self._reload)
        self._reload()

    @property
    def _connection(self) -> sqlite3.Connection | None:
        database = self._app.database
        return None if database is None else database.connection

    # ------------------------------------------------------------ the trip list

    def _reload(self) -> None:
        connection = self._connection
        self._places = {} if connection is None else place_labels(connection)
        self._trips = [] if connection is None else trip_rows(connection, self._filter)
        self.trips_model.replace_all([
            {"row": trip.row, "name": trip.name or "(No name)", "dates": _dates(trip),
             "place": self._places.get(trip.location_xml_id or "", ""), "notes": trip.notes}
            for trip in self._trips
        ])  # fmt: skip
        self.listChanged.emit()
        selected = self._selected
        if selected is None or not any(trip.row == selected for trip in self._trips):
            selected = self._trips[0].row if self._trips else None
        self._selected = None
        self._select(selected)

    @Property(int, notify=listChanged)
    def tripCount(self) -> int:
        connection = self._connection
        if connection is None:
            return 0
        return int(connection.execute("SELECT count(*) FROM trips").fetchone()[0])

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter

    @Slot(str)
    def setFilter(self, text: str) -> None:
        self._filter = text.strip()
        self.filterChanged.emit()
        self._reload()

    # ------------------------------------------------------------ choosing a trip

    @Property(int, notify=selectionChanged)
    def currentIndex(self) -> int:
        return next((i for i, trip in enumerate(self._trips) if trip.row == self._selected), -1)

    @Slot(int)
    def selectIndex(self, index: int) -> None:
        if self._trips:
            self._select(self._trips[max(0, min(index, len(self._trips) - 1))].row)

    @Slot(int)
    def select(self, row: int) -> None:
        self._select(row)

    def _select(self, row: int | None) -> None:
        if row == self._selected:
            return
        self._selected = row
        trip = next((trip for trip in self._trips if trip.row == row), None)
        connection = self._connection
        taxa = self._app.entry_taxa
        if trip is None or connection is None:
            self._details = {}
            self.species_model.replace_all([])
            self._sightings = self._species = 0
        else:
            ids = trip_sighting_ids(connection, trip)
            seen = [] if taxa is None else species_at(
                connection, taxa, None, SpeciesRollup(taxa), sighting_ids=ids
            )  # fmt: skip
            self.species_model.replace_all([
                {"key": entry.key, "common": entry.common, "scientific": entry.scientific,
                 "sightings": entry.sightings, "first": entry.first_text,
                 "last": entry.last_text, "heardOnly": entry.heard_only == entry.sightings,
                 "places": len(entry.places)}
                for entry in seen
            ])  # fmt: skip
            self._sightings = len(ids)
            self._species = sum(
                1 for entry in seen if entry.is_species and not entry.key.startswith("ext:")
            )
            self._details = {
                "row": trip.row, "name": trip.name, "start": str(trip.start),
                "end": str(trip.end), "dates": _dates(trip), "startTime": trip.start_time,
                "placeXmlId": trip.location_xml_id or "",
                "place": self._places.get(trip.location_xml_id or "", ""),
                "notes": trip.notes, "links": trip.links, "photos": trip.photos,
            }  # fmt: skip
        self.selectionChanged.emit()

    @Property("QVariantMap", notify=selectionChanged)
    def trip(self) -> dict[str, Any]:
        return self._details

    @Property(int, notify=selectionChanged)
    def sightingCount(self) -> int:
        return self._sightings

    @Property(int, notify=selectionChanged)
    def speciesCount(self) -> int:
        return self._species

    # ------------------------------------------------------------ choosing a place

    @Slot(str)
    def findPlaces(self, query: str) -> None:
        """Places for the trip's place (and "no place"), by name."""
        connection = self._connection
        needle = query.strip().casefold()
        found: list[dict[str, Any]] = []
        self._choices = []
        if not needle or needle in "no place":
            found.append({"xmlId": "", "name": "No place", "path": "The trip is anywhere"})
            self._choices.append(None)
        if connection is not None:
            for xml_id, name in connection.execute(
                "SELECT xml_id, name FROM locations ORDER BY name"
            ):
                if needle and needle not in name.casefold():
                    continue
                label = self._places.get(xml_id, name)
                found.append({"xmlId": xml_id, "name": name,
                              "path": label.partition(" · ")[2]})  # fmt: skip
                self._choices.append(xml_id)
                if len(found) >= CHOICE_LIMIT:
                    break
        self.choices_model.replace_all(found)

    @Slot(int, result=str)
    def choiceLabel(self, index: int) -> str:
        rows = self.choices_model.rows()
        if not 0 <= index < len(rows):
            return ""
        row = rows[index]
        return f"{row['name']} · {row['path']}" if row["path"] else str(row["name"])

    @Slot(int, result=str)
    def choiceXmlId(self, index: int) -> str:
        if 0 <= index < len(self._choices):
            return self._choices[index] or ""
        return "?"

    # ------------------------------------------------------------ changes

    def _apply(self, label: str, change: Callable[[sqlite3.Connection], object]) -> bool:
        database = self._app.database
        if database is None:
            return False
        if database.read_only:
            self._app.message.emit("This list is read-only")
            return False
        try:
            with database.action(label) as connection:
                change(connection)
        except TripError as error:
            self._app.message.emit(str(error))
            return False
        except sqlite3.Error as error:
            log.exception("trip change failed")
            self._app.message.emit(f"Could not save: {error}")
            return False
        self._app.changed()
        self._app.message.emit(f"{label} · Ctrl+Z undoes")
        return True

    @Slot(int, str, str, str, str, str, result=bool)
    def saveTrip(  # noqa: PLR0917 (QML calls slots with positional arguments)
        self, row: int, name: str, start: str, end: str, place_xml_id: str, notes: str
    ) -> bool:
        trip = next((trip for trip in self._trips if trip.row == row), None)
        label = f"Edit trip {trip.name if trip else ''}".rstrip()
        return self._apply(
            label,
            lambda c: trip_ops.update_trip(c, row, name=name, start=start, end=end,
                                           location_xml_id=place_xml_id or None, notes=notes),
        )  # fmt: skip

    @Slot(int, result=bool)
    def deleteTrip(self, row: int) -> bool:
        trip = next((trip for trip in self._trips if trip.row == row), None)
        return self._apply(
            f"Delete trip {trip.name if trip else ''}".rstrip(),
            lambda c: trip_ops.delete_trip(c, row),
        )

    # ------------------------------------------------------------ models

    @Property(QObject, constant=True)
    def trips(self) -> DictListModel:
        return self.trips_model

    @Property(QObject, constant=True)
    def species(self) -> DictListModel:
        return self.species_model

    @Property(QObject, constant=True)
    def choices(self) -> DictListModel:
        return self.choices_model

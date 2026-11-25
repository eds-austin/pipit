"""The Locations screen for QML: the place tree, what was seen in the selected place, its
visits and details, and the changes (new, rename, edit, move, merge, delete).

Each change is one undoable action (``ListDatabase.action``) using Scythebill's rules from
``pipit.storage.location_ops``. The species pane refreshes shortly after the selection
settles, so holding an arrow key through the tree stays smooth.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from pipit.browse.locations import (
    PlaceNode,
    SpeciesRollup,
    location_tree,
    place_details,
    species_at,
    visits_at,
)
from pipit.domain.report import LOCATION_TYPES
from pipit.entry.taxa import EntryTaxa
from pipit.storage import location_ops
from pipit.storage.location_ops import LocationError
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)

SPECIES_DELAY_MS = 120
CHOICE_LIMIT = 60
PATH_SEPARATOR = " \u203a "  # a single right-pointing angle quote between ancestors


class LocationsBackend(QObject):
    treeChanged = Signal()
    selectionChanged = Signal()
    speciesChanged = Signal()
    filterChanged = Signal()

    def __init__(self, app: AppController) -> None:
        super().__init__()
        self._app = app
        self._nodes: list[PlaceNode] = []
        self._by_row: dict[int, PlaceNode] = {}
        self._expanded: set[int] = set()
        self._filter = ""
        self._selected: int | None = None
        self._details: dict[str, Any] = {}
        self._rollup: SpeciesRollup | None = None
        self._rollup_taxa: EntryTaxa | None = None
        self._species_count = 0
        self._other_count = 0
        self._species_for: int | None = None
        self.tree_model = DictListModel([
            "row", "name", "depth", "hasChildren", "expanded", "sightings", "kind", "builtIn",
            "code", "matched",
        ])  # fmt: skip
        self.species_model = DictListModel(
            ["key", "common", "scientific", "sightings", "first", "last", "heardOnly", "places"]
        )
        self.visits_model = DictListModel(
            ["visitId", "date", "start", "protocol", "duration", "distance", "party",
             "complete", "comments", "sightings", "dateRaw"]
        )  # fmt: skip
        self.choices_model = DictListModel(["row", "name", "path"])
        self._species_timer = QTimer(self)
        self._species_timer.setSingleShot(True)
        self._species_timer.setInterval(SPECIES_DELAY_MS)
        self._species_timer.timeout.connect(self._refresh_species)
        app.listChanged.connect(self._list_changed)
        app.dataChanged.connect(self._data_changed)
        app.taxaReadyChanged.connect(self._schedule_species)
        self._list_changed()

    # ------------------------------------------------------------ loading

    @property
    def _connection(self) -> sqlite3.Connection | None:
        database = self._app.database
        return None if database is None else database.connection

    def _list_changed(self) -> None:
        self._expanded = set()
        self._selected = None
        self._filter = ""
        self._reload_tree()
        roots = [node for node in self._nodes if node.depth == 0]
        self._expanded = {node.row for node in roots}
        first = next((node for node in roots if node.sightings), roots[0] if roots else None)
        self._rebuild_rows()
        self.filterChanged.emit()
        self._set_selected(None if first is None else first.row)

    def _data_changed(self) -> None:
        before = self._selected
        old_node = None if before is None else self._by_row.get(before)
        self._reload_tree()
        selected = before
        if selected is not None and selected not in self._by_row:
            # Deleted or merged away: fall back to its old parent, then to a root.
            selected = old_node.parent if old_node is not None else None
            if selected not in self._by_row:
                selected = self._nodes[0].row if self._nodes else None
        self._expanded &= set(self._by_row)
        self._reveal(selected)
        self._rebuild_rows()
        self._selected = None  # force a refresh of the panes
        self._set_selected(selected)

    def _reload_tree(self) -> None:
        connection = self._connection
        self._nodes = [] if connection is None else location_tree(connection)
        self._by_row = {node.row: node for node in self._nodes}

    def _ancestors(self, row: int) -> list[int]:
        found = []
        node = self._by_row.get(row)
        while node is not None and node.parent is not None:
            found.append(node.parent)
            node = self._by_row.get(node.parent)
        return found

    def _reveal(self, row: int | None) -> None:
        if row is not None:
            self._expanded.update(self._ancestors(row))

    # ------------------------------------------------------------ tree rows

    def _visible(self) -> list[tuple[PlaceNode, bool]]:
        """(node, matched) for the rows on screen. With a filter: the matches and their
        ancestors, all open."""
        if self._filter:
            needle = self._filter.casefold()
            matched = {node.row for node in self._nodes if needle in node.name.casefold()}
            shown = set(matched)
            for row in matched:
                shown.update(self._ancestors(row))
            return [(node, node.row in matched) for node in self._nodes if node.row in shown]
        visible = []
        hidden_below: int | None = None
        for node in self._nodes:
            if hidden_below is not None:
                if node.depth > hidden_below:
                    continue
                hidden_below = None
            visible.append((node, False))
            if node.child_count and node.row not in self._expanded:
                hidden_below = node.depth
        return visible

    def _rebuild_rows(self) -> None:
        filtering = bool(self._filter)
        self.tree_model.reset([
            {"row": node.row, "name": node.name, "depth": node.depth,
             "hasChildren": node.child_count > 0,
             "expanded": filtering or node.row in self._expanded,
             "sightings": node.sightings, "kind": node.type or "", "builtIn": node.built_in,
             "code": node.ebird_code or "", "matched": matched}
            for node, matched in self._visible()
        ])  # fmt: skip
        self.treeChanged.emit()
        self.selectionChanged.emit()  # the selected row's index may have moved

    @Slot(int, result=int)
    def indexOfRow(self, row: int) -> int:
        for index, item in enumerate(self.tree_model.rows()):
            if item["row"] == row:
                return int(index)
        return -1

    @Property(int, notify=selectionChanged)
    def currentIndex(self) -> int:
        return -1 if self._selected is None else self.indexOfRow(self._selected)

    @Slot(int)
    def selectIndex(self, index: int) -> None:
        rows = self.tree_model.rows()
        if rows:
            self._set_selected(rows[max(0, min(index, len(rows) - 1))]["row"])

    @Slot()
    def expandOrEnter(self) -> None:
        """Right: open the place; if it is open, go to the first place inside."""
        node = None if self._selected is None else self._by_row.get(self._selected)
        if node is None or not node.child_count:
            return
        if self._filter or node.row in self._expanded:
            self.selectIndex(self.currentIndex + 1)
        else:
            self.toggle(node.row)

    @Slot()
    def collapseOrLeave(self) -> None:
        """Left: close the place; if it is closed, go to the place it is in."""
        node = None if self._selected is None else self._by_row.get(self._selected)
        if node is None:
            return
        if node.child_count and node.row in self._expanded and not self._filter:
            self.toggle(node.row)
        elif node.parent is not None:
            self._set_selected(node.parent)

    @Slot(int)
    def toggle(self, row: int) -> None:
        if row in self._expanded:
            self._expanded.discard(row)
        else:
            self._expanded.add(row)
        self._rebuild_rows()

    @Slot(int, bool)
    def setExpanded(self, row: int, expanded: bool) -> None:
        if expanded == (row in self._expanded):
            return
        self.toggle(row)

    @Slot(int, result=int)
    def parentOf(self, row: int) -> int:
        node = self._by_row.get(row)
        return -1 if node is None or node.parent is None else node.parent

    @Slot(str)
    def setFilter(self, text: str) -> None:
        self._filter = text.strip()
        self._rebuild_rows()
        self.filterChanged.emit()
        if self._filter:
            first = next((item for item in self.tree_model.rows() if item["matched"]), None)
            if first is not None:
                self._set_selected(first["row"])
        elif self._selected is not None:
            self._reveal(self._selected)
            self._rebuild_rows()

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter

    # ------------------------------------------------------------ selection

    @Slot(int)
    def select(self, row: int) -> None:
        self._set_selected(row)

    def _set_selected(self, row: int | None) -> None:
        if row == self._selected:
            return
        self._selected = row
        connection = self._connection
        details = None if row is None or connection is None else place_details(connection, row)
        node = None if row is None else self._by_row.get(row)
        if row is None or connection is None or details is None or node is None:
            self._details = {}
            self.visits_model.reset([])
        else:
            reason = location_ops.can_delete(connection, row)
            self._details = {
                "row": details.row, "xmlId": details.xml_id, "name": details.name,
                "kind": details.type or "",
                "path": PATH_SEPARATOR.join(details.path), "code": details.ebird_code or "",
                "hotspot": details.hotspot or "", "latitude": details.latitude or "",
                "longitude": details.longitude or "", "private": details.private,
                "description": details.description, "builtIn": node.built_in,
                "hasChecklist": details.has_checklist, "sightings": node.sightings,
                "children": node.child_count, "deleteBlocked": reason or "",
                "renameBlocked": "Built-in places keep their names." if node.built_in else "",
            }  # fmt: skip
            self.visits_model.reset([
                {"visitId": visit.visit_id, "date": visit.date_text, "start": visit.start_time,
                 "protocol": visit.protocol,
                 "duration": "" if visit.duration_minutes is None
                             else f"{visit.duration_minutes} min",
                 "distance": "" if visit.distance_km is None else f"{visit.distance_km} km",
                 "party": "" if visit.party_size is None else str(visit.party_size),
                 "complete": visit.complete, "comments": visit.comments,
                 "sightings": visit.sightings, "dateRaw": visit.date_raw}
                for visit in visits_at(connection, details.xml_id)
            ])  # fmt: skip
        self.selectionChanged.emit()
        self._schedule_species()

    @Property(int, notify=selectionChanged)
    def selectedRow(self) -> int:
        return -1 if self._selected is None else self._selected

    @Property("QVariantMap", notify=selectionChanged)
    def details(self) -> dict[str, Any]:
        return self._details

    # ------------------------------------------------------------ species

    def _schedule_species(self) -> None:
        self._species_timer.start()

    def refresh_species_now(self) -> None:
        """Tests and screenshots: skip the settle delay."""
        self._species_timer.stop()
        self._refresh_species()

    def _refresh_species(self) -> None:
        connection = self._connection
        taxa = self._app.entry_taxa
        if connection is None or taxa is None or self._selected is None:
            self.species_model.reset([])
            self._species_count = 0
            self._other_count = 0
            self._species_for = None
            self.speciesChanged.emit()
            return
        if self._rollup is None or self._rollup_taxa is not taxa:
            self._rollup = SpeciesRollup(taxa)
            self._rollup_taxa = taxa
        seen = species_at(connection, taxa, self._selected, self._rollup)
        self.species_model.reset([
            {"key": entry.key, "common": entry.common, "scientific": entry.scientific,
             "sightings": entry.sightings, "first": entry.first_text, "last": entry.last_text,
             "heardOnly": entry.heard_only == entry.sightings, "places": len(entry.places)}
            for entry in seen
        ])  # fmt: skip
        self._species_count = sum(
            1 for entry in seen if entry.is_species and not entry.key.startswith("ext:")
        )
        self._other_count = sum(
            1 for entry in seen if entry.is_species and entry.key.startswith("ext:")
        )
        self._species_for = self._selected
        self.speciesChanged.emit()

    @Property(int, notify=speciesChanged)
    def speciesCount(self) -> int:
        """Rows that are one species (a sp., hybrid or genus-level row adds none)."""
        return self._species_count

    @Property(int, notify=speciesChanged)
    def otherSpeciesCount(self) -> int:
        """Species of the other taxonomies in the list (mammals), counted apart."""
        return self._other_count

    @Property(bool, notify=speciesChanged)
    def speciesReady(self) -> bool:
        return self._species_for is not None and self._species_for == self._selected

    # ------------------------------------------------------------ choosing a place

    @Slot(str, int)
    def findPlaces(self, query: str, excluding: int) -> None:
        """Places for the move and merge pickers: names containing ``query``, leaving out
        ``excluding`` and everything inside it."""
        needle = query.strip().casefold()
        inside = {excluding}
        for node in self._nodes:
            if node.parent in inside:
                inside.add(node.row)
        found = []
        for node in self._nodes:
            if node.row in inside or (needle and needle not in node.name.casefold()):
                continue
            path = [self._by_row[row].name for row in reversed(self._ancestors(node.row))]
            found.append({"row": node.row, "name": node.name, "path": PATH_SEPARATOR.join(path)})
            if len(found) >= CHOICE_LIMIT:
                break
        self.choices_model.reset(found)

    @Slot(int, result=int)
    def choiceRow(self, index: int) -> int:
        rows = self.choices_model.rows()
        return int(rows[index]["row"]) if 0 <= index < len(rows) else -1

    # ------------------------------------------------------------ changes

    def _apply(self, label: str, change: Callable[[sqlite3.Connection], Any]) -> Any:
        database = self._app.database
        if database is None:
            return None
        if database.read_only:
            self._app.message.emit("This list is read-only")
            return None
        try:
            with database.action(label) as connection:
                result = change(connection)
        except LocationError as error:
            self._app.message.emit(str(error))
            return None
        except sqlite3.Error as error:
            log.exception("location change failed")
            self._app.message.emit(f"Could not save: {error}")
            return None
        self._app.changed()
        self._app.message.emit(f"{label} · Ctrl+Z undoes")
        return result if result is not None else True

    def _name(self, row: int) -> str:
        node = self._by_row.get(row)
        return node.name if node is not None else "place"

    @Slot(int, str, str, result=bool)
    def addPlace(self, parent: int, name: str, kind: str) -> bool:
        xml_id = self._apply(
            f"Add {name.strip()}",
            lambda c: location_ops.add_location(c, parent, name, kind or None),
        )
        if not xml_id:
            return False
        connection = self._connection
        if connection is not None:
            row = location_ops.row_of(connection, str(xml_id))
            self._reveal(row)
            self._rebuild_rows()
            self._set_selected(row)
        return True

    @Slot(int, str, str, str, str, bool, str, result=bool)
    def updatePlace(  # noqa: PLR0917 (QML calls slots with positional arguments)
        self, row: int, name: str, latitude: str, longitude: str, description: str,
        private: bool, hotspot: str,
    ) -> bool:  # fmt: skip
        """The edit dialog: a new name (custom places only) and the other fields, saved as
        one undoable change."""
        old = self._name(row)
        renamed = name.strip() != old

        def change(connection: sqlite3.Connection) -> None:
            if renamed:
                location_ops.rename_location(connection, row, name)
            location_ops.edit_location(
                connection, row, latitude=latitude, longitude=longitude,
                description=description, private=private, hotspot=hotspot,
            )  # fmt: skip

        label = f"Rename {old} to {name.strip()}" if renamed else f"Edit {old}"
        return bool(self._apply(label, change))

    @Slot(int, int, result=bool)
    def movePlace(self, row: int, new_parent: int) -> bool:
        done = bool(
            self._apply(
                f"Move {self._name(row)} into {self._name(new_parent)}",
                lambda c: location_ops.move_location(c, row, new_parent),
            )
        )
        if done:
            self._reveal(row)
            self._rebuild_rows()
        return done

    @Slot(int, int, result=bool)
    def mergePlace(self, row: int, into: int) -> bool:
        done = bool(
            self._apply(
                f"Merge {self._name(row)} into {self._name(into)}",
                lambda c: location_ops.merge_location(c, row, into),
            )
        )
        if done:
            self._reveal(into)
            self._rebuild_rows()
            self._set_selected(into)
        return done

    @Slot(int, result=bool)
    def deletePlace(self, row: int) -> bool:
        return bool(
            self._apply(f"Delete {self._name(row)}", lambda c: location_ops.delete_location(c, row))
        )

    # ------------------------------------------------------------ models

    @Property("QStringList", constant=True)
    def locationTypes(self) -> list[str]:
        return ["", *LOCATION_TYPES]

    @Property(QObject, constant=True)
    def tree(self) -> DictListModel:
        return self.tree_model

    @Property(QObject, constant=True)
    def species(self) -> DictListModel:
        return self.species_model

    @Property(QObject, constant=True)
    def visits(self) -> DictListModel:
        return self.visits_model

    @Property(QObject, constant=True)
    def choices(self) -> DictListModel:
        return self.choices_model

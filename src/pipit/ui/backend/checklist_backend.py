"""Editing a place's own checklist (Scythebill's ``EditChecklistPanel``) for QML: open it,
change statuses, add and remove species, then save (one undo step, written as Scythebill
writes it) or delete it. Nothing is stored until Save.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from pipit.browse.checklists import ChecklistRow, add_species, checklist_rows, with_status
from pipit.entry.taxa import Match
from pipit.storage import checklist_ops
from pipit.storage.checklist_ops import ChecklistError
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)

#: The status menu, in Scythebill's order and words (``STATUS_INDICES``).
STATUS_CHOICES: tuple[tuple[str | None, str], ...] = (
    (None, "Regular"), ("introduced", "Introduced"), ("provisional", "Provisional"),
    ("escaped", "Not established"), ("rarity", "Rarity"),
    ("rarity-from-introduced", "Rarity, from introduced pop."), ("endemic", "Endemic"),
    ("extinct", "Extinct"),
)  # fmt: skip
_INDEX = {status: index for index, (status, _label) in enumerate(STATUS_CHOICES)}


class ChecklistBackend(QObject):
    changed = Signal()  # rows, dirty state, or the open place
    matchesChanged = Signal()

    def __init__(self, app: AppController) -> None:
        super().__init__()
        self._app = app
        self._place: str | None = None
        self._place_name = ""
        self._exists = False
        self._rows: list[ChecklistRow] = []
        self._original: list[ChecklistRow] = []
        self._matches: list[Match] = []
        self.rows_model = DictListModel(["common", "scientific", "status", "statusIndex"])
        self.matches_model = DictListModel(["name", "scientific", "onList"])
        app.listChanged.connect(self.close)

    @property
    def _connection(self) -> sqlite3.Connection | None:
        database = self._app.database
        return None if database is None else database.connection

    # ------------------------------------------------------------ open and close

    @Slot(str, str, result=bool)
    def open(self, xml_id: str, place_name: str) -> bool:
        """Start editing ``xml_id``'s checklist (a new, empty one if it has none)."""
        connection = self._connection
        taxa = self._app.entry_taxa
        if connection is None or taxa is None:
            return False
        self._place = xml_id
        self._place_name = place_name
        self._exists = checklist_ops.has_checklist(connection, xml_id)
        self._rows = checklist_rows(taxa, checklist_ops.read_checklist(connection, xml_id))
        self._original = list(self._rows)
        self._matches = []
        self.matches_model.replace_all([])
        self._publish(reset=True)
        return True

    @Slot()
    def close(self) -> None:
        self._place = None
        self._rows = self._original = []
        self._publish(reset=True)

    def _publish(self, reset: bool = False) -> None:
        rows = [
            {"common": row.common, "scientific": row.scientific,
             "status": STATUS_CHOICES[_INDEX.get(row.status, 0)][1] if row.status else "",
             "statusIndex": _INDEX.get(row.status, 0)}
            for row in self._rows
        ]  # fmt: skip
        if reset:
            self.rows_model.replace_all(rows)
        else:
            self.rows_model.reset(rows)
        self.changed.emit()

    @Property(bool, notify=changed)
    def isOpen(self) -> bool:
        return self._place is not None

    @Property(str, notify=changed)
    def placeName(self) -> str:
        return self._place_name

    @Property(bool, notify=changed)
    def exists(self) -> bool:
        """The place already has a checklist of its own (Delete is offered)."""
        return self._exists

    @Property(bool, notify=changed)
    def dirty(self) -> bool:
        return [row.entry for row in self._rows] != [row.entry for row in self._original]

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._rows)

    @Property("QStringList", constant=True)
    def statusLabels(self) -> list[str]:
        return [label for _status, label in STATUS_CHOICES]

    # ------------------------------------------------------------ edits

    @Slot(int, int)
    def setStatus(self, row: int, status_index: int) -> None:
        if 0 <= row < len(self._rows) and 0 <= status_index < len(STATUS_CHOICES):
            self._rows[row] = with_status(self._rows[row], STATUS_CHOICES[status_index][0])
            self._publish()

    @Slot(int)
    def removeRow(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            del self._rows[row]
            self._publish()

    @Slot(str)
    def searchSpecies(self, text: str) -> None:
        taxa = self._app.entry_taxa
        self._matches = [] if taxa is None or not text.strip() else taxa.search(text, limit=20)
        on_list = {row.row_id for row in self._rows}
        self.matches_model.replace_all([
            {"name": match.common_name, "scientific": match.scientific_name,
             "onList": match.taxon_id in on_list}
            for match in self._matches
        ])  # fmt: skip
        self.matchesChanged.emit()

    @Slot(int, result=int)
    def addMatch(self, index: int) -> int:
        """Add a search match (as Regular); returns its row (an existing one if it was
        already on the list), or -1."""
        taxa = self._app.entry_taxa
        if taxa is None or not 0 <= index < len(self._matches):
            return -1
        try:
            self._rows, row = add_species(taxa, self._rows, self._matches[index].taxon_id)
        except ValueError as error:
            self._app.message.emit(str(error))
            return -1
        self._publish(reset=True)
        return row

    # ------------------------------------------------------------ save and delete

    def _apply(self, label: str, change: Callable[[sqlite3.Connection], None]) -> bool:
        database = self._app.database
        if database is None or self._place is None:
            return False
        if database.read_only:
            self._app.message.emit("This list is read-only")
            return False
        try:
            with database.action(label) as connection:
                change(connection)
        except ChecklistError as error:
            self._app.message.emit(str(error))
            return False
        except sqlite3.Error as error:
            log.exception("checklist change failed")
            self._app.message.emit(f"Could not save: {error}")
            return False
        self._app.changed()
        self._app.message.emit(f"{label} · Ctrl+Z undoes")
        return True

    @Slot(result=bool)
    def save(self) -> bool:
        place = self._place
        if place is None:
            return False
        if not self._rows:
            self._app.message.emit("A checklist needs at least one species (or delete it).")
            return False
        entries = [row.entry for row in self._rows]
        done = self._apply(
            f"Save checklist of {self._place_name}",
            lambda c: checklist_ops.save_checklist(c, place, entries),
        )
        if done:
            self.close()
        return done

    @Slot(result=bool)
    def deleteChecklist(self) -> bool:
        place = self._place
        if place is None or not self._exists:
            return False
        done = self._apply(
            f"Delete checklist of {self._place_name}",
            lambda c: checklist_ops.delete_checklist(c, place),
        )
        if done:
            self.close()
        return done

    # ------------------------------------------------------------ models

    @Property(QObject, constant=True)
    def rows(self) -> DictListModel:
        return self.rows_model

    @Property(QObject, constant=True)
    def matches(self) -> DictListModel:
        return self.matches_model

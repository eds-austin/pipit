"""The open list, the data pack and the taxonomies, shared by every screen.

Taxonomies take about two seconds to load, so they load on a worker thread; screens that
need them watch ``taxaReady``. The list itself opens at once (with its integrity checks;
a damaged list opens read-only and says why).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from pipit.config import paths
from pipit.config.settings import AppSettings, save_settings
from pipit.datapack.pack import DataPack, PackError
from pipit.entry.context import ListContext
from pipit.entry.taxa import EntryTaxa
from pipit.storage import drafts
from pipit.storage.cli import find_pack
from pipit.storage.lists import LIST_SUFFIX, OpenedList, import_bsxm, open_list
from pipit.ui.backend.dispatch import Dispatcher, run_in_thread

log = logging.getLogger(__name__)


class AppController(QObject):
    listChanged = Signal()
    taxaReadyChanged = Signal()
    dataChanged = Signal()  # the list's contents changed (save, undo, redo)
    message = Signal(str)  # a short toast for the status bar

    def __init__(
        self,
        settings: AppSettings,
        save: Callable[[AppSettings], None] = save_settings,
        pack_path: Path | None = None,
        backups_root: Path | None = None,
        load_in_background: bool = True,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._save = save
        self._backups_root = backups_root
        self._dispatcher = Dispatcher()
        self._opened: OpenedList | None = None
        self.context: ListContext | None = None
        self.taxa: dict[str, EntryTaxa] = {}
        self.pack: DataPack | None = None
        self._pack_error = ""
        try:
            self.pack = DataPack(find_pack(pack_path))
        except (PackError, OSError) as error:
            self._pack_error = str(error)
        if self.pack is not None:
            self._predefined = self.pack.predefined_locations()
            self._base_ids = self.pack.base_taxon_ids()
            if load_in_background:
                pack_file = self.pack.path
                run_in_thread("load-taxa", lambda: self._load_taxa(pack_file))
        self._load_on_open = not load_in_background

    # ------------------------------------------------------------ taxa

    @staticmethod
    def _build_taxa(pack_file: Path) -> dict[str, EntryTaxa]:
        with DataPack(pack_file) as pack:  # own connection: this may run on a worker thread
            base, avilist = pack.load_base_and_avilist()
        return {"avilist": EntryTaxa(base, avilist), "clements": EntryTaxa(base, base)}

    def _load_taxa(self, pack_file: Path) -> None:
        loaded = self._build_taxa(pack_file)
        self._dispatcher.post(lambda: self._taxa_loaded(loaded))

    def _taxa_loaded(self, loaded: dict[str, EntryTaxa]) -> None:
        self.taxa = loaded
        self.taxaReadyChanged.emit()

    @Property(bool, notify=taxaReadyChanged)
    def taxaReady(self) -> bool:
        return bool(self.taxa)

    @property
    def entry_taxa(self) -> EntryTaxa | None:
        return self.taxa.get(self._settings.display_taxonomy)

    @Property(str, notify=taxaReadyChanged)
    def displayTaxonomyName(self) -> str:
        taxa = self.entry_taxa
        return taxa.display.name if taxa else ""

    # ------------------------------------------------------------ the list

    @property
    def database(self):  # type: ignore[no-untyped-def]
        return None if self._opened is None else self._opened.database

    @Property(bool, notify=listChanged)
    def hasList(self) -> bool:
        return self._opened is not None

    @Property(str, notify=listChanged)
    def listName(self) -> str:
        return "" if self._opened is None else self._opened.database.path.stem

    @Property(bool, notify=listChanged)
    def readOnly(self) -> bool:
        return self._opened is not None and self._opened.read_only

    @Property("QStringList", notify=listChanged)
    def problems(self) -> list[str]:
        return [] if self._opened is None else list(self._opened.problems)

    @Property(str, notify=listChanged)
    def packProblem(self) -> str:
        return self._pack_error

    @Property(int, notify=dataChanged)
    def sightingCount(self) -> int:
        if self._opened is None:
            return 0
        row = self._opened.database.connection.execute("SELECT count(*) FROM sightings").fetchone()
        return int(row[0])

    @Property(str, notify=dataChanged)
    def undoLabel(self) -> str:
        database = self.database
        return "" if database is None or database.read_only else database.undo_label() or ""

    @Property(str, notify=dataChanged)
    def redoLabel(self) -> str:
        database = self.database
        return "" if database is None or database.read_only else database.redo_label() or ""

    def open_path(self, path: Path) -> bool:
        if self.pack is None:
            self.message.emit(self._pack_error or "No data pack")
            return False
        self.close_list()
        try:
            self._opened = open_list(
                path, self._base_ids, self._backups_root or paths.backups_dir()
            )
        except Exception as error:
            log.exception("could not open %s", path)
            self.message.emit(f"Could not open {path.name}: {error}")
            return False
        if self._load_on_open and not self.taxa:
            self._taxa_loaded(self._build_taxa(self.pack.path))
        self.context = ListContext(self._opened.database.connection, self.pack, self._predefined)
        self._settings = replace(self._settings, last_list=str(path))
        self._save(self._settings)
        self.listChanged.emit()
        self.dataChanged.emit()
        if self._opened.problems:
            self.message.emit(f"{path.stem} opened read-only: it failed its checks")
        return True

    def close_list(self) -> None:
        if self._opened is not None:
            self._opened.database.close()
            self._opened = None
            self.context = None
            self.listChanged.emit()

    def reopen_last(self) -> None:
        last = self._settings.last_list
        if last and Path(last).is_file():
            self.open_path(Path(last))

    @Slot(QUrl)
    def openList(self, url: QUrl) -> None:
        self.open_path(Path(url.toLocalFile()))

    @Slot(QUrl)
    def importScythebill(self, url: QUrl) -> None:
        source = Path(url.toLocalFile())
        if self.pack is None:
            self.message.emit(self._pack_error or "No data pack")
            return
        target = paths.lists_dir() / (source.stem + LIST_SUFFIX)
        number = 2
        while target.exists():
            target = paths.lists_dir() / f"{source.stem} {number}{LIST_SUFFIX}"
            number += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = import_bsxm(
                source, target, self.pack.base_taxonomy_id, self._base_ids, self._predefined
            )
        except Exception as error:
            self.message.emit(f"Could not import {source.name}: {error}")
            return
        self.open_path(target)
        self.message.emit(f"Imported {result.sightings} sightings from {source.name}")

    # ------------------------------------------------------------ changes

    def changed(self) -> None:
        """Call after saving: refreshes the list context and every view."""
        if self._opened is not None and self.context is not None:
            self.context.reload(self._opened.database.connection)
        self.dataChanged.emit()

    @Slot()
    def undo(self) -> None:
        database = self.database
        if database is None or database.read_only:
            return
        label = database.undo()
        self.changed()
        self.message.emit(f"Undid: {label}" if label else "Nothing to undo")

    @Slot()
    def redo(self) -> None:
        database = self.database
        if database is None or database.read_only:
            return
        label = database.redo()
        self.changed()
        self.message.emit(f"Redid: {label}" if label else "Nothing to redo")

    # ------------------------------------------------------------ drafts

    def save_draft(self, session_json: str) -> None:
        if self.database is not None:
            drafts.save_draft(self.database, session_json)

    def load_draft(self) -> str | None:
        return None if self.database is None else drafts.load_draft(self.database)

    def clear_draft(self) -> None:
        if self.database is not None:
            drafts.clear_draft(self.database)

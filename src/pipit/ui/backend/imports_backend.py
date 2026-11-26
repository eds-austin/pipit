"""Importing an eBird file (My Data, the Record Format or a life list) into the open list,
as a sequence of questions and a review (QML: ImportDialog).

One worker thread runs the whole import (``pipit.imports.session.ImportRun``) on its own
read-only connection and the data pack, and waits for the answers to Scythebill's
questions in turn: only the new dates?, which species are the names it didn't know?, what
about sightings already in the list?, and finally the review: store it or not. Storing
makes a backup snapshot first, then writes the import as one undo step.
"""

from __future__ import annotations

import csv
import logging
import queue
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from pipit.datapack.pack import DataPack
from pipit.domain.locations import is_built_in
from pipit.domain.partial_date import format_partial_date
from pipit.domain.report import Location
from pipit.imports.commit import ImportStoreError, store
from pipit.imports.formats import open_source
from pipit.imports.my_data import MissingHeaderError
from pipit.imports.scythebill_csv import UnsupportedFileError
from pipit.imports.session import ImportOutcome, ImportRefusedError, ImportRun
from pipit.imports.taxa import TbdTaxon
from pipit.query.checklists import Checklists
from pipit.query.model import load_query_list
from pipit.storage import backup
from pipit.storage.database import ListDatabase
from pipit.storage.repository import load_report
from pipit.taxa.model import Taxonomy
from pipit.taxa.sighting_taxon import SightingTaxon
from pipit.ui.backend.dispatch import Dispatcher, run_in_thread
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)
_CANCEL = "cancel"
_SHOWN_PLACES = 200


@dataclass(frozen=True)
class _Job:
    source: Path
    list_path: Path
    pack_path: Path
    display: Taxonomy
    backups_root: Path


class ImportsBackend(QObject):
    changed = Signal()
    matchesChanged = Signal()

    def __init__(self, app: Any) -> None:
        super().__init__()
        self._app = app
        self._dispatcher = Dispatcher()
        self._answers: queue.Queue[Any] = queue.Queue()
        self._stage = "idle"
        self._file_name = ""
        self._format_name = ""
        self._error = ""
        self._details: dict[str, Any] = {}
        self._names: list[tuple[str, TbdTaxon]] = []
        self._chosen: dict[str, SightingTaxon] = {}
        self._name_index = 0
        self._run: ImportRun | None = None
        self._matches: list[Any] = []
        self.matches_model = DictListModel(["name", "scientific"])
        self._failed_rows: list[list[str]] = []
        self._header: list[str] | None = None
        self._source: Path | None = None

    # ------------------------------------------------------------ state for QML

    @Property(str, notify=changed)
    def stage(self) -> str:
        """idle, reading, dates, allDates, names, duplicates, review, storing, failed, done."""
        return self._stage

    @Property(str, notify=changed)
    def fileName(self) -> str:
        return self._file_name

    @Property(str, notify=changed)
    def formatName(self) -> str:
        """The file's kind ("eBird My Data", "Scythebill CSV", ...), once it's read."""
        return self._format_name

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Property("QVariantMap", notify=changed)
    def details(self) -> dict[str, Any]:
        return self._details

    @Property(int, notify=changed)
    def nameIndex(self) -> int:
        return self._name_index

    @Property(int, notify=changed)
    def nameCount(self) -> int:
        return len(self._names)

    @Property("QVariantMap", notify=changed)
    def currentName(self) -> dict[str, Any]:
        if not 0 <= self._name_index < len(self._names):
            return {}
        key, name = self._names[self._name_index]
        chosen = self._chosen.get(key)
        return {
            "common": name.common_name or "", "scientific": name.scientific_name or "",
            "subspecies": name.subspecies or "", "places": self._place_names(name),
            "chosen": self._chosen_label(chosen) if chosen is not None else "",
        }  # fmt: skip

    @Property(QObject, notify=matchesChanged)
    def matches(self) -> DictListModel:
        return self.matches_model

    # ------------------------------------------------------------ starting

    @Slot(QUrl)
    def start(self, url: QUrl) -> None:
        database = self._app.database
        taxa = self._app.entry_taxa
        pack = self._app.pack
        if database is None or taxa is None or pack is None or self._stage not in (
                "idle", "done", "failed"):  # fmt: skip
            return
        if database.read_only:
            self._app.message.emit(f"{database.path.name} is open read-only")
            return
        source = Path(url.toLocalFile())
        job = _Job(source, Path(database.path), pack.path, taxa.display, self._app.backups_root)
        self._answers = queue.Queue()
        self._source = source
        self._file_name = source.name
        self._error = ""
        self._format_name = ""
        self._details = {}
        self._names = []
        self._chosen = {}
        self._name_index = 0
        self._failed_rows = []
        self._set_stage("reading")
        run_in_thread("import", lambda: self._work(job))

    def _set_stage(self, stage: str, **details: Any) -> None:
        self._stage = stage
        if details:
            self._details = details
        self.changed.emit()

    def _post(self, stage: str, **details: Any) -> None:
        self._dispatcher.post(lambda: self._set_stage(stage, **details))

    def _wait(self) -> Any:
        return self._answers.get()

    # ------------------------------------------------------------ the worker

    def _work(self, job: _Job) -> None:
        try:
            self._import(job)
        except (ImportRefusedError, MissingHeaderError, UnsupportedFileError, ImportStoreError,
                OSError, ValueError,
                sqlite3.Error) as error:  # fmt: skip
            log.warning("import of %s failed: %s", job.source.name, error)
            message = str(error)
            self._dispatcher.post(lambda: self._fail(message))

    def _fail(self, message: str) -> None:
        self._error = message
        self._run = None
        self._set_stage("failed")

    def _import(self, job: _Job) -> None:
        connection = sqlite3.connect(f"file:{job.list_path}?mode=ro", uri=True)
        try:
            with DataPack(job.pack_path) as pack:
                report = load_report(connection)
                before = {location.id for location in report.iter_locations()}
                if report.users:
                    raise ImportRefusedError(
                        "This list has observers; Pipit can't yet ask which of them saw "
                        "imported sightings. Import the file in Scythebill instead.")  # fmt: skip
                source = open_source(job.source)
                name = source.format_name
                self._dispatcher.post(lambda: self._set_format(name))
                checklists = Checklists(pack, connection, load_query_list(connection))
                run = ImportRun(report, source, taxonomy=job.display, pack=pack,
                                checklists=checklists)  # fmt: skip
                self._run = run
                self._header = source.header
                run.check()
                if source.mass_export and self._ask_dates(run) == _CANCEL:
                    return self._cancelled()
                self._post("reading")
                names = run.read_places_and_taxa()
                if names:
                    self._dispatcher.post(lambda: self._ask_names(list(names.items())))
                    chosen = self._wait()
                    if chosen == _CANCEL:
                        return self._cancelled()
                    run.resolve(chosen)
                duplicates = run.read_sightings()
                choice = "importAll"
                if run.asks_about_duplicates(duplicates):
                    self._post("duplicates", duplicates=duplicates, total=len(run.imports),
                               all=duplicates == len(run.imports))  # fmt: skip
                    choice = self._wait()
                    if choice == _CANCEL:
                        return self._cancelled()
                outcome = run.finish(choice)
                self._failed_rows = list(run.counts.failed_rows)
                self._post("review", **self._review(run, outcome, before))
                if self._wait() != "store":
                    return self._cancelled()
                self._post("storing")
                with ListDatabase.open(job.list_path) as database:
                    backup.snapshot(database.connection, job.list_path, job.backups_root,
                                    "import")  # fmt: skip
                    store(database, run, outcome, f"Import {job.source.name}")
                added = len(outcome.added)
                self._dispatcher.post(lambda: self._stored(added))
        finally:
            connection.close()
        return None

    def _ask_dates(self, run: ImportRun) -> str | None:
        """A mass export: only the dates new to the list? (where the format can narrow it),
        or, if the list has every date, import anyway?"""
        dates = run.dates()
        if run.source.filters_dates and 0 < len(dates.new) < dates.in_file:
            self._post("dates", new=len(dates.new), inFile=dates.in_file,
                       first=format_partial_date(dates.new[0]),
                       last=format_partial_date(dates.new[-1]))  # fmt: skip
            answer = self._wait()
            if answer == _CANCEL:
                return _CANCEL
            if answer:
                run.only_dates(dates.new)
        elif not dates.new:
            self._post("allDates", inFile=dates.in_file)
            if self._wait() == _CANCEL:
                return _CANCEL
        return None

    def _set_format(self, name: str) -> None:
        self._format_name = name
        self.changed.emit()

    def _cancelled(self) -> None:
        self._dispatcher.post(lambda: self._set_stage("idle"))

    def _stored(self, added: int) -> None:
        self._run = None
        self._set_stage("done")
        self._app.changed()
        self._app.message.emit(f"Imported {added} sightings from {self._file_name}")

    def _review(self, run: ImportRun, outcome: ImportOutcome,
                before: set[str]) -> dict[str, Any]:  # fmt: skip
        new_places = [location for location in run.places.walk() if location.id not in before]
        updated = [location for location in run.place_builder.changed if location.id in before]
        counts = run.counts
        return {
            "added": len(outcome.added), "removed": len(outcome.removed),
            "newPlaces": len(new_places),
            "places": [_path(location) for location in new_places
                       if not is_built_in(location)][:_SHOWN_PLACES],
            "updatedPlaces": len(updated),
            "visitsAdded": outcome.visits_added, "visitsReplaced": outcome.visits_replaced,
            "failed": counts.failed, "spuhsDropped": counts.spuhs_dropped,
            "merged": counts.merged, "spToResolve": len(outcome.sp_to_resolve),
        }  # fmt: skip

    # ------------------------------------------------------------ answers

    @Slot(bool)
    def answerDates(self, only_new: bool) -> None:
        if self._stage == "dates":
            self._set_stage("reading")
            self._answers.put(only_new)

    @Slot()
    def importAnyway(self) -> None:
        if self._stage == "allDates":
            self._set_stage("reading")
            self._answers.put(True)

    @Slot(str)
    def answerDuplicates(self, choice: str) -> None:
        if self._stage == "duplicates" and choice in ("importAll", "drop", "overwrite"):
            self._set_stage("reading")
            self._answers.put(choice)

    @Slot()
    def confirm(self) -> None:
        if self._stage == "review":
            self._answers.put("store")

    @Slot()
    def cancel(self) -> None:
        if self._stage in ("dates", "allDates", "names", "duplicates", "review"):
            self._answers.put(_CANCEL)
            self._set_stage("idle")
        elif self._stage in ("failed", "done"):
            self._set_stage("idle")

    # ------------------------------------------------------------ names

    def _ask_names(self, names: list[tuple[str, TbdTaxon]]) -> None:
        self._names = names
        self._chosen = {}
        self._name_index = 0
        self._set_stage("names", count=len(names))

    @Slot(str)
    def searchSpecies(self, text: str) -> None:
        taxa = self._app.entry_taxa
        self._matches = [] if taxa is None or not text.strip() else taxa.search(text, limit=20)
        self.matches_model.replace_all([
            {"name": match.common_name, "scientific": match.scientific_name}
            for match in self._matches
        ])  # fmt: skip
        self.matchesChanged.emit()

    @Slot(int)
    def pickMatch(self, index: int) -> None:
        """The species searched for is what the current name means; on to the next."""
        if self._run is None or not 0 <= index < len(self._matches):
            return
        key, name = self._names[self._name_index]
        try:
            self._chosen[key] = self._run.chosen_taxon(self._matches[index].taxon_id, name)
        except (KeyError, ValueError) as error:
            self._app.message.emit(str(error))
            return
        self.searchSpecies("")
        self._next_name()

    @Slot()
    def leaveOut(self) -> None:
        """Leave the current name's sightings out of the import."""
        if 0 <= self._name_index < len(self._names):
            self._chosen.pop(self._names[self._name_index][0], None)
            self._next_name()

    @Slot()
    def previousName(self) -> None:
        if self._stage == "names" and self._name_index > 0:
            self._name_index -= 1
            self.changed.emit()

    def _next_name(self) -> None:
        self._name_index += 1
        if self._name_index >= len(self._names):
            self._set_stage("reading")
            self._answers.put(dict(self._chosen))
            return
        self.changed.emit()

    # ------------------------------------------------------------ rows left out

    @Slot(result=str)
    def saveFailedRows(self) -> str:
        """``writeFailedLines``: the rows not imported, with the header, next to the file
        as "<name>-failed.csv" (or -1-failed, -2-failed... if taken). Returns the path."""
        if self._source is None or not self._failed_rows:
            return ""
        stem = self._source.stem
        for index in range(50):
            suffix = "-failed.csv" if index == 0 else f"-{index}-failed.csv"
            target = self._source.with_name(stem + suffix)
            if not target.exists():
                break
        else:
            return ""
        with target.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            if self._header is not None:  # Record Format files have none
                writer.writerow(self._header)
            writer.writerows(self._failed_rows)
        self._app.message.emit(f"Saved the rows not imported as {target.name}")
        return str(target)

    # ------------------------------------------------------------ helpers

    def _place_names(self, name: TbdTaxon) -> str:
        run = self._run
        if run is None:
            return ""
        shown = [_path(run.places.by_id[location_id]) for location_id in name.location_ids
                 if location_id in run.places.by_id][:3]  # fmt: skip
        more = len(name.location_ids) - len(shown)
        return "; ".join(shown) + (f" and {more} more" if more > 0 else "")

    def _chosen_label(self, taxon: SightingTaxon) -> str:
        run = self._run
        if run is None:
            return ""
        found = run.base.get(taxon.ids[0])
        return (found.common_name or found.name) if found is not None else taxon.ids[0]


def _path(location: Location) -> str:
    """A place and what it's in, up to its country: "Madrona Marsh, Los Angeles, California"."""
    names = []
    current: Location | None = location
    while current is not None and current.type != "region":
        names.append(current.name)
        if current.type == "country":
            break
        current = current.parent
    return ", ".join(names)

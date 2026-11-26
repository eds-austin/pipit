"""The Special screen's family report: the Reports screen's query, counted by order, family
or genus against the checklist of the query's places (Scythebill's ``FamilyReportPanel``)."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from pipit.output.names import PlaceNames
from pipit.output.print_html import list_place_names
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext, parse_query
from pipit.query.fields_place_time import UnsupportedQueryError
from pipit.query.fields_simple import QueryJsonError
from pipit.query.synthetic import REGION_NAMES
from pipit.special.family import FamilyReport, FamilyTotals, GroupTotal, family_report
from pipit.taxa.model import TaxonType
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel
from pipit.ui.backend.reports_backend import ReportsBackend

log = logging.getLogger(__name__)

RUN_DELAY_MS = 150
GROUP_BY = [["ORDER", "Order"], ["FAMILY", "Family"], ["GENUS", "Genus"]]
SORTS = [["TAXONOMIC", "Taxonomic order"], ["SPECIES_SEEN", "Species seen"],
         ["FRACTION_SEEN", "Fraction seen"], ["SPECIES_UNSEEN", "Species unseen"],
         ["TOTAL_SPECIES", "Total species"]]  # fmt: skip
_GROUPS_OF = {"ORDER": "Orders", "FAMILY": "Families", "GENUS": "Genera"}


def join_names(names: list[str]) -> str:
    """``Messages.join``: "A", "A and B", "A, B, and C"."""
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _count(number: int) -> str:
    return f"{number:,}"


class SpecialBackend(QObject):
    familyChanged = Signal()
    optionsChanged = Signal()
    selectionChanged = Signal()

    def __init__(self, app: AppController, reports: ReportsBackend) -> None:
        super().__init__()
        self._app = app
        self._reports = reports
        self._active = False
        self._stale = True
        self._group_by = "FAMILY"
        self._sort = "TAXONOMIC"
        self._descending = True
        self._report: FamilyReport | None = None
        self._totals: FamilyTotals | None = None
        self._shown: list[GroupTotal] = []
        self._checklist_name = ""
        self._error = ""
        self._selected = -1
        self.groups_model = DictListModel(["groupId", "name", "scientific", "seen", "total",
                                           "percent", "fraction", "counts"])  # fmt: skip
        self.species_model = DictListModel(["name", "scientific", "seen"])
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RUN_DELAY_MS)
        self._timer.timeout.connect(self.run)
        reports.queryChanged.connect(self._invalidate)
        app.listChanged.connect(self._invalidate)
        app.dataChanged.connect(self._invalidate)
        app.taxaReadyChanged.connect(self._invalidate)

    # ------------------------------------------------------------ running

    def _invalidate(self) -> None:
        self._stale = True
        if self._active:
            self._timer.start()

    @Slot(bool)
    def setActive(self, active: bool) -> None:
        """Counts only while the screen is shown (the query may change many times on Reports)."""
        self._active = active
        if active and self._stale:
            self._timer.start()

    def run_now(self) -> None:
        """Tests and screenshots: skip the settle delay."""
        self._timer.stop()
        self.run()

    @Slot()
    def run(self) -> None:
        self._stale = False
        self._report = None
        self._error = ""
        self._checklist_name = ""
        context = self._context()
        if context is not None:
            database = self._app.database
            pack = self._app.pack
            assert database is not None and pack is not None
            checklists = Checklists(pack, database.connection, context.query_list)
            try:
                query = parse_query(self._reports.query_json(), context.query_list,
                                    context.users)  # fmt: skip
                self._report = family_report(context, checklists, query)
            except (QueryJsonError, UnsupportedQueryError, ValueError, KeyError) as error:
                log.info("family report refused: %s", error)
                self._error = str(error)
            else:
                places = list_place_names(context.query_list, checklists)
                names = [self._place_name(places, xml_id) for xml_id in self._report.scope.places]
                self._checklist_name = join_names(names)
        self._recount()

    def _context(self) -> EngineContext | None:
        database = self._app.database
        taxa = self._app.entry_taxa
        if database is None or taxa is None or self._app.pack is None:
            return None
        query_list = self._reports._ensure_list()  # one list, loaded once
        if query_list is None:
            return None
        users = frozenset(u for (u,) in database.connection.execute("SELECT xml_id FROM users"))
        return EngineContext(query_list, taxa.display, TaxonType.SPECIES, users=users)

    @staticmethod
    def _place_name(places: PlaceNames, xml_id: str) -> str:
        if xml_id in REGION_NAMES:
            return REGION_NAMES[xml_id]
        if xml_id in places.places:
            return places.disambiguated_name(xml_id)
        return xml_id

    def _recount(self) -> None:
        self._totals = None if self._report is None else self._report.totals(self._group_by)
        self._resort()

    def _resort(self) -> None:
        self._shown = (
            [] if self._totals is None else self._totals.sorted(self._sort, self._descending)
        )
        self.groups_model.replace_all([self._group_row(group) for group in self._shown])
        self._selected = -1
        self.species_model.replace_all([])
        self.familyChanged.emit()
        self.selectionChanged.emit()

    @staticmethod
    def _group_row(group: GroupTotal) -> dict[str, Any]:
        common = group.common_name
        return {
            "groupId": group.group.id,
            "name": common or group.group.name,
            "scientific": group.group.name if common else "",
            "seen": group.seen,
            "total": group.total,
            "percent": group.percent_text,
            "fraction": group.fraction,
            "counts": f"{_count(group.seen)}/{_count(group.total)}",
        }

    # ------------------------------------------------------------ the summary

    @Property(str, notify=familyChanged)
    def error(self) -> str:
        return self._error

    @Property(bool, notify=familyChanged)
    def ready(self) -> bool:
        return self._totals is not None

    @Property(str, notify=familyChanged)
    def checklistName(self) -> str:
        """Empty for the whole world."""
        return self._checklist_name

    @Property(str, notify=familyChanged)
    def groupsSummary(self) -> str:
        if self._totals is None:
            return ""
        return (f"{_GROUPS_OF[self._group_by]}: {_count(self._totals.seen_groups)} of "
                f"{_count(len(self._totals.groups))}")  # fmt: skip

    @Property(str, notify=familyChanged)
    def speciesSummary(self) -> str:
        if self._totals is None:
            return ""
        return (f"Species: {_count(self._totals.seen_species)} of "
                f"{_count(self._totals.total_species)}")  # fmt: skip

    @Property(int, notify=familyChanged)
    def seenSpecies(self) -> int:
        return 0 if self._totals is None else self._totals.seen_species

    @Property(int, notify=familyChanged)
    def totalSpecies(self) -> int:
        return 0 if self._totals is None else self._totals.total_species

    @Property(int, notify=familyChanged)
    def seenGroups(self) -> int:
        return 0 if self._totals is None else self._totals.seen_groups

    @Property(int, notify=familyChanged)
    def totalGroups(self) -> int:
        return 0 if self._totals is None else len(self._totals.groups)

    @Property(str, notify=familyChanged)
    def groupsLabel(self) -> str:
        """ "Orders", "Families" or "Genera"."""
        return _GROUPS_OF[self._group_by]

    @Property(float, notify=familyChanged)
    def speciesFraction(self) -> float:
        if self._totals is None or self._totals.total_species == 0:
            return 0.0
        return self._totals.seen_species / self._totals.total_species

    @Property(QObject, constant=True)
    def groups(self) -> DictListModel:
        return self.groups_model

    # ------------------------------------------------------------ options

    @Property("QVariantList", constant=True)
    def groupByChoices(self) -> list[list[str]]:
        return GROUP_BY

    @Property("QVariantList", constant=True)
    def sortChoices(self) -> list[list[str]]:
        return SORTS

    @Property(str, notify=optionsChanged)
    def groupBy(self) -> str:
        return self._group_by

    @Slot(str)
    def setGroupBy(self, group_by: str) -> None:
        if group_by == self._group_by or group_by not in _GROUPS_OF:
            return
        self._group_by = group_by
        self.optionsChanged.emit()
        self._recount()

    @Property(str, notify=optionsChanged)
    def sort(self) -> str:
        return self._sort

    @Slot(str)
    def setSort(self, sort: str) -> None:
        if sort == self._sort:
            return
        self._sort = sort
        self.optionsChanged.emit()
        self._resort()

    @Property(bool, notify=optionsChanged)
    def descending(self) -> bool:
        return self._descending

    @Slot(bool)
    def setDescending(self, descending: bool) -> None:
        if descending == self._descending:
            return
        self._descending = descending
        self.optionsChanged.emit()
        self._resort()

    # ------------------------------------------------------------ one group's species

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:
        return self._selected

    @Property(str, notify=selectionChanged)
    def selectedName(self) -> str:
        if not 0 <= self._selected < len(self._shown):
            return ""
        group = self._shown[self._selected]
        return group.common_name or group.group.name

    @Property(QObject, constant=True)
    def species(self) -> DictListModel:
        return self.species_model

    @Slot(int)
    def select(self, index: int) -> None:
        """The group's possible species in taxonomic order, seen ones marked (as Scythebill's
        browser lists them, unseen ones grayed)."""
        if not 0 <= index < len(self._shown) or self._report is None:
            index = -1
        self._selected = index
        rows: list[dict[str, Any]] = []
        report = self._report
        if index >= 0 and report is not None:
            for taxon, seen in report.group_species(self._shown[index].group):
                rows.append({"name": taxon.common_name or taxon.name,
                             "scientific": taxon.name, "seen": seen})  # fmt: skip
        self.species_model.replace_all(rows)
        self.selectionChanged.emit()

    @Slot(int, int)
    def selectStep(self, index: int, step: int) -> None:
        if not self._shown:
            return
        target = max(0, min(len(self._shown) - 1, index + step))
        self.select(target)

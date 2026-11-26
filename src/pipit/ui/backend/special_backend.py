"""The Special screen: the family report (the Reports screen's query counted by order, family
or genus against the checklist of the query's places, Scythebill's ``FamilyReportPanel``) and
the checklist status report (``ChecklistStatusReportPanel``)."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from pipit.browse.dates import display_date
from pipit.domain.partial_date import PartialDate, PartialField
from pipit.output.names import PlaceNames, resolved_common_name
from pipit.output.print_html import list_place_names
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext, parse_query
from pipit.query.fields_place_time import UnsupportedQueryError
from pipit.query.fields_simple import QueryJsonError
from pipit.query.model import QueryList
from pipit.query.synthetic import REGION_NAMES
from pipit.special.checklist_status import CHOICES, StatusPlace, checklist_status
from pipit.special.family import FamilyReport, FamilyTotals, GroupTotal, family_report
from pipit.special.splits_lumps import (
    SECTIONS,
    SplitsUnavailableError,
    describe,
    splits_report,
    versions_for,
)
from pipit.special.splits_lumps import totals as splits_totals
from pipit.special.timeline import SORTS as TIMELINE_SORTS
from pipit.special.timeline import Period, Timeline, decade_of, timeline
from pipit.special.year_comparison import SORTS as YEAR_SORTS
from pipit.special.year_comparison import (
    Half,
    SpeciesResult,
    YearComparison,
    YearResult,
    compare_years,
    sorted_species,
)
from pipit.taxa.model import Taxon, TaxonType, full_name
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType
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
REPORTS = ("family", "status", "splits", "years", "timeline")
#: Countries Scythebill names with their parent in this report (``CODES_WITH_MULTIPLE_REGIONS``).
_NAMED_WITH_PARENT = frozenset({"XX", "RU", "ID"})
#: Scythebill's ``Species`` class: species, groups and subspecies.
_BELOW_GENUS = (TaxonType.SPECIES, TaxonType.GROUP, TaxonType.SUBSPECIES)


def expected_range(species: Taxon) -> str | None:
    """``TaxonUtils.getRange``: the species' range, else its groups' and subspecies' joined
    with ";"."""
    if species.range is not None:
        return species.range
    ranges = [found for child in species.children
              if child.type in _BELOW_GENUS and (found := expected_range(child))]  # fmt: skip
    return ";".join(ranges) if ranges else None


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
    reportChanged = Signal()
    statusChanged = Signal()
    splitsChanged = Signal()
    yearsChanged = Signal()
    yearsSelectionChanged = Signal()
    timelineChanged = Signal()
    timelineSelectionChanged = Signal()

    def __init__(self, app: AppController, reports: ReportsBackend) -> None:
        super().__init__()
        self._app = app
        self._reports = reports
        self._active = False
        self._stale = {report: True for report in REPORTS}
        self._current_report = "family"
        self._checklists: tuple[QueryList, str, Checklists] | None = None
        self._status_choice = "NOT_FOUND"
        self._status_places: list[StatusPlace] = []
        self._status_custom = False
        self._splits_version = ""
        self._splits_versions: list[list[str]] = []
        self._splits_totals = ""
        self._splits_error = ""
        self.splits_model = DictListModel(["heading", "text"])
        self._years: YearComparison | None = None
        self._years_from: int | None = None
        self._years_to: int | None = None
        self._years_sort = "MOST_SIGHTINGS"
        self._years_filter = "ALL"
        self._years_selected: int | None = None
        self._years_rows: list[SpeciesResult] = []
        self._years_error = ""
        self.years_model = DictListModel(["name", "scientific", "buckets", "total"])
        self._timeline: Timeline | None = None
        self._timeline_error = ""
        self._timeline_mode = "YEARS"
        self._timeline_sort = "MOST_SPECIES"
        self._timeline_lifers_only = False
        self._timeline_shown: list[Period | None] = []  # None: a decade's heading
        self._timeline_selected = -1
        self._timeline_names: dict[str, str] = {}
        self.timeline_model = DictListModel(["heading", "label", "place", "count", "lifers",
                                             "fraction"])  # fmt: skip
        self.period_species_model = DictListModel(["name", "lifer"])
        self.status_model = DictListModel(["heading", "placeId", "name", "scientific", "range",
                                           "custom"])  # fmt: skip
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
        reports.queryChanged.connect(self._query_changed)
        app.listChanged.connect(self._data_changed)
        app.dataChanged.connect(self._data_changed)
        app.taxaReadyChanged.connect(self._data_changed)

    # ------------------------------------------------------------ running

    def _query_changed(self) -> None:
        self._stale["family"] = True
        self._stale["splits"] = True
        self._stale["years"] = True
        self._stale["timeline"] = True
        self._schedule()

    def _data_changed(self) -> None:
        self._checklists = None
        self._stale = dict.fromkeys(REPORTS, True)
        self._schedule()

    def _schedule(self) -> None:
        if self._active and self._stale[self._current_report]:
            self._timer.start()

    @Slot(bool)
    def setActive(self, active: bool) -> None:
        """Counts only while the screen is shown (the query may change many times on Reports)."""
        self._active = active
        self._schedule()

    @Property(str, notify=reportChanged)
    def report(self) -> str:
        return self._current_report

    @Slot(str)
    def setReport(self, report: str) -> None:
        if report == self._current_report or report not in REPORTS:
            return
        self._current_report = report
        self.reportChanged.emit()
        self._schedule()

    def _checklists_for(self, query_list: QueryList, taxonomy_id: str) -> Checklists | None:
        """One ``Checklists`` (whose loaded checklists are cached) until the list changes."""
        database = self._app.database
        pack = self._app.pack
        if database is None or pack is None:
            return None
        cached = self._checklists
        if cached is None or cached[0] is not query_list or cached[1] != taxonomy_id:
            checklists = Checklists(pack, database.connection, query_list)
            cached = self._checklists = (query_list, taxonomy_id, checklists)
        return cached[2]

    def run_now(self) -> None:
        """Tests and screenshots: skip the settle delay."""
        self._timer.stop()
        self.run()

    @Slot()
    def run(self) -> None:
        if self._current_report == "status":
            self._run_status()
        elif self._current_report == "splits":
            self._run_splits()
        elif self._current_report == "years":
            self._run_years()
        elif self._current_report == "timeline":
            self._run_timeline()
        else:
            self._run_family()

    def _run_family(self) -> None:
        self._stale["family"] = False
        self._report = None
        self._error = ""
        self._checklist_name = ""
        context = self._context()
        checklists = (
            None
            if context is None
            else self._checklists_for(context.query_list, context.taxonomy.id)
        )
        if context is not None and checklists is not None:
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

    # ------------------------------------------------------------ checklist status

    @Property("QVariantList", constant=True)
    def statusChoices(self) -> list[list[str]]:
        return [list(choice) for choice in CHOICES]

    @Property(str, notify=statusChanged)
    def statusChoice(self) -> str:
        return self._status_choice

    @Slot(str)
    def setStatusChoice(self, choice: str) -> None:
        if choice == self._status_choice or choice not in dict(CHOICES):
            return
        self._status_choice = choice
        self._stale["status"] = True
        self.statusChanged.emit()
        self._schedule()

    def _run_status(self) -> None:
        self._stale["status"] = False
        self._status_places = []
        context = self._context()
        checklists = (
            None
            if context is None
            else self._checklists_for(context.query_list, context.taxonomy.id)
        )
        rows: list[dict[str, Any]] = []
        if context is not None and checklists is not None:
            self._status_places = checklist_status(context.query_list, checklists,
                                                   context.taxonomy, self._status_choice,
                                                   context.resolve)  # fmt: skip
            names = list_place_names(context.query_list, checklists)
            for place in self._status_places:
                rows.append({"heading": True, "placeId": place.xml_id,
                             "name": self._status_place_name(names, place.xml_id),
                             "scientific": "", "range": "", "custom": place.custom})  # fmt: skip
                for species in place.species:
                    found = expected_range(species)
                    rows.append({"heading": False, "placeId": place.xml_id,
                                 "name": species.common_name or species.name,
                                 "scientific": full_name(species),
                                 "range": found or "", "custom": place.custom})  # fmt: skip
        self.status_model.replace_all(rows)
        self.statusChanged.emit()

    @staticmethod
    def _status_place_name(names: PlaceNames, xml_id: str) -> str:
        """Its name, with its parent's for countries split across regions (Russia, Indonesia)."""
        place = names.places.get(xml_id)
        if place is None:
            return xml_id
        name = names.name(place)
        parent = names.places.get(place.parent) if place.parent else None
        if place.code in _NAMED_WITH_PARENT and parent is not None:
            return f"{name} ({names.name(parent)})"
        return name

    @Property(str, notify=statusChanged)
    def statusSummary(self) -> str:
        label = dict(CHOICES)[self._status_choice]
        if not self._status_places:
            return f"No sightings with the status “{label}” on their place's checklist."
        species = sum(len(place.species) for place in self._status_places)
        places = len(self._status_places)
        return (
            f"{_count(species)} species at {_count(places)} {'places' if places != 1 else 'place'}"
        )

    @Property(str, notify=statusChanged)
    def statusNote(self) -> str:
        """Scythebill's warning for species not on the checklist."""
        if self._status_choice != "NOT_FOUND" or not self._status_places:
            return ""
        return "These may be mistakes in your data: the wrong place, or the wrong species."

    @Property(QObject, constant=True)
    def statusRows(self) -> DictListModel:
        return self.status_model

    @Slot(int, result=bool)
    def statusIsHeading(self, index: int) -> bool:
        rows = self.status_model.rows()
        return not 0 <= index < len(rows) or bool(rows[index]["heading"])

    @Slot(int, result=str)
    def statusPlace(self, index: int) -> str:
        """The place a row is listed under (its ID)."""
        rows = self.status_model.rows()
        return str(rows[index]["placeId"]) if 0 <= index < len(rows) else ""

    # ------------------------------------------------------------ splits and lumps

    @Property("QVariantList", notify=splitsChanged)
    def splitsVersions(self) -> list[list[str]]:
        """(version, label) the display taxonomy offers."""
        return self._splits_versions

    @Property(str, notify=splitsChanged)
    def splitsVersion(self) -> str:
        return self._splits_version

    @Slot(str)
    def setSplitsVersion(self, version: str) -> None:
        if version == self._splits_version:
            return
        self._splits_version = version
        self._stale["splits"] = True
        self.splitsChanged.emit()
        self._schedule()

    @Property(str, notify=splitsChanged)
    def splitsTotals(self) -> str:
        return self._splits_totals

    @Property(str, notify=splitsChanged)
    def splitsError(self) -> str:
        return self._splits_error

    @Property(QObject, constant=True)
    def splitsRows(self) -> DictListModel:
        return self.splits_model

    def _run_splits(self) -> None:
        self._stale["splits"] = False
        self._splits_totals = ""
        self._splits_error = ""
        rows: list[dict[str, Any]] = []
        context = self._context()
        pack = self._app.pack
        if context is not None and pack is not None:
            offered = [list(version) for version in versions_for(context.taxonomy)]
            if [v[0] for v in offered] != [v[0] for v in self._splits_versions]:
                self._splits_versions = offered
                self._splits_version = offered[0][0]
            rows_of_version = pack.split_report_rows(self._splits_version)
            try:
                if not rows_of_version:
                    self._splits_error = ("This data pack has no splits-and-lumps tables: "
                                          "rebuild it with pipit-build-pack.")  # fmt: skip
                    raise SplitsUnavailableError("no table")
                query = parse_query(self._reports.query_json(), context.query_list,
                                    context.users)  # fmt: skip
                found = splits_report(context, query, rows_of_version)
            except SplitsUnavailableError as error:
                log.info("splits and lumps unavailable: %s", error)
                self._splits_error = self._splits_error or (
                    "Splits and lumps aren't available for this taxonomy version."
                )
            except (QueryJsonError, UnsupportedQueryError, ValueError, KeyError) as error:
                log.info("splits and lumps refused: %s", error)
                self._splits_error = str(error)
            else:
                if found.is_empty():
                    self._splits_totals = "No splits or lumps found."
                else:
                    self._splits_totals = splits_totals(found)
                for title, attribute in SECTIONS:
                    results = getattr(found, attribute)
                    if results:
                        rows.append({"heading": True, "text": title})
                        rows.extend({"heading": False, "text": describe(result, context.taxonomy)}
                                    for result in results)  # fmt: skip
        self.splits_model.replace_all(rows)
        self.splitsChanged.emit()

    # ------------------------------------------------------------ year comparison

    def _run_years(self) -> None:
        self._stale["years"] = False
        self._years = None
        self._years_error = ""
        context = self._context()
        if context is not None:
            try:
                query = parse_query(self._reports.query_json(), context.query_list,
                                    context.users)  # fmt: skip
                self._years = compare_years(context, query, from_year=self._years_from,
                                            to_year=self._years_to)  # fmt: skip
            except (QueryJsonError, UnsupportedQueryError, ValueError, KeyError) as error:
                log.info("year comparison refused: %s", error)
                self._years_error = str(error)
        years = self._years
        if years is not None and self._years_selected not in years.years:
            self._years_selected = None
            self._years_filter = "ALL"
        self._show_years()
        self.yearsChanged.emit()

    def _show_years(self) -> None:
        """The grid's rows: filtered by the chosen year, then sorted."""
        years = self._years
        rows: list[SpeciesResult] = []
        if years is not None:
            chosen = self._years_selected
            for species in sorted_species(years, self._years_sort):
                if self._years_filter == "NEW" and species.first_year_ever != chosen:
                    continue
                if self._years_filter == "MISSING" and (
                        chosen is None or species.year(Half.WHOLE_YEAR, chosen) is not None
                        or species.resolved.type in (SightingTaxonType.SP,
                                                     SightingTaxonType.HYBRID)):  # fmt: skip
                    continue
                rows.append(species)
        self._years_rows = rows
        span = [] if years is None else list(years.years)
        self.years_model.replace_all([
            {"name": _resolved_name(species.resolved), "scientific": "",
             "buckets": [bucket(species.year(Half.WHOLE_YEAR, year)) for year in span],
             "total": species.total_sightings}
            for species in rows
        ])  # fmt: skip
        self.yearsSelectionChanged.emit()

    @Property(str, notify=yearsChanged)
    def yearsError(self) -> str:
        return self._years_error

    @Property("QVariantList", notify=yearsChanged)
    def yearsSpan(self) -> list[int]:
        return [] if self._years is None else list(self._years.years)

    @Property("QVariantList", notify=yearsChanged)
    def speciesPerYear(self) -> list[int]:
        years = self._years
        if years is None:
            return []
        return [years.species_count(Half.WHOLE_YEAR, year) for year in years.years]

    @Property(str, notify=yearsChanged)
    def yearsSummary(self) -> str:
        years = self._years
        if years is None:
            return ""
        if not years.species:
            return "No sightings with a year."
        count = years.species_count_all_years(Half.WHOLE_YEAR)
        span = (str(years.first_year) if years.first_year == years.last_year
                else f"{years.first_year}\u2013{years.last_year}")  # fmt: skip
        return f"{count:,} species · {span}"

    @Property("QVariantList", constant=True)
    def yearsSorts(self) -> list[list[str]]:
        return [list(sort) for sort in YEAR_SORTS]

    @Property(str, notify=yearsSelectionChanged)
    def yearsSort(self) -> str:
        return self._years_sort

    @Slot(str)
    def setYearsSort(self, sort: str) -> None:
        if sort != self._years_sort:
            self._years_sort = sort
            self._show_years()

    @Property(str, notify=yearsSelectionChanged)
    def yearsFilter(self) -> str:
        return self._years_filter

    @Slot(str)
    def setYearsFilter(self, choice: str) -> None:
        if choice != self._years_filter and (choice == "ALL" or self._years_selected is not None):
            self._years_filter = choice
            self._show_years()

    @Property(int, notify=yearsSelectionChanged)
    def selectedYear(self) -> int:
        return 0 if self._years_selected is None else self._years_selected

    @Slot(int)
    def selectYear(self, year: int) -> None:
        """Choose a year (0: none) for the "new" and "missing" filters."""
        chosen = year if self._years is not None and year in self._years.years else None
        if chosen == self._years_selected:
            return
        self._years_selected = chosen
        if chosen is None:
            self._years_filter = "ALL"
        self._show_years()

    @Property(int, notify=yearsSelectionChanged)
    def yearsRowCount(self) -> int:
        return len(self._years_rows)

    @Property(QObject, constant=True)
    def yearsRows(self) -> DictListModel:
        return self.years_model

    @Slot(int, int, result=str)
    def yearsCellText(self, row: int, column: int) -> str:
        """``yearTooltip`` for a cell: "2024: 12 sightings, 28 Apr to 30 Sep"."""
        years = self._years
        if years is None or not 0 <= row < len(self._years_rows):
            return ""
        span = list(years.years)
        if not 0 <= column < len(span):
            return ""
        species = self._years_rows[row]
        year = span[column]
        name = _resolved_name(species.resolved)
        result = species.year(Half.WHOLE_YEAR, year)
        if result is None:
            return f"{name}: not seen in {year}"
        sightings = "1 sighting" if result.frequency == 1 else f"{result.frequency:,} sightings"
        if result.earliest is None or result.latest is None:
            return f"{name}: {year}: {sightings}"
        earliest = _month_day_text(result.earliest)
        latest = _month_day_text(result.latest)
        dates = earliest if earliest == latest else f"{earliest}\u2013{latest}"
        return f"{name}: {year}: {sightings}, {dates}"

    @Property(str, notify=yearsChanged)
    def yearsFrom(self) -> str:
        return "" if self._years_from is None else str(self._years_from)

    @Property(str, notify=yearsChanged)
    def yearsTo(self) -> str:
        return "" if self._years_to is None else str(self._years_to)

    @Slot(str, str, result=bool)
    def setYearRange(self, from_text: str, to_text: str) -> bool:
        """The years to compare (blank: no limit); refused when "from" is after "to"."""
        try:
            from_year = int(from_text) if from_text.strip() else None
            to_year = int(to_text) if to_text.strip() else None
        except ValueError:
            return False
        if from_year is not None and to_year is not None and from_year > to_year:
            return False
        if (from_year, to_year) != (self._years_from, self._years_to):
            self._years_from = from_year
            self._years_to = to_year
            self._stale["years"] = True
            self._schedule()
        return True

    # ------------------------------------------------------------ timeline

    def _run_timeline(self) -> None:
        self._stale["timeline"] = False
        self._timeline = None
        self._timeline_error = ""
        context = self._context()
        if context is not None:
            try:
                query = parse_query(self._reports.query_json(), context.query_list,
                                    context.users)  # fmt: skip
                self._timeline = timeline(context, query)
            except (QueryJsonError, UnsupportedQueryError, ValueError, KeyError) as error:
                log.info("timeline refused: %s", error)
                self._timeline_error = str(error)
            else:
                taxonomy = context.taxonomy
                self._timeline_names = {}
                for lifer in self._timeline.lifers:
                    taxon = taxonomy.get(lifer.species_id)
                    if taxon is not None:
                        self._timeline_names[lifer.species_id] = taxon.common_name or taxon.name
                checklists = self._checklists_for(context.query_list, taxonomy.id)
                assert checklists is not None  # the context needs a pack and a list too
                places = list_place_names(context.query_list, checklists)
                self._timeline_place_names = {
                    xml_id: places.name(place) for xml_id, place in places.places.items()
                }
        self._show_timeline()
        self.timelineChanged.emit()

    def _show_timeline(self) -> None:
        """The years or days, sorted, with decades between years when newest come first."""
        found = self._timeline
        periods: list[Period] = []
        if found is not None:
            periods = list(found.days if self._timeline_mode == "DAYS" else found.years)
        if self._timeline_lifers_only:
            periods = [p for p in periods if p.lifers > 0]
        if self._timeline_sort == "MOST_SPECIES":
            periods.sort(key=lambda p: (-p.count, -p.lifers))
        elif self._timeline_sort == "MOST_NEW":
            periods.sort(key=lambda p: (-p.lifers, -p.count))
        else:
            periods.reverse()
        most = max((p.count for p in periods), default=0)
        shown: list[Period | None] = []
        rows: list[dict[str, Any]] = []
        decades = (found is not None and self._timeline_mode == "YEARS"
                   and self._timeline_sort == "NEWEST_FIRST")  # fmt: skip
        current_decade: int | None = None
        for period in periods:
            if decades and found is not None:
                decade = decade_of(period.first_day.year)
                if decade != current_decade:
                    current_decade = decade
                    totals = found.decade(decade)
                    shown.append(None)
                    label = f"{decade}s · {totals.count:,} species · +{totals.lifers:,} new"
                    rows.append({"heading": True, "label": label, "place": "", "count": 0,
                                 "lifers": 0, "fraction": 0.0})  # fmt: skip
            shown.append(period)
            when = period.when
            rows.append({
                "heading": False,
                "label": display_date(when.get(PartialField.YEAR), when.get(PartialField.MONTH),
                                      when.get(PartialField.DAY)),
                "place": self._timeline_place_names.get(period.place or "", "")
                if period.is_day else "",
                "count": period.count,
                "lifers": period.lifers,
                "fraction": period.count / most if most else 0.0,
            })  # fmt: skip
        self._timeline_shown = shown
        self._timeline_selected = -1
        self.timeline_model.replace_all(rows)
        self.period_species_model.replace_all([])
        self.timelineSelectionChanged.emit()

    @Property(str, notify=timelineChanged)
    def timelineError(self) -> str:
        return self._timeline_error

    @Property(str, notify=timelineChanged)
    def timelineSummary(self) -> str:
        found = self._timeline
        if found is None:
            return ""
        if not found.lifers:
            return "No dated sightings."
        first = found.lifers[0].day
        last = found.latest_day or first
        return (f"Life list: {found.life_list_total:,} species · "
                f"{display_date(first.year, first.month, first.day)} to "
                f"{display_date(last.year, last.month, last.day)}")  # fmt: skip

    @Property(str, notify=timelineSelectionChanged)
    def timelineFootnote(self) -> str:
        """Scythebill's footnotes: what isn't counted toward a year or day, or at all."""
        found = self._timeline
        if found is None:
            return ""
        notes = []
        if self._timeline_mode == "YEARS" and found.sightings_in_no_year:
            spanning = found.sightings_in_no_year
            notes.append(f"Sightings from trips that span two years ({spanning:,}) aren't "
                         "counted toward any year.")  # fmt: skip
        if self._timeline_mode == "DAYS" and found.sightings_on_no_day:
            notes.append(f"Sightings with a date range ({found.sightings_on_no_day:,}) aren't "
                         "counted toward any day.")  # fmt: skip
        if found.undated_species:
            notes.append(f"{found.undated_species:,} species seen only without a date aren't "
                         "on the timeline.")  # fmt: skip
        return " ".join(notes)

    @Property("QVariantList", notify=timelineChanged)
    def lifeListPoints(self) -> list[list[float]]:
        """The life list's growth: [days since the first lifer, life list] at each change."""
        found = self._timeline
        if found is None or not found.lifers:
            return []
        start = found.lifers[0].day.toordinal()
        points: list[list[float]] = []
        for count, lifer in enumerate(found.lifers, 1):
            x = float(lifer.day.toordinal() - start)
            if points and points[-1][0] == x:
                points[-1][1] = float(count)
            else:
                points.append([x, float(count)])
        last = found.latest_day
        if last is not None and last.toordinal() - start > points[-1][0]:
            points.append([float(last.toordinal() - start), points[-1][1]])
        return points

    @Property("QVariantList", notify=timelineChanged)
    def milestonePoints(self) -> list[list[Any]]:
        """[days since the first lifer, number, species, date] for each milestone."""
        found = self._timeline
        if found is None or not found.lifers:
            return []
        start = found.lifers[0].day.toordinal()
        return [[m.lifer.day.toordinal() - start, m.number,
                 self._timeline_names.get(m.lifer.species_id, m.lifer.species_id),
                 display_date(m.lifer.day.year, m.lifer.day.month, m.lifer.day.day)]
                for m in found.milestones()]  # fmt: skip

    @Property("QVariantList", notify=timelineChanged)
    def timelineYears(self) -> list[int]:
        """The first and last years on the chart."""
        found = self._timeline
        if found is None or not found.lifers:
            return []
        last = found.latest_day or found.lifers[0].day
        return [found.lifers[0].day.year, last.year]

    @Property(str, notify=timelineSelectionChanged)
    def timelineMode(self) -> str:
        return self._timeline_mode

    @Slot(str)
    def setTimelineMode(self, mode: str) -> None:
        if mode in ("YEARS", "DAYS") and mode != self._timeline_mode:
            self._timeline_mode = mode
            self._show_timeline()

    @Property("QVariantList", constant=True)
    def timelineSorts(self) -> list[list[str]]:
        return [list(sort) for sort in TIMELINE_SORTS]

    @Property(str, notify=timelineSelectionChanged)
    def timelineSort(self) -> str:
        return self._timeline_sort

    @Slot(str)
    def setTimelineSort(self, sort: str) -> None:
        if sort != self._timeline_sort:
            self._timeline_sort = sort
            self._show_timeline()

    @Property(bool, notify=timelineSelectionChanged)
    def timelineLifersOnly(self) -> bool:
        return self._timeline_lifers_only

    @Slot(bool)
    def setTimelineLifersOnly(self, only: bool) -> None:
        if only != self._timeline_lifers_only:
            self._timeline_lifers_only = only
            self._show_timeline()

    @Property(QObject, constant=True)
    def timelineRows(self) -> DictListModel:
        return self.timeline_model

    @Property(QObject, constant=True)
    def periodSpecies(self) -> DictListModel:
        return self.period_species_model

    @Property(int, notify=timelineSelectionChanged)
    def timelineSelected(self) -> int:
        return self._timeline_selected

    @Property(str, notify=timelineSelectionChanged)
    def timelineSelectedLabel(self) -> str:
        if not 0 <= self._timeline_selected < len(self._timeline_shown):
            return ""
        return str(self.timeline_model.rows()[self._timeline_selected]["label"])

    @Slot(int)
    def selectPeriod(self, index: int) -> None:
        """A year's or day's species, lifers first, then in taxonomic order."""
        found = self._timeline
        if (found is None or not 0 <= index < len(self._timeline_shown)
                or self._timeline_shown[index] is None):  # fmt: skip
            return
        period = self._timeline_shown[index]
        assert period is not None
        self._timeline_selected = index
        rows = []
        for species in period.species:
            day = found.life_list_days.get(species)
            lifer = day is not None and period.first_day <= day <= period.last_day
            rows.append({"name": self._timeline_names.get(species, species), "lifer": lifer})
        rows.sort(key=lambda row: not row["lifer"])
        self.period_species_model.replace_all(rows)
        self.timelineSelectionChanged.emit()

    @Slot(int, int)
    def stepPeriod(self, index: int, step: int) -> None:
        """Choose the next period from ``index`` (headings skipped)."""
        target = index + step
        while 0 <= target < len(self._timeline_shown):
            if self._timeline_shown[target] is not None:
                self.selectPeriod(target)
                return
            target += 1 if step > 0 else -1


def bucket(result: YearResult | None) -> int:
    """``YearComparisonGrid.bucket``: 0 for none, then 1 (one sighting), 2 (2 to 4), 3 (5 to 19),
    4 (20 or more)."""
    if result is None or result.frequency <= 0:
        return 0
    for index, maximum in enumerate((1, 4, 19)):
        if result.frequency <= maximum:
            return index + 1
    return 4


def _month_day_text(when: PartialDate) -> str:
    """ "28 Apr" (Pipit's day-month order), or "Apr" with no day."""
    return display_date(None, when.get(PartialField.MONTH), when.get(PartialField.DAY))


def _resolved_name(resolved: Resolved) -> str:
    try:
        return resolved_common_name(resolved)
    except ValueError:
        return resolved.taxon.name

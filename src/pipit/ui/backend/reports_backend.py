"""The Reports screen for QML: a query built row by row (Scythebill's query fields, kept as
the very JSON Scythebill stores), run with ``pipit.query`` as soon as it changes, and the
results: Scythebill's totals line, the taxa (family headings, countable or not, lifers),
and the sightings of the chosen taxon.
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from pipit.browse.dates import display_date
from pipit.browse.species import place_labels
from pipit.domain import gson
from pipit.query import stored
from pipit.query.engine import EngineContext, parse_query, run_query
from pipit.query.fields_place_time import UnsupportedQueryError
from pipit.query.fields_simple import QueryJsonError
from pipit.query.model import QSighting, QueryList, load_query_list
from pipit.query.results import QueryResults
from pipit.query.stored import StoredQuery
from pipit.query.synthetic import regions_for
from pipit.storage.stored_query_ops import save_stored_queries, stored_queries
from pipit.taxa.model import TaxonType, full_name
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)
RUN_DELAY_MS = 150
HYBRID_SIGN = " \u00d7 "  # a multiplication sign between a hybrid's parents
DATE_RANGE = " \u2013 "  # an en dash between two dates
CHOICE_LIMIT = 40

#: The field types in Scythebill's menu order (``QueryPanel.FIELD_TYPE_TO_TITLE``), each
#: with its label, the editor QML shows, its comparisons ("type" in the JSON) and the
#: value a new field starts with.
FIELD_TYPES: list[dict[str, Any]] = [
    {"type": "LOCATION", "label": "Location", "editor": "place",
     "options": [["IN", "is in"], ["NOT_IN", "is not in"], ["IS", "is"], ["IS_NOT", "is not"],
                 ["IS_NEARER_THAN", "is nearer than"], ["IS_NOT_SET", "is not set"]],
     "default": {"type": "IN"}},
    {"type": "DATE", "label": "Date", "editor": "dates",
     "options": [["DURING", "is during"], ["BETWEEN", "is between"], ["AFTER", "is after"],
                 ["BEFORE", "is before"], ["THIS_YEAR", "is this year"], ["TODAY", "is today"],
                 ["NOT_DURING", "is not during"], ["NOT_SET", "is not set"]],
     "default": {"type": "DURING"}},
    {"type": "USER", "label": "Observers", "editor": "user",
     "options": [["INCLUDES", "includes"], ["DOES_NOT_INCLUDE", "does not include"],
                 ["IS_ONLY", "is only"], ["ARE_EMPTY", "are empty"]],
     "default": {"type": "INCLUDES"}},
    {"type": "FIRST_SIGHTINGS", "label": "First records (lifers)", "editor": "none",
     "options": [["HIGHLIGHTED", "highlighted"], ["INCLUDED", "included"]],
     "default": {"type": "HIGHLIGHTED"}},
    {"type": "ALLOW_HEARD_ONLY", "label": "Heard only", "editor": "heard",
     "options": [], "default": False},
    {"type": "SPECIES_STATUS", "label": "IUCN Redlist", "editor": "iucn",
     "options": [["IS", "is"], ["IS_NOT", "is not"], ["IS_OR_WORSE", "is or worse"]],
     "default": {"type": "IS", "statusId": "LC"}},
    {"type": "SIGHTING_STATUS", "label": "Status", "editor": "status",
     "options": [["IS", "is"], ["IS_NOT", "is not"], ["ANY", "is any"]],
     "default": {"type": "IS", "statusId": "none"}},
    {"type": "BREEDING_CODE", "label": "Breeding code", "editor": "breeding",
     "options": [["IS", "is"], ["IS_AT_LEAST", "is at least"], ["IS_NOT", "is not"],
                 ["ANY", "is any"]],
     "default": {"type": "IS", "level": "CONFIRMED"}},
    {"type": "PHOTOGRAPHED", "label": "Photographed", "editor": "none",
     "options": [["HAS_PHOTO", "has a photo"], ["HAS_NO_PHOTO", "has no photo"],
                 ["HAS_FAVORITE", "has a favorite photo"],
                 ["HAS_NO_FAVORITE", "has no favorite photo"]],
     "default": {"type": "HAS_PHOTO"}},
    {"type": "SIGHTING_NOTES", "label": "Sighting notes", "editor": "text",
     "options": [["CONTAINS", "contains"], ["DOES_NOT_CONTAIN", "does not contain"],
                 ["IS_EXACTLY", "is exactly"], ["STARTS_WITH_WORD", "starts with the word"],
                 ["CONTAINS_CASE_SENSITIVE", "contains (case-sensitive)"],
                 ["DOES_NOT_CONTAIN_CASE_SENSITIVE", "does not contain (case-sensitive)"],
                 ["IS_EXACTLY_CASE_SENSITIVE", "is exactly (case-sensitive)"],
                 ["STARTS_WTIH_WORD_CASE_SENSITIVE", "starts with the word (case-sensitive)"]],
     "default": {"type": "CONTAINS", "text": ""}},
    {"type": "VISIT_COMMENTS", "label": "Visit comments", "editor": "text",
     "options": None, "default": {"type": "CONTAINS", "text": ""}},
    {"type": "SEX_AGE", "label": "Sex and age", "editor": "none",
     "options": [["IS_FEMALE", "is female"], ["IS_MALE", "is male"], ["IS_ADULT", "is adult"],
                 ["IS_IMMATURE", "is immature"]],
     "default": {"type": "IS_FEMALE"}},
    {"type": "TIMES_SIGHTED", "label": "Times sighted", "editor": "count",
     "options": [["EXACTLY", "exactly"], ["AT_MOST", "at most"], ["AT_LEAST", "at least"],
                 ["LESS_THAN", "less than"], ["MORE_THAN", "more than"]],
     "default": {"type": "EXACTLY", "count": 1}},
    {"type": "FAMILY", "label": "Family or order", "editor": "family",
     "options": [["IS_IN", "is in"], ["IS_NOT_IN", "is not in"]],
     "default": {"type": "IS_IN"}},
    {"type": "SUBSPECIES_ALLOCATED", "label": "Subspecies", "editor": "none",
     "options": [["IS", "is allocated"], ["IS_NOT", "is not allocated"]],
     "default": {"type": "IS"}},
    {"type": "SP_OR_HYBRID", "label": "Sp./Hybrid", "editor": "sphybrid",
     "options": [["IS", "is"], ["IS_NOT", "is not"]],
     "default": {"type": "IS", "statusType": "SP"}},
]  # fmt: skip
FIELD_TYPES[10]["options"] = FIELD_TYPES[9]["options"]  # visit comments: same as notes
_BY_TYPE = {spec["type"]: spec for spec in FIELD_TYPES}
#: Each value's keys in its Scythebill ``Persisted`` class's field order (Gson writes them so).
_VALUE_ORDER = {
    "LOCATION": ("type", "id", "milesOrKilometers", "distance"),
    "DATE": ("type", "from", "to"),
    "USER": ("type", "id"),
    "FIRST_SIGHTINGS": ("type", "id", "query"),
    "SPECIES_STATUS": ("type", "statusId"),
    "SIGHTING_STATUS": ("type", "statusId"),
    "BREEDING_CODE": ("type", "level"),
    "SIGHTING_NOTES": ("type", "text"),
    "VISIT_COMMENTS": ("type", "text"),
    "TIMES_SIGHTED": ("type", "count"),
    "FAMILY": ("type", "id"),
    "SP_OR_HYBRID": ("type", "statusType"),
}
OPERATIONS = [["ALL", "And"], ["ANY", "Or"], ["NEVER", "Never"], ["NEVER_ALL", "Never All"]]
DEPTHS = [["species", "Species"], ["group", "Groups"], ["subspecies", "Subspecies"]]
STATUS_CHOICES = [
    ["none", "(None)"], ["notAccepted", "Not accepted"], ["bvd", "Better view desired"],
    ["intro", "Introduced"], ["provisional", "Provisional"], ["notEstablished", "Not established"],
    ["restrained", "Restrained"], ["domestic", "Domestic"], ["idUncertain", "Uncertain ID"],
    ["unsatisfactoryViews", "Unsatisfactory views"], ["notByMe", "Not by me"], ["dead", "Dead"],
    ["signs", "Signs only"],
]  # fmt: skip
IUCN_CHOICES = [["LC", "Least concern"], ["NE", "Not evaluated"], ["DD", "Data deficient"],
                ["NT", "Near threatened"], ["VU", "Vulnerable"], ["EN", "Endangered"],
                ["CR", "Critically endangered"], ["EW", "Extinct in the wild"],
                ["EX", "Extinct"]]  # fmt: skip
BREEDING_CHOICES = [["CONFIRMED", "Confirmed"], ["CONFIRMED_PROBABLE", "Confirmed or probable"],
                    ["PROBABLE", "Probable"], ["POSSIBLE", "Possible"]]  # fmt: skip
SP_CHOICES = [["SP", "a sp."], ["HYBRID", "a hybrid"], ["NEITHER", "neither"]]


def _with_commas(number: int) -> str:
    return f"{number:,d}"


def totals_text(results: QueryResults, depth: TaxonType) -> str:
    """``ReportsPanel.queryResultsUpdated``: "Total species: 1,234 (groups: 1,300, 5 "sp.")"."""
    species = results.countable_species_size(False)
    total = f"Total species: {_with_commas(species)}"
    others = []
    if depth is not TaxonType.SPECIES:
        groups = results.countable_groups_size(False)
        if groups != species:
            others.append(f"groups: {_with_commas(groups)}")
        if depth is TaxonType.SUBSPECIES:
            subspecies = results.countable_subspecies_size(False)
            if subspecies != groups:
                others.append(f"ssps: {_with_commas(subspecies)}")
    spuh = results.spuh_count()
    if spuh:
        others.append(f'{_with_commas(spuh)} "sp."')
    return total + (f" ({', '.join(others)})" if others else "")


class ReportsBackend(QObject):
    queryChanged = Signal()
    resultsChanged = Signal()
    selectionChanged = Signal()
    savedChanged = Signal()

    def __init__(self, app: AppController) -> None:
        super().__init__()
        self._app = app
        self._rows: list[dict[str, Any]] = []
        self._depth = TaxonType.SPECIES
        self._query_list: QueryList | None = None
        self._contexts: dict[tuple[str, TaxonType], EngineContext] = {}
        self._results: QueryResults | None = None
        self._error = ""
        self._totals = ""
        self._families = ""
        self._selected = -1
        self._places: dict[str, str] = {}
        self.rows_model = DictListModel(["type", "operation", "label", "editor", "options",
                                         "value"])  # fmt: skip
        self.results_model = DictListModel(
            ["heading", "name", "scientific", "countable", "lifer", "sightings"]
        )
        self.sightings_model = DictListModel(["date", "time", "place", "count", "details"])
        self.choices_model = DictListModel(["key", "name", "path"])
        self.saved_model = DictListModel(["name", "kind", "loadable"])
        self._saved: list[StoredQuery] = []
        self._current_saved = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RUN_DELAY_MS)
        self._timer.timeout.connect(self.run)
        app.listChanged.connect(self._list_changed)
        app.dataChanged.connect(self._data_changed)
        app.taxaReadyChanged.connect(self._data_changed)
        self._rows = [self._new_row("LOCATION", "ALL")]
        self._publish_rows()
        self._load_saved()

    # ------------------------------------------------------------ the list

    def _list_changed(self) -> None:
        self._rows = [self._new_row("LOCATION", "ALL")]
        self._current_saved = ""
        self._publish_rows()
        self._data_changed()

    def _data_changed(self) -> None:
        self._load_saved()
        self._query_list = None
        self._contexts = {}
        self._schedule()

    def _ensure_list(self) -> QueryList | None:
        database = self._app.database
        if database is None:
            return None
        if self._query_list is None:
            self._query_list = load_query_list(database.connection)
            self._places = place_labels(database.connection)
        return self._query_list

    def _context(self) -> EngineContext | None:
        query_list = self._ensure_list()
        taxa = self._app.entry_taxa
        if query_list is None or taxa is None:
            return None
        key = (taxa.display.id, self._depth)
        context = self._contexts.get(key)
        if context is None:
            database = self._app.database
            assert database is not None
            users = frozenset(u for (u,) in database.connection.execute("SELECT xml_id FROM users"))
            context = self._contexts[key] = EngineContext(query_list, taxa.display, self._depth,
                                                          users=users)  # fmt: skip
        return context

    # ------------------------------------------------------------ the query rows

    def _new_row(self, field_type: str, operation: str) -> dict[str, Any]:
        return {"type": field_type, "bool": operation,
                "value": copy.deepcopy(_BY_TYPE[field_type]["default"])}  # fmt: skip

    def _publish_rows(self) -> None:
        self.rows_model.replace_all([
            {"type": row["type"], "operation": row["bool"],
             "label": _BY_TYPE[row["type"]]["label"], "editor": _BY_TYPE[row["type"]]["editor"],
             "options": _BY_TYPE[row["type"]]["options"],
             "value": row["value"] if isinstance(row["value"], dict) else {"value": row["value"]}}
            for row in self._rows
        ])  # fmt: skip
        self.queryChanged.emit()
        self._schedule()

    def query_json(self) -> str:
        """The query exactly as Scythebill stores it (``StoredQueries.persist``): each field as
        type, value, bool; each value's keys in its ``Persisted`` class order (Gson)."""
        fields = []
        for row in self._rows:
            value = row["value"]
            if isinstance(value, dict):
                order = _VALUE_ORDER.get(row["type"], ("type",))
                value = {key: value[key] for key in order if value.get(key) is not None}
            fields.append({"type": row["type"], "value": value, "bool": row["bool"]})
        return gson.dumps({"fields": fields})

    def set_query_json(self, text: str) -> None:
        data = json.loads(text)
        legacy = data.get("type")
        self._rows = [
            {"type": field["type"], "bool": field.get("bool", legacy) or "ALL",
             "value": field.get("value")}
            for field in data["fields"]
        ]  # fmt: skip
        self._publish_rows()

    @Property(str, notify=queryChanged)
    def queryJson(self) -> str:
        return self.query_json()

    @Slot()
    def addRow(self) -> None:
        """Scythebill adds the first field type not used yet (Date if all are)."""
        used = {row["type"] for row in self._rows}
        field_type = next((spec["type"] for spec in FIELD_TYPES if spec["type"] not in used),
                          "DATE")  # fmt: skip
        self._rows.append(self._new_row(field_type, "ALL"))
        self._publish_rows()

    @Slot(int)
    def removeRow(self, index: int) -> None:
        if 0 <= index < len(self._rows):
            del self._rows[index]
            if not self._rows:
                self._rows = [self._new_row("LOCATION", "ALL")]
            self._publish_rows()

    @Slot(int, str)
    def setRowType(self, index: int, field_type: str) -> None:
        if (0 <= index < len(self._rows) and field_type in _BY_TYPE
                and self._rows[index]["type"] != field_type):  # fmt: skip
            self._rows[index] = self._new_row(field_type, self._rows[index]["bool"])
            self._publish_rows()

    @Slot(int, str)
    def setRowOperation(self, index: int, operation: str) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index]["bool"] = operation
            self._publish_rows()

    @Slot(int, str, "QVariant")
    def setRowValue(self, index: int, key: str, value: Any) -> None:
        """Set one key of the row's JSON value ("" or None removes it, as Gson omits nulls);
        the heard-only field's value is the whole value (true, false or null)."""
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        if key == "count" and value is not None:
            value = int(value)  # Gson writes an int ("5", not "5.0")
        elif key == "distance" and value is not None:
            value = float(value)  # a Float ("150.0")
        if row["type"] == "ALLOW_HEARD_ONLY":
            row["value"] = value
        elif value is None or value == "":
            row["value"].pop(key, None)
        else:
            row["value"][key] = value
        self._publish_rows()

    @Slot()
    def resetQuery(self) -> None:
        self._rows = [self._new_row("LOCATION", "ALL")]
        self._publish_rows()

    # ------------------------------------------------------------ saved reports

    def _load_saved(self) -> None:
        database = self._app.database
        self._saved = stored_queries(database.connection) if database is not None else []
        if self._current_saved not in {query.name for query in self._saved}:
            self._current_saved = ""
        self.saved_model.reset([
            {"name": query.name, "loadable": query.type == stored.REPORTS,
             "kind": "" if query.type == stored.REPORTS
             else f"Total ticks ({(query.ticks_type or '').title()})"}
            for query in self._saved
        ])  # fmt: skip
        self.savedChanged.emit()
        self.queryChanged.emit()

    def _save(self, queries: list[StoredQuery], label: str) -> bool:
        database = self._app.database
        if database is None or database.read_only:
            self._app.message.emit("This list is read-only")
            return False
        try:
            save_stored_queries(database, queries, label)
        except sqlite3.Error as error:
            log.exception("saving reports failed")
            self._app.message.emit(f"Could not save: {error}")
            return False
        self._app.changed()
        self._app.message.emit(f"{label} · Ctrl+Z undoes")
        return True

    @Property(str, notify=savedChanged)
    def currentSaved(self) -> str:
        """The saved report the query was loaded from or saved as ("" if none)."""
        return self._current_saved

    @Property(int, notify=savedChanged)
    def currentSavedIndex(self) -> int:
        return next((i for i, q in enumerate(self._saved) if q.name == self._current_saved), -1)

    @Property(bool, notify=queryChanged)
    def savedEdited(self) -> bool:
        """The query differs from the saved report it came from."""
        saved = next((q for q in self._saved if q.name == self._current_saved), None)
        return (
            saved is not None
            and stored.canonicalize_query_json(self.query_json()) != saved.query_json
        )

    @Slot(str, result=bool)
    def nameTaken(self, name: str) -> bool:
        return any(query.name == name for query in self._saved)

    @Slot(int)
    def loadSaved(self, index: int) -> None:
        """Load a saved report into the query (a total-ticks query is kept, not loaded)."""
        if not 0 <= index < len(self._saved) or self._saved[index].type != stored.REPORTS:
            return
        query = self._saved[index]
        try:
            self.set_query_json(query.query_json)
        except (ValueError, KeyError, TypeError, AttributeError):
            self._app.message.emit(f"“{query.name}” can't be read")
            return
        self._current_saved = query.name
        self.savedChanged.emit()
        self.queryChanged.emit()

    @Slot(str, result=bool)
    def saveAs(self, name: str) -> bool:
        """Save the query under this name (one of the same name is replaced, in place)."""
        name = name.strip()
        if not name:
            return False
        verb = "Replaced" if self.nameTaken(name) else "Saved"
        if not self._save(stored.add(self._saved, name, self.query_json()),
                          f"{verb} report “{name}”"):  # fmt: skip
            return False
        self._current_saved = name
        self.savedChanged.emit()
        self.queryChanged.emit()
        return True

    @Slot(int, str, result=bool)
    def renameSaved(self, index: int, name: str) -> bool:
        name = name.strip()
        if not 0 <= index < len(self._saved) or not name or self.nameTaken(name):
            return False
        old = self._saved[index].name
        if not self._save(stored.rename(self._saved, old, name), f"Renamed report “{name}”"):
            return False
        if self._current_saved == old:
            self._current_saved = name
            self.savedChanged.emit()
        return True

    @Slot(int)
    def deleteSaved(self, index: int) -> None:
        if 0 <= index < len(self._saved):
            name = self._saved[index].name
            self._save(stored.remove(self._saved, name), f"Deleted report “{name}”")

    @Slot(int, int)
    def moveSaved(self, from_index: int, to_index: int) -> None:
        moved = stored.move(self._saved, from_index, to_index)
        if moved != self._saved:
            self._save(moved, f"Moved report “{self._saved[from_index].name}”")

    @Property(QObject, constant=True)
    def saved(self) -> DictListModel:
        return self.saved_model

    # ------------------------------------------------------------ choices for editors

    @Slot(str, str)
    def findChoices(self, kind: str, text: str) -> None:
        """Places (with synthetic regions), families and orders, or observers matching
        ``text``, for a row's picker."""
        needle = text.strip().casefold()
        found: list[dict[str, str]] = []  # "key" is the id (QML reserves "id")
        query_list = self._ensure_list()
        if kind == "place" and query_list is not None:
            for region, _places in regions_for(query_list).items():
                name = _REGION_NAMES.get(region, region)
                if not needle or needle in name.casefold():
                    found.append({"key": region, "name": name, "path": "Region"})
            for xml_id, place in query_list.places.items():
                if not needle or needle in place.name.casefold():
                    label = self._places.get(xml_id, place.name)
                    found.append({"key": xml_id, "name": place.name,
                                  "path": label.partition(" · ")[2]})  # fmt: skip
        elif kind == "family":
            taxa = self._app.entry_taxa
            if taxa is not None:
                for taxon in taxa.display.walk():
                    if taxon.type in (TaxonType.FAMILY, TaxonType.ORDER):
                        common = taxon.common_name or ""
                        if (
                            not needle
                            or needle in taxon.name.casefold()
                            or (needle in common.casefold())
                        ):
                            kind_name = "Order" if taxon.type is TaxonType.ORDER else "Family"
                            found.append({"key": taxon.id, "name": common or taxon.name,
                                          "path": f"{kind_name} · {taxon.name}"})  # fmt: skip
        elif kind == "user":
            database = self._app.database
            if database is not None:
                for xml_id, name, abbreviation in database.connection.execute(
                    "SELECT xml_id, name, abbreviation FROM users ORDER BY ord"
                ):
                    label = name or abbreviation or xml_id
                    if not needle or needle in label.casefold():
                        found.append({"key": xml_id, "name": label, "path": abbreviation or ""})
        self.choices_model.replace_all(found[:CHOICE_LIMIT])

    @Slot(str, str, result=str)
    def choiceName(self, kind: str, choice_id: str) -> str:
        """The name shown for a row's chosen place, family or observer."""
        if not choice_id:
            return ""
        if kind == "place":
            if choice_id in _REGION_NAMES:
                return _REGION_NAMES[choice_id]
            query_list = self._ensure_list()
            place = None if query_list is None else query_list.places.get(choice_id)
            return place.name if place else choice_id
        if kind == "family":
            taxa = self._app.entry_taxa
            taxon = None if taxa is None else taxa.display.get(choice_id)
            return (taxon.common_name or taxon.name) if taxon else choice_id
        database = self._app.database
        if database is not None:
            found = database.connection.execute(
                "SELECT coalesce(name, abbreviation) FROM users WHERE xml_id = ?", (choice_id,)
            ).fetchone()
            if found:
                return str(found[0])
        return choice_id

    # ------------------------------------------------------------ running

    def _schedule(self) -> None:
        self._timer.start()

    def run_now(self) -> None:
        """Tests and screenshots: skip the settle delay."""
        self._timer.stop()
        self.run()

    @Slot()
    def run(self) -> None:
        context = self._context()
        self._selected = -1
        if context is None:
            self._results = None
            self._error = ""
            self._totals = ""
            self.results_model.replace_all([])
            self.sightings_model.replace_all([])
            self.resultsChanged.emit()
            self.selectionChanged.emit()
            return
        try:
            query = parse_query(self.query_json(), context.query_list, context.users)
            results = run_query(query, context)
        except (QueryJsonError, UnsupportedQueryError, ValueError, KeyError) as error:
            log.info("query refused: %s", error)
            self._results = None
            self._error = str(error)
            self._totals = ""
            self.results_model.replace_all([])
        else:
            self._results = results
            self._error = ""
            self._totals = totals_text(results, self._depth)
            self._families = f"Families: {_with_commas(results.family_count())}"
            lifers = {row for row, note in results.annotations.items() if note == "lifer"}
            self.results_model.replace_all([self._row(results, r, lifers) for r in results.taxa])
        self.sightings_model.replace_all([])
        self.resultsChanged.emit()
        self.selectionChanged.emit()

    def _row(self, results: QueryResults, resolved: Resolved, lifers: set[int]) -> dict[str, Any]:
        heading = resolved.smallest_type is TaxonType.FAMILY
        if heading:
            taxon = resolved.taxon
            return {"heading": True, "name": taxon.common_name or taxon.name,
                    "scientific": taxon.name, "countable": True, "lifer": False,
                    "sightings": 0}  # fmt: skip
        found = self._sightings_of(results, resolved)
        separator = HYBRID_SIGN if resolved.type is SightingTaxonType.HYBRID else "/"
        common = separator.join(t.common_name or t.name for t in resolved.taxa)
        scientific = separator.join(full_name(t) for t in resolved.taxa)
        return {"heading": False, "name": common, "scientific": scientific,
                "countable": results.is_countable(resolved),
                "lifer": any(s.row in lifers for s in found), "sightings": len(found)}  # fmt: skip

    @staticmethod
    def _sightings_of(results: QueryResults, resolved: Resolved) -> list[QSighting]:
        if resolved.type is SightingTaxonType.SINGLE:
            return results.sightings.get(resolved.taxon.id, [])
        return results.non_single.get(resolved.sighting_taxon, [])

    @Property(str, notify=resultsChanged)
    def totals(self) -> str:
        return self._totals

    @Property(str, notify=resultsChanged)
    def families(self) -> str:
        return self._families if self._results is not None else ""

    @Property(str, notify=resultsChanged)
    def error(self) -> str:
        return self._error

    @Property(int, notify=resultsChanged)
    def sightingCount(self) -> int:
        return 0 if self._results is None else self._results.sightings_count()

    # ------------------------------------------------------------ depth

    @Property(str, notify=queryChanged)
    def depth(self) -> str:
        return self._depth.name.lower()

    @Slot(str)
    def setDepth(self, depth: str) -> None:
        wanted = TaxonType[depth.upper()]
        if wanted is not self._depth:
            self._depth = wanted
            self.queryChanged.emit()
            self._schedule()

    # ------------------------------------------------------------ chosen taxon

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:
        return self._selected

    @Slot(int)
    def select(self, index: int) -> None:
        results = self._results
        if results is None or not 0 <= index < len(results.taxa):
            return
        if results.taxa[index].smallest_type is TaxonType.FAMILY:
            return
        self._selected = index
        found = self._sightings_of(results, results.taxa[index])
        rows = sorted(found, key=lambda s: s.recency, reverse=True)
        self.sightings_model.replace_all([
            {"date": _date_text(s), "time": "" if s.time is None else s.time.strftime("%H:%M"),
             "place": self._places.get(s.location_xml_id or "", "No place"),
             "count": s.count or "",
             "details": " · ".join(part for part in (
                 "heard only" if s.heard_only else "", "photo" if s.photographed else "",
                 "" if s.status == "none" else _STATUS_LABELS.get(s.status, s.status),
                 s.description) if part)}
            for s in rows
        ])  # fmt: skip
        self.selectionChanged.emit()

    @Slot(int, int)
    def selectStep(self, index: int, step: int) -> None:
        """Choose the row at ``index``, skipping family headings in the direction of
        ``step``."""
        results = self._results
        if results is None or not results.taxa:
            return
        index = max(0, min(index, len(results.taxa) - 1))
        direction = 1 if step >= 0 else -1
        while 0 <= index < len(results.taxa) and (
            results.taxa[index].smallest_type is TaxonType.FAMILY
        ):
            index += direction
        if 0 <= index < len(results.taxa):
            self.select(index)

    # ------------------------------------------------------------ models and lists

    @Property("QVariantList", constant=True)
    def fieldTypes(self) -> list[list[str]]:
        return [[spec["type"], spec["label"]] for spec in FIELD_TYPES]

    @Property("QVariantList", constant=True)
    def operations(self) -> list[list[str]]:
        return OPERATIONS

    @Property("QVariantList", constant=True)
    def depths(self) -> list[list[str]]:
        return DEPTHS

    @Property("QVariantList", constant=True)
    def statusChoices(self) -> list[list[str]]:
        return STATUS_CHOICES

    @Property("QVariantList", constant=True)
    def iucnChoices(self) -> list[list[str]]:
        return IUCN_CHOICES

    @Property("QVariantList", constant=True)
    def breedingChoices(self) -> list[list[str]]:
        return BREEDING_CHOICES

    @Property("QVariantList", constant=True)
    def spChoices(self) -> list[list[str]]:
        return SP_CHOICES

    @Property(QObject, constant=True)
    def rows(self) -> DictListModel:
        return self.rows_model

    @Property(QObject, constant=True)
    def results(self) -> DictListModel:
        return self.results_model

    @Property(QObject, constant=True)
    def sightings(self) -> DictListModel:
        return self.sightings_model

    @Property(QObject, constant=True)
    def choices(self) -> DictListModel:
        return self.choices_model


def _date_text(sighting: QSighting) -> str:
    start, end = sighting.start_date, sighting.end_date
    if start is None:
        return "No date"
    first = display_date(start.year, start.month, start.day)
    if sighting.date is None and end is not None and end != start:
        return f"{first}{DATE_RANGE}{display_date(end.year, end.month, end.day)}"
    return first


_STATUS_LABELS = dict((key, label) for key, label in STATUS_CHOICES)
#: Synthetic regions' English names (Scythebill's synthetic-locations-en.csv).
_REGION_NAMES = {
    "***aba***": "ABA region", "***abawh***": "ABA Continental",
    "***us50***": "United States - 50 states", "***us48***": "United States - contiguous",
    "***aou***": "AOS Area - North", "***aossouth***": "AOS Area - South",
    "***wepale***": "Western Palearctic", "***sounafr***": "Southern Africa",
    "***uswidepterr***": "United States (with dependent territories)",
    "***auwidepterr***": "Australia (with dependent territories)",
    "***austaba***": "Australasia (ABA)", "***pacoceaba***": "Pacific Ocean (ABA)",
    "***orireg***": "Oriental Region", "***clwidepterr***": "Chile (with offshore islands)",
    "***cowidepterr***": "Colombia (with Caribbean islands)",
    "***ecwidepterr***": "Ecuador (with Galapagos)",
    "***ptwidepterr***": "Portugal (with Azores and Madeira)",
    "***eswidepterr***": "Spain (with Canary Islands, Ceuta, and Melilla)",
    "***nzwidepterr***": "New Zealand (with Tokelau)",
    "***nowidepterr***": "Norway (with Bouvet Island and Svalbard)",
    "***gbwidepterr***": "United Kingdom (with dependent territories)",
    "***cnwidepterr***": "China (with administrative regions)",
    "***dkwidepterr***": "Kingdom of Denmark",
    "***zawidepterr***": "South Africa (with Prince Edward and Marion Islands)",
    "***frwidepterr***": "France (with Overseas Territories)",
    "***ireislof***": "Ireland (Island of)",
    "***ushiwinowiis***": "Hawaii (with Northwestern Islands)",
    "***nlwidepterr***": "Kingdom of the Netherlands",
}  # fmt: skip

"""A report as printable HTML, exactly as Scythebill's Print writes it.

Ported from Scythebill's ``ui/.../io/HtmlOutput.java`` and ``PrintHtml.java`` (the page), and
``panels/reports/PrintAction.java`` with ``ReportPrintDialog`` (the options, the heading and
the summary line). The styles and print script are Scythebill's own (``resources/``).

The page is the heading (the query's name, else the list's file name), a summary line (file
name, date, totals), then the species: in families as a table (with their sightings), or in
compact mode as three columns; or, sorted other than taxonomically, one row per sighting.
Badges mark checklist statuses (endemic, introduced, rarity...) and IUCN statuses, lifers are
bold, and a legend explains only the badges used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as calendar_date
from importlib import resources

from pipit.domain.partial_date import PartialDate, PartialField, common_partial_date
from pipit.output.html_writer import HtmlWriter
from pipit.output.names import (
    PlaceNames,
    resolved_common_name,
    resolved_full_name,
    resolved_simple_common_name,
    resolved_status,
)
from pipit.query.checklists import STATUS_ORDER, Checklist, Checklists
from pipit.query.engine import (
    EngineContext,
    FamilyValue,
    StoredQuery,
    UserValue,
    parse_query,
    run_query,
)
from pipit.query.fields_place_time import DateValue, LocationValue
from pipit.query.fields_simple import PhotographedValue
from pipit.query.model import QSighting, QTrip
from pipit.query.results import QueryResults
from pipit.query.sorting import SORT_TYPES, sorted_rows
from pipit.query.synthetic import REGION_NAMES, regions_for
from pipit.taxa.model import IUCN_STATUSES, Taxon, Taxonomy, TaxonType, walk
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

#: ``NamesPreferences.ScientificOrCommon``
COMMON_FIRST = "COMMON_FIRST"
SCIENTIFIC_FIRST = "SCIENTIFIC_FIRST"
COMMON_ONLY = "COMMON_ONLY"
SCIENTIFIC_ONLY = "SCIENTIFIC_ONLY"

SHORT_FAMILY_SIZE = 7
LIFER_TEXT = "Lifer"

_CHECKLIST_ABBREVIATIONS = {"ENDEMIC": "E", "EXTINCT": "X", "INTRODUCED": "I",
                            "PROVISIONAL": "P", "RARITY": "R", "RARITY_FROM_INTRODUCED": "R*",
                            "ESCAPED": "NE"}  # fmt: skip
_CHECKLIST_TEXT = {"NATIVE": "Regular", "ENDEMIC": "Endemic", "EXTINCT": "Extinct",
                   "INTRODUCED": "Introduced", "PROVISIONAL": "Provisional",
                   "RARITY": "Rarity", "RARITY_FROM_INTRODUCED": "Rarity, from introduced pop.",
                   "ESCAPED": "Not established"}  # fmt: skip
_IUCN_TEXT = {"LC": "Least Concern", "NE": "Not Evaluated", "DD": "Data Deficient",
              "NT": "Near Threatened", "VU": "Vulnerable", "EN": "Endangered",
              "CR": "Critically Endangered", "EW": "Extinct in the Wild", "EX": "Extinct",
              "IN": "Feral form", "DO": "Domestic form", "UN": "Undescribed"}  # fmt: skip
#: ``SightingFlags.appendSightingInfo``: " - status" (lower case), or a mark.
_STATUS_FLAGS = {"intro": " - introduced", "provisional": " - provisional",
                 "notAccepted": " - not accepted", "notEstablished": " - not established",
                 "notByMe": " - not by me", "signs": " - signs only", "domestic": " - domestic",
                 "restrained": " - restrained", "unsatisfactoryViews": " - unsatisfactory views",
                 "dead": " (†)", "idUncertain": " (?)", "bvd": " (BVD)"}  # fmt: skip
_INTRODUCED_CHECKLIST = ("INTRODUCED", "PROVISIONAL", "RARITY_FROM_INTRODUCED", "ESCAPED")
_INTRODUCED_SIGHTING = ("intro", "provisional", "notEstablished")


@dataclass(frozen=True)
class PrintOptions:
    """``ReportPrintPreferences``, with Scythebill's defaults."""

    include_scientific: bool = True
    show_families: bool = True
    show_status: bool = True
    maximum_sightings: int = 1
    sort_type: str = "DEFAULT"  # species
    sort_sightings_type: str = "DEFAULT"
    compact: bool = False
    only_countable: bool = False
    omit_sp_and_hybrid: bool = False


def names_order(preference: str, options: PrintOptions) -> str:
    """``ReportPrintDialog.getScientificOrCommonFromConfiguration``."""
    if options.include_scientific:
        return COMMON_FIRST if preference == COMMON_ONLY else preference
    return COMMON_ONLY


def _number(value: int) -> str:
    return f"{value:,d}"


# ------------------------------------------------------------------ dates and trips


def short_date(date: PartialDate) -> str:
    """``PartialDateDisplay.toShortUserString`` in US English ("11/25/26")."""
    day, month, year = (date.get(PartialField.DAY), date.get(PartialField.MONTH),
                        date.get(PartialField.YEAR))  # fmt: skip
    if day is not None:
        if month is not None and year is not None:
            return f"{month}/{day}/{year % 100:02d}"
        return f"{day}/{'' if month is None else month}/{'' if year is None else _year(year)}"
    text = ""
    if month is not None:
        text += f"{month}/"
    if year is not None:
        text += _year(year)
    return text


def _year(year: int) -> str:
    return f"0{year}" if year < 10 else str(year)


def trip_name_with_date(trip: QTrip) -> str:
    """``TripUtils.nameWithDate``."""
    name = trip.name or ""
    for date in (trip.start, trip.end):
        year = date.get(PartialField.YEAR)
        if year is not None and f"{year % 100:02d}" in name:
            return name
    common = common_partial_date(trip.start, trip.end)
    if common is None:
        start_year = trip.start.get(PartialField.YEAR)
        end_year = trip.end.get(PartialField.YEAR)
        if start_year is None or end_year is None:
            return name
        return f"{start_year}-{end_year} {name}"
    return f"{short_date(common)} {name}"


def sighting_flags(sighting: QSighting) -> str:
    """``SightingFlags.appendSightingInfo("", sighting).trim()``."""
    text = _STATUS_FLAGS.get(sighting.status, "")
    if sighting.heard_only:
        text += " (H)"
    return text.strip()


# ------------------------------------------------------------------ the heading


@dataclass(frozen=True)
class NameSources:
    """What the query's name is made from: place, observer and family names."""

    place_names: dict[str, str]  # xml_id -> name (synthetic regions too)
    users: dict[str, tuple[str | None, str | None]]  # xml_id -> (name, abbreviation)
    taxonomy: Taxonomy


def _field_name_and_abbreviation(value: object, sources: NameSources
                                 ) -> tuple[str | None, str | None]:  # fmt: skip
    """``QueryFieldValue.name()`` and ``abbreviation()``."""
    if isinstance(value, LocationValue):
        abbreviation = None
        if value.query == "IS_NOT_SET":
            abbreviation = "Location not set"
        elif value.location_id is not None:
            abbreviation = sources.place_names.get(value.location_id)
        return abbreviation or "World", abbreviation
    if isinstance(value, DateValue):
        return _date_name(value), _date_abbreviation(value)
    if isinstance(value, FamilyValue):
        taxon = sources.taxonomy.get(value.taxon_id) if value.taxon_id else None
        if taxon is None:
            return None, None
        if taxon.common_name is not None:
            name = (f"{taxon.common_name} (order)" if taxon.type is TaxonType.ORDER
                    else taxon.common_name)  # fmt: skip
        else:
            name = taxon.name
        if value.query == "IS_NOT_IN":
            name = f"not {name}"
        return name, name
    if isinstance(value, UserValue):
        if value.user is None or value.user not in sources.users:
            return None, None
        user_name, user_abbreviation = sources.users[value.user]
        return user_name or user_abbreviation, user_abbreviation or user_name
    if isinstance(value, PhotographedValue):
        return {"HAS_PHOTO": "photographed", "HAS_NO_PHOTO": "not photographed",
                "HAS_FAVORITE": "has favorite", "HAS_NO_FAVORITE": "no favorite"}[
            value.query], None  # fmt: skip
    return None, None


def _date_name(value: DateValue) -> str | None:
    if value.query == "THIS_YEAR":
        return "Year"
    if value.query == "TODAY":
        return "Today"
    if value.query == "NOT_SET":
        return "Date not set"
    if value.query == "DURING" and value.start is not None:
        return short_date(value.start)
    if value.query == "NOT_DURING" and value.start is not None:
        return f"not {short_date(value.start)}"
    if value.query == "AFTER" and value.start is not None:
        return f"after {short_date(value.start)}"
    if value.query == "BEFORE" and value.end is not None:
        return f"before {short_date(value.end)}"
    return None


def _date_abbreviation(value: DateValue) -> str | None:
    start, end = value.start, value.end
    if value.query == "BETWEEN":
        if start is None:
            return None if end is None else str(end)
        if end is None:
            return str(start)
        start_year, end_year = start.get(PartialField.YEAR), end.get(PartialField.YEAR)
        if start_year is not None and end_year is not None:
            return str(start_year) if start_year == end_year else f"{start_year}-{end_year}"
        return None
    if value.query in ("AFTER", "DURING", "NOT_DURING", "BEFORE"):
        # BEFORE uses the "from" date, as Scythebill does.
        return None if start is None else str(start)
    today = value.today or calendar_date.today()
    if value.query == "TODAY":
        return f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
    if value.query == "THIS_YEAR":
        return str(today.year)
    return None


def report_name(query: StoredQuery, sources: NameSources) -> str | None:
    """``getQueryName().or(getQueryAbbreviation())``: the fields' names (or abbreviations),
    "never ..." for never fields."""
    names: list[str] = []
    abbreviations: list[str] = []
    for value, operation in query.fields:
        name, abbreviation = _field_name_and_abbreviation(value, sources)
        never = operation in ("NEVER", "NEVER_ALL")
        if name is not None:
            names.append(f"never {name}" if never else name)
        if abbreviation is not None:
            abbreviations.append(f"never {abbreviation}" if never else abbreviation)
    if names:
        return " ".join(names)
    if abbreviations:
        return "-".join(abbreviations).replace("/", "-")
    return None


# ------------------------------------------------------------------ the page


@dataclass(frozen=True)
class _Badge:
    text: str
    css_class: str


class _Legend:
    def __init__(self) -> None:
        self.checklist: set[str] = set()
        self.iucn: set[str] = set()
        self.lifers = False

    def checklist_badge(self, status: str) -> _Badge:
        self.checklist.add(status)
        return _checklist_badge(status)

    def iucn_badge(self, status: str) -> _Badge:
        self.iucn.add(status)
        return _Badge(status, "badge iucn")

    def write(self, rw: HtmlWriter) -> None:
        if not self.checklist and not self.iucn and not self.lifers:
            return
        rw.start("div")
        rw.attribute("class", "legend")
        for status in STATUS_ORDER:
            if status in self.checklist:
                _legend_item(rw, _checklist_badge(status), _CHECKLIST_TEXT[status])
        for status in IUCN_STATUSES:
            if status in self.iucn:
                _legend_item(rw, _Badge(status, "badge iucn"), _IUCN_TEXT[status])
        if self.lifers:
            rw.start("span")
            rw.attribute("class", "item lifer")
            rw.write_text(LIFER_TEXT)
            rw.end("span")
        rw.end("div")


def _checklist_badge(status: str) -> _Badge:
    return _Badge(_CHECKLIST_ABBREVIATIONS[status],
                  "badge endemic" if status == "ENDEMIC" else "badge")  # fmt: skip


def _legend_item(rw: HtmlWriter, badge: _Badge, label: str) -> None:
    rw.start("span")
    rw.attribute("class", "item")
    _write_badge(rw, badge)
    rw.write_text(label)
    rw.end("span")


def _write_badge(rw: HtmlWriter, badge: _Badge) -> None:
    rw.start("span")
    rw.attribute("class", badge.css_class)
    rw.write_text(badge.text)
    rw.end("span")


def _resource(name: str) -> str:
    return resources.files("pipit.output").joinpath("resources", name).read_text("utf-8")


@dataclass
class _Entry:
    taxon: Resolved
    sightings: list[QSighting]


@dataclass
class _FamilyGroup:
    family: Resolved | None
    members: list[Resolved]
    entries: list[_Entry]


@dataclass
class PrintPage:
    """``HtmlOutput`` as ``PrintAction`` sets it up."""

    results: QueryResults
    places: PlaceNames
    root: str | None
    title: str
    document_title: str
    details: list[str]
    options: PrintOptions
    names_order: str
    show_family_totals: bool
    print_on_load: bool = True

    def __post_init__(self) -> None:
        self._legend = _Legend()
        sorted_species = self.options.sort_type != "DEFAULT"
        self._show_families = self.options.show_families and not sorted_species
        if sorted_species:
            self.show_family_totals = False

    # ------------------------------------------------------------ options

    @property
    def _compact(self) -> bool:
        return self.options.compact

    @property
    def _sightings_count(self) -> int:
        if self._compact:
            return 1
        return self.options.maximum_sightings

    @property
    def _checklist(self) -> Checklist | None:
        return self.results.checklist

    def _omitted(self, taxon: Resolved) -> bool:
        return self.options.omit_sp_and_hybrid and taxon.type in (
            SightingTaxonType.HYBRID,
            SightingTaxonType.SP,
        )

    # ------------------------------------------------------------ writing

    def html(self) -> str:
        rw = HtmlWriter()
        results = self.results
        if self.options.sort_type != "DEFAULT":
            groups = self._sorted_group()
        else:
            groups = self._family_groups()
        self._start_document(rw)
        self._write_header(rw, self._summary_items(groups))
        if self._compact:
            rw.start("div")
            rw.attribute("class", "main")
            for group in groups:
                self._family_header(rw, group)
                for entry in group.entries:
                    self._compact_entry(rw, entry)
            rw.end("div")
        else:
            rw.start("table")
            rw.attribute("class", "list report" if self._sightings_count > 0
                         else "list report no-sightings")  # fmt: skip
            for group in groups:
                rw.start("tbody")
                if group.family is not None and len(group.entries) <= SHORT_FAMILY_SIZE:
                    rw.attribute("class", "short-family")
                self._family_header(rw, group)
                for entry in group.entries:
                    self._entry_rows(rw, entry)
                rw.end("tbody")
            rw.end("table")
        self._legend.write(rw)
        rw.start("p")
        rw.attribute("class", "taxonomy")
        rw.write_text(results.taxonomy.name)
        rw.end("p")
        rw.end("body")
        rw.end("html")
        return rw.text()

    def _family_groups(self) -> list[_FamilyGroup]:
        ordering = SORT_TYPES[self.options.sort_sightings_type]
        groups: list[_FamilyGroup] = []
        current: _FamilyGroup | None = None
        for taxon in self.results.taxa:
            if taxon.smallest_type is TaxonType.FAMILY:
                current = _FamilyGroup(taxon, [], [])
                groups.append(current)
                continue
            if current is None:
                current = _FamilyGroup(None, [], [])
                groups.append(current)
            current.members.append(taxon)
            if not self._omitted(taxon):
                best = self.results.best_sightings(taxon, ordering, self._sightings_count)
                current.entries.append(_Entry(taxon, best))
        return [group for group in groups if group.entries]

    def _sorted_group(self) -> list[_FamilyGroup]:
        rows = sorted_rows(self.results, self.results.taxa, self.options.sort_type,
                           self._sightings_count, self._omitted)  # fmt: skip
        return [_FamilyGroup(None, [], [_Entry(row.taxon, [row.sighting]) for row in rows])]

    def _start_document(self, rw: HtmlWriter) -> None:
        rw.start_document()
        rw.comment("saved from url=(0016)http://localhost")
        rw.start("html")
        rw.start("head")
        rw.start("meta")
        rw.attribute("http-equiv", "Content-Type")
        rw.attribute("content", "text/html; charset=UTF-8")
        rw.end("meta")
        rw.start("title")
        rw.write_text(self.document_title)
        rw.end("title")
        rw.start("style")
        rw.attribute("type", "text/css")
        rw.raw("".join(_resource(name) + "\n" for name in ("print-base.css",
                                                           "report-print.css")))  # fmt: skip
        rw.end("style")
        if self.print_on_load:
            rw.start("script")
            rw.attribute("type", "text/javascript")
            rw.raw(_resource("print-columns.js"))
            rw.raw("\nfunction onload_script() {\n")
            if self._compact:
                rw.raw("  if (scythebillIsSafari()) {\n    scythebillMakeBands();\n  }\n")
            rw.raw("  window.print();\n}\n")
            rw.end("script")
        rw.end("head")
        rw.start("body")
        if not self._compact:
            body_class = "regular"
        elif self.names_order in (COMMON_ONLY, SCIENTIFIC_ONLY):
            body_class = "compact one-name"
        else:
            body_class = "compact"
        rw.attribute("class", body_class)
        if self.print_on_load:
            rw.attribute("onload", "onload_script();")

    def _write_header(self, rw: HtmlWriter, items: list[str]) -> None:
        rw.start("header")
        rw.start("h1")
        rw.write_text(self.title)
        rw.end("h1")
        if items:
            rw.start("div")
            rw.attribute("class", "summary")
            for item in items:
                rw.start("span")
                rw.attribute("class", "item")
                rw.write_text(item)
                rw.end("span")
            rw.end("div")
        rw.end("header")

    def _summary_items(self, groups: list[_FamilyGroup]) -> list[str]:
        results = self.results
        items = list(self.details)
        species = results.countable_species_size(False)
        items.append(f"Species: {_number(species)}")
        if results.smallest_type is not TaxonType.SPECIES:
            groups_count = results.countable_groups_size(False)
            if groups_count != species:
                items.append(f"Groups: {_number(groups_count)}")
            if results.smallest_type is TaxonType.SUBSPECIES:
                subspecies = results.countable_subspecies_size(False)
                if subspecies != groups_count:
                    items.append(f"Subspecies: {_number(subspecies)}")
        if any(self._is_lifer(e) for g in groups for e in g.entries):
            lifers = len(results.taxa_with_annotation_at("lifer", TaxonType.SPECIES))
            if lifers:
                items.append(f"Lifers: {_number(lifers)}")
            if results.smallest_type is not TaxonType.SPECIES:
                lifer_groups = len(results.taxa_with_annotation_at("lifer", TaxonType.GROUP))
                if lifer_groups != lifers:
                    items.append(f"Lifer groups: {_number(lifer_groups)}")
                if results.smallest_type is TaxonType.SUBSPECIES:
                    lifer_subspecies = len(
                        results.taxa_with_annotation_at("lifer", TaxonType.SUBSPECIES)
                    )
                    if lifer_subspecies != lifer_groups:
                        items.append(f"Lifer subspecies: {_number(lifer_subspecies)}")
        if self._show_families:
            families = sum(
                1 for g in groups if g.family is not None
                and any(results.is_countable(e.taxon) for e in g.entries)
            )  # fmt: skip
            if self.show_family_totals:
                possible = count_families(results.taxonomy, self._checklist)
                items.append(f"Families: {_number(families)} of {_number(possible)}")
            else:
                items.append(f"Families: {_number(families)}")
        items.append(f"Total sightings: {_number(results.sightings_count())}")
        return items

    def _is_lifer(self, entry: _Entry) -> bool:
        return self.results.contains_annotation("lifer", entry.taxon)

    def _entry_rows(self, rw: HtmlWriter, entry: _Entry) -> None:
        show_sightings = self._sightings_count > 0
        sightings = entry.sightings if show_sightings else []
        rw.start("tr")
        rw.attribute("class", "species end" if len(sightings) <= 1 else "species")
        rw.start("td")
        rw.attribute("class", "name")
        self._names(rw, entry)
        rw.end("td")
        if show_sightings:
            rw.start("td")
            rw.attribute("class", "sighting")
            if sightings:
                self._sighting(rw, sightings[0])
            rw.end("td")
        rw.end("tr")
        for i in range(1, len(sightings)):
            rw.start("tr")
            rw.attribute("class", "more-sighting end" if i == len(sightings) - 1
                         else "more-sighting")  # fmt: skip
            rw.start("td")
            rw.attribute("class", "name")
            rw.end("td")
            rw.start("td")
            rw.attribute("class", "sighting")
            self._sighting(rw, sightings[i])
            rw.end("td")
            rw.end("tr")

    def _compact_entry(self, rw: HtmlWriter, entry: _Entry) -> None:
        rw.start("div")
        rw.attribute("class", "species")
        rw.start("span")
        rw.attribute("class", "text")
        self._names(rw, entry)
        if entry.sightings:
            self._flags(rw, entry.sightings[0])
        rw.end("span")
        rw.end("div")

    def _names(self, rw: HtmlWriter, entry: _Entry) -> None:
        lifer = self._is_lifer(entry)
        if lifer:
            self._legend.lifers = True
        badges = self._badges(entry)
        taxon = entry.taxon
        order = self.names_order
        if order == COMMON_FIRST:
            primary = resolved_simple_common_name(taxon)
        elif order == COMMON_ONLY:
            primary = resolved_common_name(taxon)
        else:
            primary = resolved_full_name(taxon)
        scientific_first = order in (SCIENTIFIC_FIRST, SCIENTIFIC_ONLY)
        primary_class = "primary"
        if scientific_first:
            primary_class += " scientific"
        if lifer:
            primary_class += " lifer"
        secondary = None
        if order == COMMON_FIRST:
            secondary = resolved_full_name(taxon)
        elif order == SCIENTIFIC_FIRST:
            secondary = resolved_simple_common_name(taxon)
        secondary_class = "secondary scientific" if order == COMMON_FIRST else "secondary"
        if secondary is None:
            _name_with_badges(rw, primary_class, primary, badges)
        else:
            _name_with_badges(rw, primary_class, primary, [])
            _name_with_badges(rw, secondary_class, secondary, badges)

    def _badges(self, entry: _Entry) -> list[_Badge]:
        badges: list[_Badge] = []
        taxon = entry.taxon
        checklist = self._checklist
        if checklist is not None:
            if taxon.smallest_type is TaxonType.SPECIES:
                species = taxon.sighting_taxon
            else:
                species = taxon.parent_of_at_least_type(TaxonType.SPECIES)
            status = checklist.status(species)
            if (
                status is not None
                and status != "NATIVE"
                and not (status in _INTRODUCED_CHECKLIST and self._shown_introduced(entry))
            ):
                badges.append(self._legend.checklist_badge(status))
        if self.options.show_status:
            iucn = resolved_status(taxon)
            if iucn not in ("LC", "NT"):
                badges.append(self._legend.iucn_badge(iucn))
        return badges

    def _shown_introduced(self, entry: _Entry) -> bool:
        if not self._compact and self._sightings_count == 0:
            return False
        return any(s.status in _INTRODUCED_SIGHTING for s in entry.sightings)

    def _family_header(self, rw: HtmlWriter, group: _FamilyGroup) -> None:
        if not self._show_families or group.family is None:
            return
        family = group.family.taxon
        if self._compact:
            rw.start("h2")
        else:
            rw.start("tr")
            rw.attribute("class", "family")
            rw.start("th")
            rw.attribute("colspan", 2 if self._sightings_count > 0 else 1)
        rw.attribute("class", "familyTitle")
        _family_name(rw, family, self.names_order)
        if self.show_family_totals:
            species_ids: set[str] = set()
            for member in group.members:
                if self.results.is_countable(member):
                    parent = member.parent_of_at_least_type(TaxonType.SPECIES)
                    if parent.type is SightingTaxonType.SINGLE:
                        species_ids.add(parent.ids[0])
            possible = count_children(family, TaxonType.SPECIES, self._checklist)
            rw.start("span")
            rw.attribute("class", "family-count")
            rw.write_text(f"{_number(len(species_ids))}/{_number(possible)}")
            rw.end("span")
        if self._compact:
            rw.end("h2")
        else:
            rw.end("th")
            rw.end("tr")

    def _sighting(self, rw: HtmlWriter, sighting: QSighting) -> None:
        date = sighting.single_date
        place = None
        if sighting.location_xml_id is not None:
            place = self.places.path_name(sighting.location_xml_id, self.root)
        trip = sighting.trip
        if date is None and trip is not None:
            if place is not None and (not trip.name or place not in trip.name):
                rw.write_text(place)
                rw.write_text(" ")
            rw.write_text(trip_name_with_date(trip))
        else:
            if place is not None:
                rw.write_text(place)
                if date is not None:
                    rw.write_text(" ")
            if date is not None:
                rw.write_text(short_date(date))
        self._flags(rw, sighting)

    def _flags(self, rw: HtmlWriter, sighting: QSighting) -> None:
        flags = sighting_flags(sighting)
        if not flags:
            return
        rw.write_text(" ")
        rw.start("span")
        rw.attribute("class", "flags")
        rw.write_text(flags)
        rw.end("span")


def _name_with_badges(rw: HtmlWriter, css_class: str, name: str, badges: list[_Badge]) -> None:
    if not badges:
        rw.start("span")
        rw.attribute("class", css_class)
        rw.write_text(name)
        rw.end("span")
        return
    last_space = name.rfind(" ")
    if last_space > 0:
        rw.start("span")
        rw.attribute("class", css_class)
        rw.write_text(name[:last_space])
        rw.end("span")
    rw.start("span")
    rw.attribute("class", "nowrap")
    rw.start("span")
    rw.attribute("class", css_class)
    rw.write_text(name[last_space + 1 :])
    rw.end("span")
    for badge in badges:
        _write_badge(rw, badge)
    rw.end("span")


def _family_name(rw: HtmlWriter, family: Taxon, order: str) -> None:
    secondary = None
    if order == COMMON_FIRST:
        rw.write_text(family.common_name or "")
        secondary = family.name
    elif order == SCIENTIFIC_FIRST:
        rw.write_text(family.name)
        secondary = family.common_name
    elif order == SCIENTIFIC_ONLY:
        rw.write_text(family.name)
    else:
        rw.write_text(family.common_name or "")
    if secondary is not None:
        rw.start("span")
        rw.attribute("class", "family-secondary")
        rw.write_text(secondary)
        rw.end("span")


# ------------------------------------------------------------------ checklist counts


def count_children(taxon: Taxon, taxon_type: TaxonType, checklist: Checklist | None,
                   excluding: tuple[str, ...] = ()) -> int:  # fmt: skip
    """``TaxonUtilsChecklists.countChildren``."""
    total = 0
    for child in taxon.children:
        if child.type is taxon_type:
            if checklist is None or checklist.includes(child.id, excluding):
                total += 1
        else:
            total += count_children(child, taxon_type, checklist, excluding)
    return total


def count_families(taxonomy: Taxonomy, checklist: Checklist | None,
                   excluding: tuple[str, ...] = ("ESCAPED",)) -> int:  # fmt: skip
    """``TaxonUtilsChecklists.countFamilies`` (as Print calls it, not counting escapees)."""
    if checklist is None:
        assert taxonomy.root is not None
        return sum(1 for taxon in walk(taxonomy.root) if taxon.type is TaxonType.FAMILY)
    families: set[SightingTaxon] = set()
    for taxon, status in checklist.statuses.items():
        if status in excluding:
            continue
        resolved = taxon.resolve_internal(taxonomy)
        families.add(resolved.parent_of_at_least_type(TaxonType.FAMILY))
    return len(families)


def family_totals_shown(query: StoredQuery, checklist: Checklist | None) -> bool:
    """``PrintAction``: no family totals with a species-status field, or with a place but
    no checklist for it (they would be the world's)."""
    if any(v.type == "SPECIES_STATUS" for v, _op in query.fields):
        return False
    has_place = any(v.type == "LOCATION" and not getattr(v, "is_no_op", False)
                    for v, _op in query.fields)  # fmt: skip
    return not (has_place and checklist is None)


# ------------------------------------------------------------------ PrintAction


def print_report(*, context: EngineContext, checklists: Checklists, query_json: str,
                 users: dict[str, tuple[str | None, str | None]], file_name: str, date: str,
                 options: PrintOptions, names_preference: str = COMMON_FIRST,
                 print_on_load: bool = True) -> PrintedReport:  # fmt: skip
    """``PrintAction.actionPerformed`` on the Reports screen's query: the page.

    ``file_name`` is the list's file name without its extension, and ``date`` today's date
    as Scythebill writes it (``short_date``)."""
    query_list = context.query_list
    query = parse_query(query_json, query_list, users.keys())
    results = run_query(query, context, only_countable=options.only_countable)
    locations = [v for v, _op in query.fields if isinstance(v, LocationValue)]
    known = set(query_list.places) | set(regions_for(query_list))
    places = {v.location_id if v.location_id in known else None for v in locations}
    if len(places) == 1:
        (only,) = places
        if only is not None:
            results.checklist = checklists.checklist(context.taxonomy, only)
    root = None
    if len(locations) == 1 and locations[0].query in ("IN", "IS"):
        root = locations[0].location_id if locations[0].location_id in known else None
    place_names = {xml_id: place.name for xml_id, place in query_list.places.items()}
    place_names.update(REGION_NAMES)
    name = report_name(query, NameSources(place_names, users, context.taxonomy))
    title = name or file_name
    if name is not None:
        details = [file_name, date]
        document_title = f"{title} - {file_name} - {date}"
    else:
        details = [date]
        document_title = f"{file_name} - {date}"
    page = PrintPage(
        results=results, places=PlaceNames(query_list.places), root=root, title=title,
        document_title=document_title, details=details, options=options,
        names_order=names_order(names_preference, options),
        show_family_totals=family_totals_shown(query, results.checklist),
        print_on_load=print_on_load,
    )  # fmt: skip
    return PrintedReport(page.html(), title)


@dataclass(frozen=True)
class PrintedReport:
    html: str
    title: str  # the heading, which also names the file (browsers print its address)


def safe_file_name(name: str, fallback: str) -> str:
    """``IOUtils.safeFileName``."""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "-", name).strip()
    safe = re.sub(r"[. ]+$", "", safe)
    if len(safe) > 80:
        safe = safe[:80].strip()
    return safe or fallback

"""A trip report, as Scythebill's Save as trip report writes it: HTML (to paste into Word or
Pages), a plain-text copy, and a Word document, all from one pass over the content.

Ported from Scythebill's ``ui/.../io/TripReportDocOutput.java`` and
``panels/reports/SaveAsTripReportAction.java`` (lifers, the trips a report covers, which
sightings count). Photos in the report and other taxonomies' sections aren't ported yet
(Pipit has neither photos nor custom taxonomies); a sighting's photos online are still
linked from the species list, as Scythebill links them.

The report is a title (the report's name, then its dates and region), a row of totals, then
optionally: an itinerary (a table per run of days, trips as headings between them), a table
of species by day, and a species list (numbered by family, each species with the stops it
was found at and what was recorded there, then a legend for the markers used).
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date as calendar_date
from datetime import time
from decimal import ROUND_HALF_EVEN, Decimal
from functools import cmp_to_key

from pipit.domain.partial_date import (
    PartialDate,
    PartialField,
    after_or_equals,
    before,
    before_or_equals,
    compare_partial_dates,
    parse_partial_date,
)
from pipit.domain.report import BREEDING_CODES, SIGHTING_STATUSES
from pipit.domain.values import ApproximateNumber, float32, parse_time
from pipit.output.html_writer import HtmlWriter
from pipit.output.names import (
    PlaceNames,
    ordered_taxa,
    resolved_common_name,
    resolved_full_name,
    resolved_status,
)
from pipit.output.print_html import (
    COMMON_FIRST,
    COMMON_ONLY,
    SCIENTIFIC_FIRST,
    list_place_names,
    name_sources,
    query_name,
    run_report_query,
    short_date,
)
from pipit.output.report_document import (
    BlockStyle,
    CellStyle,
    HtmlReportDocumentWriter,
    PlainTextTee,
    ReportDocumentWriter,
    RowStyle,
    SpanStyle,
    TableStyle,
)
from pipit.output.report_docx import DocxReportDocumentWriter
from pipit.output.trip_stops import GUAVA_WHITESPACE, Stop, TripStops
from pipit.query.checklists import Checklists
from pipit.query.definition import Predicate
from pipit.query.engine import CountingPreferences, EngineContext, StoredQuery
from pipit.query.model import QSighting, QTrip, QueryList
from pipit.query.results import QueryResults
from pipit.taxa.model import Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType

LIFER_MARKER = "★"
HEARD_ONLY_LETTER = "H"
HEARD_ONLY_MARKER = "(H)"
MALE_MARKER = "♂"
FEMALE_MARKER = "♀"
PHOTO_MARKER = "P"
DOT_SEPARATOR = " · "
#: A species found at more stops than this gets a summary rather than a list of them.
MAXIMUM_LISTED_STOPS = 8
MILES_PER_KILOMETER = 0.621371
#: ``SaveAsTripReportAction``: no species table for more visits than this (or none).
MAXIMUM_VISITS_FOR_SPECIES_TABLE = 200
THREATENED_STATUSES = ("VU", "EN", "CR", "EW", "EX")
#: Protocols worth mentioning in the itinerary, with their names.
NOTABLE_PROTOCOLS = {"banding": "Banding", "pelagic": "eBird Pelagic Protocol",
                     "nocturnal": "Nocturnal Birding",
                     "flight_call": "Nocturnal Flight Call Count"}  # fmt: skip
#: Statuses the species list doesn't mention (the checklist markers cover them).
UNMENTIONED_STATUSES = ("none", "intro", "provisional")
#: Breeding codes too weak to be evidence of breeding.
NON_BREEDING_CODES = ("", "H", "F")
STATUS_TEXT = {"notAccepted": "Not accepted", "bvd": "Better view desired",
               "intro": "Introduced", "provisional": "Provisional",
               "notEstablished": "Not established", "restrained": "Restrained",
               "domestic": "Domestic", "idUncertain": "Uncertain ID",
               "unsatisfactoryViews": "Unsatisfactory views", "notByMe": "Not by me",
               "dead": "Dead", "signs": "Signs only"}  # fmt: skip
BREEDING_TEXT = {
    "NY": "Nest with Young", "NE": "Nest with Eggs", "CS": "Carrying Fecal Sac",
    "FY": "Feeding Young", "CF": "Carrying Food", "FL": "Recently Fledged Young",
    "ON": "Occupied nest", "UN": "Used Nest (enter 0 if no birds seen)",
    "DD": "Distraction Display", "NB": "Nest Building", "CN": "Carrying Nesting Material",
    "PE": "Brood Patch and Physiological Evidence", "B": "Wren/Woodpecker Nest Building",
    "A": "Agitated Behavior", "N": "Visiting Probable Nest Site",
    "C": "Courtship, Display or Copulation", "T": "Territorial Defense",
    "P": "Pair in Suitable Habitat", "M": "Multiple (7+) singing birds",
    "S7": "Singing Bird", "S": "Singing Bird", "H": "In Appropriate Habitat",
    "F": "Flying Over Only",
}  # fmt: skip
IUCN_TEXT = {"LC": "Least Concern", "NE": "Not Evaluated", "DD": "Data Deficient",
             "NT": "Near Threatened", "VU": "Vulnerable", "EN": "Endangered",
             "CR": "Critically Endangered", "EW": "Extinct in the Wild", "EX": "Extinct",
             "IN": "Feral form", "DO": "Domestic form", "UN": "Undescribed"}  # fmt: skip
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")  # fmt: skip
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_STRINGS_TO_STRIP = ("Part", "part", "(", "[")
_LEGEND_ORDER = ("LIFER", "ENDEMIC", "INTRODUCED", "HEARD_ONLY", "COUNT", "MALE", "FEMALE",
                 "ADULT", "IMMATURE", "PHOTO")  # fmt: skip


# ------------------------------------------------------------------ list data


@dataclass(frozen=True)
class VisitInfo:
    observation_type: str
    duration_minutes: int | None
    distance_km: float | None  # ``Distance.kilometers()``: float32, at three decimals
    comments: str | None


@dataclass(frozen=True, order=False)
class VisitKey:
    """``VisitInfoKey``: a visit is a place, a date and a start time."""

    location: str
    date: PartialDate
    start_time: time | None


@dataclass(frozen=True)
class Photo:
    uri: str
    name: str | None
    favorite: bool


@dataclass
class ReportListData:
    """What a trip report reads from the list beyond the query: visits, trips in list order
    with their notes, sightings' photos and the observers."""

    visit_info: dict[VisitKey, VisitInfo] = field(default_factory=dict)
    trips: list[QTrip] = field(default_factory=list)
    trip_notes: dict[str, str] = field(default_factory=dict)
    photos: dict[int, list[Photo]] = field(default_factory=dict)  # sighting row -> photos
    users: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)


def load_report_data(connection: sqlite3.Connection, query_list: QueryList) -> ReportListData:
    data = ReportListData()
    for location, date, start, kind, minutes, distance, comments in connection.execute(
        "SELECT location_xml_id, date, start_time, observation_type, duration_minutes, "
        "distance_km, comments FROM visits ORDER BY ord"
    ):
        key = VisitKey(location, parse_partial_date(date), parse_time(start) if start else None)
        data.visit_info[key] = VisitInfo(
            kind, minutes, None if distance is None else _kilometers(float(distance)), comments
        )
    for xml_id, notes in connection.execute("SELECT xml_id, notes FROM trips ORDER BY ord"):
        trip = query_list.trips.get(xml_id)
        if trip is not None:
            data.trips.append(trip)
        if notes is not None:
            data.trip_notes[xml_id] = notes
    for sighting, uri, name, favorite in connection.execute(
        "SELECT sighting_id, uri, name, favorite FROM photos WHERE sighting_id IS NOT NULL "
        "ORDER BY sighting_id, ord"
    ):
        data.photos.setdefault(sighting, []).append(Photo(uri, name, bool(favorite)))
    for xml_id, name, abbreviation in connection.execute(
        "SELECT xml_id, name, abbreviation FROM users ORDER BY ord"
    ):
        data.users[xml_id] = (name, abbreviation)
    return data


def _kilometers(stored: float) -> float:
    """``Distance.kilometers()``: rounded to three decimals in float32 arithmetic."""
    value = float32(stored)
    scaled = float32(float32(value * float32(1000.0)) + float32(0.5))
    return float32(float32(float(int(scaled // 1))) / float32(1000.0))


def visit_key(sighting: QSighting) -> VisitKey | None:
    """``VisitInfoKey.forSighting``: needs a place and a stored date."""
    if sighting.location_xml_id is None or sighting.date is None:
        return None
    return VisitKey(sighting.location_xml_id, sighting.date, sighting.time)


def compare_visits(left: VisitKey, right: VisitKey) -> int:
    """``VisitInfoKeyOrdering``: by date, then start time (none first), then place ID."""
    dates = compare_partial_dates(left.date, right.date)
    if dates:
        return dates
    if left.start_time is not None:
        if right.start_time is None:
            return 1
        times = (left.start_time.hour - right.start_time.hour
                 or left.start_time.minute - right.start_time.minute)  # fmt: skip
        if times:
            return times
    elif right.start_time is not None:
        return -1
    return (left.location > right.location) - (left.location < right.location)


def report_visits(results: QueryResults) -> list[VisitKey]:
    """``getAllVisitInfoKeys``: the visits of single taxa's sightings (not sp.s' or
    hybrids'), and of the matching sightings of other taxonomies."""
    sightings = [s for found in results.sightings.values() for s in found]
    sightings += results.incompatible
    return sorted_visits(key for s in sightings if (key := visit_key(s)) is not None)


def sorted_visits(keys: Iterable[VisitKey]) -> list[VisitKey]:
    """A ``TreeSet`` of visits: sorted, and those comparing equal kept once."""
    found: list[VisitKey] = []
    for key in sorted(keys, key=cmp_to_key(compare_visits)):
        if not found or compare_visits(found[-1], key) != 0:
            found.append(key)
    return found


# ------------------------------------------------------------------ formatting


def _number(value: int) -> str:
    return f"{value:,d}"


def _one_decimal(value: float) -> str:
    """``NumberFormat.getNumberInstance()`` with one fraction digit at most."""
    rounded = Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    whole, _, fraction = f"{rounded:f}".partition(".")
    text = f"{int(whole):,d}" if whole != "-0" else "-0"
    return text if fraction in ("", "0") else f"{text}.{fraction}"


def _java_sum(values: Iterable[float]) -> float:
    """``DoubleStream.sum``: Kahan summation, as the JDK does it."""
    total = 0.0
    compensation = 0.0
    simple = 0.0
    for value in values:
        adjusted = value - compensation
        velvel = total + adjusted
        compensation = (velvel - total) - adjusted
        total = velvel
        simple += value
    return total - compensation


def short_time(value: time) -> str:
    """``TimeDisplay.toShortUserString`` in US English: "6:15 AM" (a narrow space)."""
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d}\u202f{'AM' if value.hour < 12 else 'PM'}"


def _plus_minutes(value: time, minutes: int) -> time:
    total = (value.hour * 60 + value.minute + minutes) % (24 * 60)
    return time(total // 60, total % 60)


def _full_date(date: PartialDate) -> calendar_date | None:
    year, month, day = (date.get(PartialField.YEAR), date.get(PartialField.MONTH),
                        date.get(PartialField.DAY))  # fmt: skip
    if year is None or month is None or day is None:
        return None
    return calendar_date(year, month, day)


def weekday(date: PartialDate) -> str | None:
    full = _full_date(date)
    return None if full is None else _WEEKDAYS[full.weekday()]


def long_date(date: PartialDate) -> str:
    """A date written out ("February 1, 2025"), or ``PartialDateDisplay.toUserString``."""
    full = _full_date(date)
    if full is not None:
        return f"{_MONTHS[full.month - 1]} {full.day}, {full.year}"
    parts = []
    day, month, year = (date.get(PartialField.DAY), date.get(PartialField.MONTH),
                        date.get(PartialField.YEAR))  # fmt: skip
    if day is not None:
        parts.append(f"{day} ")
    if month is not None:
        parts.append(f"{_MONTHS[month - 1][:3]} ")
    if year is not None:
        parts.append(f"0{year}" if 0 <= year < 10 else str(year))
    return "".join(parts).strip()


def _guava_trim(text: str) -> str:
    start = 0
    end = len(text)
    while start < end and text[start] in GUAVA_WHITESPACE:
        start += 1
    while end > start and text[end - 1] in GUAVA_WHITESPACE:
        end -= 1
    return text[start:end]


def _common_prefix(first: str, second: str) -> str:
    """``Strings.commonPrefix``: whole UTF-16 characters (Python strings are code points)."""
    length = 0
    while length < min(len(first), len(second)) and first[length] == second[length]:
        length += 1
    return first[:length]


_URI_INVALID = re.compile(r"[\s\"<>\\^`{|}]|%(?![0-9A-Fa-f]{2})")


def is_web_address(uri: str) -> bool:
    """A link that ``URI.create`` accepts, to an http(s) address."""
    if _URI_INVALID.search(uri):
        return False
    lower = uri.lower()
    return lower.startswith(("https://", "http://"))


def ascii_uri(uri: str) -> str:
    """``URI.toASCIIString``: characters outside ASCII percent-encoded as UTF-8."""
    return "".join(c if ord(c) < 0x80 else "".join(f"%{b:02X}" for b in c.encode("utf-8"))
                   for c in uri)  # fmt: skip


# ------------------------------------------------------------------ the report


@dataclass(frozen=True)
class TripReportOptions:
    """``TripReportPreferences`` (photos and other taxonomies aside), with the distance
    unit (``VisitInfoPreferences``)."""

    include_scientific: bool = True
    itinerary: bool = True
    species_table: bool = True
    species_list: bool = True
    show_status: bool = True
    lifers_in_bold: bool = True
    use_miles: bool = False


@dataclass(frozen=True)
class _SpeciesEntry:
    family: Taxon | None
    species: Resolved
    taxa: tuple[Resolved, ...]

    @property
    def display_taxon(self) -> Resolved:
        return self.taxa[0] if len(self.taxa) == 1 else self.species


@dataclass
class _ItineraryVisit:
    first: VisitKey
    last: VisitKey
    visits: list[VisitKey]


@dataclass
class _ItineraryRow:
    trip: QTrip | None
    visits: list[_ItineraryVisit] | None

    def is_multi_day(self) -> bool:
        return (self.visits is not None and len(self.visits) == 1
                and self.visits[0].first.date != self.visits[0].last.date)  # fmt: skip

    def date(self) -> PartialDate:
        assert self.visits
        return self.visits[0].first.date


@dataclass(frozen=True)
class _Column:
    """A column of the species table: a date, or a trip with sightings recorded on it."""

    date: PartialDate | None = None
    trip: QTrip | None = None

    @property
    def sort_date(self) -> PartialDate:
        if self.trip is not None:
            return self.trip.start
        assert self.date is not None
        return self.date


class TripReport:
    """``TripReportDocOutput``."""

    def __init__(self, *, results: QueryResults, data: ReportListData, places: PlaceNames,
                 root: str | None, names_order: str, options: TripReportOptions,
                 name: str | None, trips: Iterable[QTrip] | None, lifer_ids: set[str],
                 countable: Predicate) -> None:  # fmt: skip
        self.results = results
        self.data = data
        self.places = places
        self.root = root
        self.names_order = names_order
        self.options = options
        self.name = name
        self.lifer_ids = lifer_ids
        self.countable = countable
        self.visits = report_visits(results)
        self.entries = _gather_entries(results.taxa)
        self.trips: list[QTrip] = []
        self._set_trips(trips)
        self._legend: set[str] = set()
        self._used_users: dict[str, None] = {}
        self._report_users: frozenset[str] = frozenset()
        self._all_same_year = False
        self.stops: TripStops
        self._species_by_visit: dict[VisitKey, set[Resolved]] = {}

    def _set_trips(self, trips: Iterable[QTrip] | None) -> None:
        """``setTrips``: with no name, the report is named for what the trips' names share."""
        self.trips = list(trips or [])
        if self.name is None and self.trips:
            name = self.trips[0].name or ""
            for trip in self.trips[1:]:
                name = _common_prefix(name, trip.name or "")
                if not name:
                    break
            for strip in _STRINGS_TO_STRIP:
                if name.endswith(strip):
                    name = name[: -len(strip)]
            if len(name) > 3:
                self.name = name

    # ------------------------------------------------------------ writing

    def html(self) -> tuple[str, str]:
        """``writeReport``: the HTML, and its plain-text copy."""
        writer = HtmlWriter(indent=False)
        tee = PlainTextTee(writer)
        self.write(HtmlReportDocumentWriter(tee))
        return writer.text(), tee.plain_text()

    def word(self, *, letter_paper: bool = True) -> tuple[bytes, bytes]:
        """``writeWordDocument``: the .docx, and its ``word/document.xml``."""
        writer = DocxReportDocumentWriter(letter_paper=letter_paper)
        self.write(writer)
        return writer.data, writer.document_xml()

    def write(self, out: ReportDocumentWriter) -> None:
        results = self.results
        all_sightings = results.all_sightings()
        self.stops = self._compute_stops(all_sightings)
        self._species_by_visit = self._compute_species_by_visit()
        self._legend = set()
        self._used_users = {}
        self._report_users = frozenset(u for s in all_sightings for u in s.user_order)
        self.trips = sorted(self.trips, key=cmp_to_key(_by_trip_start))
        years = {_year(key.date) for key in self.visits}
        years |= {_year(trip.start) for trip in self.trips}
        years |= {_year(trip.end) for trip in self.trips}
        self._all_same_year = len(years) == 1
        out.start_document()
        self._write_title(out)
        if len(self.trips) == 1 or not self.options.itinerary:
            for trip in self.trips:
                self._write_trip_notes(out, trip)
        self._write_summary(out, all_sightings)
        out.start_block(BlockStyle.CONTENT)
        if self.options.itinerary:
            self._write_itinerary(out)
        if self.options.species_table:
            self._write_species_table(out, all_sightings)
        if self.options.species_list:
            self._write_species_list(out)
        out.end_block()
        out.end_document()

    def _write_trip_notes(self, out: ReportDocumentWriter, trip: QTrip) -> None:
        notes = self.data.trip_notes.get(trip.xml_id)
        if not notes:
            return
        for paragraph in notes.split("\n"):
            _block(out, BlockStyle.BODY, paragraph)

    def _write_title(self, out: ReportDocumentWriter) -> None:
        if self.name:
            _block(out, BlockStyle.TITLE, self.name)
        date_range = self._date_range()
        region = self._region_name()
        if date_range is not None and region is not None:
            subtitle = f"{date_range} · {region}"
        elif date_range is not None:
            subtitle = date_range
        elif region is not None:
            subtitle = region
        else:
            return
        _block(out, BlockStyle.SUBTITLE, subtitle)

    def _date_range(self) -> str | None:
        dates = [key.date for key in self.visits]
        for trip in self.trips:
            dates.extend((trip.start, trip.end))
        if not dates:
            return None
        dates.sort(key=cmp_to_key(compare_partial_dates))
        first, last = dates[0], dates[-1]
        if first == last:
            return long_date(first)
        return f"{long_date(first)} \u2013 {long_date(last)}"

    def _region_name(self) -> str | None:
        """The root place's name, unless the report is the world's (a root with no parent,
        or a synthetic region)."""
        root = self.places.places.get(self.root) if self.root is not None else None
        if root is None or root.parent is None:
            return None
        return self._location_name(root.xml_id)

    def _location_name(self, location_id: str) -> str:
        if location_id == self.root:
            return self.places.path_name(location_id, self.root)
        return self.places.disambiguated_name(location_id)

    def _counted(self, entries: Iterable[_SpeciesEntry]) -> list[_SpeciesEntry]:
        return [entry for entry in entries
                if any(self.countable(s) for taxon in entry.taxa
                       for s in self.results.sightings_of(taxon))]  # fmt: skip

    def summary(self) -> list[tuple[str, str]]:
        """The row of totals under the title, as (number, label): species, lifers, endemics,
        days and sites (stops), each only if there are some (species always)."""
        if not hasattr(self, "stops"):
            self.stops = self._compute_stops(self.results.all_sightings())
        return self._summary(self.results.all_sightings())

    def _summary(self, all_sightings: list[QSighting]) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        counted = self._counted(self.entries)
        found.append((_number(len(counted)), "Species"))
        if self.options.lifers_in_bold:
            lifers = sum(1 for entry in counted if self._is_lifer(entry.species))
            if lifers > 0:
                found.append((_number(lifers), "Lifers"))
        endemics = sum(1 for entry in counted if self._checklist_status(entry.species) == "ENDEMIC")
        if endemics > 0:
            found.append((_number(endemics), "Endemics"))
        days = len({key.date for key in self.visits})
        if days > 0:
            found.append((_number(days), "Days"))
        site_ids = {key.location for key in self.visits}
        site_ids |= {s.location_xml_id for s in all_sightings
                     if s.trip is not None and s.location_xml_id is not None}  # fmt: skip
        sites = len({self._stop_key(site) for site in site_ids})
        if sites > 0:
            found.append((_number(sites), "Sites"))
        return found

    def _write_summary(self, out: ReportDocumentWriter, all_sightings: list[QSighting]) -> None:
        summary = self._summary(all_sightings)
        out.start_table(TableStyle.SUMMARY, len(summary))
        out.start_row(RowStyle.PLAIN)
        for number, _label in summary:
            _cell(out, CellStyle.SUMMARY_NUMBER, number)
        out.end_row()
        out.start_row(RowStyle.PLAIN)
        for _number_text, label in summary:
            _cell(out, CellStyle.SUMMARY_LABEL, label)
        out.end_row()
        out.end_table()

    def _section_heading(self, out: ReportDocumentWriter, heading: str, *asides: str) -> None:
        out.start_block(BlockStyle.SECTION_HEADING)
        out.text(heading)
        for aside in asides:
            out.text(DOT_SEPARATOR)
            _span(out, SpanStyle.HEADING_ASIDE, aside)
        out.end_block()

    # ------------------------------------------------------------ the itinerary

    def _visit_info(self, key: VisitKey) -> VisitInfo | None:
        return self.data.visit_info.get(key)

    def _write_itinerary(self, out: ReportDocumentWriter) -> None:
        ordered = self._itinerary_order()
        if not ordered and len(self.trips) <= 1:
            return
        rows = self._itinerary_rows(self._with_trips(ordered))
        self._section_heading(out, "Itinerary")
        documented: dict[str, None] = {}
        so_far: set[Resolved] = set()
        table_open = False
        first_row_in_table = True
        for row in rows:
            if row.trip is not None:
                if table_open:
                    out.end_table()
                    table_open = False
                self._write_itinerary_trip(out, row.trip, documented)
                continue
            if not table_open:
                out.start_table(TableStyle.ITINERARY, 3)
                table_open = True
                first_row_in_table = True
            self._write_itinerary_day(out, row, first_row_in_table, so_far, documented)
            first_row_in_table = False
        if table_open:
            out.end_table()

    def _itinerary_order(self) -> list[VisitKey]:
        """Each day's visits, those with no time put first if the place was visited the day
        before, last if it's visited the day after, else among those with times."""
        by_date: dict[PartialDate, list[VisitKey]] = {}
        for key in self.visits:
            by_date.setdefault(key.date, []).append(key)
        dates = list(by_date)
        ordered: list[VisitKey] = []
        for i, current_date in enumerate(dates):
            today = by_date[current_date]
            if len(today) == 1:
                ordered.extend(today)
                continue
            previous = {k.location for k in by_date[dates[i - 1]]} if i > 0 else set()
            following = ({k.location for k in by_date[dates[i + 1]]} if i < len(dates) - 1
                         else set())  # fmt: skip
            middle = [k for k in today if k.start_time is not None]
            end: list[VisitKey] = []
            for key in today:
                if key.start_time is not None:
                    continue
                if key.location in previous:
                    ordered.append(key)
                elif key.location in following:
                    end.append(key)
                else:
                    middle.append(key)
            ordered.extend(middle)
            ordered.extend(end)
        return ordered

    def _with_trips(self, ordered: list[VisitKey]) -> list[QTrip | VisitKey]:
        """With several trips, each goes in before the first visit not before its start."""
        entries: list[QTrip | VisitKey] = []
        if len(self.trips) <= 1:
            entries.extend(ordered)
            return entries
        visit_index = 0
        trip_index = 0
        while visit_index < len(ordered) or trip_index < len(self.trips):
            if visit_index >= len(ordered):
                entries.append(self.trips[trip_index])
                trip_index += 1
            elif trip_index >= len(self.trips):
                entries.append(ordered[visit_index])
                visit_index += 1
            elif compare_partial_dates(self.trips[trip_index].start,
                                       ordered[visit_index].date) <= 0:  # fmt: skip
                entries.append(self.trips[trip_index])
                trip_index += 1
            else:
                entries.append(ordered[visit_index])
                visit_index += 1
        return entries

    def _itinerary_rows(self, entries: list[QTrip | VisitKey]) -> list[_ItineraryRow]:
        """A row per day, except a stay at one stop over several days (with no comments)
        has its own; back-to-back visits to a stop on a day are one entry."""
        rows: list[_ItineraryRow] = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            if isinstance(entry, QTrip):
                rows.append(_ItineraryRow(entry, None))
                i += 1
                continue
            visits = [entry]
            last = entry
            stop_key = self._stop_key(entry.location)
            has_comments = self._comments(self._visit_info(entry)) is not None
            for j in range(i + 1, len(entries)):
                later = entries[j]
                if isinstance(later, QTrip) or stop_key != self._stop_key(later.location):
                    break
                later_has = self._comments(self._visit_info(later)) is not None
                if later.date != last.date and (has_comments or later_has):
                    break
                has_comments = has_comments or later_has
                visits.append(later)
                last = later
                i = j
            visit = _ItineraryVisit(entry, last, visits)
            previous_row = rows[-1] if rows else None
            multi_day = entry.date != last.date
            if (not multi_day and previous_row is not None and previous_row.trip is None
                    and not previous_row.is_multi_day()
                    and previous_row.date() == entry.date):  # fmt: skip
                assert previous_row.visits is not None
                previous_row.visits.append(visit)
            else:
                rows.append(_ItineraryRow(None, [visit]))
            i += 1
        return rows

    def _write_itinerary_day(self, out: ReportDocumentWriter, row: _ItineraryRow,
                             first_in_table: bool, so_far: set[Resolved],
                             documented: dict[str, None]) -> None:  # fmt: skip
        """A day's rows: one per visit (the date and counts on the first), then rows for a
        visit's parts and comments; the day's time and distance go under the date."""
        assert row.visits is not None
        row_species: set[Resolved] = set()
        for visit in row.visits:
            for key in visit.visits:
                row_species |= self._species_by_visit.get(key, set())
        new_count = len(row_species - so_far)
        so_far |= row_species
        day_style = RowStyle.ITINERARY_FIRST_DAY if first_in_table else RowStyle.ITINERARY_DAY
        day_totals = self._day_totals(row)
        for index, visit in enumerate(row.visits):
            first_visit = index == 0
            out.start_row(day_style if first_visit else RowStyle.ITINERARY_CONTINUATION)
            if first_visit:
                out.start_cell(CellStyle.ITINERARY_DATE, 1)
                self._write_itinerary_date(out, row, visit)
            elif day_totals is not None:
                out.start_cell(CellStyle.ITINERARY_DAY_TOTALS, 1)
                out.text(day_totals)
                day_totals = None
            else:
                out.start_cell(CellStyle.ITINERARY_DATE, 1)
            out.end_cell()
            out.start_cell(CellStyle.ITINERARY_SITES, 1)
            self._write_itinerary_visit(out, visit, documented)
            out.end_cell()
            out.start_cell(CellStyle.ITINERARY_COUNTS, 1)
            if first_visit and row_species:
                out.text(f"{_number(len(row_species))} species \u00b7 {_number(new_count)} new")
            out.end_cell()
            out.end_row()
            parts = ", ".join(dict.fromkeys(
                part for key in visit.visits
                if (part := self.stops.part(key.location)) is not None))  # fmt: skip
            if parts:
                _itinerary_note_row(out, CellStyle.ITINERARY_PARTS, parts, day_totals)
                day_totals = None
            comments = DOT_SEPARATOR.join(dict.fromkeys(
                comment for key in visit.visits
                if (comment := self._comments(self._visit_info(key))) is not None))  # fmt: skip
            if comments:
                _itinerary_note_row(out, CellStyle.ITINERARY_COMMENTS, comments, day_totals)
                day_totals = None
        if day_totals is not None:
            _itinerary_note_row(out, CellStyle.ITINERARY_SPACER, "", day_totals)

    def _write_itinerary_date(self, out: ReportDocumentWriter, row: _ItineraryRow,
                              visit: _ItineraryVisit) -> None:  # fmt: skip
        date = visit.first.date
        if row.is_multi_day():
            out.text(f"{self._date_text(date)} \u2013 {self._date_text(visit.last.date)}")
        else:
            day = weekday(date)
            out.text(f"{day} {self._date_text(date)}" if day else self._date_text(date))

    def _write_itinerary_visit(self, out: ReportDocumentWriter, visit: _ItineraryVisit,
                               documented: dict[str, None]) -> None:  # fmt: skip
        time_range = self._time_range(visit.first, visit.last)
        if time_range is not None:
            _span(out, SpanStyle.SECONDARY, time_range)
            out.text(" ")
        stop = self.stops.stop(visit.first.location)
        name = stop.name
        index = name.lower().find(stop.short_name.lower())
        if self.options.species_list and stop.shortened and index >= 0:
            out.text(name[:index])
            _span(out, SpanStyle.BOLD, name[index : index + len(stop.short_name)])
            out.text(name[index + len(stop.short_name) :])
            documented[stop.key] = None
        else:
            out.text(name)
            self._write_stop_short_name(out, visit.first.location, documented)
        infos = [info for key in visit.visits if (info := self._visit_info(key)) is not None]
        details = list(dict.fromkeys(NOTABLE_PROTOCOLS[info.observation_type] for info in infos
                                     if info.observation_type in NOTABLE_PROTOCOLS))  # fmt: skip
        distance = self._distance_text(infos)
        if distance is not None:
            details.append(distance)
        if time_range is None:
            duration = _duration_text(infos)
            if duration is not None:
                details.append(duration)
        if details:
            out.text(" ")
            _span(out, SpanStyle.SECONDARY, DOT_SEPARATOR.strip() + " "
                  + DOT_SEPARATOR.join(details))  # fmt: skip

    def _day_totals(self, row: _ItineraryRow) -> str | None:
        assert row.visits is not None
        infos = [info for visit in row.visits for key in visit.visits
                 if (info := self._visit_info(key)) is not None]  # fmt: skip
        totals = [text for text in (_duration_text(infos), self._distance_text(infos)) if text]
        return DOT_SEPARATOR.join(totals) if totals else None

    def _distance_text(self, infos: list[VisitInfo]) -> str | None:
        kilometers = _java_sum(info.distance_km for info in infos if info.distance_km is not None)
        if kilometers <= 0:
            return None
        if self.options.use_miles:
            return f"{_one_decimal(kilometers * MILES_PER_KILOMETER)} mi"
        return f"{_one_decimal(kilometers)} km"

    def _time_range(self, visit: VisitKey, last: VisitKey) -> str | None:
        if visit.start_time is None:
            return None
        start = short_time(visit.start_time)
        if last.start_time is None:
            return start
        end = last.start_time
        last_info = self._visit_info(last)
        if last_info is not None and last_info.duration_minutes is not None:
            end = _plus_minutes(end, last_info.duration_minutes)
        elif last is visit:
            return start
        return f"{start} \u2013 {short_time(end)}"

    def _write_stop_short_name(self, out: ReportDocumentWriter, location_id: str,
                               documented: dict[str, None]) -> None:  # fmt: skip
        if not self.options.species_list or location_id not in self.stops:
            return
        stop = self.stops.stop(location_id)
        if stop.shortened and stop.key not in documented:
            documented[stop.key] = None
            out.text(" ")
            _span(out, SpanStyle.SITE_CODE, stop.short_name)

    def _stop_key(self, location_id: str) -> str:
        return self.stops.stop(location_id).key if location_id in self.stops else location_id

    def _write_itinerary_trip(self, out: ReportDocumentWriter, trip: QTrip,
                              documented: dict[str, None]) -> None:  # fmt: skip
        out.start_block(BlockStyle.TRIP_HEADING)
        if trip.start == trip.end:
            dates = self._date_text(trip.start)
        else:
            dates = f"{self._date_text(trip.start)} \u2013 {self._date_text(trip.end)}"
        if trip.location_xml_id is not None:
            out.text(f"{dates}: {self._location_name(trip.location_xml_id)}")
            self._write_stop_short_name(out, trip.location_xml_id, documented)
        else:
            out.text(dates)
        out.end_block()
        self._write_trip_notes(out, trip)

    @staticmethod
    def _comments(info: VisitInfo | None) -> str | None:
        if info is None or info.comments is None:
            return None
        comments = info.comments
        index = comments.find("<br />Submitted from")
        if index >= 0:
            comments = comments[:index]
        comments = _guava_trim(comments)
        return comments or None

    # ------------------------------------------------------------ the species table

    def _write_species_table(self, out: ReportDocumentWriter,
                             all_sightings: list[QSighting]) -> None:  # fmt: skip
        dates = list(dict.fromkeys(key.date for key in self.visits))
        direct_trips = self._trips_with_direct_sightings(all_sightings)
        if not dates and not direct_trips:
            return
        columns = [_Column(date=date) for date in dates]
        columns += [_Column(trip=trip) for trip in direct_trips]
        columns.sort(key=cmp_to_key(_by_column_date))
        self._section_heading(out, "Species by day")
        two_names = not self.options.species_list and self.names_order in (
            COMMON_FIRST,
            SCIENTIFIC_FIRST,
        )
        name_columns = 2 if two_names else 1
        column_count = len(columns) + name_columns
        out.start_table(TableStyle.SPECIES, column_count)
        out.start_table_header()
        out.start_row(RowStyle.PLAIN)
        out.start_cell(CellStyle.SPECIES_HEADER, name_columns)
        out.text("Species")
        out.end_cell()
        for column in columns:
            _cell(out, CellStyle.COLUMN_HEADER, self._column_header(column))
        out.end_row()
        out.end_table_header()
        per_column = [0] * len(columns)
        new_per_column = [0] * len(columns)
        first_columns: list[int] = []
        out.start_table_body()
        current_family: Taxon | None = None
        shaded = False
        for entry in self._counted(self.entries):
            if entry.family is not None and entry.family is not current_family:
                current_family = entry.family
                out.start_row(RowStyle.FAMILY)
                out.start_cell(CellStyle.FAMILY, column_count)
                out.text(self._family_name(current_family))
                out.end_cell()
                out.end_row()
                shaded = False
            out.start_row(RowStyle.SPECIES_SHADED if shaded else RowStyle.SPECIES)
            shaded = not shaded
            self._write_species_names(out, entry.display_taxon, two_names)
            first_column = self._write_species_counts(out, entry, columns, per_column)
            first_columns.append(first_column)
            out.end_row()
        out.end_table_body()
        for first_column in first_columns:
            if first_column >= 0:
                new_per_column[first_column] += 1
        out.start_table_footer()
        _totals_row(out, RowStyle.TOTALS, "Species", per_column, name_columns)
        _totals_row(out, RowStyle.NEW_TOTALS, "New for trip", new_per_column, name_columns)
        out.end_table_footer()
        out.end_table()

    def _write_species_names(self, out: ReportDocumentWriter, taxon: Resolved,
                             two_names: bool) -> None:  # fmt: skip
        style = CellStyle.LIFER_SPECIES_NAME if self._in_bold(taxon) else CellStyle.SPECIES_NAME
        order = self.names_order
        if order == COMMON_FIRST:
            _name_cell(out, style, _common_name_at_least_at_group(taxon), italic=False)
            if two_names:
                _name_cell(out, style, resolved_full_name(taxon), italic=True)
        elif order == SCIENTIFIC_FIRST:
            _name_cell(out, style, resolved_full_name(taxon), italic=True)
            if two_names:
                _name_cell(out, style, _common_name_at_least_at_group(taxon), italic=False)
        elif order == COMMON_ONLY:
            _name_cell(out, style, _common_name_at_least_at_group(taxon), italic=False)
        else:
            _name_cell(out, style, resolved_full_name(taxon), italic=True)

    def _write_species_counts(self, out: ReportDocumentWriter, entry: _SpeciesEntry,
                              columns: list[_Column], per_column: list[int]) -> int:  # fmt: skip
        """A species' cell in each column; returns the first column where it counts."""
        by_date: dict[PartialDate, list[QSighting]] = defaultdict(list)
        by_trip: dict[str, list[QSighting]] = defaultdict(list)
        for taxon in entry.taxa:
            for sighting in self.results.sightings_of(taxon):
                if sighting.date is not None:
                    by_date[sighting.date].append(sighting)
                if sighting.trip is not None:
                    by_trip[sighting.trip.xml_id].append(sighting)
        first_column = -1
        for i, column in enumerate(columns):
            if column.trip is not None:
                found = by_trip.get(column.trip.xml_id, [])
            else:
                assert column.date is not None
                found = by_date.get(column.date, [])
            text = _text_for_sightings(found)
            if any(self.countable(s) for s in found):
                per_column[i] += 1
                if first_column < 0:
                    first_column = i
            _cell(out, CellStyle.FAINT_DATA if text == "X" else CellStyle.DATA, text)
        return first_column

    def _column_header(self, column: _Column) -> str:
        trip = column.trip
        if trip is not None:
            if trip.name:
                return trip.name
            if trip.start == trip.end:
                return self._date_text(trip.start)
            return f"{self._date_text(trip.start)} \u2013 {self._date_text(trip.end)}"
        assert column.date is not None
        day = weekday(column.date)
        text = self._date_text(column.date)
        return f"{day} {text}" if day else text

    def _trips_with_direct_sightings(self, all_sightings: list[QSighting]) -> list[QTrip]:
        trips = list(dict.fromkeys(s.trip for s in all_sightings if s.trip is not None))
        return sorted(trips, key=cmp_to_key(_by_trip_start))

    # ------------------------------------------------------------ the species list

    def _write_species_list(self, out: ReportDocumentWriter) -> None:
        used_stops: dict[Stop, None] = {}
        self._write_taxonomy_species(out, self.results.taxonomy, self.entries, used_stops)
        shortened = sorted((stop for stop in used_stops if stop.shortened),
                           key=lambda stop: _case_insensitive(stop.short_name))  # fmt: skip
        if not self.options.itinerary and shortened:
            _block(out, BlockStyle.SITE_KEY, ", ".join(
                f"{stop.short_name} - {stop.name}" for stop in shortened))  # fmt: skip
        self._write_legend(out)

    def _write_taxonomy_species(self, out: ReportDocumentWriter, taxonomy: Taxonomy,
                                entries: list[_SpeciesEntry],
                                used_stops: dict[Stop, None]) -> None:  # fmt: skip
        counted = self._counted(entries)
        lifers = (sum(1 for entry in counted if self._is_lifer(entry.species))
                  if self.options.lifers_in_bold else 0)  # fmt: skip
        species_text = ("1 species" if len(counted) == 1
                        else f"{_number(len(counted))} species")  # fmt: skip
        if lifers > 0:
            lifer_text = f"{_number(lifers)} lifer" + ("" if lifers == 1 else "s")
            self._section_heading(out, taxonomy.name, species_text, lifer_text)
        else:
            self._section_heading(out, taxonomy.name, species_text)
        current_family: Taxon | None = None
        list_open = False
        for i, entry in enumerate(counted):
            if not list_open or (entry.family is not None and entry.family is not current_family):
                if list_open:
                    out.end_numbered_list()
                if entry.family is not None:
                    current_family = entry.family
                    self._write_family_heading(out, current_family)
                out.start_numbered_list(i + 1)
                list_open = True
            self._write_entry(out, entry, mark_lifers=True, used_stops=used_stops)
        if list_open:
            out.end_numbered_list()
        uncounted = [entry for entry in entries if entry not in counted]
        if uncounted:
            _block(out, BlockStyle.FAMILY_HEADING, "Not counted")
            out.start_bulleted_list()
            for entry in uncounted:
                self._write_entry(out, entry, mark_lifers=False, used_stops=used_stops)
            out.end_bulleted_list()

    def _write_entry(self, out: ReportDocumentWriter, entry: _SpeciesEntry, *,
                     mark_lifers: bool, used_stops: dict[Stop, None]) -> None:  # fmt: skip
        out.start_list_item()
        display = entry.display_taxon
        self._write_taxon_text(out, display, mark_lifers)
        if len(entry.taxa) == 1:
            self._write_sighting_text(out, self.results.sightings_of(display), used_stops,
                                      on_new_line=True)  # fmt: skip
        else:
            for taxon in entry.taxa:
                out.line_break()
                out.start_span(SpanStyle.SUB_ENTRY)
                self._write_abbreviated_taxon_text(out, entry.species, taxon, mark_lifers)
                out.end_span()
                self._write_sighting_text(out, self.results.sightings_of(taxon), used_stops,
                                          on_new_line=False)  # fmt: skip
        out.end_list_item()

    def _write_family_heading(self, out: ReportDocumentWriter, family: Taxon) -> None:
        out.start_block(BlockStyle.FAMILY_HEADING)
        order = self.names_order
        if order in (COMMON_FIRST, COMMON_ONLY):
            out.text(family.common_name if family.common_name is not None else family.name)
            if order == COMMON_FIRST and family.common_name is not None:
                out.text(" ")
                _span(out, SpanStyle.FAMILY_SECONDARY_NAME, family.name)
        else:
            out.text(family.name)
            if order == SCIENTIFIC_FIRST and family.common_name is not None:
                out.text(" ")
                _span(out, SpanStyle.FAMILY_SECONDARY_NAME, family.common_name)
        out.end_block()

    def _family_name(self, family: Taxon) -> str:
        scientific = self.names_order not in (COMMON_FIRST, COMMON_ONLY)
        if scientific or family.common_name is None:
            return family.name
        return family.common_name

    def _write_legend(self, out: ReportDocumentWriter) -> None:
        if not self._legend and not self._used_users:
            return
        out.start_block(BlockStyle.LEGEND)
        first = True
        for item in _LEGEND_ORDER:
            if item not in self._legend:
                continue
            if not first:
                out.text(DOT_SEPARATOR)
            first = False
            if item == "LIFER":
                _span(out, SpanStyle.LIFER_MARKER, LIFER_MARKER)
                out.text(" ")
                out.text("lifer")
            elif item == "ENDEMIC":
                _span(out, SpanStyle.ENDEMIC_MARKER, "E")
                out.text(" ")
                out.text("endemic")
            elif item == "INTRODUCED":
                _span(out, SpanStyle.INTRODUCED_MARKER, "I")
                out.text(" ")
                out.text("introduced")
            elif item == "PHOTO":
                _span(out, SpanStyle.SITE_CODE, PHOTO_MARKER)
                out.text(" ")
                out.text("photographed (linked to the photo, if online)")
            else:
                marker, meaning = {
                    "HEARD_ONLY": (HEARD_ONLY_MARKER, "heard only"),
                    "COUNT": ("(2)", "number recorded"),
                    "MALE": (MALE_MARKER, "male"),
                    "FEMALE": (FEMALE_MARKER, "female"),
                    "ADULT": ("ad.", "adult"),
                    "IMMATURE": ("imm.", "immature"),
                }[item]  # fmt: skip
                out.text(f"{marker} {meaning}")
        for user in self._used_users:
            if not first:
                out.text(DOT_SEPARATOR)
            first = False
            name, _abbreviation = self.data.users.get(user, (None, None))
            out.text(f"{self._user_abbreviation(user)} {name or ''}")
        out.end_block()

    def _write_sighting_text(self, out: ReportDocumentWriter, sightings: list[QSighting],
                             used_stops: dict[Stop, None], *,
                             on_new_line: bool) -> None:  # fmt: skip
        """``writeTaxonListSightingText``: the stops (with what was recorded), then notes."""
        stops: dict[Stop, None] = {}
        keys = [key for s in sightings if (key := visit_key(s)) is not None]
        for key in sorted(keys, key=cmp_to_key(compare_visits)):
            if key.location in self.stops:
                stops[self.stops.stop(key.location)] = None
        on_trips = sorted((s for s in sightings if s.trip is not None),
                          key=cmp_to_key(_by_sighting_trip_start))  # fmt: skip
        for sighting in on_trips:
            location = sighting.location_xml_id
            if location is not None and location in self.stops:
                stops[self.stops.stop(location)] = None
        if stops:
            if on_new_line:
                out.line_break()
            else:
                out.text("  ")
            out.start_span(SpanStyle.SECONDARY)
            if len(stops) > MAXIMUM_LISTED_STOPS:
                days = len({key.date for key in keys})
                all_days = len({key.date for key in self.visits})
                out.text(f"At {_number(len(stops))} of {_number(self.stops.size())} sites, "
                         f"on {_number(days)} of {_number(all_days)} days")  # fmt: skip
            else:
                first = True
                for stop in stops:
                    at_stop = [s for s in sightings if s.location_xml_id is not None
                               and s.location_xml_id in self.stops
                               and self.stops.stop(s.location_xml_id) == stop]  # fmt: skip
                    if not first:
                        out.text(", ")
                    first = False
                    used_stops[stop] = None
                    _span(out, SpanStyle.SITE_CODE, stop.short_name)
                    self._write_stop_details(out, at_stop)
            out.end_span()
        in_note_order = [s for stop in stops for s in sightings if self._stop_of(s) == stop]
        in_note_order += [s for s in sightings if self._stop_of(s) is None]
        for sighting in in_note_order:
            if not sighting.description:
                continue
            out.line_break()
            out.start_span(SpanStyle.NOTE)
            stop_of = self._stop_of(sighting)
            if stop_of is not None and len(stops) > 1:
                _span(out, SpanStyle.NOTE_SITE_CODE, stop_of.short_name)
                out.text(" ")
            out.text(sighting.description)
            out.end_span()

    def _stop_of(self, sighting: QSighting) -> Stop | None:
        location = sighting.location_xml_id
        return (
            self.stops.stop(location) if location is not None and location in self.stops else None
        )

    def _write_stop_details(self, out: ReportDocumentWriter, sightings: list[QSighting]) -> None:
        """What was recorded at a stop, in parentheses ("(3, ♂ imm., H, *Dead*, AW)"), then
        "P" or "P1 P2" linked to the photos online."""
        parts: list[str] = []
        italic: list[str] = []
        count = _total_count(sightings)
        if count > 0:
            parts.append(_number(count))
            self._legend.add("COUNT")
        sex_age = []
        for flag, marker, item in (("male", MALE_MARKER, "MALE"),
                                   ("female", FEMALE_MARKER, "FEMALE"),
                                   ("adult", "ad.", "ADULT"),
                                   ("immature", "imm.", "IMMATURE")):  # fmt: skip
            if any(getattr(s, flag) for s in sightings):
                sex_age.append(marker)
                self._legend.add(item)
        if sex_age:
            parts.append(" ".join(sex_age))
        if sightings and all(s.heard_only for s in sightings):
            parts.append(HEARD_ONLY_LETTER)
            self._legend.add("HEARD_ONLY")
        statuses = sorted({s.status for s in sightings if s.status not in UNMENTIONED_STATUSES},
                          key=SIGHTING_STATUSES.index)  # fmt: skip
        italic.extend(STATUS_TEXT[status] for status in statuses)
        breeding = [s.breeding for s in sightings if s.breeding not in NON_BREEDING_CODES]
        if breeding:
            italic.append(BREEDING_TEXT[min(breeding, key=BREEDING_CODES.index)])
        stop_users = list(dict.fromkeys(u for s in sightings for u in s.user_order))
        observers = []
        if (len(self._report_users) > 1 and stop_users
                and frozenset(stop_users) != self._report_users):  # fmt: skip
            for user in stop_users:
                observers.append(self._user_abbreviation(user))
                self._used_users[user] = None
        if parts or italic or observers:
            out.text(" ")
            out.start_span(SpanStyle.COUNT)
            out.text("(" + ", ".join(parts))
            first = not parts
            for text in italic:
                out.text("" if first else ", ")
                first = False
                _span(out, SpanStyle.NOTE, text)
            if observers:
                out.text(("" if first else ", ") + " ".join(observers))
            out.text(")")
            out.end_span()
        self._write_photo_links(out, sightings)

    def _write_photo_links(self, out: ReportDocumentWriter, sightings: list[QSighting]) -> None:
        photos = [photo for s in sightings for photo in self.data.photos.get(s.row, [])]
        web = [photo for photo in photos if is_web_address(photo.uri)]
        web.sort(key=lambda photo: not photo.favorite)
        seen: set[str] = set()
        unique = []
        for photo in web:
            if photo.uri not in seen:
                seen.add(photo.uri)
                unique.append(photo)
        if not unique:
            if any(s.photographed or self.data.photos.get(s.row) for s in sightings):
                out.text(" ")
                _span(out, SpanStyle.SITE_CODE, PHOTO_MARKER)
                self._legend.add("PHOTO")
            return
        self._legend.add("PHOTO")
        for i, photo in enumerate(unique):
            out.text(" ")
            out.start_link(ascii_uri(photo.uri), photo.name)
            _span(out, SpanStyle.SITE_CODE,
                  PHOTO_MARKER if len(unique) == 1 else f"{PHOTO_MARKER}{i + 1}")  # fmt: skip
            out.end_link()

    def _user_abbreviation(self, user: str) -> str:
        name, abbreviation = self.data.users.get(user, (None, None))
        return abbreviation if abbreviation else (name or "")

    # ------------------------------------------------------------ names and markers

    def _in_bold(self, taxon: Resolved) -> bool:
        return self.options.lifers_in_bold and self._is_lifer(taxon)

    def _is_lifer(self, taxon: Resolved) -> bool:
        species = taxon.parent_of_at_least_type(TaxonType.SPECIES)
        return species.type is SightingTaxonType.SINGLE and species.id in self.lifer_ids

    def _checklist_status(self, taxon: Resolved) -> str | None:
        checklist = self.results.checklist
        if checklist is None:
            return None
        species = taxon.parent_of_at_least_type(TaxonType.SPECIES)
        if species.type is not SightingTaxonType.SINGLE:
            return None
        return checklist.status(species)

    def _write_taxon_text(self, out: ReportDocumentWriter, taxon: Resolved,
                          mark_lifers: bool) -> None:  # fmt: skip
        lifer = mark_lifers and self._in_bold(taxon)
        if lifer:
            _span(out, SpanStyle.LIFER_MARKER, LIFER_MARKER)
            out.text(" ")
            self._legend.add("LIFER")
            out.start_span(SpanStyle.BOLD)
        order = self.names_order
        if order == COMMON_FIRST:
            out.text(_common_name_at_least_at_group(taxon))
            if lifer:
                out.end_span()
            out.text(" ")
            _span(out, SpanStyle.SCIENTIFIC_NAME, resolved_full_name(taxon))
        elif order == COMMON_ONLY:
            out.text(resolved_common_name(taxon))
            if lifer:
                out.end_span()
        elif order == SCIENTIFIC_FIRST:
            _span(out, SpanStyle.ITALIC, resolved_full_name(taxon))
            if lifer:
                out.end_span()
            out.text(" ")
            _span(out, SpanStyle.SECONDARY_NAME, _common_name_at_least_at_group(taxon))
        else:
            _span(out, SpanStyle.ITALIC, resolved_full_name(taxon))
            if lifer:
                out.end_span()
        self._write_checklist_info(out, taxon)
        self._write_taxon_status(out, taxon)

    def _write_checklist_info(self, out: ReportDocumentWriter, taxon: Resolved) -> None:
        status = self._checklist_status(taxon)
        if status == "ENDEMIC":
            out.text(" ")
            _span(out, SpanStyle.ENDEMIC_MARKER, "E")
            self._legend.add("ENDEMIC")
        elif status == "INTRODUCED":
            out.text(" ")
            _span(out, SpanStyle.INTRODUCED_MARKER, "I")
            self._legend.add("INTRODUCED")
        elif status in ("RARITY", "RARITY_FROM_INTRODUCED"):
            _status_text(out, SpanStyle.STATUS, "Rarity")
        elif status == "PROVISIONAL":
            _status_text(out, SpanStyle.STATUS, "Provisional")
        elif status == "ESCAPED":
            _status_text(out, SpanStyle.STATUS, "Not established")

    def _write_taxon_status(self, out: ReportDocumentWriter, taxon: Resolved) -> None:
        if not self.options.show_status:
            return
        status = resolved_status(taxon)
        if status in ("LC", "NT"):
            return
        style = SpanStyle.THREATENED_STATUS if status in THREATENED_STATUSES else SpanStyle.STATUS
        _status_text(out, style, IUCN_TEXT[status])

    def _write_abbreviated_taxon_text(self, out: ReportDocumentWriter, species: Resolved,
                                      taxon: Resolved, mark_lifers: bool) -> None:  # fmt: skip
        lifer = mark_lifers and self.options.lifers_in_bold and self._is_lifer(taxon)
        if lifer:
            out.start_span(SpanStyle.BOLD)
        order = self.names_order
        name = _resolved_name(taxon)
        if order == COMMON_FIRST:
            if not _has_common_name(taxon):
                _span(out, SpanStyle.ITALIC, name)
            else:
                out.text(_abbreviated_common_name(species, taxon))
                out.text(" ")
                _span(out, SpanStyle.SCIENTIFIC_NAME, name)
        elif order == COMMON_ONLY:
            out.text(_abbreviated_common_name(species, taxon))
        elif order == SCIENTIFIC_FIRST:
            _span(out, SpanStyle.ITALIC, name)
            if not _has_common_name(taxon):
                out.text(" ")
                _span(out, SpanStyle.SECONDARY_NAME, _abbreviated_common_name(species, taxon))
        else:
            _span(out, SpanStyle.ITALIC, name)
        if lifer:
            out.end_span()
        self._write_taxon_status(out, taxon)

    # ------------------------------------------------------------ dates and stops

    def _date_text(self, date: PartialDate) -> str:
        month, day = date.get(PartialField.MONTH), date.get(PartialField.DAY)
        if self._all_same_year and day is not None and month is not None:
            return f"{month}/{day}"
        return short_date(date)

    def _compute_species_by_visit(self) -> dict[VisitKey, set[Resolved]]:
        found: dict[VisitKey, set[Resolved]] = defaultdict(set)
        for entry in self.entries:
            for taxon in entry.taxa:
                for sighting in self.results.sightings_of(taxon):
                    key = visit_key(sighting)
                    if key is not None and self.countable(sighting):
                        found[key].add(entry.species)
        return found

    def _compute_stops(self, all_sightings: list[QSighting]) -> TripStops:
        by_date: dict[PartialDate, list[str]] = {}
        for key in self.visits:
            by_date.setdefault(key.date, []).append(key.location)
        days: list[list[str]] = list(by_date.values())
        days += [[trip.location_xml_id] for trip in self.trips if trip.location_xml_id]
        days += [[s.location_xml_id] for s in all_sightings
                 if s.trip is not None and s.location_xml_id is not None]  # fmt: skip
        return TripStops(self.places, days, self._location_name)


# ------------------------------------------------------------------ helpers


def _by_column_date(left: _Column, right: _Column) -> int:
    return compare_partial_dates(left.sort_date, right.sort_date)


def _by_trip_start(left: QTrip, right: QTrip) -> int:
    return compare_partial_dates(left.start, right.start)


def _by_sighting_trip_start(left: QSighting, right: QSighting) -> int:
    assert left.trip is not None and right.trip is not None
    return compare_partial_dates(left.trip.start, right.trip.start)


def _year(date: PartialDate) -> int:
    year = date.get(PartialField.YEAR)
    return 0 if year is None else year


def _case_insensitive(text: str) -> str:
    """``String.CASE_INSENSITIVE_ORDER``: compares upper-cased then lower-cased chars."""
    return "".join(c.upper().lower() if len(c.upper()) == 1 else c for c in text)


def _block(out: ReportDocumentWriter, style: BlockStyle, text: str) -> None:
    out.start_block(style)
    out.text(text)
    out.end_block()


def _span(out: ReportDocumentWriter, style: SpanStyle, text: str) -> None:
    out.start_span(style)
    out.text(text)
    out.end_span()


def _cell(out: ReportDocumentWriter, style: CellStyle, text: str) -> None:
    out.start_cell(style, 1)
    out.text(text)
    out.end_cell()


def _name_cell(out: ReportDocumentWriter, style: CellStyle, text: str, *, italic: bool) -> None:
    out.start_cell(style, 1)
    if italic:
        _span(out, SpanStyle.ITALIC, text)
    else:
        out.text(text)
    out.end_cell()


def _totals_row(out: ReportDocumentWriter, style: RowStyle, label: str, counts: list[int],
                name_columns: int) -> None:  # fmt: skip
    out.start_row(style)
    out.start_cell(CellStyle.TOTAL_LABEL, name_columns)
    out.text(label)
    out.end_cell()
    for count in counts:
        _cell(out, CellStyle.TOTAL, _number(count))
    out.end_row()


def _itinerary_note_row(out: ReportDocumentWriter, style: CellStyle, text: str,
                        day_totals: str | None) -> None:  # fmt: skip
    out.start_row(RowStyle.ITINERARY_COMMENTS)
    if day_totals is not None:
        out.start_cell(CellStyle.ITINERARY_DAY_TOTALS, 1)
        out.text(day_totals)
    else:
        out.start_cell(CellStyle.ITINERARY_SPACER, 1)
    out.end_cell()
    out.start_cell(style, 2)
    out.text(text)
    out.end_cell()
    out.end_row()


def _status_text(out: ReportDocumentWriter, style: SpanStyle, text: str) -> None:
    out.text(" ")
    _span(out, style, text)


def _duration_text(infos: list[VisitInfo]) -> str | None:
    minutes = sum(info.duration_minutes for info in infos if info.duration_minutes is not None)
    if minutes <= 0:
        return None
    hours, remaining = divmod(minutes, 60)
    if hours == 0:
        return f"{remaining} min"
    if remaining == 0:
        return f"{hours} h"
    return f"{hours} h {remaining} min"


def _total_count(sightings: Iterable[QSighting]) -> int:
    total = 0
    for sighting in sightings:
        if sighting.count is not None:
            number = ApproximateNumber.parse(sighting.count)
            if number is not None:
                total += number.number
    return total


def _text_for_sightings(sightings: list[QSighting]) -> str:
    if not sightings:
        return ""
    if all(s.heard_only for s in sightings):
        return HEARD_ONLY_MARKER
    count = _total_count(sightings)
    return _number(count) if count > 0 else "X"


def _has_common_name(resolved: Resolved) -> bool:
    return all(taxon.common_name is not None for taxon in resolved.taxa)


def _resolved_name(resolved: Resolved) -> str:
    """``Resolved.getName``: the scientific name, a sp.'s joined ("a/b")."""
    if resolved.type is SightingTaxonType.SINGLE:
        return resolved.taxon.name
    joiner = " x " if resolved.type is SightingTaxonType.HYBRID else "/"
    return joiner.join(taxon.name for taxon in ordered_taxa(resolved))


def _common_name_at_least_at_group(taxon: Resolved) -> str:
    if taxon.smallest_type is not TaxonType.SUBSPECIES:
        return resolved_common_name(taxon)
    parent = taxon.parent_of_at_least_type(TaxonType.GROUP)
    return resolved_common_name(parent.resolve_internal(taxon.taxa[0].taxonomy))


def _abbreviated_common_name(species: Resolved, taxon: Resolved) -> str:
    species_name = resolved_common_name(species)
    name = resolved_common_name(taxon)
    if name.startswith(species_name):
        name = name[len(species_name) :].strip()
    return name


def _gather_entries(taxa: list[Resolved]) -> list[_SpeciesEntry]:
    """``gatherSpeciesEntries``: taxa (in taxonomic order, with families) by species."""
    family_by_species: dict[Resolved, Taxon | None] = {}
    taxa_by_species: dict[Resolved, list[Resolved]] = {}
    family: Taxon | None = None
    for taxon in taxa:
        if taxon.smallest_type is TaxonType.FAMILY:
            family = taxon.taxon
            continue
        if taxon.smallest_type > TaxonType.SPECIES:
            continue
        if taxon.smallest_type is TaxonType.SPECIES:
            species = taxon
        else:
            species = taxon.parent_of_at_least_type(TaxonType.SPECIES).resolve_internal(
                taxon.taxa[0].taxonomy)  # fmt: skip
        family_by_species.setdefault(species, family)
        found = taxa_by_species.setdefault(species, [])
        if taxon not in found:
            found.append(taxon)
    return [_SpeciesEntry(family_by_species[species], species, tuple(found))
            for species, found in taxa_by_species.items()]  # fmt: skip


# ------------------------------------------------------------------ SaveAsTripReportAction


def lifer_ids(results: QueryResults, query_list: QueryList, countable: Predicate) -> set[str]:
    """``computeLiferTaxonIds``: species in the report not seen anywhere in the list before
    the report's earliest date."""
    resolve = results.resolve
    assert resolve is not None
    earliest: PartialDate | None = None
    in_report: set[str] = set()
    for sighting in results.all_sightings():
        if sighting.taxonomy_id is not None or not countable(sighting):
            continue
        start = sighting.start_date
        if start is not None and (earliest is None or compare_partial_dates(start, earliest) < 0):
            earliest = start
        resolved = resolve(sighting.taxon)
        if resolved is None:
            continue
        species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
        if species.type is SightingTaxonType.SINGLE:
            in_report.add(species.id)
    if earliest is None:
        return set()
    seen_before: set[str] = set()
    for sighting in query_list.sightings:
        end = sighting.end_date
        if end is None or not before(earliest, end):
            continue
        if sighting.taxonomy_id is not None or not countable(sighting):
            continue
        resolved = resolve(sighting.taxon)
        if resolved is None:
            continue
        species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
        if species.type is SightingTaxonType.SINGLE:
            seen_before.add(species.id)
    return in_report - seen_before


def matching_trips(results: QueryResults, trips: list[QTrip],
                   query_list: QueryList) -> list[QTrip]:  # fmt: skip
    """``matchingTrips``: the trips of the report's sightings, or whose dates (and place)
    take in one of its undated-by-trip sightings, in the order found."""
    found: dict[str, QTrip] = {}
    remaining: list[QTrip | None] = list(trips)
    predicates: list[Callable[[QSighting], bool] | None] = [
        _trip_predicate(trip, query_list) for trip in trips
    ]
    for sighting in results.all_sightings():
        if sighting.trip is not None:
            if sighting.trip.xml_id not in found:
                found[sighting.trip.xml_id] = sighting.trip
                for i, trip in enumerate(remaining):
                    if trip is not None and trip.xml_id == sighting.trip.xml_id:
                        remaining[i] = None
                        predicates[i] = None
        else:
            for i, predicate in enumerate(predicates):
                if predicate is not None and predicate(sighting):
                    trip = remaining[i]
                    assert trip is not None
                    found.setdefault(trip.xml_id, trip)
                    remaining[i] = None
                    predicates[i] = None
    return list(found.values())


def _trip_predicate(trip: QTrip, query_list: QueryList) -> Callable[[QSighting], bool]:
    within = query_list.places_within(trip.location_xml_id) if trip.location_xml_id else None

    def predicate(sighting: QSighting) -> bool:
        start, end = sighting.start_date, sighting.end_date
        if start is None or not after_or_equals(trip.start, start):
            return False
        if end is None or not before_or_equals(trip.end, end):
            return False
        return within is None or sighting.location_xml_id in within

    return predicate


def trip_report(*, context: EngineContext, checklists: Checklists, data: ReportListData,
                query_json: str, options: TripReportOptions,
                names_preference: str = COMMON_FIRST,
                trips: list[QTrip] | None = None) -> TripReport:  # fmt: skip
    """``SaveAsTripReportAction.actionPerformed`` on the Reports screen's query (``trips``:
    the trips to report on, else those the sightings belong to)."""
    query, results, root = run_report_query(context, checklists, query_json, data.users,
                                            only_countable=False,
                                            include_incompatible=True)  # fmt: skip
    places = list_place_names(context.query_list, checklists)
    name = query_name(query, name_sources(places, data.users, context.taxonomy))
    visits = report_visits(results)
    if len(visits) > MAXIMUM_VISITS_FOR_SPECIES_TABLE or not visits:
        options = replace(options, species_table=False)
    countable = CountingPreferences().countable(StoredQuery(()), context.undescribed())
    if trips is None:
        trips = matching_trips(results, data.trips, context.query_list)
    return TripReport(
        results=results, data=data, places=places, root=root,
        names_order=names_order(names_preference, options.include_scientific),
        options=options, name=name, trips=trips,
        lifer_ids=lifer_ids(results, context.query_list, countable), countable=countable,
    )  # fmt: skip


def names_order(preference: str, include_scientific: bool) -> str:
    """``TripReportDialog.getScientificOrCommonFromConfiguration``."""
    if include_scientific:
        return COMMON_FIRST if preference == COMMON_ONLY else preference
    return COMMON_ONLY

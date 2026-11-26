"""eBird Record Format export, as Scythebill's Save for eBird writes it.

Ported from Scythebill's ``model/.../export/EBirdCsvExport.java`` and
``ui/.../panels/reports/EbirdExportAction.java``. The query runs in Clements at group depth
(eBird's taxonomy, no subspecies). Sightings are written oldest first, then in taxonomic
order, one line each, in eBird's 19 columns, with no header. A sighting is left out with no
place, a place that is a built-in region or private, or a rejected or uncertain record.
Sightings without a full date become "list-building" records (1/1/1900, Incidental).
Protocols eBird can't import are swapped for ones it can.

Files are split as Scythebill splits them: past 900K, the rest go to "name-1.csv", and so
on. Scythebill checks the bytes that have reached the file, which lag behind its writers'
buffers (a ``BufferedWriter`` of 10,240 characters before a UTF-8 encoder with an 8K
buffer); ``JavaWriterBytes`` follows them exactly, so the files split at the same lines.

One difference: Scythebill fails on a sighting with an impossible date (February 30);
Pipit leaves it out and counts it (``EBirdExport.impossible_dates``).
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as calendar_date
from functools import cmp_to_key

from pipit.domain.partial_date import PartialDate, PartialField, parse_partial_date
from pipit.domain.report import ObservationType, VisitField
from pipit.domain.values import (
    ApproximateNumber,
    float32,
    format_time,
    java_float_to_string,
    parse_time,
    round_three_digits,
)
from pipit.output.names import resolved_common_name
from pipit.output.trip_stops import GUAVA_WHITESPACE
from pipit.query.engine import Resolver
from pipit.query.model import QPlace, QSighting, QueryList
from pipit.query.results import QueryResults
from pipit.query.sorting import more_recent, resolved_comparator
from pipit.taxa.model import TaxonType, parent_of_type
from pipit.taxa.sighting_taxon import SightingTaxonType

#: Past this many bytes, the rest go to another file (eBird takes up to 1MB).
MAX_FILE_SIZE = 900 * 1024
COLUMN_COUNT = 19
(COMMON_NAME, GENUS, SPECIES, COUNT, SPECIES_COMMENTS, LOCATION, LATITUDE, LONGITUDE, DATE,
 START_TIME, STATE, COUNTRY, PROTOCOL, OBSERVERS, DURATION, ALL_REPORTED, DISTANCE, AREA,
 CHECKLIST_COMMENTS) = range(COLUMN_COUNT)  # fmt: skip
#: Protocols eBird doesn't import, and what Scythebill writes instead.
UNSUPPORTED_PROTOCOLS = {"pelagic": "traveling", "banding": "historical",
                         "flight_call": "stationary", "nocturnal": "historical"}  # fmt: skip
#: ``Locations.GROUPED_LOCATION_TERMINI``: a place's name stands alone below one of these.
GROUPED_LOCATION_TERMINI = frozenset({"town", "city", "county", "state", "country", "region"})
MILES_IN_A_KILOMETER = float32(0.621371)
ACRES_IN_A_HECTARE = float32(2.47105)
_LAT_LONG_CHARS = frozenset("-.0123456789,")


@dataclass(frozen=True)
class _Visit:
    observation_type: str
    duration_minutes: int | None
    distance_km: float | None  # float32, as stored
    area_hectares: float | None
    party_size: int | None
    comments: str | None
    complete: bool


@dataclass(frozen=True)
class _Place:
    name: str  # as stored (``getModelName``)
    type: str | None
    parent: str | None
    built_in: bool
    private: bool
    ebird_code: str | None
    latitude: str | None  # as stored
    longitude: str | None


@dataclass
class EBirdListData:
    """What the export reads from the list beyond the query: places and visits."""

    places: dict[str, _Place] = field(default_factory=dict)
    visits: dict[tuple[str, PartialDate, object], _Visit] = field(default_factory=dict)


def load_ebird_data(connection: sqlite3.Connection, query_list: QueryList) -> EBirdListData:
    data = EBirdListData()
    rows = connection.execute("SELECT xml_id, private, latitude, longitude FROM locations")
    details = {xml_id: (bool(private), lat, long) for xml_id, private, lat, long in rows}
    for xml_id, place in query_list.places.items():
        private, latitude, longitude = details.get(xml_id, (False, None, None))
        data.places[xml_id] = _place(place, private, latitude, longitude)
    for (
        location,
        date,
        start,
        kind,
        minutes,
        distance,
        area,
        party,
        comments,
        complete,
    ) in connection.execute(
        "SELECT location_xml_id, date, start_time, observation_type, duration_minutes, "
        "distance_km, area_hectares, party_size, comments, complete FROM visits"
    ):
        key = (location, parse_partial_date(date), parse_time(start) if start else None)
        data.visits[key] = _Visit(
            kind, minutes, None if distance is None else float32(float(distance)),
            None if area is None else float32(float(area)), party, comments, bool(complete),
        )  # fmt: skip
    return data


def _place(place: QPlace, private: bool, latitude: str | None, longitude: str | None) -> _Place:
    return _Place(place.name, place.type, place.parent, place.built_in, private,
                  place.ebird_code, latitude, longitude)  # fmt: skip


# ------------------------------------------------------------------ which records


def is_acceptable(sighting: QSighting, data: EBirdListData) -> bool:
    """``isAcceptableEBirdRecord``: a place that isn't a built-in region or private, and
    not a rejected or uncertain record."""
    if sighting.location_xml_id is None:
        return False
    place = data.places.get(sighting.location_xml_id)
    if place is None:
        return False
    if place.built_in and place.type == "region":
        return False
    if place.private:
        return False
    return sighting.status not in ("notAccepted", "idUncertain")


def is_list_building(date: PartialDate | None) -> bool:
    """Records without a full day, month and year must be "list-building"."""
    return date is None or None in (date.get(PartialField.YEAR), date.get(PartialField.MONTH),
                                    date.get(PartialField.DAY))  # fmt: skip


def _is_impossible(date: PartialDate | None) -> bool:
    if is_list_building(date):
        return False
    assert date is not None
    try:
        calendar_date(date.get(PartialField.YEAR) or 0, date.get(PartialField.MONTH) or 0,
                      date.get(PartialField.DAY) or 0)  # fmt: skip
    except ValueError:
        return True
    return False


# ------------------------------------------------------------------ CSV and the writers


def csv_line(fields: list[str | None]) -> str:
    """opencsv's ``writeNext`` as Scythebill sets it up: every field quoted (quotes doubled),
    empty and missing fields left bare, a "\\n" after."""
    return ",".join("" if not value else '"' + value.replace('"', '""') + '"'
                    for value in fields) + "\n"  # fmt: skip


class JavaWriterBytes:
    """How many bytes have reached the file through Java's ``BufferedWriter`` (10,240
    characters) and ``OutputStreamWriter`` (UTF-8, its encoder writing 8K at a time)."""

    def __init__(self) -> None:
        self._chars: list[int] = []  # UTF-16 units waiting in the BufferedWriter
        self._position = 0  # bytes waiting in the encoder's buffer
        self._high_surrogate = False
        self.count = 0

    def write(self, text: str) -> None:
        units = text.encode("utf-16-le")
        for i in range(0, len(units), 2):
            self._chars.append(units[i] | (units[i + 1] << 8))
            if len(self._chars) >= 10240:
                self._flush()

    def _flush(self) -> None:
        for unit in self._chars:
            if 0xD800 <= unit < 0xDC00:
                self._high_surrogate = True
                continue
            if self._high_surrogate:
                self._high_surrogate = False
                size = 4
            else:
                size = 1 if unit < 0x80 else 2 if unit < 0x800 else 3
            if self._position + size > 8192:
                self.count += self._position
                self._position = 0
            self._position += size
        self._chars = []


# ------------------------------------------------------------------ the export


@dataclass
class EBirdExport:
    files: list[bytes]  # the first file's, then "-1", "-2"...
    lines: int
    impossible_dates: int  # sightings left out that Scythebill would fail on


def export(results: QueryResults, data: EBirdListData) -> EBirdExport:
    """``EbirdExportAction``: ``results`` is the query in Clements at group depth."""
    resolve = Resolver(results.taxonomy)
    taxonomic = resolved_comparator(results)

    def order(a: QSighting, b: QSighting) -> int:
        # preferEarlier().compound(inTaxonomicOrder(clements)).reversed(): preferEarlier is
        # MoreRecentComparator reversed, so reversing again leaves it; inTaxonomicOrder
        # compares right with left
        by_date = more_recent(a, b)
        if by_date:
            return by_date
        left, right = resolve(a.taxon), resolve(b.taxon)
        assert left is not None and right is not None
        return -taxonomic(right, left)

    sightings = sorted(results.all_sightings(), key=cmp_to_key(order))
    files: list[bytes] = []
    lines = 0
    impossible = 0
    position = 0
    while True:
        counter = JavaWriterBytes()
        out: list[str] = []
        while position < len(sightings):
            sighting = sightings[position]
            position += 1
            if not is_acceptable(sighting, data):
                continue
            if _is_impossible(sighting.single_date):
                impossible += 1
                continue
            line = csv_line(_fields(sighting, resolve, data))
            out.append(line)
            lines += 1
            counter.write(line)
            if counter.count > MAX_FILE_SIZE:
                break
        files.append("".join(out).encode("utf-8"))
        if position >= len(sightings):
            break
    return EBirdExport(files, lines, impossible)


def _fields(sighting: QSighting, resolve: Resolver, data: EBirdListData) -> list[str | None]:
    line: list[str | None] = [None] * COLUMN_COUNT
    taxon = resolve(sighting.taxon)
    assert taxon is not None
    if taxon.smallest_type is TaxonType.SUBSPECIES:
        parent = resolve(taxon.parent_of_at_least_type(TaxonType.GROUP))
        assert parent is not None
        taxon = parent
    line[COMMON_NAME] = resolved_common_name(taxon)
    if sighting.taxon.type is SightingTaxonType.HYBRID:
        line[COMMON_NAME] = f"{line[COMMON_NAME]} (hybrid)"
    if taxon.type is SightingTaxonType.SINGLE:
        single = taxon.taxon
        species = parent_of_type(single, TaxonType.SPECIES)
        if single.type is TaxonType.GROUP:
            line[SPECIES] = f"{species.name} {single.name}"
        else:
            line[SPECIES] = species.name
        line[GENUS] = parent_of_type(single, TaxonType.GENUS).name
    assert sighting.location_xml_id is not None
    place = data.places[sighting.location_xml_id]
    line[LOCATION] = _grouped_name(sighting.location_xml_id, data)
    if place.latitude is not None and place.longitude is not None:
        line[LATITUDE] = canonical_coordinate(place.latitude)
        line[LONGITUDE] = canonical_coordinate(place.longitude)
    _state_and_country(line, sighting.location_xml_id, data)
    date = sighting.single_date
    if is_list_building(date):
        line[DATE] = "1/1/1900"
        line[START_TIME] = ""
    else:
        assert date is not None
        line[DATE] = (f"{date.get(PartialField.MONTH)}/{date.get(PartialField.DAY)}/"
                      f"{date.get(PartialField.YEAR):04d}")  # fmt: skip
        if sighting.time is not None:
            line[START_TIME] = format_time(sighting.time)
    number = ApproximateNumber.parse(sighting.count) if sighting.count else None
    line[COUNT] = "X" if number is None else str(number.number)
    if sighting.description:
        line[SPECIES_COMMENTS] = trim_lat_long(_replace_disallowed(sighting.description))
    visit = None
    if sighting.date is not None:
        visit = data.visits.get((sighting.location_xml_id, sighting.date, sighting.time))
    if visit is not None:
        _visit_fields(line, visit, sighting)
    else:
        line[ALL_REPORTED] = "N"
        line[PROTOCOL] = "Incidental"
    if is_list_building(date):
        line[PROTOCOL] = "Incidental"
        comments = line[CHECKLIST_COMMENTS]
        line[CHECKLIST_COMMENTS] = ("life-list building checklist" if not comments
                                    else f"life-list building checklist. {comments}")  # fmt: skip
    return line


def _visit_fields(line: list[str | None], visit: _Visit, sighting: QSighting) -> None:
    kind = UNSUPPORTED_PROTOCOLS.get(visit.observation_type, visit.observation_type)
    protocol = ObservationType.from_id(kind)
    # A protocol needing a start time, with none: Scythebill snaps back to Historical
    needs_time = protocol is not None and VisitField.START_TIME in protocol.required
    if sighting.time is None and needs_time:
        kind = "historical"
    line[PROTOCOL] = kind
    line[ALL_REPORTED] = "Y" if visit.complete else "N"
    if visit.area_hectares is not None:
        acres = round_three_digits(float32(visit.area_hectares * ACRES_IN_A_HECTARE))
        line[AREA] = java_float_to_string(acres)
    if visit.comments is not None:
        line[CHECKLIST_COMMENTS] = _replace_disallowed(visit.comments)
    if visit.distance_km is not None:
        miles = round_three_digits(float32(visit.distance_km * MILES_IN_A_KILOMETER))
        line[DISTANCE] = java_float_to_string(miles)
    if visit.duration_minutes is not None and visit.duration_minutes > 0:
        line[DURATION] = str(visit.duration_minutes)
    if visit.party_size is not None:
        line[OBSERVERS] = str(visit.party_size)


def _grouped_name(xml_id: str, data: EBirdListData) -> str:
    """``Locations.getGroupedLocationModelName``: "Park--Trail" for a place inside another
    below a town (or larger), unless the name already has the parent's."""
    place = data.places[xml_id]
    parent = data.places.get(place.parent) if place.parent else None
    if parent is None or parent.type in GROUPED_LOCATION_TERMINI:
        return place.name
    assert place.parent is not None
    parent_name = _grouped_name(place.parent, data)
    return place.name if parent_name in place.name else f"{parent_name}--{place.name}"


def _state_and_country(line: list[str | None], xml_id: str, data: EBirdListData) -> None:
    state = _ancestor_with_code(xml_id, "state", data)
    country = _ancestor_with_code(xml_id, "country", data)
    if state is not None and state.ebird_code is not None:
        code = state.ebird_code
        if "-" in code:  # Northern Ireland: a "state" of the United Kingdom
            hyphen = code.index("-")
            line[COUNTRY] = code[:hyphen]
            line[STATE] = code[hyphen + 1 :]
        else:
            line[STATE] = code
    if country is not None and country.ebird_code is not None:
        code = country.ebird_code
        if "-" in code:  # England: a "state" of the United Kingdom
            hyphen = code.index("-")
            if line[COUNTRY] is None:
                line[COUNTRY] = code[:hyphen]
            state_half = code[hyphen + 1 :]
            if len(state_half) <= 3 and line[STATE] is None:  # not Ceuta and Melilla
                line[STATE] = state_half
        elif line[COUNTRY] is None:
            line[COUNTRY] = code


def _ancestor_with_code(xml_id: str, place_type: str, data: EBirdListData) -> _Place | None:
    """``getAncestorOfTypeWithEbirdCode``: the place itself or its nearest ancestor of a
    type, with an eBird code."""
    place: _Place | None = data.places[xml_id]
    while place is not None and (place.type != place_type or place.ebird_code is None):
        place = data.places.get(place.parent) if place.parent else None
    return place


def canonical_coordinate(stored: str) -> str:
    """``LatLongCoordinates.latitudeAsCanonicalString``: seven decimals, rounded half up."""
    value = float(stored.replace(",", "."))
    negative = value < 0
    scaled = math.floor(abs(value) * 10.0**7 + 0.5)
    whole, fraction = divmod(scaled, 10**7)
    return f"{'-' if negative else ''}{whole}.{fraction:07d}"


def _replace_disallowed(text: str) -> str:
    """eBird disallows double quotes and line breaks."""
    return text.replace("\n", " ").replace("\r", " ").replace('"', "'")


def trim_lat_long(text: str) -> str:
    """BirdLasser and Observado imports add "LL:" and a latitude and longitude; eBird
    shouldn't get those."""
    while True:
        start = text.rfind("LL:")
        if start < 0:
            break
        end = next((i for i in range(start + 3, len(text)) if not _is_lat_long(text[i])), -1)
        if end == start + 3:
            break
        text = text[:start] if end < 0 else text[:start] + text[end:]
        text = _guava_trim(text)
    return text


def _is_lat_long(char: str) -> bool:
    return char in _LAT_LONG_CHARS and char not in GUAVA_WHITESPACE


def _guava_trim(text: str) -> str:
    start, end = 0, len(text)
    while start < end and text[start] in GUAVA_WHITESPACE:
        start += 1
    while end > start and text[end - 1] in GUAVA_WHITESPACE:
        end -= 1
    return text[start:end]


def acceptable_count(sightings: Iterable[QSighting], data: EBirdListData) -> int:
    return sum(1 for sighting in sightings if is_acceptable(sighting, data))

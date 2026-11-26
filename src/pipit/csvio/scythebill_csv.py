"""Scythebill CSV export: every detail of each sighting, as Scythebill's Save as Scythebill
CSV writes it.

Ported from Scythebill's ``model/.../export/FullReportExport.java`` and
``ui/.../panels/reports/ScythebillCsvExportAction.java``. The Reports screen's query (in the
display taxonomy, at the screen's depth), sorted by ``MoreRecentComparator``, one line per
sighting after a header: names, taxonomic index, date and time, count, sex and age, status,
breeding code, photos, notes, the place (coordinates, description, region, country, state,
county and city, then the other places it lies in, as "Location 1", "Location 2"...), then
the visit's details (once per visit), observers, and the trip (its notes once per trip).
Place names are display names. Excel-compatible output (an option in Scythebill's import
preferences) puts spaces for line breaks.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import time
from functools import cmp_to_key

from pipit.domain.locations import BUILT_IN_PREFIX, PredefinedLocations, location_code
from pipit.domain.partial_date import PartialDate, format_partial_date, parse_partial_date
from pipit.domain.report import Location
from pipit.domain.values import (
    ApproximateNumber,
    float32,
    format_time,
    java_float_to_string,
    parse_time,
    round_three_digits,
)
from pipit.ebird.record_format import csv_line
from pipit.output.names import (
    PlaceNames,
    ordered_taxa,
    resolved_common_name,
    resolved_full_name,
)
from pipit.query.engine import Resolver
from pipit.query.model import QSighting, QueryList
from pipit.query.results import QueryResults, taxonomy_index
from pipit.query.sorting import more_recent
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType

HEADER = ["Common", "Scientific", "Subspecies", "Index", "Date", "Start time", "Number",
          "Female", "Male", "Immature", "Adult", "Heard only", "Status", "Breeding",
          "Photographed", "Photos", "Description", "Latitude", "Longitude",
          "Location Description", "Region", "Country", "State", "County", "City"]  # fmt: skip
VISIT_HEADER = ["Observation type", "Duration", "Distance", "Area", "Party size",
                "Complete list", "Visit comments", "Visit photos"]  # fmt: skip
USER_HEADER = ["Observers", "Observer Names"]
TRIP_HEADER = ["Trip name", "Trip start date", "Trip start time", "Trip end date",
               "Trip end time", "Trip notes", "Trip links", "Trip photos"]  # fmt: skip
REGION, COUNTRY, STATE, COUNTY, CITY = 20, 21, 22, 23, 24
#: ``SightingStatus.getExportText``
STATUS_EXPORT = {"none": "", "notAccepted": "not accepted", "bvd": "better view desired",
                 "intro": "introduced", "provisional": "provisional",
                 "notEstablished": "not established", "restrained": "restrained",
                 "domestic": "domestic", "idUncertain": "uncertain",
                 "unsatisfactoryViews": "unsatisfactory views", "notByMe": "not by me",
                 "dead": "dead", "signs": "signs"}  # fmt: skip


@dataclass(frozen=True)
class Link:
    uri: str
    name: str | None
    favorite: bool = False
    is_photo: bool = False

    def encoded(self) -> str:
        """``Link.toEncodedLine`` / ``Photo``: "[* name](uri)", "[name](uri)", or the URI."""
        name = None if self.name is None else self.name.replace("\\", "\\\\").replace("]", "\\]")
        if self.is_photo and self.favorite:
            name = "*" if name is None else f"* {name}"
        return self.uri if name is None else f"[{name}]({self.uri})"


@dataclass(frozen=True)
class _Visit:
    observation_type: str
    duration_minutes: int | None
    distance_km: float | None
    area_hectares: float | None
    party_size: int | None
    complete: bool
    comments: str | None
    photos: tuple[Link, ...]


@dataclass(frozen=True)
class _Trip:
    name: str | None
    start: str
    start_time: str | None
    end: str
    notes: str | None
    links: tuple[Link, ...]
    photos: tuple[Link, ...]


@dataclass
class CsvListData:
    """What the export reads from the list beyond the query."""

    descriptions: dict[str, str] = field(default_factory=dict)
    coordinates: dict[str, tuple[str, str]] = field(default_factory=dict)  # as stored
    visits: dict[tuple[str, PartialDate, time | None], _Visit] = field(default_factory=dict)
    trips: dict[str, _Trip] = field(default_factory=dict)
    has_trips: bool = False
    photos: dict[int, list[Link]] = field(default_factory=dict)  # by sighting row
    users: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)


def load_csv_data(connection: sqlite3.Connection) -> CsvListData:
    data = CsvListData()
    for xml_id, description, latitude, longitude in connection.execute(
        "SELECT xml_id, description, latitude, longitude FROM locations"
    ):
        if description is not None:
            data.descriptions[xml_id] = description
        if latitude is not None and longitude is not None:
            data.coordinates[xml_id] = (latitude, longitude)
    photos: dict[tuple[str, int], list[Link]] = {}
    for sighting, trip, visit, uri, name, favorite in connection.execute(
        "SELECT sighting_id, trip_id, visit_id, uri, name, favorite FROM photos ORDER BY ord"
    ):
        owner = ("s", sighting) if sighting is not None else (
            ("t", trip) if trip is not None else ("v", visit))  # fmt: skip
        photos.setdefault(owner, []).append(Link(uri, name, bool(favorite), is_photo=True))
    data.photos = {key: found for (kind, key), found in photos.items() if kind == "s"}
    for (
        row,
        location,
        date,
        start,
        kind,
        minutes,
        distance,
        area,
        party,
        complete,
        comments,
    ) in connection.execute(
        "SELECT id, location_xml_id, date, start_time, observation_type, duration_minutes, "
        "distance_km, area_hectares, party_size, complete, comments FROM visits"
    ):
        key = (location, parse_partial_date(date), parse_time(start) if start else None)
        data.visits[key] = _Visit(
            kind, minutes, None if distance is None else float32(float(distance)),
            None if area is None else float32(float(area)), party, bool(complete), comments,
            tuple(photos.get(("v", row), [])),
        )  # fmt: skip
    links: dict[int, list[Link]] = {}
    for trip, uri, name in connection.execute(
        "SELECT trip_id, uri, name FROM links ORDER BY trip_id, ord"
    ):
        links.setdefault(trip, []).append(Link(uri, name))
    for row, xml_id, name, start, start_time, end, notes in connection.execute(
        "SELECT id, xml_id, name, start_date, start_time, end_date, notes FROM trips"
    ):
        data.has_trips = True
        data.trips[xml_id] = _Trip(
            name, format_partial_date(parse_partial_date(start)),
            format_time(parsed) if start_time and (parsed := parse_time(start_time)) else None,
            format_partial_date(parse_partial_date(end)), notes, tuple(links.get(row, [])),
            tuple(photos.get(("t", row), [])),
        )  # fmt: skip
    for xml_id, name, abbreviation in connection.execute(
        "SELECT xml_id, name, abbreviation FROM users ORDER BY ord"
    ):
        data.users[xml_id] = (name, abbreviation)
    return data


# ------------------------------------------------------------------ the export


def export(results: QueryResults, query_list: QueryList, places: PlaceNames,
           data: CsvListData, predefined: PredefinedLocations, *,
           excel_compatible: bool = False) -> bytes:  # fmt: skip
    """``FullReportExport.exportReportSet``: ``results`` is the Reports screen's query."""
    resolve = Resolver(results.taxonomy)
    index = taxonomy_index(results.taxonomy)
    sightings = sorted(results.all_sightings(), key=cmp_to_key(more_recent))
    depth = maximum_location_depth(populated_tree(query_list, predefined))
    header = [*HEADER, *(f"Location {i + 1}" for i in range(depth)), *VISIT_HEADER]
    if data.users:
        header += USER_HEADER
    if data.has_trips:
        header += TRIP_HEADER
    lines = [_line(header, excel_compatible)]
    written_visits: set[tuple[str, PartialDate, time | None]] = set()
    writing = _Writing(index, places, data, depth)
    for sighting in sightings:
        taxon = resolve(sighting.taxon)
        assert taxon is not None
        visit = None
        if sighting.location_xml_id is not None and sighting.date is not None:
            key = (sighting.location_xml_id, sighting.date, sighting.time)
            if key not in written_visits:
                visit = data.visits.get(key)
                written_visits.add(key)
        fields = _fields(sighting, taxon, visit, writing)
        lines.append(_line(fields, excel_compatible))
    return "".join(lines).encode("utf-8")


def _line(fields: list[str], excel_compatible: bool) -> str:
    if excel_compatible:
        fields = [value.replace("\n", " ") for value in fields]
    return csv_line(list(fields))


@dataclass
class _Writing:
    """What writing every line needs."""

    index: dict[str, int]
    places: PlaceNames
    data: CsvListData
    depth: int
    written_trips: set[str] = field(default_factory=set)


def _fields(sighting: QSighting, taxon: Resolved, visit: _Visit | None,
            writing: _Writing) -> list[str]:  # fmt: skip
    """``writeSighting``."""
    data = writing.data
    out = _taxon_fields(taxon, writing.index)
    out.append("" if sighting.date is None else format_partial_date(sighting.date))
    out.append("" if sighting.time is None else format_time(sighting.time))
    number = ApproximateNumber.parse(sighting.count) if sighting.count else None
    out.append("" if number is None else str(number))
    for flag in (sighting.female, sighting.male, sighting.immature, sighting.adult,
                 sighting.heard_only):  # fmt: skip
        out.append("Y" if flag else "")
    out.append(STATUS_EXPORT.get(sighting.status, ""))
    out.append(sighting.breeding)
    out.append("Y" if sighting.photographed else "")
    out.append("\n".join(photo.encoded() for photo in data.photos.get(sighting.row, [])))
    out.append(sighting.description)
    _place_fields(out, sighting.location_xml_id, writing)
    users = list(dict.fromkeys(u for u in sighting.user_order if u in data.users))
    if visit is not None:
        out.extend(_visit_fields(visit))
    elif users or sighting.trip is not None:
        out.extend([""] * len(VISIT_HEADER))
    if users:
        out.append(",".join(a for u in users if (a := data.users[u][1]) is not None))
        out.append("\n".join(n for u in users if (n := data.users[u][0]) is not None))
    elif data.users and sighting.trip is not None:
        out.extend([""] * len(USER_HEADER))
    if sighting.trip is not None:
        out.extend(_trip_fields(sighting.trip.xml_id, writing))
    return out


def _taxon_fields(taxon: Resolved, index: dict[str, int]) -> list[str]:
    """Common and scientific names, subspecies, and the taxonomic index (a sp.'s or
    hybrid's just after its last taxon, "1234.5")."""
    taxonomy = taxon.taxa[0].taxonomy
    if taxon.smallest_type is TaxonType.SPECIES:
        out = [resolved_common_name(taxon) if _has_common(taxon) else "",
               resolved_full_name(taxon), ""]  # fmt: skip
    else:
        group = taxon.parent_of_at_least_type(TaxonType.GROUP).resolve_internal(taxonomy)
        species = taxon.parent_of_at_least_type(TaxonType.SPECIES).resolve_internal(taxonomy)
        out = [resolved_common_name(group) if _has_common(group) else "",
               resolved_full_name(species), _name(taxon)]  # fmt: skip
    if taxon.type is SightingTaxonType.SINGLE:
        out.append(str(index[taxon.taxon.id]))
    else:
        out.append(f"{index[ordered_taxa(taxon)[-1].id]}.5")
    return out


def _place_fields(out: list[str], location: str | None, writing: _Writing) -> None:
    """Coordinates, description, region...city, then "Location N" columns."""
    place = writing.places.places.get(location) if location is not None else None
    known = place is not None and location is not None
    coordinates = writing.data.coordinates.get(location) if known and location else None
    out.extend(coordinates if coordinates is not None else ("", ""))
    out.append(writing.data.descriptions.get(location, "") if known and location else "")
    out.extend(["", "", "", "", ""])
    if known and location is not None:
        _append_places(out, location, writing.places)
    while len(out) < len(HEADER) + writing.depth:
        out.append("")


def _visit_fields(visit: _Visit) -> list[str]:
    def float_text(value: float | None) -> str:
        return "" if value is None else java_float_to_string(round_three_digits(value))

    return [visit.observation_type,
            "" if visit.duration_minutes is None else str(visit.duration_minutes),
            float_text(visit.distance_km), float_text(visit.area_hectares),
            "" if visit.party_size is None else str(visit.party_size),
            "Y" if visit.complete else "", visit.comments or "",
            "\n".join(photo.encoded() for photo in visit.photos)]  # fmt: skip


def _trip_fields(trip_id: str, writing: _Writing) -> list[str]:
    """The trip, its notes only the first time; links and photos only when there are any."""
    trip = writing.data.trips[trip_id]
    first = trip_id not in writing.written_trips
    writing.written_trips.add(trip_id)
    out = [trip.name or "", trip.start, trip.start_time or "", trip.end,
           "",  # Scythebill never has an end time (its parser keeps none)
           (trip.notes or "") if first else ""]  # fmt: skip
    if trip.links or trip.photos:
        out.append("\n".join(link.encoded() for link in trip.links))
    if trip.photos:
        out.append("\n".join(photo.encoded() for photo in trip.photos))
    return out


def _has_common(resolved: Resolved) -> bool:
    return all(taxon.common_name is not None for taxon in resolved.taxa)


def _name(resolved: Resolved) -> str:
    """``Resolved.getName``: a sp.'s or hybrid's names joined, in its own order."""
    if resolved.type is SightingTaxonType.SINGLE:
        return resolved.taxon.name
    joiner = " x " if resolved.type is SightingTaxonType.HYBRID else "/"
    return joiner.join(taxon.name for taxon in ordered_taxa(resolved))


def _append_places(out: list[str], xml_id: str, places: PlaceNames) -> None:
    """``appendLocations``: the place and its ancestors, root first, each in its column
    (region, country, state, county, city) if free, else after them."""
    place = places.places[xml_id]
    if place.parent is not None and place.parent in places.places:
        _append_places(out, place.parent, places)
    name = places.name(place)
    parent = places.places.get(place.parent) if place.parent else None
    kind = place.type
    if kind == "region":
        if out[REGION] == "":
            out[REGION] = name
            return
        if parent is not None and parent.type == kind and out[REGION] == places.name(parent):
            out[REGION] = name
            return
    elif kind == "country":
        if out[COUNTRY] == "":
            out[COUNTRY] = name
            return
        if (place.built_in and parent is not None and parent.built_in
                and parent.type == "country" and out[STATE] == ""):  # fmt: skip
            out[STATE] = name  # the UK: a built-in country inside another
            return
    elif kind == "state":
        if out[STATE] == "":
            out[STATE] = name
            return
    elif kind == "county":
        if out[COUNTY] == "":
            out[COUNTY] = name
            return
    elif kind in ("city", "town") and out[CITY] == "":
        out[CITY] = name
        return
    out.append(name)


def populated_tree(query_list: QueryList, predefined: PredefinedLocations) -> list[Location]:
    """The list's places as Scythebill holds them once a file is open: with every predefined
    place added that isn't there yet (``PredefinedLocationPopulator``: not if its parent has
    a child of its name, or any place has its code), new ones visited in turn. Returns the
    roots."""
    nodes: dict[str, Location] = {}
    for xml_id, place in query_list.places.items():
        nodes[xml_id] = Location(xml_id, place.name, place.type, ebird_code=place.ebird_code)
    roots: list[Location] = []
    for xml_id, place in query_list.places.items():
        node = nodes[xml_id]
        parent = nodes.get(place.parent) if place.parent else None
        if parent is None:
            roots.append(node)
        else:
            node.parent = parent
            parent.children.append(node)
    codes = {code for node in nodes.values() if (code := location_code(node)) is not None}

    def populate(parent: Location) -> None:
        for candidate in predefined.children(parent):
            if parent.child_named(candidate.name) is not None or candidate.code in codes:
                continue
            created = Location(f"{BUILT_IN_PREFIX}pre_{candidate.code}", candidate.name,
                               candidate.type, parent=parent,
                               ebird_code=candidate.code)  # fmt: skip
            parent.children.append(created)
            codes.add(location_code(created) or candidate.code)
        for child in list(parent.children):
            populate(child)

    for root in list(roots):
        populate(root)
    return roots


def maximum_location_depth(roots: list[Location]) -> int:
    """``findMaximumLocationDepth``: how many "Location N" columns the deepest place needs
    beyond the first region, country, state and county on its way down."""
    deepest = 0
    stack: list[tuple[Location, int, frozenset[str]]] = [(root, 0, frozenset()) for root in roots]
    while stack:
        node, depth, found = stack.pop()
        kind = node.type
        if kind in ("region", "country", "state", "county"):
            if kind in found:
                depth += 1
            else:
                found = found | {kind}
        else:
            depth += 1
        deepest = max(deepest, depth)
        stack.extend((child, depth, found) for child in node.children)
    return deepest

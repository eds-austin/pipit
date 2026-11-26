"""Scythebill's own CSV (Save as Scythebill CSV, or a spreadsheet laid out the same way).

Ported from Scythebill ``ui/.../imports/ScythebillImporter.java`` and the field mappers it
uses. Columns are found by their header, ignoring case and spaces: Common, Scientific (or
Genus and Species), Subspecies, Date, Start time, End time, Number, Female, Male, Immature,
Adult, Heard only, Status, Breeding, Photographed, Photos, Description, Region, Country,
State, County, City, Location (and Location 1, 2, ...), Latitude, Longitude, Location
Description, and a checklist's Observation type, Duration, Distance (km), Area (ha), Party
size, Complete list, Visit comments and Visit photos.

Scythebill's ways, kept: rows with neither a common nor a scientific name are skipped; no
introduced or domestic status is added (a round trip keeps what the file says); a checklist's
details are gathered from all its rows, in the order the file first has them, with "Complete
list" true when the file has no such column, and a duration from the start and end times if
there's none (more than five minutes); a place written with more than one set of coordinates
gets them in each sighting's description ("LL:lat,long"); names are matched within two
letters; a place that can't be made leaves its rows not imported.

Trips come from the Trip name, start date, start time, end date, notes, links and photos
columns (``lookForTripInfo``): a row's trip is found or made (``pipit.imports.trips``), but
only an undated sighting is put on it, as in Scythebill. A trip's end time isn't kept (Pipit,
like Scythebill once a file is reopened, has none).

Dates are read in Scythebill's own form, then in forms guessed from the file's other dates
(``pipit.imports.date_formats``).

Not yet imported (refused with a message): observers, and places given only as location
text without a region, country, state, county or city.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipit.domain.partial_date import PartialDate, parse_partial_date
from pipit.domain.report import Link, ObservationType, Photo, Sighting
from pipit.domain.values import (
    ApproximateNumber,
    is_valid_uri,
    normalize_file_localhost,
)
from pipit.imports.date_formats import choose_formats
from pipit.imports.fields import (
    DateParseError,
    JodaDateParser,
    bool_at,
    breeding_code,
    float_at,
    int_at,
    parse_external_time,
    read_rows,
    string_at,
)
from pipit.imports.my_data import MissingHeaderError
from pipit.imports.places import ImportedLocation, LocationShortcuts
from pipit.imports.source import VisitFields
from pipit.imports.taxa import WHITESPACE, TaxonResolver, java_trim
from pipit.imports.trips import TripInfo

#: ``SightingStatus.forExportText``.
STATUSES = {"not accepted": "notAccepted", "better view desired": "bvd",
            "introduced": "intro", "provisional": "provisional",
            "not established": "notEstablished", "restrained": "restrained",
            "domestic": "domestic", "uncertain": "idUncertain",
            "unsatisfactory views": "unsatisfactoryViews", "not by me": "notByMe",
            "dead": "dead", "signs": "signs", "": "none"}  # fmt: skip
_MARKDOWN_LINK = re.compile(r"\[(.*)\]\((.*)\)")


class UnsupportedFileError(ValueError):
    """Something Scythebill imports that Pipit doesn't yet."""


def photos_from_text(text: str) -> list[Photo]:
    """``ScythebillImporter.photosFromString``: one encoded photo a line ("uri", or
    "[* name](uri)" with "*" for a favorite). Lines whose URI isn't valid are left out
    (Scythebill takes them if they name a file on the computer)."""
    return _encoded(text, True)


def _encoded(text: str, photos_wanted: bool) -> list[Photo]:
    """Encoded links or photos (``Links``/``Photos.fromEncodedLineOrFile``); a link's
    "*" is part of its name."""
    photos: list[Photo] = []
    for raw in re.split(r"[\r\n]", text):
        line = java_trim(raw)
        if not line:
            continue
        match = _MARKDOWN_LINK.fullmatch(line)
        uri, bracket = (match.group(2), match.group(1)) if match else (line, None)
        if not is_valid_uri(uri):
            continue
        photo = Photo(normalize_file_localhost(uri))
        if photos_wanted and bracket is not None and bracket.startswith("*"):
            photo.favorite = True
            rest = bracket[1:].strip()
            photo.name = _unescape(rest) or None
        elif bracket is not None:
            photo.name = _unescape(bracket) or None
        photos.append(photo)
    return photos


def _unescape(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in "\\]":
            out.append(text[i + 1])
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _trim_coordinate(text: str) -> str:
    decimal = text.find(".")
    if decimal < 0 or decimal + 7 >= len(text):
        return text
    return text[: decimal + 7]


@dataclass(slots=True)
class VisitBuilder:
    """A checklist's details as rows give them (``VisitInfo.Builder``)."""

    observation_type: ObservationType = ObservationType.HISTORICAL
    duration_minutes: int | None = None
    distance_km: float | None = None
    area_hectares: float | None = None
    party_size: int | None = None
    complete: bool = False
    comments: str | None = None
    photos: list[Photo] = field(default_factory=list)

    def fields(self) -> VisitFields:
        return VisitFields(self.observation_type, self.duration_minutes, self.distance_km,
                           self.area_hectares, self.party_size, self.complete, self.comments,
                           list(self.photos))  # fmt: skip


class ScythebillCsvFile:
    mass_export = False
    filters_dates = False
    format_name = "Scythebill CSV"
    name_distance = 2
    default_statuses = False
    accumulates_visits = True
    place_errors_fail_rows = True
    unreadable_message = (
        "Pipit could not read any sightings from this file. Often the dates can't be read: "
        "Scythebill's own form is 2024-04-13 (or 2024-04, or 2024).")  # fmt: skip

    def __init__(self, path: Path) -> None:
        self.path = path
        rows = read_rows(path)
        if not rows:
            raise MissingHeaderError("The file is empty.")
        self.header: list[str] | None = rows[0]
        self.rows = rows[1:]
        index = {"".join(c for c in name if c not in WHITESPACE).lower(): i
                 for i, name in enumerate(rows[0])}  # fmt: skip
        self._index = index
        if "common" not in index and "scientific" not in index:
            raise MissingHeaderError("The file has neither a Common nor a Scientific column.")
        if "date" not in index:
            raise MissingHeaderError('The file has no "Date" column.')
        get = index.get
        self._common, self._scientific = get("common"), get("scientific")
        self._genus, self._species, self._subspecies = (
            get("genus"),
            get("species"),
            get("subspecies"),
        )
        self._date, self._start, self._end = index["date"], get("starttime"), get("endtime")
        self._region, self._country, self._state = get("region"), get("country"), get("state")
        self._county, self._city = get("county"), get("city")
        self._locations = [i for i in [get("location")] if i is not None]
        number = 1
        while True:
            column = get(f"location{number}")
            if column is None:
                if number >= 2:
                    break
                number += 1
                continue
            self._locations.append(column)
            number += 1
        self._latitude, self._longitude = get("latitude"), get("longitude")
        self._place_description = get("locationdescription")
        #: Location keys written with more than one set of coordinates (``read_places``).
        self.multiple_coordinates: set[str] = set()
        self._date_parsers = self._choose_date_parsers(rows)
        self._check_supported()

    def _choose_date_parsers(self, rows: list[list[str]]) -> list[JodaDateParser]:
        """``computeExtendedMappings``: the dates (the header's "Date" among them, as in
        Scythebill) that aren't in Scythebill's own form choose patterns for the others."""
        other: dict[str, None] = {}
        for row in rows:
            text = string_at(row, self._date)
            if text:
                try:
                    parse_partial_date(text)
                except ValueError:
                    other[text] = None
        return [JodaDateParser(pattern) for pattern in choose_formats(other)]

    def parse_date(self, text: str | None) -> PartialDate | None:
        """``parseDate``: Scythebill's own form ("2024-04-13", "2024-04", "2024"), then the
        chosen patterns; ValueError if none reads it."""
        if not text:
            return None
        try:
            return parse_partial_date(text)
        except ValueError:
            pass
        for parser in self._date_parsers:
            try:
                return parser.parse(text)
            except DateParseError:
                continue
        raise ValueError(f"Could not parse date {text} with any known format")

    # -------------------------------------------------------------- what isn't ported yet

    def _check_supported(self) -> None:
        index = self._index
        for row in self.rows:
            if self.skip(row):
                continue
            if any(string_at(row, index.get(name)) for name in ("observers", "observernames")):
                raise UnsupportedFileError("Pipit can't import observers yet.")
            if self._freeform(row):
                raise UnsupportedFileError(
                    "Some places are only location text, without a region, country, state, "
                    "county or city; Pipit can't place those yet.")  # fmt: skip

    def _freeform(self, row: list[str]) -> bool:
        if any(string_at(row, i) for i in (self._region, self._country, self._state,
                                           self._county, self._city)):  # fmt: skip
            return False
        return any((string_at(row, i) or "").strip() for i in self._locations)

    # -------------------------------------------------------------- rows and keys

    def skip(self, row: list[str]) -> bool:
        """No common and no scientific name (a row of totals, say)."""
        return not string_at(row, self._common) and not string_at(row, self._scientific)

    def location_key(self, row: list[str]) -> str:
        columns = [self._region, self._country, self._state, self._county, self._city,
                   *self._locations]  # fmt: skip
        return "|".join(string_at(row, i) or "" for i in columns)

    def taxon_key(self, row: list[str]) -> str:
        columns = [self._common, self._scientific, self._subspecies, self._species, self._genus]
        return "|".join(string_at(row, i) or "" for i in columns)

    def date(self, row: list[str]) -> PartialDate | None:
        return self.parse_date(string_at(row, self._date))

    def coordinates(self, row: list[str]) -> tuple[str, str] | None:
        latitude = string_at(row, self._latitude)
        longitude = string_at(row, self._longitude)
        return (latitude, longitude) if latitude and longitude else None

    def imported_location(self, row: list[str],
                          shortcuts: LocationShortcuts) -> ImportedLocation:  # fmt: skip
        del shortcuts
        return ImportedLocation(
            region=string_at(row, self._region), country=string_at(row, self._country),
            state=string_at(row, self._state), county=string_at(row, self._county),
            city=string_at(row, self._city),
            location_names=[string_at(row, i) for i in self._locations],
            latitude=string_at(row, self._latitude) or None,
            longitude=string_at(row, self._longitude) or None,
            description=string_at(row, self._place_description) or None,
        )  # fmt: skip

    def names(self, row: list[str],
              resolver: TaxonResolver) -> tuple[str | None, str | None, str | None]:  # fmt: skip
        del resolver
        scientific = string_at(row, self._scientific)
        if not scientific:
            species = string_at(row, self._species)
            genus = string_at(row, self._genus)
            scientific = f"{genus} {species}" if species and genus else None
        return (string_at(row, self._common) or None, scientific or None,
                string_at(row, self._subspecies))  # fmt: skip

    # -------------------------------------------------------------- sightings

    def map_fields(self, row: list[str], sighting: Sighting) -> None:
        """Scythebill's mapper order: time, number, description, female, male, immature,
        adult, heard only, photographed, photos, status, breeding, date (the only one that
        fails)."""
        get = self._index.get
        if self._start is not None:
            text = string_at(row, self._start)
            if text:
                with contextlib.suppress(ValueError):
                    sighting.time = parse_external_time(text)
        number = get("number")
        if number is not None:
            text = string_at(row, number)
            count = ApproximateNumber.parse(text) if text is not None else None
            if count is not None:
                sighting.count = count
        description = self._description(row)
        if description:
            sighting.description = description
        for name, attribute in (("female", "female"), ("male", "male"),
                                ("immature", "immature"), ("adult", "adult"),
                                ("heardonly", "heard_only"),
                                ("photographed", "photographed")):  # fmt: skip
            column = get(name)
            if column is not None and bool_at(row, column):
                setattr(sighting, attribute, True)
        photos_column = get("photos")
        if photos_column is not None:
            text = string_at(row, photos_column)
            photos = photos_from_text(text) if text else []
            if photos:
                sighting.photos = photos
                if get("photographed") is None:
                    sighting.photographed = True
        status_column = get("status")
        if status_column is not None:
            text = string_at(row, status_column)
            if text and text in STATUSES:
                sighting.status = STATUSES[text]
        breeding_column = get("breeding")
        if breeding_column is not None:
            code = breeding_code(string_at(row, breeding_column))
            if code is not None:
                sighting.breeding = code
        date = self.date(row)
        if date is not None:
            sighting.date = date

    def _description(self, row: list[str]) -> str | None:
        column = self._index.get("description")
        text = string_at(row, column) if column is not None else None
        if self.location_key(row) not in self.multiple_coordinates:
            return text
        description = text or ""
        coordinates = self.coordinates(row)
        if coordinates is not None:
            prefix = "" if not description else "\n"
            description += (f"{prefix}LL:{_trim_coordinate(coordinates[0])},"
                            f"{_trim_coordinate(coordinates[1])}")  # fmt: skip
        return description

    def visit(self, row: list[str]) -> VisitFields | None:
        del row
        return None

    def trip_info(self, row: list[str]) -> tuple[str, TripInfo] | None:
        """The row's trip, keyed by its start, end and name as written; None without one."""
        get = self._index.get
        start_column, end_column = get("tripstartdate"), get("tripenddate")
        if start_column is None or end_column is None:
            return None
        start_text, end_text = string_at(row, start_column), string_at(row, end_column)
        if start_text is None or end_text is None:
            return None
        start = self.parse_date(start_text)
        end = self.parse_date(end_text)
        if start is None or end is None:
            return None
        name = string_at(row, get("tripname")) if get("tripname") is not None else None
        info = TripInfo(start, end, None, name=name or None)
        time_column = get("tripstarttime")
        start_time = string_at(row, time_column) if time_column is not None else None
        if start_time:
            with contextlib.suppress(ValueError):
                info.start_time = parse_external_time(start_time)
        notes_column = get("tripnotes")
        info.notes = (string_at(row, notes_column) if notes_column is not None else None) or None
        links_column = get("triplinks")
        links_text = string_at(row, links_column) if links_column is not None else None
        if links_text:
            info.links = [Link(photo.uri, photo.name) for photo in _encoded(links_text, False)]
        photos_column = get("tripphotos")
        photos_text = string_at(row, photos_column) if photos_column is not None else None
        if photos_text:
            info.photos = photos_from_text(photos_text)
        return f"{start_text}|{end_text}|{name or ''}", info

    def merge_visit(self, builder: VisitBuilder | None, row: list[str]) -> VisitBuilder:
        """``lookForVisitInfo``: what this row adds to its checklist's details."""
        get = self._index.get
        if builder is None:
            builder = VisitBuilder()
        column = get("observationtype")
        text = string_at(row, column) if column is not None else None
        if text:
            observation_type = ObservationType.from_id(text)
            if observation_type is not None:
                builder.observation_type = observation_type
        duration = int_at(row, get("duration"))
        if duration is not None:
            builder.duration_minutes = duration
        else:
            minutes = self._minutes_between(row)
            if minutes is not None and minutes > 5:
                builder.duration_minutes = minutes
        distance = float_at(row, get("distance"))
        if distance is not None:
            builder.distance_km = distance
        area = float_at(row, get("area"))
        if area is not None:
            builder.area_hectares = area
        party = int_at(row, get("partysize"))
        if party is not None and party > 0:
            builder.party_size = party
        comments_column = get("visitcomments")
        comments = string_at(row, comments_column) if comments_column is not None else None
        if comments:
            builder.comments = comments
        photos_column = get("visitphotos")
        photos_text = string_at(row, photos_column) if photos_column is not None else None
        if photos_text:
            photos = photos_from_text(photos_text)
            if photos:
                builder.photos = photos
        complete_column = get("completelist")
        if complete_column is None or bool_at(row, complete_column):
            builder.complete = True
        return builder

    def _minutes_between(self, row: list[str]) -> int | None:
        start = string_at(row, self._start) if self._start is not None else None
        end = string_at(row, self._end) if self._end is not None else None
        if not start or not end:
            return None
        try:
            first = parse_external_time(start)
            last = parse_external_time(end)
        except ValueError:
            return None
        return (last.hour * 60 + last.minute) - (first.hour * 60 + first.minute)

"""A checklist downloaded from its page on eBird ("Download" on a checklist: S123456789.csv),
in any of eBird's languages.

Ported from Scythebill ``ui/.../imports/EBirdChecklistImporter.java`` and ``EBird``'s
``durationHrsMins``, ``distanceMilesOrKilometers`` and ``areaHectaresOrAcres``. The file has
no state or county, so before reading places Pipit asks eBird (when the user has turned that
on: ``pipit.ebird.api``) for the checklist's state, county and hotspot, from the checklist
ID in the file name; with them, the place is made as for other eBird files. Without them
(no access, no answer, or a file name without the ID) Scythebill finds the country from
coordinates in the place's name or asks the user where it is; Pipit refuses the file for now.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable
from pathlib import Path

from pipit.domain.partial_date import PartialDate
from pipit.domain.report import Sighting
from pipit.domain.values import ApproximateNumber, float32, parse_float32
from pipit.ebird.api import ChecklistPlace, EBirdApi
from pipit.imports.ebird_life_list import (
    _common_part,
    _scientific_part,
    just_genus_and_species,
    name_and_lat_long,
    subspecies_if_present,
)
from pipit.imports.ebird_record import HECTARES_IN_AN_ACRE, KILOMETERS_IN_A_MILE, PlaceUnknownError
from pipit.imports.fields import (
    JodaDateParser,
    bool_at,
    int_at,
    parse_external_time,
    parse_first_match,
    read_rows,
    string_at,
)
from pipit.imports.my_data import MissingHeaderError, observation_type
from pipit.imports.places import ImportedLocation, LocationShortcuts
from pipit.imports.source import VisitFields
from pipit.imports.taxa import TaxonResolver

DATE_PATTERNS = ("dd MMM, yy", "MMM dd, yy", "dd MMM yy", "dd-MMM-yy", "dd/MM/yy", "MM dd, yy",
                 "yy MMM dd", "dd.MM.yyyy", "dd.MMM.yyyy", "dd/MMM/yy", "yyyy-MM-dd")  # fmt: skip
DATE_PARSERS = [JodaDateParser(pattern) for pattern in DATE_PATTERNS]
CHECKLIST_ID = re.compile(r"(S[0-9]+).*", re.DOTALL)

_HOURS_AND_MINUTES = [re.compile(p) for p in (
    r"(\d+) hour.*?(\d+) minute.*", r"(\d+) hodin.*?(\d+) minut.*",
    r"(\d+) Stunde.*?(\d+) Minute.*", r"(\d+) ordu.*?(\d+) minutu.*",
    r"(\d+) heure.*?(\d+) minute.*", r"(\d+) ora.*?(\d+) minute.*",
    "(\\d+) שעות, (\\d+) דקות",
    "(\\d+) 時間.*?(\\d+) 分", r"(\d+) time.*?(\d+) minutt.*",
    r"(\d+) hora.*?(\d+) minuto.*",
    "(\\d+) час.*?(\\d+) минута.*",
    r"(\d+) saat, (\d+) dakika",
    "(\\d+) годин.*?(\\d+) хвилин.*",
    "(\\d+) 小时, (\\d+) 分钟", "(\\d+) 小時.*?(\\d+) 分.*")]  # fmt: skip
_HOURS = [re.compile(p) for p in (
    r"(\d+) hour.*", r"(\d+) hodin.*", r"(\d+) Stunde.*", r"(\d+) ordu.*", r"(\d+) heure.*",
    r"(\d+) ora.*", "(\\d+) שעות", "(\\d+) 時間.*?",
    r"(\d+) time.*", r"(\d+) hora.*", "(\\d+) час.*", r"(\d+) saat",
    "(\\d+) годин.*", "(\\d+) 小時.*", "(\\d+) 小时")]  # fmt: skip
_MINUTES = [re.compile(p) for p in (
    r"(\d+) minut.*", r"(\d+) Minute.*", "(\\d+) דקות", "(\\d+) 分",
    "(\\d+) минута.*", r"(\d+) dakika",
    "(\\d+) хвилин.*", "(\\d+) 分.*",
    "(\\d+) 分钟")]  # fmt: skip
_MILES = ("mil", "Meile", "miglio", "מייל", "マイル",
          "миля", "миль", "英里")  # fmt: skip
_KILOMETERS = ("kilo", "Kilo", "kiló", "chilo", "quiló", "km",
               "кило", "кіло", "千米",
               "公里", "קילו",
               "キロメートル")  # fmt: skip


def duration_minutes(text: str | None) -> int | None:
    """``EBird.durationHrsMins``: "1 hour(s), 30 minute(s)" (and other languages)."""
    if not text:
        return None
    for pattern in _HOURS_AND_MINUTES:
        match = pattern.fullmatch(text)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2))
    for pattern in _HOURS:
        match = pattern.fullmatch(text)
        if match:
            return int(match.group(1)) * 60
    for pattern in _MINUTES:
        match = pattern.fullmatch(text)
        if match:
            return int(match.group(1))
    return None


def _decimal(text: str) -> str:
    return "".join(c for c in text if "0" <= c <= "9" or c == ".")


def distance_km(text: str | None) -> float | None:
    """``EBird.distanceMilesOrKilometers``: "2.0 mile(s)", "3.0 kilometer(s)"."""
    if text is None or not _decimal(text):
        return None
    value = parse_float32(_decimal(text))
    if value is None:
        raise ValueError(f"not a distance: {text!r}")  # Float.parseFloat fails
    if any(unit in text for unit in _MILES):
        return float32(value * KILOMETERS_IN_A_MILE)
    if any(unit in text for unit in _KILOMETERS):
        return value
    return None


def area_hectares(text: str | None) -> float | None:
    """``EBird.areaHectaresOrAcres``: "2.0 ac", "5.0 ha"."""
    if text is None or not _decimal(text):
        return None
    value = parse_float32(_decimal(text))
    if value is None:
        raise ValueError(f"not an area: {text!r}")
    if "ac" in text:
        return float32(value * HECTARES_IN_AN_ACRE)
    if "ha" in text:
        return value
    return None


def header_names(rows: Iterable[list[str]]) -> dict[str, list[str]]:
    """``ebird-checklist-headers.csv``: each English header, then its translations."""
    lines = [row for row in rows if row and any(row)]
    english = lines[0]
    names: dict[str, list[str]] = {name: [name] for name in english}
    for line in lines[1:]:
        for name, translated in zip(english, line, strict=True):
            names[name].append(translated.strip())
    return names


class EBirdChecklistFile:
    mass_export = False
    filters_dates = False
    format_name = "eBird checklist"
    name_distance = 1
    unreadable_message = "Pipit could not read any sightings from this checklist."

    def __init__(self, path: Path, names: dict[str, list[str]]) -> None:
        self.path = path
        rows = read_rows(path)
        if not rows:
            raise MissingHeaderError("The file is empty.")
        self.header: list[str] | None = rows[0]
        self.rows = rows[1:]
        index = {name: i for i, name in enumerate(rows[0])}

        def required(english: str) -> int:
            for localized in names.get(english, [english]):
                if localized in index:
                    return index[localized]
            raise MissingHeaderError(f'The file has no "{english}" column.')

        self._species = required("Species")
        self._count = required("Count")
        self._location = required("Location")
        self._date = required("Observation date")
        self._start = required("Start Time")
        comments = index.get("Comments")
        self._comments = comments if comments is not None else required("Details")
        self._protocol = required("Observation type")
        self._duration = required("Duration")
        self._distance = required("Distance")
        self._area = required("Area")
        self._party = required("Party Size")
        self._complete = required("Complete Checklist")
        #: Where eBird says the checklist was (``prepare``).
        self.place: ChecklistPlace | None = None

    def prepare(self, api: EBirdApi | None) -> None:
        """``longRunningTask``: ask eBird where the checklist was (any failure: no answer)."""
        match = CHECKLIST_ID.fullmatch(self.path.name)
        if api is None or match is None:
            return
        with contextlib.suppress(Exception):
            self.place = api.checklist_place(match.group(1))

    def location_key(self, row: list[str]) -> str:
        return string_at(row, self._location) or ""

    def taxon_key(self, row: list[str]) -> str:
        return string_at(row, self._species) or ""

    def date(self, row: list[str]) -> PartialDate | None:
        text = string_at(row, self._date)
        return parse_first_match(DATE_PARSERS, text) if text else None

    def imported_location(self, row: list[str],
                          shortcuts: LocationShortcuts) -> ImportedLocation:  # fmt: skip
        del shortcuts
        name, lat_long = name_and_lat_long(self.location_key(row))
        place = self.place
        if place is None or place.country_code is None:
            raise PlaceUnknownError(
                f"Pipit doesn't know where {name} is: turn on eBird access in Settings (with "
                "your eBird API key), and keep the checklist's file name (S…csv).")  # fmt: skip
        return ImportedLocation(
            country_code=place.country_code, state_code=place.state_code, county=place.county,
            ebird_hotspot_id=place.hotspot_id, location_names=[name],
            latitude=lat_long.latitude if lat_long else None,
            longitude=lat_long.longitude if lat_long else None,
        )  # fmt: skip

    def names(self, row: list[str],
              resolver: TaxonResolver) -> tuple[str | None, str | None, str | None]:  # fmt: skip
        """``EBird.CommonNameExtractor`` and ``ScientificNameExtractor``, then
        ``FieldTaxonImporter``'s binomial and subspecies."""
        name = string_at(row, self._species)
        scientific = _scientific_part(name, resolver)
        return (_common_part(name, resolver) or None, just_genus_and_species(scientific) or None,
                subspecies_if_present(scientific))  # fmt: skip

    def map_fields(self, row: list[str], sighting: Sighting) -> None:
        """Date, start time, count, details (only the date can fail)."""
        date = self.date(row)
        if date is not None:
            sighting.date = date
        start = string_at(row, self._start)
        if start:
            with contextlib.suppress(ValueError):
                sighting.time = parse_external_time(start)
        count = string_at(row, self._count)
        if count is not None:
            number = ApproximateNumber.parse(count)
            if number is not None:
                sighting.count = number
        details = string_at(row, self._comments)
        if details:
            sighting.description = details

    def visit(self, row: list[str]) -> VisitFields | None:
        party = int_at(row, self._party)
        return VisitFields(
            observation_type(string_at(row, self._protocol)),
            duration_minutes(string_at(row, self._duration)),
            distance_km(string_at(row, self._distance)),
            area_hectares(string_at(row, self._area)),
            party if party is not None and party > 0 else None,
            bool_at(row, self._complete),
            None,
        )

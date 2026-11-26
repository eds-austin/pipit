"""eBird life lists (the download on eBird's "My eBird" life list page): one row per species,
with the first sighting's place, state and date.

Ported from Scythebill ``ui/.../imports/EBird2023LifeListImporter.java`` (since 2023:
"Row #, Taxon Order, Category, Common Name, Scientific Name, Count, Location, S/P, Date,
LocID, SubID, Exotic, Countable") and ``EBirdLifeListImporter.java`` (earlier: a name column
that may hold the common name, the scientific name or both, then count, location, S/P and
date), and ``EBird.extractLatLongFromName`` and the name extractors. Dates are like
"05 Mar 2024" or "05-Mar-24". "Exotic" rows are introduced but not established. Names are
matched within one letter. Not a mass export, and no checklist details.
"""

from __future__ import annotations

import re
from pathlib import Path

from pipit.domain.partial_date import PartialDate
from pipit.domain.report import Sighting
from pipit.domain.values import ApproximateNumber, LatLong
from pipit.imports.fields import (
    JodaDateParser,
    bool_at,
    parse_first_match,
    read_rows,
    string_at,
)
from pipit.imports.my_data import MissingHeaderError
from pipit.imports.places import ImportedLocation, LocationShortcuts
from pipit.imports.source import VisitFields
from pipit.imports.taxa import TaxonResolver, java_trim, whitespace_count

DATE_PARSERS = [JodaDateParser("dd MMM yy"), JodaDateParser("dd-MMM-yy")]
UNREADABLE = "Pipit could not read any sightings from this file."

_PAREN = re.compile(r"(.*?) \((-?\d+\.\d+), (-?\d+\.\d+)\)")
_X = re.compile(r"(.*?) - (-?\d+\.\d+)x(-?\d+\.\d+)")
_COMMA = re.compile(r"(.*?)\s*(-?\d+\.\d+),\s*(-?\d+\.\d+)")
_COMMON_AND_SCIENTIFIC_IN_PARENS = re.compile(r"^(.+) \((.+)\)$")
_COMMON_AND_SCIENTIFIC_HYPHENATED = re.compile(r"^(.+) - (.+)$")
_SCIENTIFIC = re.compile(r"^\(?[A-Z][a-z]+ [a-z]+\)?")


def name_and_lat_long(name: str) -> tuple[str, LatLong | None]:
    """``EBird.extractLatLongFromName``: "Pond (12.34, -56.78)", "Pond - 12.34x-56.78" or
    "Pond 12.34, -56.78"."""
    for pattern in (_PAREN, _X, _COMMA):
        match = pattern.fullmatch(name)
        if match is not None:
            try:
                return match.group(1), LatLong.parse(match.group(2), match.group(3))
            except ValueError:
                return name, None
    return name, None


def just_genus_and_species(scientific: str | None) -> str | None:
    """``TaxonImporter.justGenusAndSpecies``: of three words, the first two."""
    if scientific is None or whitespace_count(scientific) <= 1:
        return scientific
    words = [word for word in (java_trim(part) for part in scientific.split(" ")) if word]
    return scientific if len(words) != 3 else f"{words[0]} {words[1]}"


def subspecies_if_present(scientific: str | None) -> str | None:
    """``TaxonImporter.subspeciesIfPresent``: of three words, the third."""
    if scientific is None or whitespace_count(scientific) <= 1:
        return None
    words = [word for word in (java_trim(part) for part in scientific.split(" ")) if word]
    return None if len(words) != 3 else words[2]


def _place(region: str, location: str | None) -> ImportedLocation:
    parts = region.split("-")
    if len(parts) != 2:
        raise ValueError(f"Doesn't look like an eBird file. The state is {region}")
    imported = ImportedLocation(country_code=parts[0], state_code=parts[1])
    if location:
        name, lat_long = name_and_lat_long(location)
        imported.location_names.append(name)
        if lat_long is not None:
            imported.latitude = lat_long.latitude
            imported.longitude = lat_long.longitude
    return imported


def _date(text: str | None) -> PartialDate | None:
    return parse_first_match(DATE_PARSERS, text) if text else None


def _count(row: list[str], index: int, sighting: Sighting) -> None:
    text = string_at(row, index)
    if text is not None:
        number = ApproximateNumber.parse(text)
        if number is not None:
            sighting.count = number


class EBirdLifeList2023File:
    mass_export = False
    filters_dates = False
    format_name = "eBird life list"
    name_distance = 1
    unreadable_message = UNREADABLE

    def __init__(self, path: Path) -> None:
        self.path = path
        rows = read_rows(path)
        if not rows:
            raise MissingHeaderError("The file is empty.")
        self.header: list[str] | None = rows[0]
        self.rows = rows[1:]
        index = {name.lower(): i for i, name in enumerate(rows[0])}

        def required(name: str) -> int:
            found = index.get(name.lower())
            if found is None:
                raise MissingHeaderError(f'The file has no "{name}" column.')
            return found

        self._common = required("Common Name")
        self._scientific = required("Scientific Name")
        self._count = required("Count")
        self._location = required("Location")
        self._date = required("Date")
        self._region = required("S/P")
        self._exotic = required("Exotic")
        self._hotspot = required("LocID")

    def location_key(self, row: list[str]) -> str:
        return f"{string_at(row, self._region) or ''}|{string_at(row, self._location) or ''}"

    def taxon_key(self, row: list[str]) -> str:
        return f"{string_at(row, self._common) or ''}|{string_at(row, self._scientific) or ''}"

    def date(self, row: list[str]) -> PartialDate | None:
        return _date(string_at(row, self._date))

    def imported_location(self, row: list[str],
                          shortcuts: LocationShortcuts) -> ImportedLocation:  # fmt: skip
        del shortcuts
        imported = _place(string_at(row, self._region) or "", string_at(row, self._location))
        imported.ebird_hotspot_id = string_at(row, self._hotspot) or None
        return imported

    def names(self, row: list[str],
              resolver: TaxonResolver) -> tuple[str | None, str | None, str | None]:  # fmt: skip
        del resolver
        scientific = string_at(row, self._scientific)
        return (string_at(row, self._common) or None,
                just_genus_and_species(scientific) or None,
                subspecies_if_present(scientific))  # fmt: skip

    def map_fields(self, row: list[str], sighting: Sighting) -> None:
        date = self.date(row)
        if date is not None:
            sighting.date = date
        _count(row, self._count, sighting)
        if bool_at(row, self._exotic):
            sighting.status = "notEstablished"

    def visit(self, row: list[str]) -> VisitFields | None:
        del row
        return None


class EBirdLifeListFile:
    """The life list before 2023: Row #, name, count, location, S/P, date."""

    mass_export = False
    filters_dates = False
    format_name = "eBird life list"
    name_distance = 1
    unreadable_message = UNREADABLE

    def __init__(self, path: Path) -> None:
        self.path = path
        rows = read_rows(path)
        self.header: list[str] | None = rows[0] if rows else None
        self.rows = rows[1:]

    def location_key(self, row: list[str]) -> str:
        return f"{string_at(row, 3) or ''}|{string_at(row, 4) or ''}"

    def taxon_key(self, row: list[str]) -> str:
        return string_at(row, 1) or ""

    def date(self, row: list[str]) -> PartialDate | None:
        return _date(string_at(row, 5))

    def imported_location(self, row: list[str],
                          shortcuts: LocationShortcuts) -> ImportedLocation:  # fmt: skip
        del shortcuts
        if len(row) < 5:
            raise ValueError(f"only {len(row)} columns")
        return _place(row[4], row[3] or None)

    def names(self, row: list[str],
              resolver: TaxonResolver) -> tuple[str | None, str | None, str | None]:  # fmt: skip
        """``EBird.CommonNameExtractor`` and ``ScientificNameExtractor`` on the one column,
        then ``FieldTaxonImporter``'s binomial and subspecies."""
        name = string_at(row, 1)
        common = _common_part(name, resolver)
        scientific = _scientific_part(name, resolver)
        return (common or None, just_genus_and_species(scientific) or None,
                subspecies_if_present(scientific))  # fmt: skip

    def map_fields(self, row: list[str], sighting: Sighting) -> None:
        date = self.date(row)
        if date is not None:
            sighting.date = date
        _count(row, 2, sighting)

    def visit(self, row: list[str]) -> VisitFields | None:
        del row
        return None


def _might_be_scientific(name: str, resolver: TaxonResolver) -> bool:
    if _SCIENTIFIC.search(name) is None:
        return False
    return resolver.map(name, None, None) is None and resolver.map(None, name, None) is not None


def _common_part(name: str | None, resolver: TaxonResolver) -> str | None:
    if name is None:
        return None
    match = _COMMON_AND_SCIENTIFIC_IN_PARENS.match(name)
    if match is not None:
        if name.endswith("))"):  # "Rock Pigeon (Feral Pigeon) (Columba livia (Domestic type))"
            first = name.find(")")
            if first > 0:
                return name[: first + 1]
        if _might_be_scientific(match.group(2), resolver):
            return match.group(1)
    match = _COMMON_AND_SCIENTIFIC_HYPHENATED.match(name)
    if match is not None and _might_be_scientific(match.group(2), resolver):
        return match.group(1)
    if _might_be_scientific(name, resolver):
        return None
    return name


def _scientific_part(name: str | None, resolver: TaxonResolver) -> str | None:
    if name is None:
        return None
    match = _COMMON_AND_SCIENTIFIC_IN_PARENS.match(name)
    if match is not None:
        if name.endswith("))"):
            middle = name.find(") (")
            if middle > 0:
                return name[middle + 3 : -1]
        if _might_be_scientific(match.group(2), resolver):
            return match.group(2)
    match = _COMMON_AND_SCIENTIFIC_HYPHENATED.match(name)
    if match is not None and _might_be_scientific(match.group(2), resolver):
        return match.group(2)
    if _might_be_scientific(name, resolver):
        return name.strip("()")
    return None

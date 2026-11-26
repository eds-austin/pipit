"""eBird's Record Format: the CSV eBird imports (and Scythebill's Save for eBird writes), 19
columns and no header.

Ported from Scythebill ``ui/.../imports/EBirdImportImporter.java``. Columns: 0 common name,
1 genus, 2 species (and maybe a subspecies), 3 count, 4 species comments, 5 location,
6 latitude, 7 longitude, 8 date (MM/dd/yyyy or MM-dd-yy), 9 start time, 10 state code,
11 country code, 12 protocol (Scythebill's IDs), 13 number of observers, 14 duration
(minutes), 15 complete (Y/N), 16 distance (miles), 17 area (acres), 18 checklist comments.

Scythebill's ways, kept: a subspecies is looked for in the common name's last parentheses or
brackets first, then as the species column's last word; names are matched within two
letters, as in older files; a duration of 0 still counts as one; distances and areas are
converted as float32 (1.60934 km a mile, 0.404686 ha an acre). It reads the file as a mass
export (asking about dates the list has) but never narrows it to the new dates. Old
Birder's Diary files without a country can name a place in brackets in the comments.

Rows whose place has no country can't be imported yet: Scythebill asks where they are.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from pipit.domain.partial_date import PartialDate
from pipit.domain.report import ObservationType, Sighting
from pipit.domain.values import ApproximateNumber, float32
from pipit.imports.fields import (
    JodaDateParser,
    bool_at,
    float_at,
    int_at,
    parse_external_time,
    parse_first_match,
    read_rows,
    string_at,
)
from pipit.imports.places import ImportedLocation, LocationShortcuts
from pipit.imports.source import VisitFields
from pipit.imports.taxa import TaxonResolver

DATE_PARSERS = [JodaDateParser("MM/dd/yyyy"), JodaDateParser("MM-dd-yy")]
KILOMETERS_IN_A_MILE = float32(1.60934)
HECTARES_IN_AN_ACRE = float32(0.404686)


class PlaceUnknownError(ValueError):
    """A place without a country, which Scythebill would ask the user to locate."""


def within_brackets(text: str | None) -> str | None:
    """``WithinBracesIfCountryIsEmpty.withinBrace``."""
    if text is None:
        return None
    start = text.find("[")
    if start < 0:
        return ""
    end = text.find("]", start + 1)
    if end < 0:
        return ""
    return text[start + 1 : end]


def subspecies_in_common_name(common: str | None) -> str | None:
    """``lookForSubspeciesInCommonName``: the last "(...)" or "[...]"."""
    if common is None:
        return None
    paren = common.rfind(")")
    bracket = common.rfind("]")
    if paren >= 0 and paren > bracket:
        start = common.rfind("(", 0, paren + 1)
        return None if start < 0 else common[start + 1 : paren]
    if bracket >= 0:
        start = common.rfind("[", 0, bracket + 1)
        return None if start < 0 else common[start + 1 : bracket]
    return None


def _last_word(species: str | None) -> str | None:
    if species is None:
        return None
    space = species.rfind(" ")
    return None if space < 0 else species[space + 1 :]


def _without_last_word(species: str | None) -> str | None:
    if species is None:
        return None
    space = species.rfind(" ")
    return species if space < 0 else species[:space]


class EBirdRecordFile:
    mass_export = True
    filters_dates = False
    format_name = "eBird Record Format"
    name_distance = 2
    unreadable_message = "Pipit could not read any sightings from this file."

    def __init__(self, path: Path) -> None:
        self.path = path
        self.header: list[str] | None = None
        self.rows = read_rows(path)

    # -------------------------------------------------------------- keys

    def location_key(self, row: list[str]) -> str:
        brackets = None if string_at(row, 11) else within_brackets(string_at(row, 4))
        return "|".join(part or "" for part in (string_at(row, 5), string_at(row, 10),
                                                 string_at(row, 11), brackets))  # fmt: skip

    def taxon_key(self, row: list[str]) -> str:
        return "|".join(string_at(row, i) or "" for i in (0, 1, 2))

    def date(self, row: list[str]) -> PartialDate | None:
        text = string_at(row, 8)
        return parse_first_match(DATE_PARSERS, text) if text else None

    # -------------------------------------------------------------- places and names

    def imported_location(self, row: list[str],
                          shortcuts: LocationShortcuts) -> ImportedLocation:  # fmt: skip
        if len(row) < 12:
            raise ValueError(f"only {len(row)} columns")
        imported = ImportedLocation(state_code=row[10] or None, country_code=row[11] or None,
                                    latitude=row[6] or None, longitude=row[7] or None)  # fmt: skip
        location = row[5] or None
        if imported.country_code is None:
            _country_from_name(shortcuts, imported, location)
            if imported.country is None and imported.country_code is None:
                imported.location_names.append(location)
        else:
            imported.location_names.append(location)
        if not row[11]:
            brackets = within_brackets(row[4]) or None
            if brackets is not None:
                imported.location_names.append(brackets)
        if (imported.country is None and imported.country_code is None
                and imported.location_names):  # fmt: skip
            names = ", ".join(str(name) for name in imported.location_names)
            raise PlaceUnknownError(f"{names} has no country")
        return imported

    def names(self, row: list[str],
              resolver: TaxonResolver) -> tuple[str | None, str | None, str | None]:  # fmt: skip
        del resolver
        common = string_at(row, 0)
        species = string_at(row, 2)
        scientific = f"{string_at(row, 1) or ''} {_without_last_word(species) or ''}"
        subspecies = subspecies_in_common_name(common)
        if subspecies is None:
            subspecies = _last_word(species)
        return common or None, scientific or None, subspecies

    # -------------------------------------------------------------- sightings

    def map_fields(self, row: list[str], sighting: Sighting) -> None:
        """Date, count, species comments, time; only the date can fail."""
        text = string_at(row, 8)
        if text:
            sighting.date = parse_first_match(DATE_PARSERS, text)
        count = string_at(row, 3)
        if count is not None:
            number = ApproximateNumber.parse(count)
            if number is not None:
                sighting.count = number
        comments = string_at(row, 4)
        if comments:
            sighting.description = comments
        time_text = string_at(row, 9)
        if time_text:
            with contextlib.suppress(ValueError):
                sighting.time = parse_external_time(time_text)

    def visit(self, row: list[str]) -> VisitFields:
        observation_type = ObservationType.from_id(string_at(row, 12) or "")
        miles = float_at(row, 16)
        acres = float_at(row, 17)
        observers = int_at(row, 13)
        return VisitFields(
            observation_type or ObservationType.HISTORICAL,
            int_at(row, 14),
            None if miles is None else float32(miles * KILOMETERS_IN_A_MILE),
            None if acres is None else float32(acres * HECTARES_IN_AN_ACRE),
            observers if observers is not None and observers > 0 else None,
            bool_at(row, 15),
            string_at(row, 18) or None,
        )


def _country_from_name(shortcuts: LocationShortcuts, imported: ImportedLocation,
                   location: str | None) -> None:  # fmt: skip
    """No country code: the place may be a country, or a US or Canadian state."""
    if location is None:
        return
    country = shortcuts.country_exact(location, None, None)
    if country is not None:
        if country.ebird_code is not None:
            imported.country_code = country.ebird_code
        else:
            imported.country = country.name
        return
    for code in ("US", "CA"):
        state = shortcuts.state_by_name(code, location)
        if state is not None:
            imported.country_code = code
            imported.state = state.name
            return

"""Location rules: built-in (predefined) places, eBird codes and new location IDs.

Ported from Scythebill:
- ``model/src/jvmMain/.../sighting/PredefinedLocations.kt``: the states, provinces and US
  counties offered below built-in countries and states (from ``all-states.csv`` and
  ``us-counties.csv``, kept as raw rows in the data pack);
- ``model/src/commonMain/.../sighting/Locations.kt`` (``getLocationCode``) and
  ``LocationImpl.getDefaultId`` / ``LocationSet.createId`` (IDs of new locations).

Countries, world regions and US states are not predefined here: Scythebill creates them in
every new list and saves them, so they are already in each list.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Container, Iterable
from dataclasses import dataclass

from pipit.domain.report import Location

BUILT_IN_PREFIX = "_"
PREDEFINED_PREFIX = "scyco"  # PredefinedLocations.PREDEFINED_LOCATION_PREFIX
DEFAULT_ID_LENGTH = 6
_WHITESPACE = re.compile(r"\s+")
_TYPE_NAMES = {
    "State": "state",
    "County": "county",
    "City": "city",
    "Country in Country": "country",
}


def is_built_in(location: Location) -> bool:
    return location.id.startswith(BUILT_IN_PREFIX)


def location_code(location: Location) -> str | None:
    """``Locations.getLocationCode``: the eBird code, with "US-" added to the bare
    two-letter codes US states store."""
    code = location.ebird_code
    if code is None:
        return None
    if location.type == "state" and "-" not in code and _is_us_child(location.parent):
        return f"US-{code}"
    return code


def _is_us_child(location: Location | None) -> bool:
    while location is not None:
        if location.ebird_code == "US":
            return True
        location = location.parent
    return False


def default_id(name: str, built_in_prefix: str | None = None) -> str:
    """``LocationImpl.getDefaultId``: up to six lowercase ASCII letters spread over the words
    of the name, behind "_<prefix>_" for built-in locations."""
    parts = [part for part in _WHITESPACE.split(name) if part]
    built = ""
    for i, part in enumerate(parts):
        remaining = DEFAULT_ID_LENGTH - len(built)
        per_word = math.ceil(remaining / (len(parts) - i)) if remaining > 0 else 0
        added = 0
        for character in part:
            if added >= per_word:
                break
            if "A" <= character <= "Z" or "a" <= character <= "z":
                built += character.lower()
                added += 1
    built = built[:DEFAULT_ID_LENGTH]
    if built_in_prefix is not None:
        return f"{BUILT_IN_PREFIX}{built_in_prefix}{BUILT_IN_PREFIX}{built}"
    return built


def create_id(
    name: str,
    existing_ids: Container[str],
    built_in_prefix: str | None = None,
    ebird_code: str | None = None,
) -> str:
    """``LocationSet.createId``: a predefined location takes "_scyco_<code>" when free;
    otherwise the default ID, with 1, 2, ... appended until unused."""
    base = default_id(name, built_in_prefix)
    populated = f"{BUILT_IN_PREFIX}{PREDEFINED_PREFIX}{BUILT_IN_PREFIX}"
    if ebird_code is not None and base.startswith(populated):
        code_id = populated + ebird_code
        if code_id not in existing_ids:
            return code_id
    i = 0
    while True:
        candidate = base if i == 0 else f"{base}{i}"
        if candidate not in existing_ids:
            return candidate
        i += 1


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def names_equal(first: str, second: str) -> bool:
    """``namesAreEqualIgnoringCaseAndAccents``."""
    return strip_accents(first).lower() == strip_accents(second).lower()


@dataclass(frozen=True, slots=True)
class PredefinedLocation:
    """A built-in place not necessarily in the list yet."""

    name: str
    code: str
    type: str  # "state", "county", "city" or "country"
    required_grandparent: str | None = None
    display_suffix: str = ""  # " (City)" for US independent cities

    @property
    def display_name(self) -> str:
        return self.name + self.display_suffix


class PredefinedLocations:
    def __init__(
        self,
        by_country: dict[str, list[PredefinedLocation]],
        us_counties: dict[str, list[PredefinedLocation]],
    ) -> None:
        self._by_country = by_country
        self._us_counties = us_counties

    @classmethod
    def from_rows(
        cls, all_states: Iterable[list[str]], us_counties: Iterable[list[str]]
    ) -> PredefinedLocations:
        """From the CSV rows (headers included), as ``loadAndParse`` reads them."""
        by_country: dict[str, list[PredefinedLocation]] = {}
        for fields in list(all_states)[1:]:
            if not fields or fields[3] == "Country":
                continue
            location_type = _TYPE_NAMES.get(fields[3])
            if location_type is None:
                raise ValueError(f"unexpected predefined location type {fields[3]!r}")
            required = fields[4] if len(fields) > 4 else None
            by_country.setdefault(fields[2], []).append(
                PredefinedLocation(fields[1], fields[0], location_type, required or None)
            )
        counties: dict[str, list[PredefinedLocation]] = {}
        for fields in list(us_counties)[1:]:
            if not fields:
                continue
            is_city = len(fields) >= 4 and fields[3] == "City"
            counties.setdefault(fields[1], []).append(
                PredefinedLocation(
                    fields[0],
                    f"US-{fields[1]}-{fields[2]}",
                    "city" if is_city else "county",
                    display_suffix=" (City)" if is_city else "",
                )
            )
        return cls(by_country, counties)

    def children(self, location: Location) -> list[PredefinedLocation]:
        """``getPredefinedLocations``: built-in places that belong directly below."""
        if location.ebird_code is None:
            return []
        parent = location.parent
        if location.type != "country":
            if location.type != "state":
                return []
            if not is_built_in(location) or parent is None or not is_built_in(parent):
                return []
            if location.name == parent.name:  # "Belize" state in "Belize" country
                return []
        if (
            is_built_in(location)
            and parent is not None
            and parent.name == "United States"
            and location.type == "state"
        ):
            return _ordered(self._us_counties.get(location.ebird_code, []))
        candidates = _ordered(self._by_country.get(location.name, []))
        if len(candidates) < 2:
            return []
        return [
            candidate
            for candidate in candidates
            if candidate.required_grandparent is None
            or _has_built_in_ancestor_named(parent, candidate.required_grandparent)
        ]


def _ordered(locations: list[PredefinedLocation]) -> list[PredefinedLocation]:
    return sorted(locations, key=lambda location: location.display_name.lower())


def _has_built_in_ancestor_named(location: Location | None, name: str) -> bool:
    """The first built-in ancestor (skipping custom ones) must have this name."""
    while location is not None:
        if is_built_in(location):
            return location.name == name
        location = location.parent
    return False

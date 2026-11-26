"""Places while importing: the list's location tree as Scythebill holds it once a file is
open, and imported place names matched into it.

Ported from Scythebill:
- ``LocationSet`` and ``PredefinedLocationPopulator``: every predefined place (states,
  provinces, US counties) is in the tree from the start, not "in use" until something uses
  it; unused ones aren't saved (``LocationsToSave``). IDs come from ``LocationSet.createId``.
- ``ui/.../imports/LocationShortcuts.java``: countries, states and regions by code and by
  (near) name.
- ``ui/.../imports/LocationAliases.java``: abbreviations and old names for places.
- ``ui/.../imports/ImportedLocation.java``: a country, state, county, city and place names
  turned into a place, creating what's missing.

Scythebill's look-up of a country from coordinates (``MapData``) isn't ported: the eBird
importers always give a country code, so they never need it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from pipit.domain.locations import (
    PREDEFINED_PREFIX,
    PredefinedLocations,
    create_id,
    is_built_in,
    location_code,
    names_equal,
)
from pipit.domain.report import Location, ReportSet
from pipit.domain.values import LatLong
from pipit.imports.bktree import BKTree
from pipit.output.names import REGION_KEYS, TRANSLATED_STATE_CODES
from pipit.search.normalize import normalize as trie_normalize

#: Scythebill's ``LocationSet.POPULATED_ID_PREFIX``.
POPULATED_ID_PREFIX = "_scyco_"
#: Built-in places a user may delete (``ReportSet.DELETEABLE_BUILT_IN_LOCATIONS``); none of
#: them is ever removed by an import, which only removes places it added.


class Places:
    """The list's places, with the predefined ones added, and which of those are in use."""

    def __init__(self, report: ReportSet, predefined: PredefinedLocations,
                 display_bundle: dict[str, str]) -> None:  # fmt: skip
        self.roots = report.roots
        self.predefined = predefined
        self._bundle = display_bundle
        self.by_id: dict[str, Location] = {}
        self.by_code: dict[str, Location] = {}
        self._codes: dict[str, list[Location]] = {}
        self._unused: set[int] = set()
        self._pending_built_in: set[int] = set()
        for location in report.iter_locations():
            self._index(location)
        self._populate()

    # -------------------------------------------------------------- the tree

    def _index(self, location: Location) -> None:
        self.by_id[location.id] = location
        code = location_code(location)
        if code is not None:
            self.by_code[code] = location
            self._codes.setdefault(code, []).append(location)

    def _populate(self) -> None:
        """``PredefinedLocationPopulator.populate``."""

        def populate(parent: Location) -> None:
            for candidate in self.predefined.children(parent):
                if parent.child_named(candidate.name) is not None:
                    continue
                if candidate.code in self.by_code:
                    continue
                created = Location("", candidate.name, candidate.type, parent=parent,
                                   ebird_code=candidate.code)  # fmt: skip
                if (location_code(created) or candidate.code) in self.by_code:
                    continue
                self._pending_built_in.add(id(created))
                self._attach(created)
                if created.id == POPULATED_ID_PREFIX + candidate.code:
                    self._unused.add(id(created))
            for child in list(parent.children):
                populate(child)

        for root in list(self.roots):
            populate(root)

    def _attach(self, location: Location) -> None:
        """``LocationSet.addLocation`` for a location whose parent is added."""
        prefix = PREDEFINED_PREFIX if id(location) in self._pending_built_in else None
        location.id = create_id(location.name, self.by_id, prefix, location.ebird_code)
        self._pending_built_in.discard(id(location))
        if location.parent is None:
            self.roots.append(location)
        else:
            location.parent.children.append(location)
        self._index(location)

    def new_location(self, name: str, location_type: str | None, parent: Location | None,
                     *, ebird_code: str | None = None) -> Location:  # fmt: skip
        """``Location.builder()...build()``: not added yet."""
        return Location("", name, location_type, parent=parent, ebird_code=ebird_code)

    def add(self, location: Location) -> None:
        if location.parent is not None and not location.parent.id:
            self.add(location.parent)
        self._attach(location)

    def ensure_added(self, location: Location) -> None:
        """``LocationSet.ensureAdded``: added, and (with its ancestors) in use."""
        if location.parent is not None:
            self.ensure_added(location.parent)
        if location.id:
            self._unused.discard(id(location))
            return
        self.add(location)

    def is_in_use(self, location: Location) -> bool:
        return id(location) not in self._unused

    def is_built_in(self, location: Location) -> bool:
        if not location.id:
            return id(location) in self._pending_built_in
        return is_built_in(location)

    def display_name(self, location: Location) -> str:
        """``Location.getDisplayName``."""
        if not self.is_built_in(location):
            return location.name
        code = location_code(location)
        if location.type == "state" and code not in TRANSLATED_STATE_CODES:
            return location.name
        if code is not None and code in self._bundle:
            return self._bundle[code]
        if location.type == "region" and location.name in REGION_KEYS:
            return self._bundle.get(REGION_KEYS[location.name], location.name)
        return location.name

    def codes(self, code: str) -> list[Location]:
        return self._codes.get(code, [])

    def delete(self, location: Location) -> None:
        """``ReportSet.deleteLocation`` for an empty place nothing refers to."""
        assert not location.children
        parent = location.parent
        if parent is not None:
            self.ensure_added(parent)
            parent.children.remove(location)
        else:
            self.roots.remove(location)
        del self.by_id[location.id]
        code = location_code(location)
        if code is not None:
            if self.by_code.get(code) is location:
                del self.by_code[code]
            self._codes[code].remove(location)
        location.parent = None

    def walk(self) -> Iterator[Location]:
        stack = list(reversed(self.roots))
        while stack:
            location = stack.pop()
            yield location
            stack.extend(reversed(location.children))

    def built_in_child(self, parent: Location, name: str) -> Location | None:
        """``PredefinedLocations.findBuiltInChild``."""
        return next(
            (
                child
                for child in parent.children
                if self.is_built_in(child) and names_equal(name, child.name)
            ),
            None,
        )

    def predefined_child(self, location: Location, name: str) -> bool:
        """``getPredefinedLocationChild(...) != null``."""
        return any(names_equal(name, candidate.name)
                   for candidate in self.predefined.children(location))  # fmt: skip

    def trim_unused(self, referenced: set[str]) -> None:
        """``LocationsToSave``: drop predefined places nothing uses, keeping ancestors of
        whatever is kept."""

        def keep(location: Location) -> bool:
            kept = [child for child in location.children if keep(child)]
            location.children[:] = kept
            return bool(kept) or self.is_in_use(location) or location.id in referenced

        self.roots[:] = [root for root in self.roots if keep(root)]


def is_descendent(ancestor: Location, location: Location | None) -> bool:
    """``Locations.isDescendentOfLocation``: ``location`` is ``ancestor`` or inside it."""
    while location is not None:
        if location is ancestor:
            return True
        location = location.parent
    return False


# ------------------------------------------------------------------ shortcuts

_ALTERNATE_NAMES: list[tuple[str, tuple[str, ...]]] = [
    ("AO-CAB", ("Cabinda",)), ("BA", ("Bosnia",)),
    ("BQ", ("Bonaire, Sint Eustatius and Saba", "Netherlands Antilles")),
    ("CD", ("Democratic Republic of Congo (Zaire)",)), ("CG", ("Peoples Republic of Congo",)),
    ("CI", ("Côte d'Ivoire",)), ("CW", ("Curaçao",)), ("CZ", ("Czechia",)),
    ("CY", ("Northern Cyprus",)), ("FK", ("Falkland Islands (Malvinas)", "Malvinas")),
    ("GB", ("Great Britain",)), ("FM", ("Federated States of Micronesia",)),
    ("GM", ("The Gambia",)), ("GS", ("South Georgia", "South Sandwich Islands")),
    ("HM", ("Heard Island",)), ("IT-88", ("Sardinia",)), ("IT-82", ("Sicily",)),
    ("MF", ("Saint-Martin",)), ("MK", ("Macedonia",)),
    ("MP", ("Commonwealth of the Northern Mariana Islands",)), ("MV", ("Maldive Islands",)),
    ("MY-12", ("Borneo",)), ("PM", ("Saint Pierre and Miquelon",)), ("PS", ("Palestine",)),
    ("RU", ("Russian Federation",)), ("SJ", ("Spitzbergen",)), ("SX", ("Sint Maarten",)),
    ("TF", ("French Southern Territories",)), ("TL", ("Timor-Leste",)),
    ("US", ("United States of America",)), ("VC", ("St Vincent & Grenadines",)),
    ("VI", ("United States Virgin Islands",)), ("WS", ("Western Samoa",)),
]  # fmt: skip
_SOMETIMES_COUNTRIES = frozenset({"SH-AC", "SH-SH", "SH-TA", "GB-ENG", "GB-NIR", "GB-SCT",
                                  "GB-WLS", "UM-71", "UM-79", "MY-12", "MY-13"})  # fmt: skip
_KNOWN_WITH_PARENT_CODES = {
    "Novaya Zemlya": "RU-ARK", "Franz Josef Land": "RU-ARK", "South Shetland Islands": "AQ",
    "South Orkney Islands": "AQ", "Amsterdam Island": "TF", "Kerguelen Island": "TF",
    "Crozet Islands": "TF", "Aru Islands": "ID-MA", "Kermadec Islands": "NZ-NTL",
}  # fmt: skip
_KNOWN_WITH_PARENT_REGIONS = {
    "Southern Caribbean Islands": "West Indies", "Lesser Antilles": "West Indies",
    "Virgin Islands": "West Indies", "Anguilla, St Martin & St Barthélémy": "West Indies",
    "Channel Islands": "Europe", "Mascarene Islands": "Indian Ocean",
}  # fmt: skip
_PREFERRED_PARENTS = {"United States": "North America", "Egypt": "Africa", "Turkey": "Asia",
                      "Indonesia": "Asia"}  # fmt: skip


def _preferred_order(location: Location) -> tuple[int, str]:
    """``PREFERRED_PARENT_ORDERING`` as a sort key: the preferred region first, then by the
    region's name."""
    parent = location.parent
    parent_name = parent.name if parent is not None else ""
    preferred = _PREFERRED_PARENTS.get(location.name)
    return (0 if preferred is not None and preferred == parent_name else 1, parent_name)


class _SortedValues:
    """A ``TreeMultimap``'s values for one key: sorted by ``_preferred_order``, each order
    once."""

    def __init__(self) -> None:
        self.items: list[Location] = []

    def add(self, location: Location) -> None:
        key = _preferred_order(location)
        if any(_preferred_order(item) == key for item in self.items):
            return
        self.items.append(location)
        self.items.sort(key=_preferred_order)


def _normalize_names(name: str) -> str:
    return trie_normalize(name.lower()).replace("saint", "st").replace("&", "and")


def _java_half(length: int) -> int:
    """(length - 1) / 2 with Java's truncation."""
    return int((length - 1) / 2)


@dataclass(slots=True)
class _CaseInsensitiveTable:
    """A ``TreeBasedTable`` with case-insensitive column keys."""

    rows: dict[str, dict[str, Location]] = field(default_factory=dict)

    def put(self, row: str, column: str, location: Location) -> None:
        self.rows.setdefault(row, {})[column.lower()] = location

    def get(self, row: str, column: str) -> Location | None:
        return self.rows.get(row, {}).get(column.lower())


class LocationShortcuts:
    """Countries, states and regions by code and name."""

    def __init__(self, places: Places, translated_countries: Iterable[tuple[str, str]]) -> None:
        self._places = places
        self._translated: dict[str, list[str]] = {}
        for code, name in translated_countries:
            self._translated.setdefault(code, []).append(name)
        self._countries_by_code: dict[str, _SortedValues] = {}
        self._all: dict[str, list[Location]] = {}
        self._states_by_code: dict[tuple[str | None, str], Location] = {}
        self._states_by_name = _CaseInsensitiveTable()
        self._by_code: dict[str, Location] = {}
        self._exact_countries: dict[str, _SortedValues] = {}
        self._country_names: BKTree[Location] = BKTree(_normalize_names)
        self._region_names: BKTree[Location] = BKTree(_normalize_names)
        self.max_distance = 3
        self._build(places.roots)
        for code, names in _ALTERNATE_NAMES:
            location = self.location_for_code(code)
            if location is not None:
                for name in names:
                    self._country_names.add(name, location)

    def _put_all(self, name: str, location: Location) -> None:
        found = self._all.setdefault(name, [])
        if location not in found:
            found.append(location)

    def _build(self, locations: Iterable[Location]) -> None:
        places = self._places
        for location in locations:
            display = places.display_name(location)
            different = display != location.name
            self._put_all(location.name, location)
            if different:
                self._put_all(display, location)
            code = location_code(location)
            if location.type == "country" or code in _SOMETIMES_COUNTRIES:
                self._country_names.add(location.name, location)
                self._exact_countries.setdefault(location.name, _SortedValues()).add(location)
                if different:
                    self._country_names.add(display, location)
                    self._exact_countries.setdefault(display, _SortedValues()).add(location)
                if code is not None:
                    self._by_code[code] = location
                if location.ebird_code is not None:
                    self._countries_by_code.setdefault(location.ebird_code,
                                                       _SortedValues()).add(location)  # fmt: skip
                for name in self._translated.get(code or "", []):
                    self._exact_countries.setdefault(name, _SortedValues()).add(location)
                    self._put_all(name, location)
            elif code is not None:
                self._by_code[code] = location
                for name in self._translated.get(code, []):
                    self._put_all(name, location)
            parent = location.parent
            if (_is_state_or_country_in_country(location) and location.ebird_code is not None
                    and parent is not None and parent.ebird_code is not None):  # fmt: skip
                self._states_by_code[(location_code(parent), code or "")] = location
                self._states_by_name.put(parent.ebird_code, location.name, location)
                if different:
                    self._states_by_name.put(parent.ebird_code, display, location)
            if location.type == "region" and places.is_built_in(location):
                self._region_names.add(location.name, location)
                if different:
                    self._region_names.add(display, location)
            self._build(location.children)

    # -------------------------------------------------------------- look-ups

    def country_from_code_with_child(self, code: str, child: str | None) -> Location | None:
        found = self._countries_by_code.get(code)
        return self._created(self._by_child(found.items if found else [], child))

    def country_from_code_with_parent(self, code: str, parent: str | None) -> Location | None:
        found = self._countries_by_code.get(code)
        return self._created(self._by_parent(found.items if found else [], parent))

    def location_for_code(self, code: str) -> Location | None:
        """``getLocationFromEBirdCode``."""
        return self._created(self._by_code.get(code))

    def state_by_code(self, country_code: str, state_code: str) -> Location | None:
        return self._created(self._states_by_code.get((country_code, state_code)))

    def state_by_name(self, country_code: str, name: str) -> Location | None:
        """``getStateByName``: a state of a country (by code), its name in any case."""
        return self._created(self._states_by_name.get(country_code, name))

    def region(self, name: str) -> Location | None:
        return self._created(self._growing_search(self._region_names, name))

    def country_exact(self, country: str, region: Location | None,
                      child: str | None) -> Location | None:  # fmt: skip
        if region is not None:
            in_region = region.child_named(country)
            if in_region is not None:
                return in_region
        found = self._exact_countries.get(country)
        return self._by_child(found.items if found else [], child)

    def country_inexact(self, country: str, region: Location | None,
                        child: str | None) -> Location | None:  # fmt: skip
        location = self._growing_search(self._country_names, country)
        if location is None:
            return None
        if region is not None:
            in_region = region.child_named(location.name)
            return in_region if in_region is not None else location
        if child is not None and not self._has_child(location, child):
            exact = self.country_exact(location.name, None, child)
            if exact is not None:
                location = exact
        return location

    def country_not_even_built_in_state(self, name: str) -> Location | None:
        code = _KNOWN_WITH_PARENT_CODES.get(name)
        if code is not None:
            parent = self.location_for_code(code)
            assert parent is not None, f"no location with code {code} for {name}"
            existing = parent.child_named(name)
            return existing or self._places.new_location(name, None, parent)
        region_name = _KNOWN_WITH_PARENT_REGIONS.get(name)
        if region_name is not None:
            region = self.region(region_name)
            assert region is not None, f"no region {region_name} for {name}"
            existing = region.child_named(name)
            return existing or self._places.new_location(name, None, region)
        return None

    def any_named(self, name: str) -> list[Location]:
        return self._all.get(name, [])

    def _growing_search(self, tree: BKTree[Location], name: str) -> Location | None:
        for distance in range(min(_java_half(len(name)), self.max_distance)):
            found = tree.search(name, distance)
            if found:
                return found[0]
        return None

    def _by_child(self, candidates: list[Location], child: str | None) -> Location | None:
        if not candidates:
            return None
        if len(candidates) > 1 and child is not None:
            for location in candidates:
                if self._has_child(location, child):
                    return location
        return candidates[0]

    def _by_parent(self, candidates: list[Location], parent: str | None) -> Location | None:
        if not candidates:
            return None
        if len(candidates) > 1 and parent is not None:
            for location in candidates:
                above = location.parent
                if above is not None and parent in (above.name,
                                                    self._places.display_name(above)):  # fmt: skip
                    return location
        return candidates[0]

    def _has_child(self, location: Location, child: str) -> bool:
        return (location.child_named(child) is not None
                or self._places.predefined_child(location, child))  # fmt: skip

    def _created(self, location: Location | None) -> Location | None:
        """``replaceWithCreated``: an added location stands; one not added yet becomes the
        added child of the same name, if there is one."""
        if location is None or location.id or location.parent is None:
            return location
        old_parent = location.parent
        new_parent = self._created(old_parent)
        assert new_parent is not None
        if new_parent is not old_parent:
            location = self._places.new_location(location.name, location.type, new_parent,
                                                 ebird_code=location.ebird_code)  # fmt: skip
        existing = new_parent.child_named(location.name)
        return location if existing is None else existing


def _is_state_or_country_in_country(location: Location) -> bool:
    if location.type == "state":
        return True
    parent = location.parent
    return location.type == "country" and parent is not None and parent.type == "country"


# ------------------------------------------------------------------ aliases

_APOSTROPHES = re.compile("['\u2018\u2019\u02bb\u02bc`]")
_NOT_LETTERS_OR_DIGITS = re.compile(r"[^\w]+|_+")


@dataclass(frozen=True, slots=True)
class Alias:
    kind: str  # "code", "inside" or "region"
    codes: tuple[str, ...]
    name: str | None
    type: str | None


def normalize_alias(text: str) -> str:
    """``LocationAliases.normalize``: lower case, no accents or apostrophes, "&" as "and",
    other punctuation and spaces as single spaces."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.category(c).startswith("M"))
    lowered = stripped.lower().replace("&", " and ")
    lowered = _APOSTROPHES.sub("", lowered)
    return _NOT_LETTERS_OR_DIGITS.sub(" ", lowered).strip()


def load_aliases(rows: Iterable[list[str]]) -> dict[str, Alias]:
    """``location-aliases.csv`` (comments and the header skipped, fields trimmed)."""
    aliases: dict[str, Alias] = {}
    header_seen = False
    for raw in rows:
        line = [field.strip() for field in raw]
        if not line or not line[0] or line[0].startswith("#"):
            continue
        if not header_seen:
            header_seen = True
            continue
        kind = line[1].lower()
        codes = tuple(code.strip() for code in line[2].split("|"))
        name = (line[3] or None) if len(line) > 3 else None
        location_type = (line[4] or None) if len(line) > 4 else None
        key = normalize_alias(line[0])
        if key in aliases:
            raise ValueError(f"duplicate location alias {line[0]!r}")
        aliases[key] = Alias(kind, codes, name, location_type)
    return aliases


# ------------------------------------------------------------------ imported places

_COUNTRY_WITH_REGION = re.compile(r"^(.*\S)\s*\(([^()]+)\)$")


@dataclass(slots=True)
class ImportedLocation:
    """``ImportedLocation``: what a file says about a place."""

    country_code: str | None = None
    country: str | None = None
    state_code: str | None = None
    state: str | None = None
    county: str | None = None
    location_names: list[str | None] = field(default_factory=list)
    city: str | None = None
    region: str | None = None
    default_region: str = "North America"
    latitude: str | None = None
    longitude: str | None = None
    description: str | None = None
    ebird_hotspot_id: str | None = None

    def lat_long(self) -> LatLong | None:
        if not self.longitude or not self.latitude:
            return None
        try:
            found = LatLong.parse(self.latitude, self.longitude)
        except ValueError:
            return None
        if float(found.latitude) == 0.0 and float(found.longitude) == 0.0:
            return None
        return found


class PlaceBuilder:
    """``ImportedLocation.addToLocationSet`` and its helpers."""

    def __init__(self, places: Places, shortcuts: LocationShortcuts,
                 aliases: dict[str, Alias]) -> None:  # fmt: skip
        self.places = places
        self.shortcuts = shortcuts
        self.aliases = aliases
        #: Places whose coordinates, description or hotspot an import set.
        self.changed: list[Location] = []

    def add(self, imported: ImportedLocation) -> Location | None:  # noqa: PLR0915
        places = self.places
        shortcuts = self.shortcuts
        current: Location | None = None
        country = imported.country
        if country is not None and country.lower() in ("usa", "us"):
            imported.country_code = "US"
        if country is not None and country.lower() == "uk":
            imported.country_code = "GB"
            imported.country = None
        if (
            imported.country is not None
            and len(imported.country) == 2
            and not imported.country_code
        ):
            imported.country_code = imported.country
            imported.country = None
        state = imported.state
        if state is not None and 1 <= len(state) <= 3 and imported.state_code is None:
            imported.state_code = state
        if not imported.country_code and (
            not imported.country
            or (
                shortcuts.country_exact(imported.country, None, None) is None
                and self.aliases.get(normalize_alias(imported.country)) is None
                and shortcuts.country_inexact(imported.country, None, None) is None
                and shortcuts.country_not_even_built_in_state(imported.country) is None
            )
        ):
            self._codes_from_lat_long(imported)
        if imported.country_code:
            if imported.state is not None:
                current = shortcuts.country_from_code_with_child(imported.country_code,
                                                                 imported.state)  # fmt: skip
            else:
                region = imported.region if imported.region is not None else imported.default_region
                current = shortcuts.country_from_code_with_parent(imported.country_code, region)
            if imported.state_code:
                with_state = shortcuts.location_for_code(
                    f"{imported.country_code}-{imported.state_code}"
                )
                if with_state is not None:
                    current = with_state
                    imported.state = None
                    imported.state_code = None
            if current is None and imported.country is None:
                imported.country = imported.country_code
        if current is None:
            current = self._country(imported)
            if current is None:
                return None
        current = self._special_states(imported, current)
        if imported.state_code or imported.state:
            current = self._state(imported, current)
        if imported.county:
            current = self._county(imported, current)
        if imported.city:
            city = current.child_named(imported.city)
            if city is None:
                city = self._add_if_necessary(places.new_location(imported.city, "city", current))
            current = city
        for name in imported.location_names:
            if name and name != current.name:
                location = current.child_named(name)
                if location is None:
                    grouped = self._grouped_parent(current, name)
                    if grouped is not None:
                        current = grouped
                        location = current.child_named(name)
                    if location is None:
                        location = self._add_if_necessary(places.new_location(name, None, current))
                current = location
        places.ensure_added(current)
        if not places.is_built_in(current):
            self._set_details(imported, current)
        return current

    def _set_details(self, imported: ImportedLocation, current: Location) -> None:
        """Coordinates, description and hotspot on a place of the user's own. Scythebill
        replaces the place with a copy that has them, which moves it to the end of its
        parent's places."""
        changed = False
        lat_long = imported.lat_long()
        if lat_long is not None:
            current.lat_long = lat_long
            changed = True
        if imported.description:
            current.description = imported.description
            changed = True
        if imported.ebird_hotspot_id:
            current.ebird_hotspot_id = imported.ebird_hotspot_id
            changed = True
        if not changed:
            return
        parent = current.parent
        if parent is not None:
            parent.children.remove(current)
            parent.children.append(current)
        if current not in self.changed:
            self.changed.append(current)

    def _country(self, imported: ImportedLocation) -> Location | None:
        shortcuts = self.shortcuts
        country = imported.country
        if country:
            region = shortcuts.region(imported.region) if imported.region is not None else None
            current = shortcuts.country_exact(country, region, imported.state)
            if current is None:
                current = self._alias(country, region, imported.state)
            if current is None:
                current = shortcuts.country_inexact(country, region, imported.state)
            if current is None:
                current = shortcuts.country_not_even_built_in_state(country)
            if current is None:
                current = self._country_with_region(country, imported.state)
            if current is None:
                if region is None:
                    region = shortcuts.region(imported.default_region)
                current = self._add_if_necessary(
                    self.places.new_location(country, "country", region)
                )
            elif current.ebird_code is not None:
                imported.country_code = current.ebird_code
            return current
        if imported.region:
            current = shortcuts.region(imported.region)
            if current is None:
                raise ValueError(f"Couldn't find region {imported.region}")
            return current
        return None

    def _special_states(self, imported: ImportedLocation, current: Location) -> Location:
        """The Falklands in the UK, the Galápagos in Ecuador and the Canaries in Spain."""
        state = imported.state
        swap: str | None = None
        if current.ebird_code == "GB" and state == "Falkland Islands":
            swap = "FK"
        elif current.ebird_code == "EC" and state is not None and (
                "Galapagos" in state or "Galápagos" in state):  # fmt: skip
            swap = "EC-W"
        elif current.ebird_code == "ES" and state is not None and (
                "Canary" in state or "Canarias" in state):  # fmt: skip
            swap = "ES-CN"
        if swap is not None:
            replacement = self.places.by_code.get(swap)
            if replacement is not None:
                imported.state = None
                imported.state_code = None
                return replacement
        return current

    def _state(self, imported: ImportedLocation, current: Location) -> Location:
        places = self.places
        state_location: Location | None = None
        if imported.state_code is not None and imported.country_code is not None:
            state_location = self.shortcuts.state_by_code(
                imported.country_code, f"{imported.country_code}-{imported.state_code}"
            )
            if state_location is not None:
                state_location = self._add_if_necessary(state_location)
        if state_location is not None:
            return state_location
        state_name = imported.state if imported.state is not None else imported.state_code
        assert state_name is not None
        if current.ebird_code == "ID":
            current, state_name = self._indonesia(imported, current, state_name)
        state_location = current.child_named(state_name)
        if state_location is None and places.built_in_child(current, state_name) is None:
            state_location = self._alias(state_name, current, None)
        if state_location is None:
            state_location = self._add_if_necessary(
                places.new_location(state_name, "state", current)
            )
        return state_location

    def _indonesia(self, imported: ImportedLocation, current: Location,
                   state_name: str) -> tuple[Location, str]:  # fmt: skip
        """Indonesian provinces by their usual birding names, and in Australasia where
        they're there."""
        names = imported.location_names
        if "Papua" in state_name or "Geelvink" in state_name or "Irian Jaya" in state_name:
            australasia = self.shortcuts.country_from_code_with_parent("ID", "Australasia")
            if australasia is not None:
                current = australasia
            if state_name not in ("Papua", "Irian Jaya"):
                names.insert(0, state_name)
            return current, "Papua"
        if any(word in state_name for word in ("Halmahera", "Timor", "Seram", "Molucca")):
            australasia = self.shortcuts.country_from_code_with_parent("ID", "Australasia")
            if australasia is not None:
                current = australasia
            if state_name not in ("Moluccas", "Molucca"):
                names.insert(0, state_name)
            return current, "Maluku"
        if state_name == "Java":
            return current, "Jawa"
        if state_name == "Sumatra":
            return current, "Sumatera"
        if state_name == "Bali":
            names.insert(0, "Bali")
            return current, "Nusa Tenggara"
        return current, state_name

    def _county(self, imported: ImportedLocation, current: Location) -> Location:
        county = imported.county
        assert county is not None
        names = imported.location_names
        original = county
        if county.endswith(" Co"):
            county = county[:-3]
        elif county.endswith(" County"):
            county = county[: -len(" County")]
        elif " (County" in county:
            county = county[: county.find(" (County")]
        if county != original and names and names[0] == original:
            names.pop(0)
        imported.county = county
        location = current.child_named(county)
        if location is None and self.places.built_in_child(current, county) is None:
            location = self._alias(county, current, None)
        if location is None:
            location = self._add_if_necessary(self.places.new_location(county, "county", current))
        return location

    def _country_with_region(self, country: str, state: str | None) -> Location | None:
        match = _COUNTRY_WITH_REGION.match(country)
        if match is None:
            return None
        region = self.shortcuts.region(match.group(2))
        if region is None:
            return None
        found = self.shortcuts.country_exact(match.group(1), region, state)
        if found is None:
            found = self.shortcuts.country_inexact(match.group(1), region, state)
        return found

    def _alias(self, text: str, within: Location | None,
               narrower: str | None) -> Location | None:  # fmt: skip
        """``resolveAlias``."""
        alias = self.aliases.get(normalize_alias(text))
        if alias is None:
            return None
        resolved: Location | None
        if alias.kind == "code":
            resolved = _within(within, self._for_code(alias.codes[0]))
        elif alias.kind == "inside":
            parent = _within(within, self._for_code(alias.codes[0]))
            if parent is None:
                resolved = None
            else:
                assert alias.name is not None
                resolved = parent.child_named(alias.name) or self._add_if_necessary(
                    self.places.new_location(alias.name, alias.type, parent)
                )
        else:
            resolved = self._region_alias(alias, within, narrower)
        if resolved is not None:
            self.places.ensure_added(resolved)
        return resolved

    def _region_alias(self, alias: Alias, within: Location | None,
                      narrower: str | None) -> Location | None:  # fmt: skip
        candidates = [found for code in alias.codes
                      if (found := _within(within, self._for_code(code))) is not None]  # fmt: skip
        if narrower:
            normalized = normalize_alias(narrower)
            for candidate in candidates:
                if normalized in (
                    normalize_alias(candidate.name),
                    normalize_alias(self.places.display_name(candidate)),
                ):
                    return candidate.parent
            for candidate in candidates:
                if (
                    candidate.child_named(narrower) is not None
                    or self.places.built_in_child(candidate, narrower) is not None
                ):
                    return candidate
        if alias.name is not None:
            default = _within(within, self._for_code(alias.name))
            if default is not None:
                return default
        if within is not None:
            inside = [candidate for candidate in candidates if candidate is not within]
            if len(inside) == 1:
                return inside[0]
        return None

    def _for_code(self, code: str) -> Location | None:
        """``LocationAliases.locationForCode``: every predefined place is already there."""
        found = self.shortcuts.location_for_code(code)
        if found is not None:
            return found
        return self.places.by_code.get(code)

    def _grouped_parent(self, current: Location, name: str) -> Location | None:
        """For "Presidio--Dragonfly Creek", a Presidio to put it in."""
        index = name.find("--")
        if index < 0:
            return None
        return self._child_matching(current, name[:index], direct=True)

    def _child_matching(self, location: Location, name: str, *, direct: bool) -> Location | None:
        """``findMatchingName``: a child by name (or display name), or a deeper place in use."""
        places = self.places
        for child in location.children:
            if ((direct or places.is_in_use(child))
                    and (child.name == name or places.display_name(child) == name)):  # fmt: skip
                return child
            found = self._child_matching(child, name, direct=False)
            if found is not None:
                return found
        return None

    def _add_if_necessary(self, location: Location) -> Location:
        """``addLocationIfNecessary``."""
        places = self.places
        parent = location.parent
        assert parent is not None
        places.ensure_added(parent)
        found = self._child_matching(parent, location.name, direct=True)
        if found is not None:
            return found
        built_in = places.built_in_child(parent, location.name)
        if built_in is not None:
            places.ensure_added(built_in)
            return built_in
        if not location.id:
            places.add(location)
        return location

    def _codes_from_lat_long(self, imported: ImportedLocation) -> bool:
        """Scythebill finds the country (and state) at the coordinates; not ported."""
        del imported
        return False


def _within(within: Location | None, location: Location | None) -> Location | None:
    if location is None:
        return None
    if within is not None and not is_descendent(within, location):
        return None
    return location

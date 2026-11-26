"""Names as Scythebill's reports write them.

- Taxa: ``TrivialLocalNames`` (the taxonomy's own English names) and ``Resolved``'s
  ``getCommonName``, ``getSimpleCommonName`` and ``getFullName``, with a sp. or hybrid joined
  by ``TaxonNames`` ("Glaucous-winged/Western Gull", "Larus occidentalis/glaucescens").
- IUCN status: ``TaxonUtils.getTaxonStatus`` (the worst up to the species), and for a sp. the
  least severe of its taxa (a hybrid is LC).
- Places: ``LocationNames.pathName`` ("Golden Gate Park, CA, United States").
"""

from __future__ import annotations

from pipit.query.model import QPlace
from pipit.query.results import taxonomy_index
from pipit.taxa.model import IUCN_STATUSES, Taxon, TaxonType, full_name, parent_of_type
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType

_LOCATION_TYPES = {"city": "City", "country": "Country", "county": "County", "park": "Park",
                   "region": "Region", "state": "State", "town": "Town"}  # fmt: skip


# ------------------------------------------------------------------ taxa


def abbreviated_name(taxon: Taxon) -> str:
    """``TaxonUtils.getAbbreviatedName``: "L.occidentalis", "L.o.wymani"."""
    if taxon.type is TaxonType.SPECIES:
        assert taxon.parent is not None
        return f"{taxon.parent.name[0]}.{taxon.name}"
    if taxon.type in (TaxonType.GROUP, TaxonType.SUBSPECIES):
        species = parent_of_type(taxon, TaxonType.SPECIES)
        assert species.parent is not None
        return f"{species.parent.name[0]}.{species.name[0]}.{taxon.name}"
    return taxon.name


def _parent_with_common_name(taxon: Taxon) -> Taxon | None:
    current = taxon
    while current.common_name is None:
        assert current.parent is not None
        current = current.parent
        if current.type > TaxonType.SPECIES:
            return None
    return current


def common_name(taxon: Taxon) -> str:
    """``TrivialLocalNames.getCommonName``."""
    if taxon.common_name is not None:
        return taxon.common_name
    parent = _parent_with_common_name(taxon)
    if parent is None:
        return full_name(taxon)
    return f"{common_name(parent)} ({abbreviated_name(taxon)})"


def simple_common_name(taxon: Taxon) -> str:
    """``TrivialLocalNames.getSimpleCommonName``: a subspecies' nearest common name."""
    parent = _parent_with_common_name(taxon)
    if parent is None:
        return full_name(parent_of_type(taxon, TaxonType.SPECIES))
    return common_name(parent)


def join_from_end(names: list[str], separator: str) -> str:
    """``TaxonNames.joinFromEnd``: shared trailing words written once."""
    if len(names) == 1:
        return names[0]
    components = [name.split(" ") for name in names]
    shortest = min(len(c) for c in components)
    if shortest == 1:
        return separator.join(names)
    shared: list[str] = []
    while True:
        index = len(components[0]) - len(shared) - 1
        if index < 0:
            break
        word = components[0][index]
        if any(len(c) - len(shared) - 1 < 0 or c[len(c) - len(shared) - 1] != word
               for c in components[1:]):  # fmt: skip
            break
        shared.insert(0, word)
        if len(shared) >= shortest - 1:
            break
    rest = [" ".join(c[: len(c) - len(shared)]) for c in components]
    return " ".join([separator.join(rest), *shared])


def join_from_start(names: list[str], separator: str) -> str:
    """``TaxonNames.joinFromStart``: shared leading words written once."""
    if len(names) == 1:
        return names[0]
    components = [name.split(" ") for name in names]
    shared: list[str] = []
    while True:
        n = len(shared)
        if n >= len(components[0]):
            break
        word = components[0][n]
        if any(n >= len(c) or c[n] != word for c in components[1:]):
            break
        shared.append(word)
    rest = [" ".join(c[len(shared) :]) for c in components]
    return " ".join([*shared, separator.join(rest)])


def ordered_taxa(resolved: Resolved) -> list[Taxon]:
    """``MultipleResolved.resolvedTaxa``: a sp.'s or hybrid's taxa in taxonomic order."""
    if len(resolved.taxa) == 1:
        return list(resolved.taxa)
    index = taxonomy_index(resolved.taxa[0].taxonomy)
    return sorted(resolved.taxa, key=lambda taxon: index[taxon.id])


def _joiner(resolved: Resolved) -> str:
    return " x " if resolved.type is SightingTaxonType.HYBRID else "/"


def _join_common(resolved: Resolved, names: list[str]) -> str:
    if resolved.largest_type is TaxonType.SPECIES:
        return join_from_end(names, _joiner(resolved))
    if resolved.largest_type in (TaxonType.GROUP, TaxonType.SUBSPECIES):
        return join_from_start(names, _joiner(resolved))
    raise ValueError(f"no common name for {resolved}")


def resolved_common_name(resolved: Resolved) -> str:
    if resolved.type is SightingTaxonType.SINGLE:
        return common_name(resolved.taxon)
    return _join_common(resolved, [common_name(t) for t in ordered_taxa(resolved)])


def resolved_simple_common_name(resolved: Resolved) -> str:
    if resolved.type is SightingTaxonType.SINGLE:
        return simple_common_name(resolved.taxon)
    names: list[str] = []
    for taxon in ordered_taxa(resolved):
        name = simple_common_name(taxon)
        if not names or names[-1] != name:
            names.append(name)
    return _join_common(resolved, names)


def resolved_full_name(resolved: Resolved) -> str:
    if resolved.type is SightingTaxonType.SINGLE:
        return full_name(resolved.taxon)
    return join_from_start([full_name(t) for t in ordered_taxa(resolved)], _joiner(resolved))


def taxon_status(taxon: Taxon) -> str:
    """``TaxonUtils.getTaxonStatus``: the most severe status from the taxon up to its species."""
    status = 0
    current: Taxon | None = taxon
    while current is not None and current.type <= TaxonType.SPECIES:
        status = max(status, IUCN_STATUSES.index(current.status or "LC"))
        current = current.parent
    return IUCN_STATUSES[status]


def resolved_status(resolved: Resolved) -> str:
    if resolved.type is SightingTaxonType.HYBRID:
        return "LC"
    return IUCN_STATUSES[min(IUCN_STATUSES.index(taxon_status(t)) for t in resolved.taxa)]


# ------------------------------------------------------------------ places


#: ``ResourceBundleLocationDisplayNames``: the states it translates (others keep their name).
TRANSLATED_STATE_CODES = frozenset({"EC-W", "PM", "CO-SAP"})
#: Built-in regions' keys in the bundle, by name.
REGION_KEYS = {"North America": "NORTH_AMERICA", "Central America": "CENTRAL_AMERICA",
               "West Indies": "WEST_INDIES", "South America": "SOUTH_AMERICA",
               "Eurasia": "EURASIA", "Europe": "EUROPE", "Asia": "ASIA", "Africa": "AFRICA",
               "Australasia": "AUSTRALASIA", "Pacific Ocean": "PACIFIC_OCEAN",
               "Indian Ocean": "INDIAN_OCEAN", "Atlantic Ocean": "ATLANTIC_OCEAN",
               "Arctic Ocean": "ARCTIC_OCEAN",
               "South Polar Region": "SOUTH_POLAR_REGION"}  # fmt: skip


def display_names(places: dict[str, QPlace], bundle: dict[str, str]) -> dict[str, str]:
    """``Location.getDisplayName`` where it isn't the stored name: built-in places named by
    Scythebill's ``locations.properties`` (by code; regions by name; most states keep
    theirs), such as "eSwatini" for Swaziland."""
    found: dict[str, str] = {}
    for xml_id, place in places.items():
        if not place.built_in:
            continue
        if place.type == "state" and place.code not in TRANSLATED_STATE_CODES:
            continue
        name = None
        if place.code is not None and place.code in bundle:
            name = bundle[place.code]
        elif place.type == "region" and place.name in REGION_KEYS:
            name = bundle.get(REGION_KEYS[place.name])
        if name is not None and name != place.name:
            found[xml_id] = name
    return found


class PlaceNames:
    """``LocationNames``, by each place's display name (``display``: those that differ from
    the stored name, from ``display_names``). Every place of the list is in use, so a place
    is told apart only from the list's other places of the same name."""

    def __init__(self, places: dict[str, QPlace], display: dict[str, str] | None = None) -> None:
        self._places = places
        self._display = display or {}
        self._by_name: dict[str, list[QPlace]] = {}
        for place in places.values():
            self._by_name.setdefault(self.name(place), []).append(place)

    @property
    def places(self) -> dict[str, QPlace]:
        return self._places

    def name(self, place: QPlace) -> str:
        """``getDisplayName``."""
        return self._display.get(place.xml_id, place.name)

    def _parent(self, place: QPlace) -> QPlace | None:
        return self._places.get(place.parent) if place.parent else None

    def name_with_type(self, place: QPlace) -> str:
        if place.type is not None and place.type != "region":
            return f"{self.name(place)} ({_LOCATION_TYPES[place.type]})"
        return self.name(place)

    def _in_ancestor_list(self, place: QPlace) -> str:
        """``nameInAncestorList``: "Park--Trail" below "Park" is "Trail"."""
        name = self.name(place)
        index = name.find("--")
        parent = self._parent(place)
        if index >= 0 and parent is not None and self.name(parent) == name[:index]:
            return name[index + 2 :]
        return name

    def _disambiguated(self, place: QPlace, standalone: bool) -> str:
        same = self._by_name.get(self.name(place), [place])
        if len(same) == 1:
            return self.name(place) if standalone else self._in_ancestor_list(place)
        by_type = all(other is place or other.type != place.type for other in same)
        parent = self._parent(place)
        if by_type or parent is None:
            return self.name_with_type(place)
        if standalone:
            return f"{self.name(place)} ({self.name(parent)})"
        return f"{self._in_ancestor_list(place)} ({self._in_ancestor_list(parent)})"

    def disambiguated_name(self, xml_id: str) -> str:
        """``disambiguatedName``: the name, with its type or parent's name when another
        place has the same name."""
        return self._disambiguated(self._places[xml_id], standalone=True)

    def _at_start(self, place: QPlace, standalone: bool) -> str:
        if place.type == "county":
            return self.name_with_type(place)
        return self._disambiguated(place, standalone)

    def path_name(self, xml_id: str, root: str | None) -> str:
        """``pathName``: the place, then its ancestors up to its country (or up to, not
        including, ``root``); intermediate places with a plain eBird code ("CA") by code."""
        if xml_id == root:
            return self._at_start(self._places[xml_id], standalone=True)
        result: str | None = None
        current = self._places.get(xml_id)
        while current is not None and current.xml_id != root:
            last = current.type == "country"
            useful_code = current.ebird_code is not None and "-" not in current.ebird_code
            if result is None:
                entry = self._at_start(current, standalone=False)
            elif not last and useful_code:
                entry = current.ebird_code or ""
            else:
                entry = self._in_ancestor_list(current)
            result = entry if result is None else f"{result}, {entry}"
            if last:
                break
            parent = self._parent(current)
            if parent is not None and self.name(current) == self.name(parent):
                parent = self._parent(parent)
            current = parent
        return result or ""

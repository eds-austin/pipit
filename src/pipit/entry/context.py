"""What entry needs to know about an open list: its places (and built-in places not yet in
it), the checklist for a place, and which species are already on the life list."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from pipit.datapack.pack import DataPack
from pipit.domain.locations import PredefinedLocations, is_built_in, location_code
from pipit.domain.report import Location
from pipit.entry.session import LocationChoice, LocationKind
from pipit.search.indexer import Indexer, bits_of
from pipit.storage.repository import load_locations
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType


def location_label(location: Location) -> str:
    """ "Point Reyes · Marin, California, United States" (up to three ancestors)."""
    ancestors: list[str] = []
    parent = location.parent
    while parent is not None and len(ancestors) < 3:
        if parent.type != "region":
            ancestors.append(parent.name)
        parent = parent.parent
    return location.name + (f" · {', '.join(ancestors)}" if ancestors else "")


@dataclass(frozen=True, slots=True)
class _Place:
    choice: LocationChoice
    location: Location | None  # existing ones
    uses: int


class ListContext:
    def __init__(self, connection: sqlite3.Connection, pack: DataPack,
                 predefined: PredefinedLocations) -> None:  # fmt: skip
        self._pack = pack
        self._predefined = predefined
        self._regions = {
            taxonomy_id: set(pack.checklist_regions(taxonomy_id))
            for (taxonomy_id,) in pack.connection.execute("SELECT id FROM taxonomies")
        }
        self._checklists: dict[tuple[str, str], dict[str, str]] = {}
        self.reload(connection)

    def reload(self, connection: sqlite3.Connection) -> None:
        """Re-read the list (after saving): places, uses and recorded taxa."""
        self.roots = load_locations(connection)
        self.locations: dict[str, Location] = {}
        stack = list(self.roots)
        while stack:
            location = stack.pop()
            self.locations[location.id] = location
            stack.extend(location.children)
        uses = Counter(
            dict(connection.execute(
                "SELECT location_xml_id, count(*) FROM sightings GROUP BY location_xml_id"
            ).fetchall())
        )  # fmt: skip
        codes = {location_code(location) for location in self.locations.values()}
        places: list[_Place] = []
        for location in self.locations.values():
            if location.restored:
                continue
            choice = LocationChoice(LocationKind.EXISTING, location.name,
                                    location_label(location), xml_id=location.id)  # fmt: skip
            places.append(_Place(choice, location, uses.get(location.id, 0)))
            if is_built_in(location):
                for predefined in self._predefined.children(location):
                    if predefined.code in codes:
                        continue
                    label = location_label(Location("", predefined.name, None, parent=location))
                    choice = LocationChoice(
                        LocationKind.PREDEFINED, predefined.name, label,
                        parent_xml_id=location.id, type=predefined.type, code=predefined.code,
                    )  # fmt: skip
                    places.append(_Place(choice, None, -1))
        places.sort(key=lambda place: (-place.uses, place.choice.label.lower()))
        self._places = places
        indexer = Indexer()
        for place in places:
            indexer.add(place.choice.name)
        self._place_index = indexer.freeze()
        self._recorded = {
            (taxonomy_id, taxon_id)
            for taxonomy_id, taxon_id in connection.execute(
                "SELECT DISTINCT taxonomy_id, taxon_id FROM sightings WHERE taxon_id IS NOT NULL"
            )
        }
        self._seen: dict[str, frozenset[str]] = {}

    # ------------------------------------------------------------ places

    def find_places(self, query: str, limit: int = 12) -> list[LocationChoice]:
        """Places whose names match (word prefixes), most-used first, built-in places after
        the list's own."""
        if not query.strip():
            return [place.choice for place in self._places[:limit] if place.uses > 0]
        hits = sorted(bits_of(self._place_index.find(query)))
        return [self._places[i].choice for i in hits[:limit]]

    def location(self, xml_id: str) -> Location | None:
        return self.locations.get(xml_id)

    # ------------------------------------------------------------ checklists

    def checklist_for(
        self, choice: LocationChoice | None, taxonomy_id: str
    ) -> dict[str, str] | None:
        """The built-in checklist of the nearest enclosing region that has one."""
        if choice is None:
            return None
        codes: list[str] = []
        if choice.kind is LocationKind.PREDEFINED and choice.code:
            codes.append(choice.code)
        start = self.locations.get(choice.xml_id or choice.parent_xml_id or "")
        while start is not None:
            code = location_code(start)
            if code:
                codes.append(code)
            start = start.parent
        regions = self._regions.get(taxonomy_id, set())
        for code in codes:
            if code in regions:
                key = (taxonomy_id, code)
                if key not in self._checklists:
                    self._checklists[key] = {
                        row.taxon_id: row.status for row in self._pack.checklist(taxonomy_id, code)
                    }
                return self._checklists[key]
        return None

    # ------------------------------------------------------------ life list

    def seen_species(self, display: Taxonomy) -> frozenset[str]:
        """Species of ``display`` with at least one sighting (any status)."""
        if display.id in self._seen:
            return self._seen[display.id]
        species: set[str] = set()
        for taxonomy_id, taxon_id in self._recorded:
            if taxonomy_id is not None:
                continue
            for taxon in _resolve(display, taxon_id):
                current: Taxon | None = taxon
                while current is not None and current.type is not TaxonType.SPECIES:
                    current = current.parent
                if current is not None:
                    species.add(current.id)
        self._seen[display.id] = frozenset(species)
        return self._seen[display.id]


def _resolve(display: Taxonomy, base_id: str) -> list[Taxon]:
    if isinstance(display, MappedTaxonomy):
        resolved = display.resolve_into(SightingTaxon.single(base_id))
        if resolved is None or resolved.type is not SightingTaxonType.SINGLE:
            return []
        return [resolved.taxon]
    taxon = display.get(base_id)
    return [taxon] if taxon is not None else []

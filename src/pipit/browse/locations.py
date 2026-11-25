"""The Locations screen's data: the place tree with sighting totals, what was seen in a place
(and every place inside it), and a place's own visits."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from pipit.browse.dates import date_key, display_date
from pipit.domain.partial_date import parse_partial_date
from pipit.domain.report import ObservationType
from pipit.entry.taxa import EntryTaxa
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

_SEPARATORS = {SightingTaxonType.SP: "/", SightingTaxonType.HYBRID: "+"}
_BELOW_SPECIES = ("subspecies", "group")


@dataclass(frozen=True, slots=True)
class PlaceNode:
    row: int
    xml_id: str
    parent: int | None
    name: str
    type: str | None
    ebird_code: str | None
    depth: int
    child_count: int
    sightings: int  # here and in every place inside

    @property
    def built_in(self) -> bool:
        return self.xml_id.startswith("_")


def location_tree(connection: sqlite3.Connection) -> list[PlaceNode]:
    """Every place in pre-order (siblings in list order)."""
    totals = dict(
        connection.execute(
            "SELECT c.ancestor, count(*) FROM sightings s "
            "JOIN locations l ON l.xml_id = s.location_xml_id "
            "JOIN location_closure c ON c.descendant = l.id GROUP BY c.ancestor"
        ).fetchall()
    )
    children: dict[int | None, list[tuple[int, str, str, str | None, str | None]]] = defaultdict(
        list
    )
    for row, parent, xml_id, name, kind, code in connection.execute(
        "SELECT id, parent_id, xml_id, name, type, ebird_code FROM locations "
        "ORDER BY parent_id, ord, id"
    ):
        children[parent].append((row, xml_id, name, kind, code))
    nodes: list[PlaceNode] = []
    stack: list[tuple[tuple[int, str, str, str | None, str | None], int | None, int]] = [
        (entry, None, 0) for entry in reversed(children[None])
    ]
    while stack:
        (row, xml_id, name, kind, code), parent, depth = stack.pop()
        nodes.append(
            PlaceNode(row, xml_id, parent, name, kind, code, depth,
                      len(children[row]), totals.get(row, 0))
        )  # fmt: skip
        stack.extend((entry, row, depth + 1) for entry in reversed(children[row]))
    return nodes


@dataclass(slots=True)
class SpeciesSeen:
    key: str  # a display taxon ID, "a/b" (sp.), "a+b" (hybrid) or "ext:<taxonomy>:<id>"
    common: str
    scientific: str
    order: int
    is_species: bool  # one species (not a sp., hybrid or genus-level entry)
    sightings: int = 0
    heard_only: int = 0
    first: tuple[int, int, int] = (99999, 0, 0)
    last: tuple[int, int, int] = (-1, 0, 0)
    first_text: str = ""
    last_text: str = ""
    places: set[str] = field(default_factory=set)
    sighting_ids: list[int] = field(default_factory=list)  # in list order


class SpeciesRollup:
    """Base sightings rolled up to species of the display taxonomy (subspecies and groups
    count as their species; a sp. or hybrid stays its own row; anything above species,
    like a genus-level sp., stays as it is)."""

    def __init__(self, taxa: EntryTaxa) -> None:
        self._taxa = taxa
        self._keys: dict[tuple[str, tuple[str, ...], str | None], str | None] = {}

    def key(self, kind: str, ids: tuple[str, ...], subspecies: str | None) -> str | None:
        cache_key = (kind, ids, subspecies)
        if cache_key not in self._keys:
            self._keys[cache_key] = self._compute(kind, ids, subspecies)
        return self._keys[cache_key]

    def _compute(self, kind: str, ids: tuple[str, ...], subspecies: str | None) -> str | None:
        stored = (
            SightingTaxon.single(ids[0]) if kind == "single"
            else SightingTaxon.with_secondary_subspecies(ids[0], subspecies or "") if kind == "ssp"
            else SightingTaxon.sp(ids) if kind == "sp"
            else SightingTaxon.hybrid(ids)
        )  # fmt: skip
        display = self._taxa.display
        resolved: Resolved | None
        try:
            if isinstance(display, MappedTaxonomy):
                resolved = display.resolve_into(stored)
            else:
                resolved = stored.resolve_internal(display)
        except (KeyError, ValueError):
            return None
        if resolved is None:
            return None
        if resolved.largest_type <= TaxonType.SPECIES:
            resolved = resolved.resolve_parent_of_type(TaxonType.SPECIES)
        if resolved.type is SightingTaxonType.SINGLE:
            return resolved.taxon.id
        separator = _SEPARATORS.get(resolved.type, "/")
        return separator.join(taxon.id for taxon in resolved.taxa)


def species_at(
    connection: sqlite3.Connection,
    taxa: EntryTaxa,
    row: int | None,
    rollup: SpeciesRollup | None = None,
    sighting_ids: list[int] | None = None,
) -> list[SpeciesSeen]:
    """What was seen in the place ``row`` and every place inside it (``None``: every
    sighting in the list, with or without a place; or just ``sighting_ids``, such as a
    trip's), in taxonomic order (other taxonomies, such as mammals, after the birds)."""
    rollup = rollup or SpeciesRollup(taxa)
    params: tuple[int | str, ...]
    if sighting_ids is not None:
        within = "WHERE s.id IN (SELECT value FROM json_each(?)) "
        params = (json.dumps(sighting_ids),)
    elif row is None:
        within, params = "", ()
    else:
        within = (
            "JOIN locations l ON l.xml_id = s.location_xml_id "
            "JOIN location_closure c ON c.descendant = l.id WHERE c.ancestor = ? "
        )
        params = (row,)
    parts: dict[int, list[str]] = defaultdict(list)
    for sighting, taxon_id in connection.execute(
        "SELECT t.sighting_id, t.taxon_id FROM sighting_taxa t "
        "JOIN sightings s ON s.id = t.sighting_id " + within + "ORDER BY t.sighting_id, t.ord",
        params,
    ):
        parts[sighting].append(taxon_id)
    extended = _extended_species(connection)
    trip_dates = _trip_dates(connection)
    seen: dict[str, SpeciesSeen] = {}
    for (
        sighting,
        taxonomy_id,
        kind,
        taxon_id,
        subspecies,
        year,
        month,
        day,
        heard,
        place,
        trip,
    ) in connection.execute(
        "SELECT s.id, s.taxonomy_id, s.kind, s.taxon_id, s.subspecies, s.date_y, "
        "s.date_m, s.date_d, s.heard_only, s.location_xml_id, s.trip_xml_id FROM sightings s "
        + within
        + "ORDER BY s.ord",
        params,
    ):
        ids = (taxon_id,) if taxon_id is not None else tuple(parts[sighting])
        if taxonomy_id is not None:
            key, common, scientific, order, is_species = extended.get(
                (taxonomy_id, ids[0]), (f"ext:{taxonomy_id}:{ids[0]}", ids[0], "", 0, False)
            )
            order += 1_000_000
        else:
            resolved_key = rollup.key(kind, ids, subspecies)
            if resolved_key is None:
                key = "?" + "/".join(ids)
                common, scientific, order = f"Unknown ({', '.join(ids)})", "", 2_000_000
                is_species = False
            else:
                key = resolved_key
                common, scientific = taxa.names(key)
                order = taxa.order(key)
                taxon = taxa.display.get(key)
                is_species = taxon is not None and taxon.type is TaxonType.SPECIES
        entry = seen.get(key)
        if entry is None:
            entry = seen[key] = SpeciesSeen(key, common, scientific, order, is_species)
        entry.sightings += 1
        entry.sighting_ids.append(sighting)
        entry.heard_only += heard
        if place is not None:
            entry.places.add(place)
        earliest, latest = _span((year, month, day), trip, trip_dates)
        when = date_key(*earliest)
        if when < entry.first:
            entry.first = when
            entry.first_text = display_date(*earliest)
        when = date_key(*latest)
        if when > entry.last:
            entry.last = when
            entry.last_text = display_date(*latest)
    return sorted(seen.values(), key=lambda entry: (entry.order, entry.key))


_Fields = tuple[int | None, int | None, int | None]


def _span(
    date: _Fields, trip: str | None, trip_dates: dict[str, tuple[_Fields, _Fields]]
) -> tuple[_Fields, _Fields]:
    """A sighting's first and last possible dates: its own, or for an undated sighting on
    a trip, the trip's (Scythebill's ``getStartDateAsPartial`` / ``getEndDateAsPartial``)."""
    if date == (None, None, None) and trip in trip_dates:
        return trip_dates[trip]
    return date, date


def _trip_dates(connection: sqlite3.Connection) -> dict[str, tuple[_Fields, _Fields]]:
    dates = {}
    for xml_id, start, end in connection.execute("SELECT xml_id, start_date, end_date FROM trips"):
        first = parse_partial_date(start)
        last = parse_partial_date(end)
        dates[xml_id] = ((first.year, first.month, first.day), (last.year, last.month, last.day))
    return dates


def _extended_species(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], tuple[str, str, str, int, bool]]:
    """(taxonomy, taxon) -> (key, common, scientific, order, is a species) of its species,
    for the embedded taxonomies (mammals)."""
    rows = {
        (taxonomy, taxon): (parent, rank, name, common, order)
        for taxonomy, taxon, parent, rank, name, common, order in connection.execute(
            "SELECT taxonomy_id, taxon_id, parent_taxon_id, rank, name, common_name, id "
            "FROM ext_taxa"
        )
    }
    result = {}
    for (taxonomy, taxon), (parent, rank, _name, _common, _order) in rows.items():
        current = taxon
        current_parent, current_rank = parent, rank
        while current_rank in _BELOW_SPECIES and current_parent is not None:
            current = current_parent
            found = rows.get((taxonomy, current))
            if found is None:
                break
            current_parent, current_rank = found[0], found[1]
        species = rows.get((taxonomy, current))
        if species is None:
            continue
        name, common, order = species[2], species[3], species[4]
        genus = rows.get((taxonomy, species[0])) if species[0] else None
        scientific = f"{genus[2]} {name}" if genus and species[1] == "species" else name
        result[(taxonomy, taxon)] = (
            f"ext:{taxonomy}:{current}", common or scientific, scientific, order,
            species[1] == "species",
        )  # fmt: skip
    return result


@dataclass(frozen=True, slots=True)
class VisitRow:
    visit_id: int
    date_text: str
    start_time: str
    protocol: str
    duration_minutes: int | None
    distance_km: str | None
    party_size: int | None
    complete: bool
    comments: str
    sightings: int
    date_raw: str


def visits_at(connection: sqlite3.Connection, xml_id: str) -> list[VisitRow]:
    """The place's own visits (eBird checklists), newest first, each with the number of
    sightings recorded at that place on that date."""
    counts = dict(
        connection.execute(
            "SELECT date, count(*) FROM sightings WHERE location_xml_id = ? GROUP BY date",
            (xml_id,),
        ).fetchall()
    )
    visits = []
    for (visit_id, date, year, month, day, start, kind, duration, distance, party,
         complete, comments) in connection.execute(
        "SELECT id, date, date_y, date_m, date_d, start_time, observation_type, "
        "duration_minutes, distance_km, party_size, complete, comments FROM visits "
        "WHERE location_xml_id = ?",
        (xml_id,),
    ):  # fmt: skip
        protocol = ObservationType.from_id(kind)
        visits.append(
            (date_key(year, month, day), start,
             VisitRow(visit_id, display_date(year, month, day), start,
                      protocol.label if protocol else kind, duration, distance, party,
                      bool(complete), comments or "", counts.get(date, 0), date))
        )  # fmt: skip
    visits.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [visit for _, _, visit in visits]


@dataclass(frozen=True, slots=True)
class PlaceDetails:
    row: int
    xml_id: str
    name: str
    type: str | None
    path: list[str]  # names from the root down to the parent
    ebird_code: str | None
    hotspot: str | None
    latitude: str | None
    longitude: str | None
    private: bool
    description: str
    has_checklist: bool


def place_details(connection: sqlite3.Connection, row: int) -> PlaceDetails | None:
    found = connection.execute(
        "SELECT id, xml_id, name, type, ebird_code, ebird_hotspot_id, latitude, longitude, "
        "private, description FROM locations WHERE id = ?",
        (row,),
    ).fetchone()
    if found is None:
        return None
    path = [
        name
        for (name,) in connection.execute(
            "SELECT l.name FROM location_closure c JOIN locations l ON l.id = c.ancestor "
            "WHERE c.descendant = ? AND c.depth > 0 ORDER BY c.depth DESC",
            (row,),
        )
    ]
    has_checklist = (
        connection.execute(
            "SELECT 1 FROM checklists WHERE location_xml_id = ? LIMIT 1", (found[1],)
        ).fetchone()
        is not None
    )
    return PlaceDetails(
        found[0], found[1], found[2], found[3], path, found[4], found[5], found[6], found[7],
        bool(found[8]), found[9] or "", has_checklist,
    )  # fmt: skip

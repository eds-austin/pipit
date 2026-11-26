"""One import, step by step, on a list held in memory.

Ported from Scythebill ``ui/.../imports/SightingsImporter.java``, ``CsvSightingsImporter.java``,
``ParsedLocationIds.java``, ``DefaultSightingStatus.java``, ``ImportCleanup.java`` and
``ImportController.java`` (without its dialogs). The steps, in Scythebill's order, each run
once:

1. ``check``: refuse a file with no row that reads (eBird's message when no date parses).
2. ``dates``: for a mass export, the dates new to the list; ``only_dates`` narrows the import
   to them ("import only the new dates?").
3. ``read_places_and_taxa``: places (all rows), then names (the rows imported); returns the
   names left to the user. ``resolve`` records what the user chose for them.
4. ``read_sightings``: the sightings, merging repeats of a taxon on one checklist; returns
   how many the list already has (same date, time and taxon).
5. ``finish``: add them (dropping or overwriting duplicates, as chosen), with their checklists'
   details; remove new places and trips nothing uses.

Scythebill counts duplicates with a Bloom filter, which can over-count by a few in tens of
thousands; Pipit counts exactly. Only what the question offers could differ; dropping and
overwriting use exact matches in both.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import time
from functools import cmp_to_key

from pipit.datapack.pack import DataPack
from pipit.domain.java_hash import hashmap_order, list_hash, string_hash
from pipit.domain.locations import location_code
from pipit.domain.partial_date import PartialDate, compare_partial_dates, parse_partial_date
from pipit.domain.report import (
    SIGHTING_STATUSES,
    Location,
    ObservationType,
    ReportSet,
    Sighting,
    Visit,
    VisitField,
    VisitKey,
)
from pipit.domain.values import ApproximateNumber, float32
from pipit.imports.fields import DateParseError
from pipit.imports.places import LocationShortcuts, PlaceBuilder, Places, load_aliases
from pipit.imports.source import ImportSource, VisitFields
from pipit.imports.taxa import (
    StatusOf,
    TaxonPossibilities,
    TaxonResolver,
    TbdTaxon,
    find_match_within,
    resolve,
)
from pipit.query.checklists import Checklists
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

NO_DATE = parse_partial_date("1900-01-01")
_DUPLICATE_SHARE = 0.0001  # ImportController.FALSE_POSITIVES


class ImportRefusedError(ValueError):
    """The file can't be imported; the message says why."""


@dataclass(frozen=True, slots=True)
class NewDates:
    """``computeNewDates``: dates in the file, and those of them the list doesn't have."""

    in_file: int
    new: list[PartialDate]


@dataclass(slots=True)
class ReadCounts:
    """What reading the sightings found (``SightingsImporter``'s counters)."""

    found: int = 0
    failed: int = 0
    merged: int = 0
    spuhs_dropped: int = 0
    failed_rows: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class ImportOutcome:
    added: list[Sighting]
    removed: list[Sighting]
    sp_to_resolve: list[SightingTaxon]
    visits_added: int = 0
    visits_replaced: int = 0


class ImportRun:
    """An import of one file into ``report`` (changed in place)."""

    def __init__(self, report: ReportSet, source: ImportSource, *, taxonomy: Taxonomy,
                 pack: DataPack, checklists: Checklists) -> None:  # fmt: skip
        self.report = report
        #: The sightings as loaded, in stored order (for storing what the import removes).
        self.original_sightings = list(report.sightings)
        self.source = source
        self.taxonomy = taxonomy
        self.base = taxonomy.base if isinstance(taxonomy, MappedTaxonomy) else taxonomy
        self.checklists = checklists
        self.places = Places(report, pack.predefined_locations(), pack.location_display_names())
        translated = [(row[1].strip(), row[0].strip())
                      for locale in ("de", "fr", "nl")
                      for row in pack.location_rows(f"imported-countries-{locale}.csv")
                      if row]  # fmt: skip
        self.shortcuts = LocationShortcuts(self.places, translated)
        self.place_builder = PlaceBuilder(
            self.places, self.shortcuts, load_aliases(pack.location_rows("location-aliases.csv"))
        )
        self._dates_filter: frozenset[PartialDate] | None = None
        self._location_ids: dict[str, str | None] = {}
        self._location_codes: dict[str, str | None] = {}
        self._taxa: dict[str, TaxonPossibilities] = {}
        self._ignored: set[str] = set()
        self.resolved_taxa = 0
        self.counts = ReadCounts()
        self._imports: list[Sighting] = []
        self._visits: dict[VisitKey, Visit] = {}
        self._sp_to_resolve: dict[SightingTaxon, None] = {}
        self._locations_before = {location.id for location in report.iter_locations()}
        self._locations_before.update(self.places.by_id)
        self._trips_before = {trip.id for trip in report.trips}

    # -------------------------------------------------------------- 1. check

    def check(self) -> None:
        """``initialCheck``: some row's fields (other than place and name) must read."""
        for row in self.source.rows:
            try:
                self.source.map_fields(row, Sighting(SightingTaxon.single("")))
            except DateParseError:
                continue
            return
        raise ImportRefusedError(self.source.unreadable_message)

    # -------------------------------------------------------------- 2. dates

    def dates(self) -> NewDates:
        """For a mass export: the file's dates (any that doesn't read stops the import),
        and those the list has no sighting on (outside private places)."""
        in_file: dict[PartialDate, None] = {}
        for row in self.source.rows:
            try:
                date = self.source.date(row)
            except DateParseError as error:
                raise ImportRefusedError(
                    f"A date in the file could not be read: {error}"
                ) from error
            if date is not None:
                in_file[date] = None
        private = {location.id for location in self.report.iter_locations() if location.private}
        existing = {
            sighting.date if sighting.date is not None else NO_DATE
            for sighting in self.report.sightings
            if sighting.taxonomy_id is None and sighting.location_id not in private
        }
        ordered = sorted(in_file, key=cmp_to_key(compare_partial_dates))
        return NewDates(len(ordered), [date for date in ordered if date not in existing])

    def only_dates(self, dates: Iterable[PartialDate]) -> None:
        """``onlyImportDatesIn``: import just these dates' rows (if the format can; for
        eBird's Record Format, Scythebill asks but imports every date anyway)."""
        if self.source.filters_dates:
            self._dates_filter = frozenset(dates)

    def _rows(self) -> list[list[str]]:
        """``importLines``: the rows imported (all, or those on the chosen dates)."""
        if self._dates_filter is None:
            return self.source.rows
        chosen = self._dates_filter
        return [row for row in self.source.rows if self.source.date(row) in chosen]

    # -------------------------------------------------------------- 3. places and names

    def read_places_and_taxa(self) -> dict[str, TbdTaxon]:
        """``parseLocationIds`` then ``parseTaxonomyIds``. Returns the names to ask about
        (by key), leaving out eBird's "sp." entries, which are dropped quietly."""
        self._read_places()
        tbd = self._read_taxa()
        self._ignored = {key for key, taxon in tbd.items() if taxon.should_ignore()}
        return {
            key: taxon
            for key, taxon in tbd.items()
            if not taxon.should_ignore() and (taxon.common_name or taxon.scientific_name)
        }

    def _read_places(self) -> None:
        first_line = 1 if self.source.header is None else 2
        for number, row in enumerate(self.source.rows, start=first_line):
            key = self.source.location_key(row)
            if key in self._location_ids:
                continue
            try:
                location = self.place_builder.add(
                    self.source.imported_location(row, self.shortcuts)
                )
            except (ValueError, AssertionError) as error:
                raise ImportRefusedError(f"The import failed on line {number}: {error}") from error
            if location is None:
                raise ImportRefusedError(f"The import failed on line {number}: no place")
            self._location_ids[key] = location.id
            self._location_codes[key] = self._nearest_checklist_code(location)

    def _read_taxa(self) -> dict[str, TbdTaxon]:
        resolver = TaxonResolver(self.taxonomy, maximum_name_distance=self.source.name_distance)
        doubtful: dict[str, tuple[TaxonPossibilities, TbdTaxon, dict[str | None, None]]] = {}
        tbd: dict[str, TbdTaxon] = {}
        self.resolved_taxa = 0
        for row in self._rows():
            key = self.source.taxon_key(row)
            location_key = self.source.location_key(row)
            if key in doubtful:
                _, later, codes = doubtful[key]
                self._note_place(later, location_key)
                codes[self._location_codes.get(location_key)] = None
            elif key in tbd:
                self._note_place(tbd[key], location_key)
            elif key not in self._taxa:
                common, binomial, rest = self.source.names(row, resolver)
                found = resolver.map(common, binomial, rest)
                if found is not None and found.good_match:
                    self._taxa[key] = found
                    self.resolved_taxa += 1
                elif found is not None:
                    later = TbdTaxon(common, binomial, rest or None)
                    self._note_place(later, location_key)
                    doubtful[key] = (found, later, {self._location_codes.get(location_key): None})
                else:
                    later = TbdTaxon(common, binomial, rest or None)
                    self._note_place(later, location_key)
                    tbd[key] = later
        for key, (found, later, codes) in doubtful.items():
            if self._matches_any_checklist(found, [code for code in codes if code is not None]):
                self._taxa[key] = found
                self.resolved_taxa += 1
            else:
                tbd[key] = later
        return tbd

    def _note_place(self, taxon: TbdTaxon, location_key: str) -> None:
        location_id = self._location_ids.get(location_key)
        if location_id is not None:
            taxon.location_ids[location_id] = None

    def _matches_any_checklist(self, found: TaxonPossibilities, codes: list[str]) -> bool:
        """``PossiblyBadTaxonMappings.matchesAnyChecklists``."""
        if not codes:
            return True
        for code in codes:
            status_of = self._status_of(self.taxonomy, code)
            if status_of is None:
                continue
            chosen = found.choose(status_of, self.taxonomy)
            resolved = resolve(chosen, self.taxonomy)
            assert resolved is not None
            species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
            if species.type is SightingTaxonType.HYBRID:
                return True
            if species.type is SightingTaxonType.SP:
                if any(status_of(SightingTaxon.single(i)) is not None for i in species.ids):
                    return True
            elif status_of(species) is not None:
                return True
        return False

    def chosen_taxon(self, taxon_id: str, name: TbdTaxon) -> SightingTaxon:
        """A taxon of the import's taxonomy picked for a name, as ``ImportResolveTaxaPanel``
        takes it: its subspecies if the name has one there, in the base taxonomy."""
        taxon = self.taxonomy[taxon_id]
        if name.subspecies and taxon.type is TaxonType.SPECIES:
            match = find_match_within(taxon, name.subspecies, prefer_groups=False)
            if match is not None:
                taxon = match
        if not isinstance(self.taxonomy, MappedTaxonomy):
            return SightingTaxon.single(taxon.id)
        mapped = self.taxonomy.mapping_of(SightingTaxon.single(taxon.id))
        if mapped is None and taxon.parent is not None:
            mapped = self.taxonomy.mapping_of(SightingTaxon.single(taxon.parent.id))
        if mapped is None:
            raise ValueError(f"{taxon.name} has no counterpart in {self.base.name}")
        return mapped

    def resolve(self, chosen: dict[str, SightingTaxon]) -> None:
        """The user's choices for names left to them (base taxa); others are dropped."""
        for key, taxon in chosen.items():
            self._taxa[key] = TaxonPossibilities(taxon, good_match=True)

    # -------------------------------------------------------------- checklists

    def _nearest_checklist_code(self, location: Location) -> str | None:
        """``getNearestBuiltInChecklist``: the code of the nearest place (itself or above)
        with a built-in checklist."""
        current: Location | None = location
        while current is not None:
            code = self._checklist_code(current)
            if code is not None and self.checklists.checklist_for_codes(self.base, [code]):
                return code
            current = current.parent
        return None

    def _checklist_code(self, location: Location) -> str | None:
        """``ChecklistLocationCodes.getChecklistLocationCode``."""
        code = location_code(location)
        parent_name = location.parent.name if location.parent is not None else None
        if (code == "US" and parent_name != "North America") or code == "UM":
            return None
        if code == "BQ" and parent_name != "West Indies":
            return None
        if code in ("RU", "ID", "XX"):
            parent = location.parent
            while parent is not None:
                if self.places.is_built_in(parent) and parent.type == "region":
                    return f"{code}-{parent.name}"
                parent = parent.parent
            return None
        return code

    def _status_of(self, taxonomy: Taxonomy, code: str | None) -> StatusOf | None:
        if code is None:
            return None
        checklist = self.checklists.checklist_for_codes(taxonomy, [code])
        return None if checklist is None else checklist.status

    # -------------------------------------------------------------- 4. sightings

    def read_sightings(self) -> int:
        """``parseSightings``; returns how many imported sightings the list already has."""
        self._imports = []
        self._visits = {}
        by_visit: dict[tuple[VisitKey, SightingTaxon], Sighting] = {}
        for row in self._rows():
            self.counts.found += 1
            try:
                sighting = self._sighting(row)
            except (DateParseError, KeyError):
                if self.source.taxon_key(row) in self._ignored:
                    self.counts.spuhs_dropped += 1
                    self.counts.found -= 1
                else:
                    self.counts.failed += 1
                    self.counts.failed_rows.append(row)
                continue
            key = _visit_key(sighting)
            if key is not None:
                existing = by_visit.get((key, sighting.taxon))
                if existing is not None:
                    sighting = _merge(existing, sighting)
                    del self._imports[next(i for i, s in enumerate(self._imports) if s is existing)]
                    self.counts.found -= 1
                    self.counts.merged += 1
                by_visit[(key, sighting.taxon)] = sighting
            self._imports.append(sighting)
            if key is not None:
                fields = self.source.visit(row)
                visit = None if fields is None else _visit(key, fields)
                if visit is not None:
                    self._visits[key] = visit
        return self._count_duplicates()

    def _sighting(self, row: list[str]) -> Sighting:
        location_id = self._location_ids[self.source.location_key(row)]
        possibilities = self._taxa[self.source.taxon_key(row)]
        code = self._location_codes.get(self.source.location_key(row))
        status_of = (
            self._status_of(self.taxonomy, code)
            if possibilities.has_alternates and location_id is not None
            else None
        )
        chosen = possibilities.choose(status_of, self.taxonomy)
        if possibilities.chose_sp_to_resolve(chosen):
            self._sp_to_resolve[chosen] = None
        sighting = Sighting(chosen, location_id=location_id)
        self.source.map_fields(row, sighting)
        if sighting.status == "none":
            sighting.status = self._default_status(chosen, code)
        if sighting.date == NO_DATE:
            sighting.date = None
            sighting.time = None
        return sighting

    def _default_status(self, taxon: SightingTaxon, code: str | None) -> str:
        """``DefaultSightingStatus.forTaxon``."""
        status = "none"
        if taxon.type is SightingTaxonType.SINGLE:
            status = {"IN": "intro", "DO": "domestic"}.get(self.base[taxon.id].status, "none")
        if status in ("none", "domestic"):
            status_of = self._status_of(self.base, code)
            if status_of is not None:
                found = status_of(taxon)
                if found in ("INTRODUCED", "RARITY_FROM_INTRODUCED"):
                    status = "intro"
                elif found == "PROVISIONAL":
                    status = "provisional"
                elif found == "ESCAPED":
                    status = "notEstablished"
        return status

    def _count_duplicates(self) -> int:
        """``countDuplicates``, exactly."""
        if not self.report.sightings:
            return 0
        starts = self._trip_starts()
        existing = {_funnel(sighting, starts) for sighting in self.report.sightings}
        return sum(1 for sighting in self._imports if _funnel(sighting, starts) in existing)

    def _trip_starts(self) -> dict[str, PartialDate]:
        return {trip.id: trip.start_date for trip in self.report.trips}

    @property
    def imports(self) -> list[Sighting]:
        return self._imports

    def asks_about_duplicates(self, count: int) -> bool:
        return count > 0 and count > 2 * (len(self._imports) * _DUPLICATE_SHARE)

    # -------------------------------------------------------------- 5. finish

    def finish(self, duplicates: str = "importAll") -> ImportOutcome:
        """``finishImport``: ``duplicates`` is "importAll", "drop" or "overwrite"."""
        imports = self._imports
        removed: list[Sighting] = []
        count = self._count_duplicates()
        if self.asks_about_duplicates(count):
            if duplicates == "drop" and count != len(imports):
                imports = self._drop_duplicates(imports)
            elif duplicates == "overwrite":
                removed = self._existing_duplicates(imports)
        removed_ids = {id(sighting) for sighting in removed}
        self.report.sightings[:] = [sighting for sighting in self.report.sightings
                                    if id(sighting) not in removed_ids]  # fmt: skip
        for sighting in imports:
            if sighting.location_id is not None:
                self.places.ensure_added(self.places.by_id[sighting.location_id])
        self.report.sightings.extend(imports)
        visits_added, visits_replaced = self._put_visits()
        self._clean_up()
        sp_to_resolve = list(self._sp_to_resolve)
        if isinstance(self.taxonomy, MappedTaxonomy):
            sp_to_resolve = [taxon for taxon in sp_to_resolve
                             if (found := resolve(taxon, self.taxonomy)) is not None
                             and found.type is SightingTaxonType.SP]  # fmt: skip
        return ImportOutcome(imports, removed, sp_to_resolve, visits_added, visits_replaced)

    def _put_visits(self) -> tuple[int, int]:
        """The checklists' details, in Scythebill's (hash) order; one that needs a start
        time but has none becomes historical. Returns how many were added and replaced."""
        added = replaced = 0
        keys = list(self._visits)
        index = {visit.key: i for i, visit in enumerate(self.report.visits)}
        for key in hashmap_order(keys, [_visit_key_hash(key) for key in keys], 16):
            visit = self._visits[key]
            if key.start_time is None and VisitField.START_TIME in visit.observation_type.required:
                visit = _with_type(visit, ObservationType.HISTORICAL)
            if key in index:
                self.report.visits[index[key]] = visit
                replaced += 1
            else:
                index[key] = len(self.report.visits)
                self.report.visits.append(visit)
                added += 1
        return added, replaced

    def _drop_duplicates(self, imports: list[Sighting]) -> list[Sighting]:
        mapped = isinstance(self.taxonomy, MappedTaxonomy)

        def taxon_of(sighting: Sighting) -> object:
            if not mapped:
                return sighting.taxon
            found = resolve(sighting.taxon, self.taxonomy)
            return None if found is None else found.sighting_taxon

        starts = self._trip_starts()
        keys = {
            key for sighting in imports if (key := _duplicate_key(sighting, starts)) is not None
        }
        existing = {
            (key, taxon_of(sighting))
            for sighting in self.report.sightings
            if sighting.taxonomy_id is None
            and (key := _duplicate_key(sighting, starts)) is not None
            and key in keys
        }
        return [sighting for sighting in imports
                if (key := _duplicate_key(sighting, starts)) is None
                or (key, taxon_of(sighting)) not in existing]  # fmt: skip

    def _existing_duplicates(self, imports: list[Sighting]) -> list[Sighting]:
        starts = self._trip_starts()
        imported = {(key, sighting.taxon) for sighting in imports
                    if (key := _duplicate_key(sighting, starts)) is not None}  # fmt: skip
        return [sighting for sighting in self.report.sightings
                if (_duplicate_key(sighting, starts), sighting.taxon) in imported]  # fmt: skip

    def _move_to_parent(self, location: Location) -> None:
        """``ReportSet.deleteLocation``: a deleted place's checklist details (unless its
        parent has some for the same visit) and trips go to its parent."""
        parent = location.parent
        visits = self.report.visits
        keys = {visit.key for visit in visits}
        for visit in [visit for visit in visits if visit.key.location_id == location.id]:
            if parent is not None:
                moved = VisitKey(parent.id, visit.key.date, visit.key.start_time)
                if moved not in keys:
                    keys.add(moved)
                    visits.append(Visit(moved, visit.observation_type, visit.area_hectares,
                                        visit.distance_km, visit.duration_minutes,
                                        visit.party_size, visit.comments, visit.complete,
                                        list(visit.photos)))  # fmt: skip
            visits.remove(visit)
        for trip in self.report.trips:
            if trip.location_id == location.id:
                trip.location_id = None if parent is None else parent.id

    def _clean_up(self) -> None:
        """``ImportCleanup.cleanUnneededLocationsAndTrips``, then ``LocationsToSave``."""
        with_sightings = {s.location_id for s in self.report.sightings if s.location_id}
        while True:
            unneeded = [location for location in self.places.walk()
                        if location.id not in self._locations_before
                        and location.id not in with_sightings
                        and not self.places.is_built_in(location)
                        and not location.children]  # fmt: skip
            if not unneeded:
                break
            for location in unneeded:
                self._move_to_parent(location)
                self.places.delete(location)
        trips_used = {s.trip_id for s in self.report.sightings if s.trip_id}
        self.report.trips[:] = [
            trip
            for trip in self.report.trips
            if trip.id in self._trips_before or trip.id in trips_used
        ]
        referenced = set(with_sightings)
        referenced.update(t.location_id for t in self.report.trips if t.location_id)
        referenced.update(visit.key.location_id for visit in self.report.visits)
        referenced.update(checklist.location_id for checklist in self.report.checklists)
        self.places.trim_unused(referenced)


# ------------------------------------------------------------------ helpers


def _visit_key(sighting: Sighting) -> VisitKey | None:
    """``VisitInfoKey.forSighting``."""
    if sighting.location_id is None or sighting.date is None:
        return None
    return VisitKey(sighting.location_id, sighting.date, sighting.time)


def _visit(key: VisitKey, fields: VisitFields) -> Visit | None:
    """``VisitInfo.Builder.build`` (historical if a required field is missing), kept only
    if it has more than a protocol (``hasData``; incidental counts)."""
    visit = Visit(key, fields.observation_type,
                  area_hectares=None if fields.area_hectares is None
                  else float32(fields.area_hectares),
                  distance_km=None if fields.distance_km is None else float32(fields.distance_km),
                  duration_minutes=fields.duration_minutes, party_size=fields.party_size,
                  complete=fields.complete,
                  comments=fields.comments)  # fmt: skip
    visit = _checked(visit)
    has_data = (
        visit.area_hectares is not None
        or visit.distance_km is not None
        or visit.duration_minutes is not None
        or visit.comments is not None
        or visit.party_size is not None
        or visit.complete
        or visit.observation_type is ObservationType.INCIDENTAL
        or bool(visit.photos)
    )
    return visit if has_data else None


def _checked(visit: Visit) -> Visit:
    required = visit.observation_type.required
    if ((VisitField.AREA in required and visit.area_hectares is None)
            or (VisitField.DURATION in required and visit.duration_minutes is None)
            or (VisitField.DISTANCE in required and visit.distance_km is None)
            or (VisitField.PARTY_SIZE in required and visit.party_size is None)):  # fmt: skip
        visit.observation_type = ObservationType.HISTORICAL
    hidden = visit.observation_type.hidden
    if VisitField.AREA in hidden:
        visit.area_hectares = None
    if VisitField.DURATION in hidden:
        visit.duration_minutes = None
    if VisitField.DISTANCE in hidden:
        visit.distance_km = None
    if VisitField.PARTY_SIZE in hidden:
        visit.party_size = None
    return visit


def _with_type(visit: Visit, observation_type: ObservationType) -> Visit:
    """``asBuilder().withObservationType(...).build()``."""
    return _checked(Visit(visit.key, observation_type, visit.area_hectares, visit.distance_km,
                          visit.duration_minutes, visit.party_size, visit.comments,
                          visit.complete, list(visit.photos)))  # fmt: skip


def _merge(existing: Sighting, new: Sighting) -> Sighting:
    """``Sighting.mergeWith``."""
    merged = Sighting(existing.taxon, existing.taxonomy_id, existing.location_id, existing.date,
                      existing.time, existing.trip_id, existing.count)  # fmt: skip
    merged.adult = existing.adult or new.adult
    merged.female = existing.female or new.female
    merged.male = existing.male or new.male
    merged.immature = existing.immature or new.immature
    merged.photographed = existing.photographed or new.photographed
    merged.photos = [*existing.photos, *new.photos]
    merged.heard_only = existing.heard_only and new.heard_only
    merged.breeding = existing.breeding or new.breeding
    if existing.count is not None and new.count is not None:
        merged.count = _plus(existing.count, new.count)
    merged.status = min(existing.status, new.status, key=SIGHTING_STATUSES.index)
    if existing.description is None:
        merged.description = new.description
    elif new.description is not None:
        merged.description = existing.description + "\n" + new.description
    else:
        merged.description = existing.description
    merged.users = (
        list(dict.fromkeys([*existing.users, *new.users])) if existing.users else list(new.users)
    )
    return merged


def _plus(first: ApproximateNumber, second: ApproximateNumber) -> ApproximateNumber:
    total = first.number + second.number
    if first.is_exact:
        return ApproximateNumber(total, second.prefix)
    return ApproximateNumber(total, first.prefix)


def _funnel(sighting: Sighting, trip_starts: dict[str, PartialDate]) -> tuple[object, ...]:
    """``SightingFunnel``'s fields: start date, time, taxonomy and taxon."""
    return (_start_date(sighting, trip_starts), sighting.time, sighting.taxonomy_id,
            sighting.taxon.type, sighting.taxon.ids)  # fmt: skip


def _start_date(sighting: Sighting, trip_starts: dict[str, PartialDate]) -> PartialDate | None:
    """``getStartDateAsPartial``: an undated sighting on a trip has the trip's start."""
    if sighting.date is not None or sighting.trip_id is None:
        return sighting.date
    return trip_starts.get(sighting.trip_id)


def _duplicate_key(sighting: Sighting,
                   trip_starts: dict[str, PartialDate]) -> tuple[object, ...] | None:  # fmt: skip
    """``DuplicateSightingKey.forSighting``: start date, time and taxonomy (not the
    place)."""
    date = _start_date(sighting, trip_starts)
    if date is None:
        return None
    return (date, sighting.time, sighting.taxonomy_id)


def _int32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def _partial_date_hash(date: PartialDate) -> int:
    ordinals = list_hash(int(field) for field, _ in date.fields)
    values = list_hash(_int32(value) for _, value in date.fields)
    return _int32(31 * ordinals + values)


def _time_hash(value: time | None) -> int:
    """``java.time.LocalTime.hashCode``."""
    if value is None:
        return 0
    nanos = ((value.hour * 60 + value.minute) * 60 + value.second) * 1_000_000_000
    return _int32(nanos ^ (nanos >> 32))


def _visit_key_hash(key: VisitKey) -> int:
    """``VisitInfoKey.hashCode``."""
    inner = _int32(31 * string_hash(key.location_id) + _partial_date_hash(key.date))
    return _int32(31 * inner + _time_hash(key.start_time))

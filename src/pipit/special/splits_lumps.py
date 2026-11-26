"""Splits and lumps: how the species a query finds would count in another taxonomy version
(an older Clements, or the other of Clements and AviList): species gained by splits, lost by
lumps, and those that may be either.

Ported from Scythebill ``ui/.../panels/reports/SplitsAndLumpsProcessor.java`` and the version
list of ``SplitsAndLumpsPanel``. The versions' tables are Scythebill's ``report-*.csv``,
kept in the data pack.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape

from pipit.output.names import abbreviated_name
from pipit.query.engine import EngineContext, StoredQuery, run_query
from pipit.query.results import QueryResults
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxonomy, TaxonType, full_name, walk
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

#: (version id, label) offered for Clements lists, newest first (``CLEMENTS_*``).
CLEMENTS_VERSIONS = (
    ("vs-avilist-2026", "AviList 2026 vs. Clements 2026"),
    ("2025", "2025 vs. 2026"), ("2024", "2024 vs. 2026"), ("2023", "2023 vs. 2026"),
    ("2022", "2022 vs. 2026"), ("2021", "2021 vs. 2026"), ("2019", "2019 vs. 2026"),
    ("2018", "2018 vs. 2026"), ("2017", "2017 vs. 2026"), ("2016", "2016 vs. 2026"),
    ("2015", "2015 vs. 2026"), ("69", "6.9 (August 2014) vs. 2026"),
    ("68", "6.8 (August 2013) vs. 2026"), ("67", "6.7 (September 2012) vs. 2026"),
    ("66", "6.6 (August 2011) vs. 2026"), ("65", "6.5 (December 2010) vs. 2026"),
)  # fmt: skip
#: (version id, label) offered for AviList lists (``AVILIST_*``).
AVILIST_VERSIONS = (
    ("vs-clements-2026", "Clements 2026 vs. AviList 2026"),
    ("avilist-2025", "2025 vs. 2026"),
)


def versions_for(taxonomy: Taxonomy) -> tuple[tuple[str, str], ...]:
    """``taxonomyChanged``: AviList's versions for AviList, Clements' otherwise."""
    return AVILIST_VERSIONS if isinstance(taxonomy, MappedTaxonomy) else CLEMENTS_VERSIONS


class SplitsUnavailableError(ValueError):
    """The version's table doesn't fit the taxonomy (Scythebill: "not available")."""


@dataclass(frozen=True, slots=True)
class OldSpecies:
    scientific: str
    common: str | None


@dataclass(slots=True)
class SingleResult:
    current: list[str]  # current species IDs
    old: list[OldSpecies]
    possible_old: list[OldSpecies]
    unresolved_sp: bool = False  # only a sp. of the bundle's species was seen


@dataclass(slots=True)
class SplitsAndLumps:
    splits: list[SingleResult] = field(default_factory=list)
    lumps: list[SingleResult] = field(default_factory=list)
    possible_splits: list[SingleResult] = field(default_factory=list)
    possible_lumps: list[SingleResult] = field(default_factory=list)
    possible_lump_or_split: list[SingleResult] = field(default_factory=list)
    known_split_count: int = 0
    known_lump_count: int = 0
    possible_split_count: int = 0
    possible_lump_count: int = 0
    #: The fewest and most species unresolved sp.'s may still stand for, beyond species seen.
    unresolved_sp_minimum: int = 0
    unresolved_sp_maximum: int = 0

    def is_empty(self) -> bool:
        return not (self.splits or self.lumps or self.possible_splits or self.possible_lumps
                    or self.possible_lump_or_split)  # fmt: skip

    def _old(self, names: Sequence[str], bundle: _Bundle) -> list[OldSpecies]:
        return [OldSpecies(name, bundle.old_common.get(name)) for name in names]

    def add_unresolved_sp_split(self, bundle: _Bundle) -> None:
        self.splits.append(SingleResult(list(bundle.species_ids),
                                        self._old(list(bundle.old_common), bundle), [],
                                        unresolved_sp=True))  # fmt: skip

    def add_unresolved_sp_range(self, sp_sightings: list[Resolved],
                                resolved_species: set[str]) -> None:  # fmt: skip
        """``addUnresolvedSpRange``."""
        candidates: dict[str, None] = {}
        needs_new: dict[frozenset[str], None] = {}
        for sighting in sp_sightings:
            ids = sighting.sighting_taxon.ids
            unresolved = [i for i in dict.fromkeys(ids) if i not in resolved_species]
            candidates.update(dict.fromkeys(unresolved))
            if unresolved and len(unresolved) == len(set(ids)):
                needs_new[frozenset(unresolved)] = None
        self.unresolved_sp_minimum += _minimum_hitting_set(list(needs_new), set())
        self.unresolved_sp_maximum += len(candidates)

    def add_bundle(self, result: _BundleResult) -> None:
        """``addBundle``."""
        current_size = len(result.current)
        known_old_size = len(result.known_old)
        possible_old_size = len(result.possible_old)
        if known_old_size == 0:
            known_old_size = 1
            possible_old_size -= 1
        if not result.known_old and len(result.possible_old) == 1:
            result.known_old.update(result.possible_old)
            result.possible_old.clear()
        single = SingleResult(list(result.current), self._old(list(result.known_old),
                                                                result.bundle), [])  # fmt: skip
        if possible_old_size == 0:
            if current_size == known_old_size:
                return
            if current_size < known_old_size:
                self.lumps.append(single)
                self.known_lump_count += known_old_size - current_size
            else:
                self.splits.append(single)
                self.known_split_count += current_size - known_old_size
            return
        single.possible_old = self._old(list(result.possible_old), result.bundle)
        if current_size < known_old_size:
            if current_size + possible_old_size > known_old_size:
                self.possible_lump_or_split.append(single)
                self.possible_lump_count += known_old_size - current_size
                self.possible_split_count += current_size + possible_old_size - known_old_size
            elif current_size + possible_old_size == known_old_size:
                self.possible_lumps.append(single)
                self.possible_lump_count += possible_old_size
            else:
                self.known_lump_count += known_old_size - (current_size + possible_old_size)
                self.possible_lump_count += possible_old_size
                self.possible_lumps.append(single)
        elif current_size == known_old_size:
            self.possible_lump_count += possible_old_size
            self.possible_lumps.append(single)
        else:
            self.known_split_count += current_size - known_old_size - possible_old_size
            self.possible_split_count += possible_old_size
            if current_size > known_old_size + possible_old_size:
                self.splits.append(single)
            else:
                self.possible_splits.append(single)


def _minimum_hitting_set(sets: list[frozenset[str]], chosen: set[str]) -> int:
    """The fewest species including one of every set (``minimumHittingSetSize``)."""
    for candidates in sets:
        if candidates.isdisjoint(chosen):
            best: int | None = None
            for species in candidates:
                chosen.add(species)
                found = _minimum_hitting_set(sets, chosen)
                chosen.discard(species)
                best = found if best is None else min(best, found)
            assert best is not None
            return best
    return len(chosen)


@dataclass(slots=True)
class _Bundle:
    current_to_old: dict[str, dict[str, None]] = field(default_factory=dict)
    old_common: dict[str, str] = field(default_factory=dict)
    species_ids: dict[str, None] = field(default_factory=dict)


@dataclass(slots=True)
class _BundleResult:
    bundle: _Bundle
    current: dict[str, None] = field(default_factory=dict)
    known_old: dict[str, None] = field(default_factory=dict)
    possible_old: dict[str, None] = field(default_factory=dict)

    def process(self, resolved: Resolved) -> None:
        """``processResolved``."""
        old: dict[str, None] = {}
        for taxon_id in resolved.sighting_taxon.ids:
            old.update(self.bundle.current_to_old.get(taxon_id, {}))
        species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
        self.current[species.ids[0]] = None
        if len(old) == 1:
            self.known_old.update(old)
            for name in old:
                self.possible_old.pop(name, None)
        else:
            for name in old:
                if name not in self.known_old:
                    self.possible_old[name] = None


class _Report:
    """``ParsedReport``: the version's bundles, by index."""

    def __init__(self, rows: list[list[str]], taxonomy: Taxonomy) -> None:
        self.bundles: dict[int, _Bundle] = {}
        self.index_of: dict[str, int] = {}
        for row in rows[1:]:
            if not row:
                continue
            try:
                index = int(row[0])
            except ValueError as error:
                raise SplitsUnavailableError(f"bad index {row[0]!r}") from error
            bundle = self.bundles.setdefault(index, _Bundle())
            current_ids = row[4].split("/")
            old_common = row[2].split("/")
            old_scientific = row[3].split("/")
            if len(old_common) != len(old_scientific):
                raise SplitsUnavailableError(f"bundle {index}: names don't pair up")
            bundle.old_common.update(zip(old_scientific, old_common, strict=True))
            if row[1] == "simple":
                if len(old_scientific) != 1:
                    raise SplitsUnavailableError(f"bundle {index}: one old name expected")
                for current_id in current_ids:
                    bundle.species_ids[current_id] = None
                    taxon = taxonomy.get(current_id)
                    if taxon is None:
                        raise SplitsUnavailableError(f"{current_id} isn't in the taxonomy")
                    for below in walk(taxon):  # groups and subspecies too
                        bundle.current_to_old.setdefault(below.id, {})[old_scientific[0]] = None
                        self.index_of[below.id] = index
            elif row[1] == "complex":
                for current_id in current_ids:
                    bundle.species_ids[current_id] = None
                    for name in old_scientific:
                        bundle.current_to_old.setdefault(current_id, {})[name] = None
                        self.index_of[current_id] = index
            else:
                raise SplitsUnavailableError(f"unexpected type {row[1]!r}")

    def bundle_index(self, taxon: SightingTaxon) -> int | None:
        return self.index_of.get(taxon.ids[0])

    def single_bundle_index(self, taxon: SightingTaxon) -> int | None:
        """The one bundle all of a sp.'s taxa are in, if there is one."""
        found: int | None = None
        for taxon_id in taxon.ids:
            index = self.index_of.get(taxon_id)
            if index is None or (found is not None and found != index):
                return None
            found = index
        return found


_SP_OR_HYBRID = (SightingTaxonType.SP, SightingTaxonType.HYBRID)


def splits_and_lumps(results: QueryResults, taxonomy: Taxonomy,
                     rows: list[list[str]]) -> SplitsAndLumps:  # fmt: skip
    """``process``: ``results`` are the query's countable sightings at species depth (with
    no families), ``rows`` the version's table."""
    if not rows:
        raise SplitsUnavailableError("the data pack has no table for this version")
    report = _Report(rows, taxonomy)
    assert results.resolve is not None
    bundle_results: dict[int, _BundleResult] = {}
    unresolved_sp: dict[int, list[Resolved]] = {}
    for sighting in results.all_sightings():
        resolved = results.resolve(sighting.taxon)
        if resolved is None:
            raise SplitsUnavailableError(f"{sighting.taxon} doesn't resolve")
        taxon = resolved.sighting_taxon
        if taxon.type in _SP_OR_HYBRID:
            if resolved.smallest_type is TaxonType.SPECIES:
                if taxon.type is SightingTaxonType.SP:
                    single = report.single_bundle_index(taxon)
                    if single is not None:
                        unresolved_sp.setdefault(single, []).append(resolved)
                continue
            species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
            if species.type in _SP_OR_HYBRID:
                continue
        index = report.bundle_index(taxon)
        if index is None:
            continue
        result = bundle_results.get(index)
        if result is None:
            result = bundle_results[index] = _BundleResult(report.bundles[index])
        result.process(resolved)
    found = SplitsAndLumps()
    for index in sorted(bundle_results):
        found.add_bundle(bundle_results[index])
    for index in sorted(unresolved_sp):
        direct = bundle_results.get(index)
        found.add_unresolved_sp_range(unresolved_sp[index],
                                      set() if direct is None else set(direct.current))  # fmt: skip
        if direct is None:
            found.add_unresolved_sp_split(report.bundles[index])
    return found


def splits_report(context: EngineContext, query: StoredQuery,
                  rows: list[list[str]]) -> SplitsAndLumps:  # fmt: skip
    """``computeSplitsAndLumps``: the query's countable sightings (``context`` at species
    depth) against one version's table."""
    results = run_query(query, context, include_families=False, only_countable=True)
    return splits_and_lumps(results, context.taxonomy, rows)


# ------------------------------------------------------------------ wording


def _join(names: list[str]) -> str:
    """``Messages.join``: "A", "A and B", "A, B, and C"."""
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _named(common: str | None, scientific: str) -> str:
    return f"<b>{escape(common or '')}</b> (<i>{escape(scientific)}</i>)"


def describe(result: SingleResult, taxonomy: Taxonomy) -> str:
    """``singleResultAsString`` as rich text: the current species (each genus written out
    the first time, then abbreviated) and the old ones, in Scythebill's sentences."""
    genera: set[str] = set()

    def current(taxon_id: str) -> str:
        taxon = taxonomy.get(taxon_id)
        if taxon is None:
            return escape(taxon_id)
        genus = taxon.parent
        while genus is not None and genus.type is not TaxonType.GENUS:
            genus = genus.parent
        first = genus is None or genus.name not in genera
        if genus is not None:
            genera.add(genus.name)
        return _named(taxon.common_name, full_name(taxon) if first else abbreviated_name(taxon))

    def old(species: OldSpecies) -> str:
        scientific = species.scientific
        genus, _space, rest = scientific.partition(" ")
        if genus in genera:
            scientific = f"{genus[0]}. {rest}"
        genera.add(genus)
        return _named(species.common, scientific)

    new = _join([current(taxon_id) for taxon_id in result.current])
    if result.unresolved_sp:
        olds = _join([old(o) for o in result.old])
        if len(result.old) == 1:
            return (f"{olds} was split into {new}, but you only have an unresolved “sp.” "
                    "record for it.")  # fmt: skip
        return (f"{olds} were split into {new}, but you only have an unresolved “sp.” "
                "record for them.")  # fmt: skip
    verb = "is" if len(result.old) == 1 else "are"
    if not result.old:
        possible = _join([old(o) for o in result.possible_old])
        verb = "is" if len(result.possible_old) == 1 else "are"
        return f"Some or all of {possible} {verb} now {new}"
    olds = _join([old(o) for o in result.old])
    if len(result.possible_old) == 1:
        return f"Some or all of {olds} and possibly {old(result.possible_old[0])} {verb} now {new}"
    if result.possible_old:
        possible = _join([old(o) for o in result.possible_old])
        return (f"Some or all of {olds} and some, none, or all of {possible} {verb} now "
                f"{new}")  # fmt: skip
    return f"{olds} {verb} now {new}"


def totals(found: SplitsAndLumps) -> str:
    """The line above the report: gained, lost, and what unresolved sp.'s may add
    (Scythebill's words, parted with " · ")."""
    gained = f"Gained: {found.known_split_count:,}"
    if found.possible_split_count > 0:
        gained += f" (+{found.possible_split_count:,} possible)"
    lost = f"Lost: {found.known_lump_count:,}"
    if found.possible_lump_count > 0:
        lost += f" (+{found.possible_lump_count:,} possible)"
    parts = [gained, lost]
    if found.unresolved_sp_maximum > 0:
        low, high = found.unresolved_sp_minimum, found.unresolved_sp_maximum
        span = f"{high:,}" if low == high else f"{low:,}\u2013{high:,}"
        parts.append(f"{span} possible in unresolved “sp.” records")
    return " · ".join(parts)


#: The report's sections, in Scythebill's order: (title, attribute).
SECTIONS = (
    ("Splits", "splits"),
    ("Possible splits", "possible_splits"),
    ("Lumps", "lumps"),
    ("Possible lumps", "possible_lumps"),
    ("Unknown: lumps, splits, or neither", "possible_lump_or_split"),
)

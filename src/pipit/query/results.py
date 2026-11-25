"""Query results and their totals: a port of Scythebill's ``QueryResults`` (only what the
Reports screen and the totals use).

Sightings are grouped by taxon at the query's depth: single taxa by ID, a sp. or hybrid by
its sighting taxon. A taxon is countable when at least one of its sightings passes the
countable predicate. The taxa list walks the taxonomy in order, putting a family heading
before the first taxon of each family, and a sp. or hybrid after the last of its taxa.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pipit.query.definition import PostProcessor, Predicate
from pipit.query.model import QSighting
from pipit.query.ordering import greatest_of
from pipit.taxa.model import Taxon, Taxonomy, TaxonType, parent_of_type_or_none
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

if TYPE_CHECKING:
    from pipit.query.checklists import Checklist

_SINGLE_KINDS = (SightingTaxonType.SINGLE, SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES)


@dataclass
class ResultsBuilder:
    sightings: dict[str, list[QSighting]] = field(default_factory=lambda: defaultdict(list))
    non_single: dict[SightingTaxon, list[QSighting]] = field(
        default_factory=lambda: defaultdict(list)
    )
    annotations: dict[int, str] = field(default_factory=dict)  # sighting row -> annotation

    def add(self, sighting: QSighting, taxon: SightingTaxon, annotation: str | None) -> None:
        if taxon.type in _SINGLE_KINDS:
            self.sightings[taxon.ids[0]].append(sighting)
        else:
            self.non_single[taxon].append(sighting)
        if annotation is not None:
            self.annotations[sighting.row] = annotation

    def post_process(self, processor: PostProcessor, countable: Predicate | None) -> None:
        for taxon_id in list(self.sightings):
            if not processor.accept_taxon(
                SightingTaxon.single(taxon_id), self.sightings[taxon_id], countable
            ):
                del self.sightings[taxon_id]
        for taxon in list(self.non_single):
            if not processor.accept_taxon(taxon, self.non_single[taxon], countable):
                del self.non_single[taxon]


class QueryResults:
    def __init__(
        self,
        taxonomy: Taxonomy,
        builder: ResultsBuilder,
        smallest_type: TaxonType,
        countable: Predicate | None,
        include_families: bool = True,
    ) -> None:
        self.taxonomy = taxonomy
        self.smallest_type = smallest_type
        self.countable = countable
        self.sightings = dict(builder.sightings)
        self.non_single = dict(builder.non_single)
        self.annotations = builder.annotations
        #: Set by ``run_query``: the display taxonomy's resolver, the query's annotator (for
        #: lifers at other levels) and the checklist of the query's one place, if any.
        self.resolve: Callable[[SightingTaxon], Resolved | None] | None = None
        self.annotate: Callable[[QSighting, SightingTaxon], str | None] | None = None
        self.checklist: Checklist | None = None
        self._with_annotation: dict[str, set[Resolved]] = {}
        self._include_families = include_families
        if countable is None:
            self.countable_ids = set(self.sightings)
            self.countable_non_single = set(self.non_single)
        else:
            self.countable_ids = {key for key, found in self.sightings.items()
                                  if any(countable(s) for s in found)}  # fmt: skip
            self.countable_non_single = {key for key, found in self.non_single.items()
                                         if any(countable(s) for s in found)}  # fmt: skip
        self.taxa = self._resolved_taxa(set(self.sightings), set(self.non_single))
        self.countable_taxa = (
            self.taxa if countable is None
            else self._resolved_taxa(self.countable_ids, self.countable_non_single)
        )  # fmt: skip

    # ------------------------------------------------------------ the taxa list

    def _resolved_taxa(self, ids: set[str], non_single: set[SightingTaxon]) -> list[Resolved]:
        """``getResolvedTaxa`` / ``addTaxa``, by sorting on positions in the taxonomy rather
        than walking it: a single taxon goes at its place in the walk; a sp. or hybrid right
        after the subtree of its last taxon (where the walk finishes it; a deeper one first);
        a family heading before the first entry inside the family."""
        order = _order(self.taxonomy)
        keyed: list[tuple[tuple[int, ...], Resolved, str | None]] = []
        for taxon_id in ids:
            position = order.get(taxon_id)
            if position is None:
                continue
            taxon = position.taxon
            if taxon.type < self.smallest_type:
                continue
            family = None if taxon.type is TaxonType.FAMILY else position.family
            keyed.append(((position.pre, 0, 0), Resolved.of(taxon), family))
        for sighting_taxon in _sorted_taxa(list(non_single)):
            positions = [order.get(part) for part in sighting_taxon.ids]
            if any(p is None for p in positions):
                continue
            last = max(positions, key=lambda p: (p.end, -p.depth))  # type: ignore[union-attr]
            assert last is not None
            resolved = sighting_taxon.resolve_internal(self.taxonomy)
            keyed.append(((last.end, 1, -last.depth), resolved, last.family))
        keyed.sort(key=lambda item: item[0])
        found: list[Resolved] = []
        headed: set[str] = set()
        for _key, resolved, family in keyed:
            if self._include_families and family is not None and family not in headed:
                headed.add(family)
                found.append(Resolved.of(order[family].taxon))
            found.append(resolved)
        return found

    # ------------------------------------------------------------ sightings and lifers

    def sightings_of(self, resolved: Resolved) -> list[QSighting]:
        if resolved.type is SightingTaxonType.SINGLE:
            return self.sightings.get(resolved.taxon.id, [])
        return self.non_single.get(resolved.sighting_taxon, [])

    def best_sightings(self, resolved: Resolved, ordering: Callable[[QSighting, QSighting], int],
                       count: int) -> list[QSighting]:  # fmt: skip
        """``getBestSightings``: Guava's ``greatestOf`` under the ordering."""
        found = self.sightings_of(resolved)
        return greatest_of(found, ordering, count) if found else []

    def _annotated(self, note: str) -> list[QSighting]:
        rows = {row for row, found in self.annotations.items() if found == note}
        if not rows:
            return []
        every = [*self.sightings.values(), *self.non_single.values()]
        return [s for found in every for s in found if s.row in rows]

    def taxa_with_annotation(self, note: str) -> set[Resolved]:
        """``getTaxaWithAnnotation(taxonomy, annotation)``: each annotated sighting's taxon and
        its parents up to its species."""
        cached = self._with_annotation
        if note in cached:
            return cached[note]
        taxa: set[Resolved] = set()
        assert self.resolve is not None
        for sighting in self._annotated(note):
            resolved = self.resolve(sighting.taxon)
            if resolved is None:
                continue
            taxa.add(resolved)
            if sighting.taxon.type is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
                plain = self.resolve(SightingTaxon.single(sighting.taxon.ids[0]))
                if plain is not None:
                    taxa.add(plain)
                    resolved = plain
            while resolved.largest_type < TaxonType.SPECIES:
                resolved = resolved.parent().resolve_internal(self.taxonomy)
                taxa.add(resolved)
        cached[note] = taxa
        return taxa

    def taxa_with_annotation_at(self, note: str, level: TaxonType) -> set[Resolved]:
        """``getTaxaWithAnnotation(taxonomy, annotation, type)``: taxa at ``level`` whose
        sighting the query annotates at that level too."""
        taxa: set[Resolved] = set()
        assert self.resolve is not None and self.annotate is not None
        for sighting in self._annotated(note):
            resolved = self.resolve(sighting.taxon)
            if resolved is None:
                continue
            parent = resolved.parent_of_at_least_type(level)
            if self.annotate(sighting, parent) == note:
                taxa.add(parent.resolve_internal(self.taxonomy))
        return taxa

    def contains_annotation(self, note: str, resolved: Resolved) -> bool:
        return resolved in self.taxa_with_annotation(note)

    # ------------------------------------------------------------ totals

    def sightings_count(self) -> int:
        return sum(map(len, self.sightings.values())) + sum(map(len, self.non_single.values()))

    def is_countable(self, resolved: Resolved) -> bool:
        if self.countable is None:
            return True
        if resolved.type is SightingTaxonType.SINGLE:
            found = self.sightings.get(resolved.taxon.id, [])
        else:
            found = self.non_single.get(resolved.sighting_taxon, [])
        return any(self.countable(sighting) for sighting in found)

    def countable_species_ids(self) -> set[str]:
        if self.smallest_type is TaxonType.SPECIES:
            ids = set(self.countable_ids)
            extra = set()
            for taxon in self.countable_non_single:
                resolved = taxon.resolve_internal(self.taxonomy)
                if resolved.smallest_type is not TaxonType.SPECIES:
                    species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
                    if species.type is SightingTaxonType.SINGLE and species.id not in ids:
                        extra.add(species.id)
            return ids | extra
        return taxa_at_level(self.countable_taxa, TaxonType.SPECIES)

    def countable_species_size(self, include_non_single: bool) -> int:
        ids = self.countable_species_ids()
        if not include_non_single:
            return len(ids)
        return len(ids) + self._count_non_single(ids, TaxonType.SPECIES)

    def countable_groups_ids(self) -> set[str]:
        taxa = self.countable_taxa
        groups = taxa_at_level(taxa, TaxonType.GROUP)
        for resolved in taxa:
            if resolved.type is SightingTaxonType.SINGLE:
                if resolved.smallest_type in (TaxonType.SPECIES, TaxonType.SUBSPECIES):
                    species = parent_of_type_or_none(resolved.taxon, TaxonType.SPECIES)
                    assert species is not None
                    if not _itself_or_a_child_in(species, groups):
                        groups.add(species.id)
            elif resolved.smallest_type is not TaxonType.SPECIES:
                species_taxon = resolved.parent_of_at_least_type(TaxonType.SPECIES)
                if species_taxon.type is SightingTaxonType.SINGLE:
                    found = self.taxonomy.get(species_taxon.id)
                    if found is not None and not _itself_or_a_child_in(found, groups):
                        groups.add(species_taxon.id)
        return groups

    def countable_groups_size(self, include_non_single: bool) -> int:
        ids = self.countable_groups_ids()
        if not include_non_single:
            return len(ids)
        return len(ids) + self._count_non_single(ids, TaxonType.GROUP)

    def countable_subspecies_ids(self) -> set[str]:
        taxa = self.countable_taxa
        found = taxa_at_level(taxa, TaxonType.SUBSPECIES)
        for wanted in (TaxonType.GROUP, TaxonType.SPECIES):
            for resolved in taxa:
                if (resolved.type is SightingTaxonType.SINGLE
                        and resolved.smallest_type is wanted
                        and not _itself_or_a_child_in(resolved.taxon, found)):  # fmt: skip
                    found.add(resolved.taxon.id)
        for resolved in taxa:
            if resolved.type is SightingTaxonType.SINGLE or (
                resolved.smallest_type is TaxonType.SPECIES
            ):
                continue
            parent = resolved.parent_of_at_least_type(TaxonType.GROUP)
            test = None
            if parent.type is SightingTaxonType.SINGLE:
                test = self.taxonomy.get(parent.id)
            else:
                parent = resolved.parent_of_at_least_type(TaxonType.SPECIES)
                if parent.type is SightingTaxonType.SINGLE:
                    test = self.taxonomy.get(parent.id)
            if test is not None and not _itself_or_a_child_in(test, found):
                found.add(test.id)
        return found

    def countable_subspecies_size(self, include_non_single: bool) -> int:
        ids = self.countable_subspecies_ids()
        if not include_non_single:
            return len(ids)
        return len(ids) + self._count_non_single(ids, TaxonType.SUBSPECIES)

    def _count_non_single(self, counted: set[str], level: TaxonType) -> int:
        """``countNonSingleTaxa``: a sp. at this level counts when none of its taxa (nor
        those of an earlier counted sp.) are counted already."""
        count = 0
        used: set[str] = set()
        for resolved in self.countable_taxa:
            if resolved.type is SightingTaxonType.SP and resolved.largest_type is level:
                ids = resolved.sighting_taxon.ids
                if not any(part in counted or part in used for part in ids):
                    count += 1
                    used.update(ids)
        return count

    def family_count(self) -> int:
        return sum(1 for resolved in self.countable_taxa
                   if resolved.smallest_type is TaxonType.FAMILY)  # fmt: skip

    def spuh_count(self) -> int:
        return sum(1 for resolved in self.countable_taxa
                   if resolved.type is SightingTaxonType.SP)  # fmt: skip


def taxa_at_level(taxa: Iterable[Resolved], level: TaxonType) -> set[str]:
    """``TaxonUtils.getTaxaAtLevel``."""
    found: set[str] = set()
    for resolved in taxa:
        if resolved.type is SightingTaxonType.SINGLE:
            if resolved.smallest_type <= level:
                parent = parent_of_type_or_none(resolved.taxon, level)
                if parent is not None:
                    found.add(parent.id)
        elif resolved.smallest_type < level:
            parent_taxon = resolved.parent_of_at_least_type(level)
            if parent_taxon.type is SightingTaxonType.SINGLE:
                found.add(parent_taxon.id)
    return found


def _itself_or_a_child_in(taxon: Taxon, ids: set[str]) -> bool:
    """``TaxonUtils.isItselfOrAChildIn``."""
    stack = [taxon]
    while stack:
        current = stack.pop()
        if current.id in ids:
            return True
        stack.extend(current.children)
    return False


@dataclass(frozen=True, slots=True)
class _Position:
    taxon: Taxon
    pre: int  # in the pre-order walk
    end: int  # the last pre-order position in its subtree
    depth: int
    family: str | None  # the family it is in (or is)


_ORDERS: dict[int, tuple[Taxonomy, dict[str, _Position]]] = {}


def _order(taxonomy: Taxonomy) -> dict[str, _Position]:
    """Each taxon's place in the walk, computed once per taxonomy."""
    cached = _ORDERS.get(id(taxonomy))
    if cached is not None and cached[0] is taxonomy:
        return cached[1]
    positions: dict[str, _Position] = {}
    counter = 0

    def visit(taxon: Taxon, depth: int, family: str | None) -> int:
        nonlocal counter
        pre = counter
        counter += 1
        if taxon.type is TaxonType.FAMILY:
            family = taxon.id
        end = pre
        for child in taxon.children:
            end = visit(child, depth + 1, family)
        positions[taxon.id] = _Position(taxon, pre, end, depth, family)
        return end

    if taxonomy.root is not None:
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 10_000))
        try:
            visit(taxonomy.root, 0, None)
        finally:
            sys.setrecursionlimit(limit)
    _ORDERS[id(taxonomy)] = (taxonomy, positions)
    return positions


def taxonomy_index(taxonomy: Taxonomy) -> dict[str, int]:
    """Each taxon's position in taxonomic order (``getTaxonomyIndex``)."""
    cached = _INDEXES.get(id(taxonomy))
    if cached is None or cached[0] is not taxonomy:
        cached = _INDEXES[id(taxonomy)] = (
            taxonomy,
            {key: position.pre for key, position in _order(taxonomy).items()},
        )
    return cached[1]


_INDEXES: dict[int, tuple[Taxonomy, dict[str, int]]] = {}


def _sorted_taxa(taxa: list[SightingTaxon]) -> list[SightingTaxon]:
    """Scythebill iterates these in hash order; the result is the same unless two sp.
    entries complete at the same taxon, which then appear in ID order here."""
    return sorted(taxa, key=lambda taxon: (taxon.type.value, taxon.ids))

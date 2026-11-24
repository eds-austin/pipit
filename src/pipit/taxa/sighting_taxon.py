"""What a sighting is of: one taxon, a "sp." of several, a hybrid, or a base taxon plus a
subspecies name from a mapped taxonomy.

Ported from Scythebill ``model/src/commonMain/kotlin/com/scythebill/birdlist/model/sighting/``
``SightingTaxon.kt`` and ``SightingTaxons.kt``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from pipit.taxa.model import (
    Taxon,
    Taxonomy,
    TaxonType,
    parent_of_at_least_type,
    parent_of_type,
    parent_of_type_or_none,
)


class SightingTaxonType(Enum):
    SINGLE = "single"
    SP = "sp"
    HYBRID = "hybrid"
    SINGLE_WITH_SECONDARY_SUBSPECIES = "ssp"


@dataclass(frozen=True, slots=True)
class SightingTaxon:
    """Immutable. Multi-taxon forms hold distinct IDs, sorted, at least two."""

    type: SightingTaxonType
    ids: tuple[str, ...]
    subspecies: str | None = None  # only for SINGLE_WITH_SECONDARY_SUBSPECIES

    @staticmethod
    def single(taxon_id: str) -> SightingTaxon:
        return SightingTaxon(SightingTaxonType.SINGLE, (taxon_id,))

    @staticmethod
    def with_secondary_subspecies(taxon_id: str, subspecies: str) -> SightingTaxon:
        return SightingTaxon(
            SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES, (taxon_id,), subspecies
        )

    @staticmethod
    def sp(taxon_ids: Iterable[str]) -> SightingTaxon:
        return SightingTaxon(SightingTaxonType.SP, _multiple(taxon_ids))

    @staticmethod
    def hybrid(taxon_ids: Iterable[str]) -> SightingTaxon:
        return SightingTaxon(SightingTaxonType.HYBRID, _multiple(taxon_ids))

    @staticmethod
    def possibly_sp(taxon_ids: Iterable[str]) -> SightingTaxon:
        """One taxon if there is exactly one ID, otherwise a sp."""
        distinct = list(dict.fromkeys(taxon_ids))
        return (
            SightingTaxon.single(distinct[0]) if len(distinct) == 1 else SightingTaxon.sp(distinct)
        )

    @property
    def is_multiple(self) -> bool:
        return self.type in (SightingTaxonType.SP, SightingTaxonType.HYBRID)

    @property
    def id(self) -> str:
        if self.is_multiple:
            raise ValueError(f"{self} has several taxa; it has no single id")
        return self.ids[0]

    def resolve_internal(self, taxonomy: Taxonomy) -> Resolved:
        """Bind the IDs to taxa of ``taxonomy`` itself (no cross-taxonomy mapping)."""
        if self.type is SightingTaxonType.SINGLE:
            return Resolved.of(_taxon(taxonomy, self.ids[0]))
        if self.type is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
            taxon = _taxon(taxonomy, self.ids[0])
            child = next((c for c in taxon.children if c.name == self.subspecies), None)
            return Resolved.of(child or taxon)
        taxa = tuple(_taxon(taxonomy, taxon_id) for taxon_id in self.ids)
        return Resolved(self.type, taxa)


def _multiple(taxon_ids: Iterable[str]) -> tuple[str, ...]:
    ids = tuple(sorted(set(taxon_ids)))
    if len(ids) < 2:
        raise ValueError(f"a sp. or hybrid needs at least two taxa, got {ids}")
    return ids


def _taxon(taxonomy: Taxonomy, taxon_id: str) -> Taxon:
    taxon = taxonomy.get(taxon_id)
    if taxon is None:
        raise KeyError(f"no taxon {taxon_id!r} in {taxonomy.id}")
    return taxon


@dataclass(frozen=True, slots=True)
class Resolved:
    """A sighting taxon bound to live taxa of one taxonomy. Type is never SSP."""

    type: SightingTaxonType
    taxa: tuple[Taxon, ...]

    @staticmethod
    def of(taxon: Taxon) -> Resolved:
        return Resolved(SightingTaxonType.SINGLE, (taxon,))

    @staticmethod
    def sp(taxa: Iterable[Taxon]) -> Resolved:
        """``newSpResolved``: keeps the given order (the IDs are sorted separately)."""
        ordered = tuple(dict.fromkeys(taxa))
        if len(ordered) < 2:
            raise ValueError("a sp. needs at least two taxa")
        return Resolved(SightingTaxonType.SP, ordered)

    @property
    def taxon(self) -> Taxon:
        if self.type is not SightingTaxonType.SINGLE:
            raise ValueError("not a single taxon")
        return self.taxa[0]

    @property
    def sighting_taxon(self) -> SightingTaxon:
        if self.type is SightingTaxonType.SINGLE:
            return SightingTaxon.single(self.taxa[0].id)
        return SightingTaxon(self.type, _multiple(taxon.id for taxon in self.taxa))

    @property
    def smallest_type(self) -> TaxonType:
        return min(taxon.type for taxon in self.taxa)

    @property
    def largest_type(self) -> TaxonType:
        return max(taxon.type for taxon in self.taxa)

    def _multiple_of(self, ids: Iterable[str]) -> SightingTaxon:
        distinct = list(dict.fromkeys(ids))
        if len(distinct) == 1:
            return SightingTaxon.single(distinct[0])
        return SightingTaxon(self.type, _multiple(distinct))

    def parent(self) -> SightingTaxon:
        if self.type is SightingTaxonType.SINGLE:
            parent = self.taxa[0].parent
            assert parent is not None
            return SightingTaxon.single(parent.id)
        level = self.largest_type
        parents = []
        for taxon in self.taxa:
            at_level = parent_of_type_or_none(taxon, level)
            assert at_level is not None and at_level.parent is not None
            parents.append(at_level.parent.id)
        return self._multiple_of(parents)

    def parent_of_at_least_type(self, taxon_type: TaxonType) -> SightingTaxon:
        if self.type is SightingTaxonType.SINGLE:
            return SightingTaxon.single(parent_of_at_least_type(self.taxa[0], taxon_type).id)
        return self._multiple_of(parent_of_at_least_type(t, taxon_type).id for t in self.taxa)

    def resolve_parent_of_type(self, taxon_type: TaxonType) -> Resolved:
        if self.type is SightingTaxonType.SINGLE:
            return Resolved.of(parent_of_type(self.taxa[0], taxon_type))
        if self.largest_type is taxon_type and self.smallest_type is taxon_type:
            return self
        parents = tuple(dict.fromkeys(parent_of_type(t, taxon_type) for t in self.taxa))
        return Resolved.of(parents[0]) if len(parents) == 1 else Resolved(self.type, parents)

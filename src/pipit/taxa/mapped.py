"""A taxonomy defined as a view over a base taxonomy (AviList over eBird/Clements).

Sightings are always stored with base IDs. This maps base sighting taxa into the mapped
taxonomy (``resolve_into``) and mapped taxa back to the base (``mapping``).

A line-by-line port of Scythebill
``model/src/commonMain/kotlin/com/scythebill/birdlist/model/taxa/MappedTaxonomy.kt`` and the
mapping registration in ``model/src/jvmMain/.../xml/XmlTaxonImport.kt``. Keep it that way:
the heuristics (lumps, partial mappings, the "gilli hack") are only right because they
match Scythebill's output.
"""

from __future__ import annotations

from collections.abc import Mapping

from pipit.taxa.model import Taxon, Taxonomy, TaxonType, first_child_of_type, parent_of_type
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

_SSP = SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES


class MappedTaxonomy(Taxonomy):
    def __init__(self, base: Taxonomy, taxonomy_id: str, name: str) -> None:
        super().__init__(taxonomy_id, name)
        self.base = base
        # mapped taxon ID -> base sighting taxon
        self._mappings_to_base: dict[str, SightingTaxon] = {}
        # base ID -> the one mapped taxon that matches it exactly
        self._base_to_mapped: dict[str, str] = {}
        # base ID -> a mapped taxon that lumps it with other base taxa (much wider)
        self._partial_base_to_mapped: dict[str, str] = {}
        # base ID -> several mapped taxa (not unique)
        self._duplicate_base_to_mapped: dict[str, set[str]] = {}

    # ------------------------------------------------------------ registration

    def set_mappings(self, mappings: Mapping[Taxon, SightingTaxon]) -> None:
        """``MappingBuilder.registerTaxonMapping`` for each mapping, then ``setMappings``."""
        base_to_mapped: dict[str, list[str]] = {}
        partial: dict[str, set[str]] = {}
        for taxon, base_mapping in mappings.items():
            if taxon.id in self._mappings_to_base:
                raise ValueError(f"mapping already existed for {taxon.id}")
            self._mappings_to_base[taxon.id] = base_mapping
            if base_mapping.type is _SSP:
                continue
            is_partial = len(base_mapping.ids) > 1
            for base_id in base_mapping.ids:
                targets = base_to_mapped.setdefault(base_id, [])
                if taxon.id not in targets:
                    targets.append(taxon.id)
                if is_partial:
                    partial.setdefault(base_id, set()).add(taxon.id)

        for base_id, mapped_ids in base_to_mapped.items():
            partial_ids = partial.get(base_id, set())
            exact_ids = [mapped_id for mapped_id in mapped_ids if mapped_id not in partial_ids]
            if len(exact_ids) == 1:
                # A single exact mapping wins; wider lumps that include it are ignored.
                self._base_to_mapped[base_id] = exact_ids[0]
            elif len(exact_ids) > 1:
                self._duplicate_base_to_mapped[base_id] = set(exact_ids)
            elif len(partial_ids) == 1:
                self._partial_base_to_mapped[base_id] = next(iter(partial_ids))
            else:
                self._duplicate_base_to_mapped[base_id] = set(partial_ids)

    def disable_unmapped_taxa(self) -> None:
        """``XmlTaxonImport.disableUnmappedTaxa``: disable every subtree with no mapping."""
        if self.root is not None:
            self._disable_unmapped(self.root)

    def _disable_unmapped(self, taxon: Taxon) -> bool:
        found = False
        for child in taxon.children:
            found = self._disable_unmapped(child) or found
        if not found:
            if taxon.id in self._mappings_to_base:
                found = True
            else:
                taxon.disabled = True
        return found

    # ------------------------------------------------------ mapped -> base

    def exact_mapping(self, taxon: Taxon) -> SightingTaxon | None:
        """The precise mapping, without synthesis from children."""
        return self._mappings_to_base.get(taxon.id)

    def exact_mappings(self) -> Mapping[str, SightingTaxon]:
        return self._mappings_to_base

    def mapping(self, taxon: Taxon) -> SightingTaxon | None:
        """``getMapping(Taxon)``: the base mapping to use; synthesized from children (as a
        sp.) when there is no exact one."""
        exact = self.exact_mapping(taxon)
        if exact is not None or not taxon.children:
            return exact

        # Families and orders: map the first species, then go up to the same rank.
        if taxon.type in (TaxonType.FAMILY, TaxonType.ORDER):
            first_species = first_child_of_type(taxon, TaxonType.SPECIES)
            assert first_species is not None
            species_mapping = self.mapping(first_species)
            if species_mapping is not None:
                resolved = species_mapping.resolve_internal(self.base)
                return resolved.parent_of_at_least_type(taxon.type)

        base_ids: list[str] = []
        for child in taxon.children:
            child_mapping = self.exact_mapping(child)
            # Skip single-with-secondary-subspecies: they all just map up to the species.
            if child_mapping is not None and child_mapping.type is not _SSP:
                for base_id in child_mapping.ids:
                    if base_id not in base_ids:
                        base_ids.append(base_id)
        if not base_ids:
            return None
        return SightingTaxon.possibly_sp(base_ids)

    def mapping_of(self, sighting_taxon: SightingTaxon) -> SightingTaxon | None:
        """``getMapping(SightingTaxon)``: a mapped sighting taxon back in the base."""
        if sighting_taxon.type is SightingTaxonType.SINGLE:
            return self.mapping(self[sighting_taxon.id])
        base_ids: set[str] = set()
        for mapped_id in sighting_taxon.ids:
            base = self.mapping(self[mapped_id])
            if base is not None:
                base_ids.update(base.ids)
        if not base_ids:
            return None
        if len(base_ids) == 1:
            return SightingTaxon.single(next(iter(base_ids)))
        if sighting_taxon.type is SightingTaxonType.SP:
            # Is the sp. in fact all of one base parent's children?
            parent = self.base[next(iter(sorted(base_ids)))].parent
            assert parent is not None
            if parent.type <= TaxonType.SPECIES and {c.id for c in parent.children} == base_ids:
                return SightingTaxon.single(parent.id)
            return SightingTaxon.sp(base_ids)
        return SightingTaxon.hybrid(base_ids)

    def exact_mapping_from_base(self, base_id: str) -> SightingTaxon | None:
        mapped = self._mapped_for(base_id)
        if mapped is not None:
            return SightingTaxon.single(mapped)
        if base_id in self._duplicate_base_to_mapped:
            return SightingTaxon.sp(self._duplicate_base_to_mapped[base_id])
        return None

    # ------------------------------------------------------ base -> mapped

    def resolve_into(self, sighting_taxon: SightingTaxon) -> Resolved | None:
        """Map a base sighting taxon into this taxonomy."""
        if sighting_taxon.type is SightingTaxonType.SINGLE:
            return self._map(sighting_taxon.id)
        if sighting_taxon.type is _SSP:
            return self._resolve_secondary_subspecies(sighting_taxon)
        return self._resolve_multiple(sighting_taxon)

    def _resolve_secondary_subspecies(self, sighting_taxon: SightingTaxon) -> Resolved | None:
        resolved = self._map(sighting_taxon.id)
        if resolved is None:
            return None
        for resolved_taxon in resolved.taxa:
            # If the "parent" is a subspecies, move up before looking for the subspecies
            # (Buteo buteo harterti: maps to a ssp. that doesn't have the child).
            parent = resolved_taxon
            if parent.type is TaxonType.SUBSPECIES:
                assert parent.parent is not None
                parent = parent.parent
            for child in parent.children:
                if child.name == sighting_taxon.subspecies:
                    return Resolved.of(child)
        return resolved

    def _resolve_multiple(self, sighting_taxon: SightingTaxon) -> Resolved:
        first = True
        highest_type: TaxonType | None = None
        multiple_types = False
        resolveds: list[Resolved] = []
        single_parent: str | None = None
        for base_id in sighting_taxon.ids:
            resolved = self._map(base_id)
            if resolved is None:
                raise ValueError(f"no mapping from base taxon {base_id}")
            resolveds.append(resolved)
            parent = resolved.parent()
            if first:
                highest_type = resolved.largest_type
                if parent.type is SightingTaxonType.SINGLE:
                    single_parent = parent.id
                first = False
            else:
                assert highest_type is not None
                if highest_type is not resolved.largest_type:
                    multiple_types = True
                    highest_type = max(highest_type, resolved.largest_type)
                if parent.type is SightingTaxonType.SINGLE:
                    if parent.id != single_parent:
                        single_parent = None
                else:
                    single_parent = None

        assert highest_type is not None
        ids: set[str] = set()
        if multiple_types:
            for resolved in resolveds:
                ids.update(resolved.parent_of_at_least_type(highest_type).ids)
        else:
            for resolved in resolveds:
                ids.update(resolved.sighting_taxon.ids)
            # All children of one parent species, and *all* of its mappable children?
            if single_parent is not None:
                parent_taxon = self[single_parent]
                if parent_taxon.type <= TaxonType.SPECIES:
                    mappable = 0
                    for child in parent_taxon.children:
                        child_mapping = self.mapping(child)
                        if child_mapping is not None and child_mapping.type is not _SSP:
                            mappable += 1
                    if mappable == len(ids):
                        return Resolved.of(parent_taxon)

        if len(ids) == 1:
            return SightingTaxon.single(next(iter(ids))).resolve_internal(self)
        if sighting_taxon.type is SightingTaxonType.SP:
            return SightingTaxon.sp(ids).resolve_internal(self)
        # Partially wrong for hybrids of a sp. (Barn x Pacific/Hill Swallow), as in Scythebill.
        return SightingTaxon.hybrid(ids).resolve_internal(self)

    def _map(self, base_id: str) -> Resolved | None:
        """``map(id)``: one base taxon into this taxonomy."""
        if base_id in self._duplicate_base_to_mapped:
            return SightingTaxon.sp(self._duplicate_base_to_mapped[base_id]).resolve_internal(self)

        mapped = self._base_to_mapped.get(base_id)
        if mapped is not None:
            return Resolved.of(self[mapped])

        partial = self._partial_base_to_mapped.get(base_id)
        if partial is not None:
            # The only mapping lumps several base taxa; prefer the base taxon's children
            # when they can all be mapped (Clements Pacific Swift).
            from_children = self._map_from_children(self.base[base_id])
            if from_children is not None:
                return from_children
            return Resolved.of(self[partial])

        base_taxon = self.base.get(base_id)
        if base_taxon is None:
            raise KeyError(f"could not get a mapping for {base_id}")
        # Families and orders: map the first species, then up to the same rank.
        if base_taxon.type in (TaxonType.FAMILY, TaxonType.ORDER):
            first_species = first_child_of_type(base_taxon, TaxonType.SPECIES)
            assert first_species is not None
            resolved_species = self._map(first_species.id)
            if resolved_species is not None:
                return resolved_species.parent_of_at_least_type(base_taxon.type).resolve_internal(
                    self
                )
            return None

        from_children = self._map_from_children(base_taxon)
        if from_children is not None:
            return from_children
        # No children, or not all mappable: map upwards, then upwards again.
        parent = base_taxon.parent
        assert parent is not None
        resolved_parent = self._resolve_parent(parent)
        if resolved_parent is not None:
            return resolved_parent
        assert parent.parent is not None
        return self._resolve_parent(parent.parent)

    def _map_from_children(self, base_taxon: Taxon) -> Resolved | None:
        """Map a base taxon through its children, or None if that can't be done."""
        if not base_taxon.children:
            return None
        all_children_mappable = True
        mapped_children: list[str] = []  # an ordered set

        def add(mapped_id: str) -> None:
            if mapped_id not in mapped_children:
                mapped_children.append(mapped_id)

        for child in base_taxon.children:
            if child.id in self._duplicate_base_to_mapped:
                for mapped_id in sorted(self._duplicate_base_to_mapped[child.id]):
                    add(mapped_id)
                continue
            mapped_child = self._mapped_for(child.id)
            if mapped_child is not None:
                add(mapped_child)
            elif base_taxon.type is TaxonType.SPECIES and child.children:
                # A species whose group can't be mapped: try all the grandchildren.
                for grandchild in child.children:
                    mapped_grandchild = self._mapped_for(grandchild.id)
                    if mapped_grandchild is not None:
                        add(mapped_grandchild)
            else:
                all_children_mappable = False

        # "AWFUL GILLI HACK" (IOC 9.1 white-eyes): more than three also counts.
        if not (all_children_mappable or len(mapped_children) > 3):
            return None
        if len(mapped_children) == 1:
            return Resolved.of(self[mapped_children[0]])

        taxa: list[Taxon] = []
        highest_type: TaxonType | None = None
        multiple_types = False
        for mapped_id in mapped_children:
            taxon = self[mapped_id]
            if taxon not in taxa:
                taxa.append(taxon)
            if highest_type is None:
                highest_type = taxon.type
            elif highest_type is not taxon.type:
                multiple_types = True
                highest_type = max(highest_type, taxon.type)
        assert highest_type is not None
        # More than three subspecies: force up to species.
        if not multiple_types and highest_type is TaxonType.SUBSPECIES and len(taxa) > 3:
            multiple_types = True
            highest_type = TaxonType.SPECIES
        if multiple_types:
            raised: list[Taxon] = []
            for taxon in taxa:
                parent = parent_of_type(taxon, highest_type)
                if parent not in raised:
                    raised.append(parent)
            taxa = raised
        return Resolved.of(taxa[0]) if len(taxa) == 1 else Resolved.sp(taxa)

    def _mapped_for(self, base_id: str) -> str | None:
        """The exact mapping, else the partial (lumped) one."""
        return self._base_to_mapped.get(base_id) or self._partial_base_to_mapped.get(base_id)

    def _resolve_parent(self, base_taxon: Taxon) -> Resolved | None:
        if base_taxon.id in self._duplicate_base_to_mapped:
            return SightingTaxon.sp(self._duplicate_base_to_mapped[base_taxon.id]).resolve_internal(
                self
            )
        mapped = self._mapped_for(base_taxon.id)
        return Resolved.of(self[mapped]) if mapped is not None else None

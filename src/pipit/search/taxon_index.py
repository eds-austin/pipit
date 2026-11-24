"""The four type-ahead indexes Scythebill keeps for each taxonomy.

Ported from Scythebill ``model/src/jvmMain/.../util/TaxonomyIndexer.java``,
``IndexerBuilder.java`` and ``BaseGroupNames.java``:

- **common**: the common name of every enabled species, group and subspecies;
- **alternate common**: their alternate common names, indexed without a trailing
  " - note" (the stored name keeps it); for a mapped taxonomy (AviList) also the base
  taxonomy's group names, for the single taxon each group maps to;
- **scientific**: "Genus species" for enabled species only;
- **alternate scientific**: alternate scientific names of species.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pipit.search.indexer import Indexer, bits_of
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxon, Taxonomy, TaxonType, full_name
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType


class IndexKind(Enum):
    COMMON = "common"
    ALTERNATE_COMMON = "alternate-common"
    SCIENTIFIC = "scientific"
    ALTERNATE_SCIENTIFIC = "alternate-scientific"


@dataclass(frozen=True, slots=True)
class Entry:
    taxon_id: str
    name: str  # for alternates: the full alternate name (with any " - note")


class _Built:
    def __init__(self) -> None:
        self.indexer = Indexer()
        self.entries: list[Entry] = []

    def add(self, indexed_name: str, entry: Entry) -> None:
        self.indexer.add(indexed_name)
        self.entries.append(entry)


def without_suffix(name: str) -> str:
    """A name without a trailing " - ..." note (``IndexerBuilder.trimSuffixes``)."""
    index = name.find(" -")
    return name[:index] if index > 0 else name


class TaxonIndex:
    """Searchable names of one taxonomy."""

    def __init__(self, taxonomy: Taxonomy, warm: bool = True) -> None:
        self.taxonomy = taxonomy
        built = {kind: _Built() for kind in IndexKind}
        if taxonomy.root is not None:
            self._add_common(taxonomy.root, built)
            self._add_scientific(taxonomy.root, built)
        if isinstance(taxonomy, MappedTaxonomy):
            self._add_base_groups(taxonomy, built[IndexKind.ALTERNATE_COMMON])
        self._indexers = {kind: b.indexer.freeze(warm) for kind, b in built.items()}
        self._entries = {kind: b.entries for kind, b in built.items()}

    def find(self, kind: IndexKind, query: str) -> list[Entry]:
        """Matching entries (in index order; callers rank)."""
        entries = self._entries[kind]
        return [entries[i] for i in bits_of(self._indexers[kind].find(query))]

    def entry_count(self, kind: IndexKind) -> int:
        return len(self._entries[kind])

    @staticmethod
    def _add_common(taxon: Taxon, built: dict[IndexKind, _Built]) -> None:
        stack = [taxon]
        while stack:
            current = stack.pop()
            if current.type.is_species_like and not current.disabled:
                if current.common_name is not None:
                    built[IndexKind.COMMON].add(
                        current.common_name, Entry(current.id, current.common_name)
                    )
                for alternate in current.alternate_common_names:
                    built[IndexKind.ALTERNATE_COMMON].add(
                        without_suffix(alternate), Entry(current.id, alternate)
                    )
            stack.extend(reversed(current.children))

    @staticmethod
    def _add_scientific(taxon: Taxon, built: dict[IndexKind, _Built]) -> None:
        stack = [taxon]
        while stack:
            current = stack.pop()
            if current.type.is_species_like:
                # Subspecies are not indexed by scientific name: stop at the species.
                if not current.disabled:
                    name = full_name(current)
                    built[IndexKind.SCIENTIFIC].add(name, Entry(current.id, name))
                    for alternate in current.alternate_names:
                        built[IndexKind.ALTERNATE_SCIENTIFIC].add(
                            without_suffix(alternate), Entry(current.id, alternate)
                        )
                continue
            stack.extend(reversed(current.children))

    @staticmethod
    def _add_base_groups(mapped: MappedTaxonomy, built: _Built) -> None:
        """``BaseGroupNames.addTo``: base group names as alternates of what they map to."""
        stack = [mapped.base.root] if mapped.base.root is not None else []
        while stack:
            current = stack.pop()
            if current.type is TaxonType.GROUP:
                resolved = mapped.resolve_into(SightingTaxon.single(current.id))
                if resolved is not None and resolved.type is SightingTaxonType.SINGLE:
                    target = resolved.taxon
                    target_names = _names(target) if target.type.is_species_like else []
                    for name in _names(current):
                        # AviList often has the name already (own name or alternate).
                        if all(name.lower() != existing.lower() for existing in target_names):
                            built.add(without_suffix(name), Entry(target.id, name))
                continue  # groups contain only subspecies
            if current.type < TaxonType.SPECIES:
                continue
            stack.extend(reversed(current.children))


def _names(taxon: Taxon) -> list[str]:
    names = [taxon.common_name] if taxon.common_name is not None else []
    return names + list(taxon.alternate_common_names)

"""The taxon tree.

Ported from Scythebill ``model/src/commonMain/kotlin/com/scythebill/birdlist/model/taxa/``
(``Taxon.kt``, ``TaxonImpl.kt``, ``Species.kt``, ``TaxonomyImpl.kt``, ``TaxonUtils.kt``).
A ``Taxon`` here covers both Scythebill's ``TaxonImpl`` and ``SpeciesImpl``: the species-level
fields (range, status, alternate names) are simply unused above species.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from enum import IntEnum


class TaxonType(IntEnum):
    """Ranks in Scythebill's order: comparisons mean "lower/higher level than"."""

    SUBSPECIES = 0
    GROUP = 1
    SPECIES = 2
    GENUS = 3
    FAMILY = 4
    ORDER = 5
    CLASS = 6
    PHYLUM = 7

    @property
    def xml_name(self) -> str:
        return "class" if self is TaxonType.CLASS else self.name.lower()

    @classmethod
    def from_xml_name(cls, name: str) -> TaxonType:
        return cls.CLASS if name == "class" else cls[name.upper()]

    @property
    def is_species_like(self) -> bool:
        """Species, groups and subspecies: Scythebill's ``Species`` instances."""
        return self <= TaxonType.SPECIES


#: IUCN status codes, as stored in ``<status>``; LC is the default and never written.
IUCN_STATUSES = ("LC", "NE", "DD", "NT", "VU", "EN", "CR", "EW", "EX", "IN", "DO", "UN")


class Taxon:
    __slots__ = (
        "account_id",
        "alternate_common_names",
        "alternate_names",
        "checklists",
        "children",
        "common_name",
        "concept_id",
        "disabled",
        "id",
        "miscellaneous",
        "name",
        "parent",
        "range",
        "status",
        "taxonomic_info",
        "taxonomy",
        "type",
    )

    def __init__(
        self,
        taxonomy: Taxonomy,
        taxon_id: str,
        taxon_type: TaxonType,
        name: str,
        parent: Taxon | None,
    ) -> None:
        self.taxonomy = taxonomy
        self.id = taxon_id
        self.type = taxon_type
        self.name = name
        self.parent = parent
        self.children: list[Taxon] = []
        self.common_name: str | None = None
        self.account_id: str | None = None  # eBird species code
        self.concept_id: str | None = None  # Avibase concept ID
        self.status: str = "LC"
        self.range: str | None = None
        self.taxonomic_info: str | None = None
        self.miscellaneous: str | None = None
        self.alternate_names: list[str] = []
        self.alternate_common_names: list[str] = []
        self.checklists: str | None = None  # extended taxonomies only
        self.disabled = False

    def __repr__(self) -> str:
        return f"Taxon({self.id!r}, {self.type.name.lower()}, {self.name!r})"


class Taxonomy:
    """A tree of taxa with an ID index. ``MappedTaxonomy`` subclasses this."""

    def __init__(
        self,
        taxonomy_id: str,
        name: str,
        account_url_format: str | None = None,
        account_link_title: str | None = None,
    ) -> None:
        self.id = taxonomy_id
        self.name = name
        self.account_url_format = account_url_format
        self.account_link_title = account_link_title
        self.additional_credits: list[str] = []
        self.root: Taxon | None = None
        self._by_id: dict[str, Taxon] = {}

    def add(self, taxon_id: str, taxon_type: TaxonType, name: str, parent: Taxon | None) -> Taxon:
        if taxon_id in self._by_id:
            raise ValueError(f"duplicate taxon id {taxon_id!r} in {self.id}")
        taxon = Taxon(self, taxon_id, taxon_type, name, parent)
        if parent is None:
            if self.root is not None:
                raise ValueError(f"second root {taxon_id!r} in {self.id}")
            self.root = taxon
        else:
            parent.children.append(taxon)
        self._by_id[taxon_id] = taxon
        return taxon

    def get(self, taxon_id: str) -> Taxon | None:
        return self._by_id.get(taxon_id)

    def __getitem__(self, taxon_id: str) -> Taxon:
        return self._by_id[taxon_id]

    def __contains__(self, taxon_id: object) -> bool:
        return taxon_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def walk(self) -> Iterator[Taxon]:
        """Every taxon in taxonomic (pre-)order."""
        if self.root is not None:
            yield from walk(self.root)

    def count(self, taxon_type: TaxonType) -> int:
        return sum(1 for taxon in self.walk() if taxon.type is taxon_type)


def walk(taxon: Taxon) -> Iterator[Taxon]:
    stack = [taxon]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def parent_of_at_least_type(taxon: Taxon, taxon_type: TaxonType) -> Taxon:
    """``TaxonUtils.getParentOfAtLeastType``: the taxon itself, or its first ancestor whose
    rank is ``taxon_type`` or higher."""
    current: Taxon | None = taxon
    while current is not None and current.type < taxon_type:
        current = current.parent
    if current is None:
        raise ValueError(f"{taxon} has no ancestor of at least {taxon_type.name}")
    return current


def parent_of_type_or_none(taxon: Taxon | None, taxon_type: TaxonType) -> Taxon | None:
    """``TaxonUtils.getParentOfTypeOrNull``: the taxon or its nearest ancestor of exactly
    ``taxon_type``."""
    current = taxon
    while current is not None and current.type is not taxon_type:
        current = current.parent
    return current


def parent_of_type(taxon: Taxon, taxon_type: TaxonType) -> Taxon:
    found = parent_of_type_or_none(taxon, taxon_type)
    if found is None:
        raise ValueError(f"{taxon} has no ancestor of type {taxon_type.name}")
    return found


def first_child_of_type(taxon: Taxon, taxon_type: TaxonType) -> Taxon | None:
    """``TaxonUtils.getFirstChildOfType``: the first taxon of that type in pre-order,
    including ``taxon`` itself."""
    for candidate in walk(taxon):
        if candidate.type is taxon_type:
            return candidate
    return None


def full_name(taxon: Taxon) -> str:
    """``TaxonUtils.getFullName``: "Genus species [subspecies]" for species-level taxa."""
    if taxon.type is TaxonType.SPECIES:
        assert taxon.parent is not None
        return f"{taxon.parent.name} {taxon.name}"
    if taxon.type in (TaxonType.GROUP, TaxonType.SUBSPECIES):
        return f"{full_name(parent_of_type(taxon, TaxonType.SPECIES))} {taxon.name}"
    return taxon.name


def visit(taxon: Taxon, visitor: Callable[[Taxon], bool]) -> None:
    """``TaxonUtils.visitTaxa``: pre-order; returning False skips that taxon's children."""
    if visitor(taxon):
        for child in taxon.children:
            visit(child, visitor)

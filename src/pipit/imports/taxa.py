"""Finding taxa from imported names: ``TaxonResolver``, ``TaxonPossibilities`` and
``FieldTaxonImporter``'s name splitting.

Ported from Scythebill ``ui/.../imports/TaxonResolver.java``, ``TaxonPossibilities.java``,
``TaxonImporter.java`` and ``TaxonUtils.simplifyTaxa``. A name is looked up by exact common
name, exact scientific name, near common names, the genus, alternate names, then as a "sp."
or hybrid; what's found is a primary taxon (or two of equal merit) and alternates, chosen
between with the checklist of where each sighting was made. Everything found is a sighting
taxon of the base taxonomy, whichever taxonomy the names are looked up in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from pipit.imports.bktree import BKTree, levenshtein
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import (
    Taxon,
    Taxonomy,
    TaxonType,
    full_name,
    parent_of_at_least_type,
    parent_of_type_or_none,
    visit,
)
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

#: A checklist's status for a sighting taxon of the taxonomy it is asked in, or None.
StatusOf = Callable[[SightingTaxon], str | None]

_SINGLES = (SightingTaxonType.SINGLE, SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES)
_COMMON_WITH_FORM = re.compile(r"^(.+) \(.*\)$", re.DOTALL)
_IN_PART = " - in part"
#: Guava ``CharMatcher.whitespace()``.
WHITESPACE = frozenset(
    chr(code)
    for code in (
        0x09,
        0x0A,
        0x0B,
        0x0C,
        0x0D,
        0x20,
        0x85,
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
    )
)


def java_trim(text: str) -> str:
    """Guava ``CharMatcher.whitespace().trimFrom``."""
    start = 0
    end = len(text)
    while start < end and text[start] in WHITESPACE:
        start += 1
    while end > start and text[end - 1] in WHITESPACE:
        end -= 1
    return text[start:end]


def whitespace_count(text: str) -> int:
    return sum(1 for character in text if character in WHITESPACE)


def resolve(taxon: SightingTaxon, taxonomy: Taxonomy) -> Resolved | None:
    """``SightingTaxon.resolve``: a base sighting taxon in ``taxonomy``."""
    if isinstance(taxonomy, MappedTaxonomy):
        return taxonomy.resolve_into(taxon)
    return taxon.resolve_internal(taxonomy)


def base_of(taxonomy: Taxonomy) -> Taxonomy:
    return taxonomy.base if isinstance(taxonomy, MappedTaxonomy) else taxonomy


def simplify_taxa(taxonomy: Taxonomy, taxa: list[str]) -> list[str]:
    """``TaxonUtils.simplifyTaxa``: all of a parent's children become the parent."""
    if len(taxa) == 1:
        return taxa
    present = set(taxa)
    for taxon_id in taxa:
        taxon = taxonomy[taxon_id]
        if taxon.type is TaxonType.SPECIES:
            continue
        assert taxon.parent is not None
        children = [child.id for child in taxon.parent.children]
        if present.issuperset(children):
            simplified = [kept for kept in taxa if kept not in set(children)]
            if taxon.parent.id not in simplified:
                simplified.append(taxon.parent.id)
            return simplify_taxa(taxonomy, simplified)
    return taxa


def _is_child_of(parent: Taxon, child: Taxon) -> bool:
    """``TaxonUtils.isChildOf``: strictly below."""
    current = child.parent
    while current is not None:
        if current is parent:
            return True
        current = current.parent
    return False


# ------------------------------------------------------------------ possibilities


@dataclass(slots=True)
class TaxonPossibilities:
    """A primary taxon (and maybe a second of equal merit) and alternates, as base sighting
    taxa; ``choose`` picks between them with a checklist."""

    primary: SightingTaxon
    good_match: bool
    another_primary: SightingTaxon | None = None
    alternates: list[SightingTaxon] | None = field(default=None)

    @staticmethod
    def adding(base: TaxonPossibilities | None, more: SightingTaxon,
               good_match: bool = False) -> TaxonPossibilities:  # fmt: skip
        if base is None:
            return TaxonPossibilities(more, good_match)
        if base.primary == more:
            return base
        if base.alternates is None:
            base.alternates = []
        if more not in base.alternates:
            base.alternates.append(more)
        return base

    @staticmethod
    def with_primary(base: TaxonPossibilities | None, another: SightingTaxon,
                     good_match: bool) -> TaxonPossibilities:  # fmt: skip
        if base is not None and base.another_primary is None and base.primary != another:
            if not base.good_match and good_match:
                replaced = TaxonPossibilities(another, good_match)
                replaced.another_primary = base.primary
                return replaced
            base.another_primary = another
            return base
        return TaxonPossibilities.adding(base, another, good_match)

    @property
    def has_alternates(self) -> bool:
        return self.alternates is not None or self.another_primary is not None

    def choose(self, status_of: StatusOf | None, taxonomy: Taxonomy) -> SightingTaxon:
        chosen = self._choose(status_of, taxonomy)
        if chosen.type is SightingTaxonType.SP:
            chosen = SightingTaxon.possibly_sp(simplify_taxa(base_of(taxonomy), list(chosen.ids)))
        return chosen

    def chose_sp_to_resolve(self, chosen: SightingTaxon) -> bool:
        return chosen.type is SightingTaxonType.SP and self.primary.type is not SightingTaxonType.SP

    def _choose(self, status_of: StatusOf | None, taxonomy: Taxonomy) -> SightingTaxon:
        if self.alternates is None and self.another_primary is None:
            return self.primary
        if status_of is None:
            if self.another_primary is None:
                return self.primary
            return _unify([self.primary, self.another_primary], taxonomy)
        if self.primary.type not in _SINGLES:
            return self.primary
        valid = [
            taxon
            for taxon in (self.primary, self.another_primary)
            if taxon is not None and _status(status_of, taxonomy, taxon) is not None
        ]
        if valid:
            return _unify(valid, taxonomy)
        if self.alternates is not None:
            others: list[SightingTaxon] = []
            rarities: list[SightingTaxon] = []
            for alternate in self.alternates:
                status = _status(status_of, taxonomy, alternate)
                if status in ("RARITY", "RARITY_FROM_INTRODUCED"):
                    rarities.append(alternate)
                elif status is not None:
                    others.append(alternate)
            if others:
                return _unify(others, taxonomy)
            if rarities:
                return _unify(rarities, taxonomy)
        if self.another_primary is None:
            return self.primary
        return _unify([self.primary, self.another_primary], taxonomy)


def _status(status_of: StatusOf, taxonomy: Taxonomy, taxon: SightingTaxon) -> str | None:
    resolved = resolve(taxon, taxonomy)
    assert resolved is not None
    return status_of(resolved.parent_of_at_least_type(TaxonType.SPECIES))


def _unify(taxa: list[SightingTaxon], taxonomy: Taxonomy) -> SightingTaxon:
    if len(taxa) == 1:
        return taxa[0]
    resolved_all = [resolve(taxon, taxonomy) for taxon in taxa]
    resolved = sorted((r for r in resolved_all if r is not None), key=lambda r: r.smallest_type)
    if len({r.smallest_type for r in resolved}) > 1:
        most_specific = resolved[0]
        if all(_is_parent_of(most_specific, other) for other in resolved[1:]):
            found = most_specific.sighting_taxon
            if isinstance(taxonomy, MappedTaxonomy):
                mapped = taxonomy.mapping_of(found)
                assert mapped is not None
                found = mapped
            return found
        species = list(dict.fromkeys(r.parent_of_at_least_type(TaxonType.SPECIES)
                                     for r in resolved))  # fmt: skip
        if isinstance(taxonomy, MappedTaxonomy):
            species = [mapped for taxon in species
                       if (mapped := taxonomy.mapping_of(taxon)) is not None]  # fmt: skip
        taxa = species
    ids = list(dict.fromkeys(taxon_id for taxon in taxa for taxon_id in taxon.ids))
    return SightingTaxon.possibly_sp(ids)


def _is_parent_of(most_specific: Resolved, maybe_parent: Resolved) -> bool:
    if most_specific.type is not SightingTaxonType.SINGLE:
        return False
    if maybe_parent.type is not SightingTaxonType.SINGLE:
        return False
    return _is_child_of(maybe_parent.taxon, most_specific.taxon)


# ------------------------------------------------------------------ names


@dataclass(slots=True)
class TbdTaxon:
    """``TaxonImporter.TbdTaxon``: an imported name left for the user to resolve."""

    common_name: str | None = None
    scientific_name: str | None = None
    subspecies: str | None = None
    location_ids: dict[str, None] = field(default_factory=dict)
    unresolved_location_names: dict[str, None] = field(default_factory=dict)

    def should_ignore(self) -> bool:
        """Definitely a "sp." (like eBird's "duck sp."): never asked about."""
        common = self.common_name
        scientific = self.scientific_name
        return (common is not None and (common.endswith(" sp.") or common.endswith(" sp.)"))
                and (scientific is None or scientific.endswith(" sp.")
                     or scientific.endswith(" sp.)")))  # fmt: skip


def normalize_common_name(name: str, subspecies: str | None = None) -> str:
    if subspecies is not None and name.find(subspecies) > 0:
        for ending in (f" ({subspecies}(", f" [{subspecies}]"):
            if name.endswith(ending):
                name = name[: -len(ending)]
    return (name.lower()
            .replace("grey", "gray").replace("ç", "c").replace("ñ", "n").replace("\u00b4", "'")
            .replace("\u2010", " ").replace("-", " ").replace("chequer", "checker")
            .replace("racquet", "racket").replace("ö", "oe").replace("ü", "ue")
            .replace("colour", "color"))  # fmt: skip


def _java_lower(text: str) -> str:
    """``toLowerCase(Locale.ROOT)`` (Python's ``lower`` agrees for the names in taxonomies)."""
    return text.lower()


def _trim_sci_suffix(name: str | None) -> str | None:
    if name is None:
        return None
    length = len(name)
    if length <= 2:
        return name
    if length > 4 and (name.endswith("orum") or name.endswith("arum")):
        return name[:-4]
    if name.endswith(("us", "um", "is", "or", "ii", "ae")):
        return name[:-2]
    if name[-1] in "eai":
        return name[:-1]
    return name


def _split_sp(text: str) -> list[str]:
    """``Splitter.on('/').trimResults(whitespace).omitEmptyStrings()``."""
    return [part for part in (java_trim(piece) for piece in text.split("/")) if part]


class TaxonResolver:
    """Names to taxa in one taxonomy (falling back to the base, for a mapped one)."""

    def __init__(self, taxonomy: Taxonomy, maximum_name_distance: int = 2) -> None:
        self.taxonomy = taxonomy
        self.maximum_name_distance = maximum_name_distance
        self._genus_names: dict[str, Taxon] = {}
        self._species_names: dict[str, list[Taxon]] = {}
        self._common_names: dict[str, list[Taxon]] = {}
        self._alternate_common_names: dict[str, list[Taxon]] = {}
        self._alternate_sci_names: dict[str, list[Taxon]] = {}
        self._common_tree: BKTree[Taxon] = BKTree()
        self._build_indices()
        self._alternate_tree: BKTree[Taxon] = BKTree()
        for name, taxa in self._alternate_common_names.items():
            if len(taxa) == 1:
                self._alternate_tree.add(name, taxa[0])
        self._base_resolver: TaxonResolver | None = None

    # -------------------------------------------------------------- indices

    @staticmethod
    def _put(index: dict[str, list[Taxon]], key: str, taxon: Taxon) -> None:
        """A ``LinkedHashMultimap``: each taxon once per key."""
        found = index.setdefault(key, [])
        if taxon not in found:
            found.append(taxon)

    def _build_indices(self) -> None:
        root = self.taxonomy.root
        assert root is not None
        put = self._put

        def visitor(taxon: Taxon) -> bool:
            if taxon.type is TaxonType.GENUS:
                self._genus_names[_java_lower(taxon.name)] = taxon
            elif taxon.type is TaxonType.SPECIES:
                put(self._species_names, _java_lower(full_name(taxon)), taxon)
                for alternate in taxon.alternate_names:
                    put(self._alternate_sci_names, _java_lower(alternate), taxon)
                if taxon.common_name is not None:
                    put(self._common_names, normalize_common_name(taxon.common_name), taxon)
                    self._common_tree.add(normalize_common_name(taxon.common_name), taxon)
                    for alternate in taxon.alternate_common_names:
                        put(self._alternate_common_names,
                            normalize_common_name(_remove_in_part(alternate)), taxon)  # fmt: skip
                    undescribed = taxon.common_name.find(" (undesc")
                    if undescribed > 0:
                        short = normalize_common_name(taxon.common_name[:undescribed])
                        put(self._common_names, short, taxon)
                        self._common_tree.add(short, taxon)
            elif taxon.type is TaxonType.GROUP:
                put(self._species_names, _java_lower(full_name(taxon)), taxon)
                for alternate in taxon.alternate_names:
                    put(self._alternate_sci_names, _java_lower(alternate), taxon)
                if taxon.common_name is not None:
                    put(self._common_names, normalize_common_name(taxon.common_name), taxon)
                for alternate in taxon.alternate_common_names:
                    put(self._alternate_common_names,
                        _remove_in_part(normalize_common_name(alternate)), taxon)  # fmt: skip
            elif taxon.type is TaxonType.SUBSPECIES:
                for alternate in taxon.alternate_common_names:
                    put(self._alternate_common_names,
                        _remove_in_part(normalize_common_name(alternate)), taxon)  # fmt: skip
            return True

        visit(root, visitor)

    # -------------------------------------------------------------- lookups

    def map(self, common_name: str | None, sci_name: str | None,
            subspecies: str | None) -> TaxonPossibilities | None:  # fmt: skip
        found = self._map_here(common_name, sci_name, subspecies)
        if found is None and isinstance(self.taxonomy, MappedTaxonomy):
            if self._base_resolver is None:
                self._base_resolver = TaxonResolver(self.taxonomy.base,
                                                    self.maximum_name_distance)  # fmt: skip
            found = self._base_resolver.map(common_name, sci_name, subspecies)
        return found

    def _map_here(self, common_name: str | None, sci_name: str | None,
                  subspecies: str | None) -> TaxonPossibilities | None:  # fmt: skip
        found: TaxonPossibilities | None = None
        if common_name is not None:
            common_name = normalize_common_name(common_name, subspecies)
            taxa = self._common_names.get(common_name, [])
            if len(taxa) == 1:
                taxon = self._sighting_taxon(taxa[0], subspecies)
                good = (self._good_scientific_name(taxon, sci_name, subspecies)
                        or self._names_no_other_species(taxa[0], sci_name))  # fmt: skip
                found = TaxonPossibilities.with_primary(found, taxon, good)
            elif len(taxa) > 1 and sci_name is not None:
                good_taxa = list(dict.fromkeys(
                    st for candidate in taxa
                    if self._good_scientific_name(
                        st := self._sighting_taxon(candidate, subspecies), sci_name, subspecies)
                ))  # fmt: skip
                if len(good_taxa) == 1:
                    found = TaxonPossibilities.with_primary(found, good_taxa[0], good_match=True)
        if sci_name is not None:
            sci_name = _java_lower(sci_name)
            taxa = self._species_names.get(sci_name, [])
            if len(taxa) == 1:
                taxon = self._sighting_taxon(taxa[0], subspecies)
                found = TaxonPossibilities.with_primary(
                    found, taxon, self._good_common_name(taxon, common_name)
                )
        if found is None and common_name is not None:
            near = self._common_tree.search(common_name, self.maximum_name_distance)
            if len(near) == 1:
                improved = False
                if sci_name is not None:
                    parts = sci_name.split(" ")
                    if len(parts) >= 2:
                        genus = parent_of_type_or_none(near[0], TaxonType.GENUS)
                        in_genus = self.find_match_within(genus, parts[1], prefer_groups=False)
                        if in_genus is not None:
                            found = TaxonPossibilities.adding(
                                found, self._sighting_taxon(in_genus, subspecies)
                            )
                            improved = True
                if not improved:
                    found = TaxonPossibilities.adding(
                        found, self._sighting_taxon(near[0], subspecies)
                    )
        if sci_name is not None and found is None:
            in_genus = self._find_in_genus(sci_name)
            if in_genus is not None:
                found = TaxonPossibilities.adding(found, self._sighting_taxon(in_genus, subspecies))
        if common_name is not None:
            found = self._alternate_common(found, common_name, subspecies)
        if sci_name is not None:
            first = found is None
            for alternate in self._alternate_sci_names.get(sci_name, []):
                taxon = self._sighting_taxon(alternate, subspecies)
                found = (TaxonPossibilities.with_primary(found, taxon, good_match=False) if first
                         else TaxonPossibilities.adding(found, taxon))  # fmt: skip
        if sci_name is not None and found is None:
            found = self._spuhs_in_scientific_name(sci_name)
        if common_name is not None and found is None:
            found = self._spuhs_in_common_name(common_name)
        return found

    def _alternate_common(self, found: TaxonPossibilities | None, common_name: str,
                          subspecies: str | None) -> TaxonPossibilities | None:  # fmt: skip
        first = found is None
        for alternate in self._alternate_common_names.get(common_name, []):
            taxon = self._sighting_taxon(alternate, subspecies)
            found = (TaxonPossibilities.with_primary(found, taxon, good_match=False) if first
                     else TaxonPossibilities.adding(found, taxon))  # fmt: skip
        if found is None and len(common_name) > 4:
            for near in self._alternate_tree.search(common_name, self.maximum_name_distance):
                found = TaxonPossibilities.with_primary(
                    found, self._sighting_taxon(near, subspecies), good_match=False
                )
        match = _COMMON_WITH_FORM.match(common_name)
        if match is not None:
            reduced = match.group(1)
            taxa = self._common_names.get(reduced, [])
            if len(taxa) == 1:
                found = TaxonPossibilities.adding(found, self._sighting_taxon(taxa[0], subspecies))
            taxa = self._alternate_common_names.get(reduced, [])
            if len(taxa) == 1:
                found = TaxonPossibilities.adding(found, self._sighting_taxon(taxa[0], subspecies))
        return found

    def _good_scientific_name(self, taxon: SightingTaxon, sci_name: str | None,
                              subspecies: str | None) -> bool:  # fmt: skip
        if not sci_name:
            return True
        resolved = resolve(taxon, self.taxonomy)
        assert resolved is not None
        if resolved.type is not SightingTaxonType.SINGLE:
            return True
        space = sci_name.find(" ")
        if space > 0:
            sci_name = sci_name[space + 1 :]
        trimmed = _trim_sci_suffix(resolved.taxon.name)
        return trimmed in (_trim_sci_suffix(sci_name), _trim_sci_suffix(subspecies))

    def _good_common_name(self, taxon: SightingTaxon, common_name: str | None) -> bool:
        if not common_name:
            return True
        resolved = resolve(taxon, self.taxonomy)
        assert resolved is not None
        if resolved.type is not SightingTaxonType.SINGLE:
            return True
        found = resolved.taxon
        if common_name == found.common_name:
            return True
        return found.type <= TaxonType.SPECIES and any(
            normalize_common_name(alternate) == common_name
            for alternate in found.alternate_common_names
        )

    def _names_no_other_species(self, taxon: Taxon, sci_name: str | None) -> bool:
        if sci_name is None:
            return True
        normalized = _java_lower(sci_name)
        named: set[Taxon] = set(self._species_names.get(normalized, []))
        named.update(self._alternate_sci_names.get(normalized, []))
        in_genus = self._find_in_genus(normalized)
        if in_genus is not None:
            named.add(in_genus)
        parts = normalized.split(" ")
        genus = parent_of_type_or_none(taxon, TaxonType.GENUS)
        if len(parts) == 2 and genus is not None:
            found = self.find_match_within(genus, parts[1], prefer_groups=False)
            if found is not None:
                named.add(found)
        species = parent_of_at_least_type(taxon, TaxonType.SPECIES)
        return all(parent_of_at_least_type(other, TaxonType.SPECIES) is species
                   for other in named)  # fmt: skip

    def _find_in_genus(self, sci_name: str) -> Taxon | None:
        """``findTaxonByScientificNameInGenus``."""
        parts = sci_name.split(" ")
        match: Taxon | None = None
        if len(parts) >= 2:
            if parts[1] == "sp.":
                return None
            if len(parts) == 2:
                genus = self._genus_names.get(parts[0])
                if genus is not None:
                    match = self.find_match_within(genus, parts[1], prefer_groups=True)
        if match is not None and match.type is TaxonType.SUBSPECIES:
            match = match.parent
        return match

    def _find_exact_and_in_genus(self, sci_name: str) -> Taxon | None:
        taxa = self._species_names.get(sci_name, [])
        if len(taxa) == 1:
            return taxa[0]
        return self._find_in_genus(sci_name)

    def _species_for_common_name(self, common_name: str) -> Taxon | None:
        taxa = self._common_names.get(common_name, [])
        if len(taxa) == 1:
            return taxa[0]
        near = self._common_tree.search(common_name, self.maximum_name_distance)
        return near[0] if len(near) == 1 else None

    def _species_possibly_appending(self, common_name: str, append_from: str) -> Taxon | None:
        """The name, else the name with the last word of ``append_from`` ("Baltimore" and
        "Bullock's Oriole"). Scythebill's loop to try more words never runs a second time."""
        taxon = self._species_for_common_name(common_name)
        if taxon is not None:
            return taxon
        last_space = append_from.rfind(" ")
        if last_space > 0:
            return self._species_for_common_name(common_name + append_from[last_space:])
        return None

    def _spuhs_in_scientific_name(self, sci_name: str) -> TaxonPossibilities | None:
        hybrid = False
        split: list[str] | None = None
        if "/" in sci_name:
            split = _split_sp(sci_name)
        elif " x " in sci_name:
            hybrid = True
            split = sci_name.split(" x ")
        if split is None or len(split) < 2:
            return None
        first = split[0]
        first_taxon = self._find_exact_and_in_genus(first)
        if first_taxon is None:
            return None
        taxa = [first_taxon.id]
        for written in split[1:]:
            # "Bubulcus ibis/coromandus": the genus is the first name's
            part = written if " " in written else first[: first.find(" ") + 1] + written
            more = self._find_exact_and_in_genus(part)
            if more is None:
                return None
            if more.id not in taxa:
                taxa.append(more.id)
        return TaxonPossibilities.adding(None, self._multiple(first_taxon, taxa, hybrid))

    def _spuhs_in_common_name(self, common_name: str) -> TaxonPossibilities | None:
        hybrid = False
        split: list[str] | None = None
        if "/" in common_name:
            split = _split_sp(common_name)
        elif " x " in common_name:
            hybrid = True
            split = common_name.split(" x ")
        found: TaxonPossibilities | None = None
        if split is not None and len(split) >= 2:
            last = split[-1]
            last_taxon = self._species_for_common_name(last)
            if last_taxon is None and " (" in last:
                last = last[: last.find(" (")]
                last_taxon = self._species_for_common_name(last)
            if last_taxon is not None:
                taxa = [last_taxon.id]
                complete = True
                for part in split[:-1]:
                    more = self._species_possibly_appending(part, last)
                    if more is None:
                        complete = False
                        break
                    taxa.append(more.id)
                if complete:
                    found = TaxonPossibilities.adding(
                        None, self._multiple(last_taxon, taxa, hybrid)
                    )
        if found is None:
            found = self._warbler_hybrids(common_name)
        return found

    def _warbler_hybrids(self, common_name: str) -> TaxonPossibilities | None:
        """Hybrids eBird gives names of their own. As in Scythebill, the parents are looked
        up by their names as written, which only near matches can find."""
        if "brewster's warbler" in common_name or "lawrence's warbler" in common_name:
            names = ("Blue-winged Warbler", "Golden-winged Warbler")
        elif "sutton's warbler" in common_name:
            names = ("Yellow-throated Warbler", "Northern Parula")
        else:
            return None
        parents = [self._species_for_common_name(name) for name in names]
        if parents[0] is None or parents[1] is None:
            return None
        return TaxonPossibilities.adding(None, SightingTaxon.hybrid(p.id for p in parents
                                                                    if p is not None))  # fmt: skip

    def _multiple(self, taxon: Taxon, ids: list[str], hybrid: bool) -> SightingTaxon:
        """A sp. or hybrid, or the one taxon if every name is the same one (Scythebill's
        import fails on "Mallard x Mallard"; Pipit imports a Mallard)."""
        ids = list(dict.fromkeys(ids))
        if len(ids) == 1:
            found = SightingTaxon.single(ids[0])
        elif hybrid:
            found = SightingTaxon.hybrid(ids)
        else:
            found = SightingTaxon.sp(ids)
        if isinstance(taxon.taxonomy, MappedTaxonomy):
            mapped = taxon.taxonomy.mapping_of(found)
            assert mapped is not None
            return mapped
        return found

    # -------------------------------------------------------------- subspecies

    def _sighting_taxon(self, taxon: Taxon, subspecies: str | None) -> SightingTaxon:
        """``getTaxon``: the taxon (or the named subspecies in it), in the base taxonomy."""
        found = SightingTaxon.single(taxon.id)
        if subspecies is not None:
            if "/" in subspecies:
                ids = [match.id for name in _split_sp(subspecies)
                       if (match := self.find_match_within(taxon, name, prefer_groups=False))
                       is not None]  # fmt: skip
                if ids:
                    found = SightingTaxon.possibly_sp(ids)
            else:
                match = self.find_match_within(taxon, subspecies, prefer_groups=False)
                if match is None:
                    match = self.find_match_within(parent_of_type_or_none(taxon, TaxonType.GENUS),
                                                   subspecies, prefer_groups=False)  # fmt: skip
                if match is not None:
                    found = SightingTaxon.single(match.id)
        mapped_taxonomy = taxon.taxonomy
        if isinstance(mapped_taxonomy, MappedTaxonomy):
            mapping = mapped_taxonomy.mapping_of(found)
            if mapping is None:
                mapping = mapped_taxonomy.mapping(taxon)
            assert mapping is not None, f"{taxon} has no mapping"
            return mapping
        return found

    def find_match_within(self, parent: Taxon | None, name: str,
                          prefer_groups: bool) -> Taxon | None:  # fmt: skip
        return find_match_within(parent, name, prefer_groups=prefer_groups,
                                 maximum_distance=self.maximum_name_distance)  # fmt: skip


def find_match_within(parent: Taxon | None, name: str, *, prefer_groups: bool,
                      maximum_distance: int = 2) -> Taxon | None:  # fmt: skip
    """``TaxonResolver.findMatchWithin``: a taxon below ``parent`` by name, exactly, else a
    species within the edit distance; only when there's exactly one."""
    if parent is None:
        return None
    matches: list[Taxon] = []

    def exact(taxon: Taxon) -> bool:
        if taxon is not parent and taxon.name == name:
            matches.append(taxon)
            return False
        return True

    visit(parent, exact)
    if not matches:

        def close(taxon: Taxon) -> bool:
            if (taxon is not parent and taxon.type is TaxonType.SPECIES
                    and _equals_or_close(name, taxon.name, maximum_distance)):  # fmt: skip
                matches.append(taxon)
                return False
            return True

        visit(parent, close)
    if len(matches) != 1:
        return None
    match = matches[0]
    if (prefer_groups and match.type is TaxonType.SUBSPECIES and match.parent is not None
            and match.parent.type is TaxonType.GROUP):  # fmt: skip
        match = match.parent
    return match


def _equals_or_close(first: str, second: str, maximum_distance: int) -> bool:
    if first == second:
        return True
    if maximum_distance == 0:
        return False
    limit = maximum_distance if len(first) > 4 else 1
    return levenshtein(first, second) <= limit


def _remove_in_part(name: str) -> str:
    return name[: -len(_IN_PART)] if name.endswith(_IN_PART) else name


# ------------------------------------------------------------------ binomials


def has_subspecies(text: str) -> bool:
    """``EBirdMyDataImporter.hasSubspecies``: more than one space, and not a hybrid."""
    return whitespace_count(text) > 1 and " x " not in text


def second_space(text: str) -> int:
    first = next((i for i, c in enumerate(text) if c in WHITESPACE), -1)
    if first < 0:
        return -1
    return next((i for i in range(first + 1, len(text)) if text[i] in WHITESPACE), -1)


def just_binomial(text: str) -> str:
    """``EBirdMyDataImporter.JustBinomial``."""
    return text[: second_space(text)] if has_subspecies(text) else text


def after_binomial(text: str) -> str | None:
    """``EBirdMyDataImporter.AfterBinomial``."""
    return text[second_space(text) + 1 :] if has_subspecies(text) else None


def empty_to_none(text: str | None) -> str | None:
    return text or None


def first_or_none[T](items: Sequence[T]) -> T | None:
    return items[0] if items else None


def ordered(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))

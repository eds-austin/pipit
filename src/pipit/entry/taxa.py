"""Taxa for entry: the display taxonomy (AviList by default, or Clements), search ranked for
the place being entered, and how a chosen taxon is stored.

Sightings are always stored with base (Clements) IDs. A taxon chosen in AviList is stored
as its base mapping (``MappedTaxonomy.getMapping``): one taxon, a sp., or a base species
plus an AviList subspecies name - exactly what Scythebill stores.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pipit.entry.commit import StoredTaxon
from pipit.search.normalize import index_words, normalize, query_text, split_words
from pipit.search.taxon_index import IndexKind, TaxonIndex
from pipit.search.word_separator import MAX_LENGTH_TO_SPLIT, boundaries
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxon, Taxonomy, TaxonType, full_name
from pipit.taxa.sighting_taxon import SightingTaxon

#: Checklist statuses that mean "expected here" (ranked first).
_EXPECTED = frozenset({"", "endemic", "introduced"})


@dataclass(frozen=True, slots=True)
class Match:
    taxon_id: str
    common_name: str
    scientific_name: str
    rank: str  # "species", "group", "subspecies"
    matched_name: str | None  # an alternate name that matched, if that was the match
    checklist_status: str | None  # None: not on the checklist (or no checklist)
    seen: bool  # the species is on the life list


class EntryTaxa:
    """One display taxonomy, ready for typing."""

    def __init__(self, base: Taxonomy, display: Taxonomy, index: TaxonIndex | None = None) -> None:
        self.base = base
        self.display = display
        self.index = index or TaxonIndex(display)
        self._order = {taxon.id: position for position, taxon in enumerate(display.walk())}
        self._codes = {
            taxon.account_id.lower(): taxon.id
            for taxon in display.walk()
            if taxon.account_id and not taxon.disabled
        }

    # ------------------------------------------------------------ storing

    def stored(self, taxon_id: str) -> StoredTaxon | None:
        """How a row is stored. Rows of several taxa ("a/b" a sp., "a+b" a hybrid) are
        stored as Scythebill stores them (``MappedTaxonomy.getMapping(SightingTaxon)``)."""
        for separator, factory in (("/", SightingTaxon.sp), ("+", SightingTaxon.hybrid)):
            if separator in taxon_id:
                parts = taxon_id.split(separator)
                if any(self.display.get(part) is None for part in parts):
                    return None
                chosen = factory(parts)
                if isinstance(self.display, MappedTaxonomy):
                    base = self.display.mapping_of(chosen)
                    if base is None:
                        return None
                else:
                    base = chosen
                return StoredTaxon(base, None, min(self._order[part] for part in parts))
        taxon = self.display.get(taxon_id)
        if taxon is None:
            return None
        if isinstance(self.display, MappedTaxonomy):
            mapping = self.display.mapping(taxon)
            if mapping is None:
                return None
            base_taxon = mapping
        else:
            base_taxon = SightingTaxon.single(taxon_id)
        return StoredTaxon(base_taxon, None, self._order[taxon_id])

    def order(self, taxon_id: str) -> int:
        parts = taxon_id.replace("+", "/").split("/")
        return min(self._order.get(part, len(self._order)) for part in parts)

    def names(self, taxon_id: str) -> tuple[str, str]:
        """(common, scientific) for a row: one taxon, a sp. ("a/b") or a hybrid ("a x b",
        with the multiplication sign)."""
        separator = "/" if "/" in taxon_id else " \u00d7 " if "+" in taxon_id else ""
        parts = taxon_id.replace("+", "/").split("/")
        taxa = [self.display.get(part) for part in parts]
        if any(taxon is None for taxon in taxa):
            return taxon_id, ""
        common = [t.common_name or full_name(t) for t in taxa if t is not None]
        scientific = [full_name(t) for t in taxa if t is not None]
        if not separator:
            return common[0], scientific[0]
        return separator.join(common), separator.join(scientific)

    # ------------------------------------------------------------ search

    def search(
        self,
        query: str,
        checklist: Mapping[str, str] | None = None,
        seen_species: frozenset[str] = frozenset(),
        limit: int = 50,
    ) -> list[Match]:
        """Every taxon whose names match ``query`` (Scythebill's word-prefix rules), best
        first: exact names and eBird codes, then birds on the place's checklist (expected
        before rarities), then species already on the life list, then species before
        groups and subspecies, then taxonomic order."""
        if not query.strip():
            return []
        found: dict[str, str | None] = {}
        for kind in IndexKind:
            alternate = kind in (IndexKind.ALTERNATE_COMMON, IndexKind.ALTERNATE_SCIENTIFIC)
            for entry in self.index.find(kind, query):
                if entry.taxon_id not in found or (
                    found[entry.taxon_id] is not None and not alternate
                ):
                    found[entry.taxon_id] = entry.name if alternate else None
        code_match = self._codes.get(query.strip().lower())
        if code_match is not None:
            found.setdefault(code_match, None)
        wanted = normalize(query.strip())

        def score(taxon_id: str) -> tuple[int, ...]:
            taxon = self.display[taxon_id]
            species = _species_of(taxon)
            common = taxon.common_name or ""
            others = [full_name(taxon), found[taxon_id] or ""]
            # Only a bird's own common name (or, for species, any name or its eBird code)
            # makes an exact match: a subspecies listed under an old species name must not
            # beat the species ("bushtit").
            candidates = (common, *others) if taxon.type is TaxonType.SPECIES else (common,)
            exact = taxon_id == code_match or any(
                normalize(name) == wanted for name in candidates if name
            )
            primary = match_quality(query, common) if common else _NO_MATCH
            other = min((match_quality(query, name) for name in others if name), default=_NO_MATCH)
            skips, split = min(primary, other)
            status = checklist.get(species.id) if checklist is not None else ""
            bucket = 0 if status in _EXPECTED else 1 if status is not None else 2
            # A subspecies or group found only through another name comes after species.
            borrowed = taxon.type is not TaxonType.SPECIES and primary[0] != skips
            return (
                0 if exact else 1,
                1 if borrowed else 0,
                skips,
                0 if primary[0] == skips else 1,  # the bird's own name beats other names
                bucket,
                0 if species.id in seen_species else 1,
                0 if taxon.type is TaxonType.SPECIES or exact else 1,
                split,
                self._order[taxon_id],
            )

        ranked = sorted(found, key=score)[:limit]
        return [
            self._match(taxon_id, found[taxon_id], checklist, seen_species) for taxon_id in ranked
        ]

    def _match(
        self,
        taxon_id: str,
        alternate: str | None,
        checklist: Mapping[str, str] | None,
        seen_species: frozenset[str],
    ) -> Match:
        taxon = self.display[taxon_id]
        species = _species_of(taxon)
        return Match(
            taxon_id=taxon_id,
            common_name=taxon.common_name or full_name(taxon),
            scientific_name=full_name(taxon),
            rank=taxon.type.xml_name,
            matched_name=alternate,
            checklist_status=None if checklist is None else checklist.get(species.id),
            seen=species.id in seen_species,
        )


_NO_MATCH = (99, 99999)


def match_quality(query: str, name: str) -> tuple[int, int]:
    """How well a query fits a name: (words skipped, split rank). (0, 0) is best: the query
    is a prefix of the first word, or its pieces are prefixes of consecutive words from the
    first ("amro" = AMerican RObin). Splits are tried in Scythebill's preferred order."""
    words = index_words(name, 5)
    entry = query_text(query)
    tokens = split_words(entry)
    splits = [tokens] if len(tokens) > 1 else []
    if len(tokens) <= 1 and entry:
        capped = entry[:MAX_LENGTH_TO_SPLIT]
        for split in boundaries(len(capped)):
            start = 0
            pieces = []
            for end in split:
                pieces.append(capped[start:end])
                start = end
            splits.append(pieces)
    best = _NO_MATCH
    for rank, pieces in enumerate(splits):
        position = 0
        skipped = 0
        for piece in pieces:
            while position < len(words) and not words[position].startswith(piece):
                position += 1
                skipped += 1
            if position == len(words):
                break
            position += 1
        else:
            best = min(best, (skipped, rank))
            if skipped == 0:
                break
    return best


def _species_of(taxon: Taxon) -> Taxon:
    current: Taxon | None = taxon
    while current is not None and current.type is not TaxonType.SPECIES:
        current = current.parent
    return current or taxon

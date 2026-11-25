"""A custom checklist as Scythebill's editor shows it (``EditChecklistPanel``): each entry
resolved into the display taxonomy, in taxonomic order (``ResolvedComparator``, the port in
``pipit.entry.commit``); entries that can't be shown go last. Adding a species stores its
base taxon (``getSightingTaxonInBaseTaxonomy``) and keeps the order; one already on the
list is not added twice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cmp_to_key

from pipit.entry.commit import StoredTaxon, compare_stored
from pipit.entry.taxa import EntryTaxa
from pipit.storage.checklist_ops import ChecklistEntry
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

_KIND = {SightingTaxonType.SINGLE: "single", SightingTaxonType.SP: "sp",
         SightingTaxonType.HYBRID: "hybrid",
         SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES: "ssp"}  # fmt: skip


@dataclass(frozen=True, slots=True)
class ChecklistRow:
    entry: ChecklistEntry
    row_id: str | None  # in the display taxonomy; None if it can't be shown
    common: str
    scientific: str

    @property
    def status(self) -> str | None:
        return self.entry.status


def _stored(entry: ChecklistEntry) -> SightingTaxon:
    if entry.kind == "ssp":
        return SightingTaxon.with_secondary_subspecies(entry.taxon_ids[0], entry.subspecies or "")
    if entry.kind == "sp":
        return SightingTaxon.sp(entry.taxon_ids)
    if entry.kind == "hybrid":
        return SightingTaxon.hybrid(entry.taxon_ids)
    return SightingTaxon.single(entry.taxon_ids[0])


def _row(taxa: EntryTaxa, entry: ChecklistEntry) -> ChecklistRow:
    row_id = taxa.row_id(_stored(entry))
    if row_id is None:
        label = "/".join(entry.taxon_ids)
        return ChecklistRow(entry, None, f"Not in {taxa.display.name} ({label})", "")
    common, scientific = taxa.names(row_id)
    return ChecklistRow(entry, row_id, common, scientific)


def _comparable(taxa: EntryTaxa, row: ChecklistRow) -> StoredTaxon | None:
    if row.row_id is None:
        return None
    separator = "/" if "/" in row.row_id else "+" if "+" in row.row_id else ""
    parts = row.row_id.split(separator) if separator else [row.row_id]
    positions = tuple(taxa.order(part) for part in parts)
    kind = "sp" if separator == "/" else "hybrid" if separator == "+" else "single"
    return StoredTaxon(_stored(row.entry), None, min(positions), positions, kind)


def sort_rows(taxa: EntryTaxa, rows: list[ChecklistRow]) -> list[ChecklistRow]:
    keyed = [(row, _comparable(taxa, row)) for row in rows]

    def compare(left: tuple[ChecklistRow, StoredTaxon | None],
                right: tuple[ChecklistRow, StoredTaxon | None]) -> int:  # fmt: skip
        if left[1] is None or right[1] is None:  # nulls last, as ResolvedComparator
            return (left[1] is None) - (right[1] is None)
        return compare_stored(left[1], right[1])

    return [row for row, _ in sorted(keyed, key=cmp_to_key(compare))]


def checklist_rows(taxa: EntryTaxa, entries: list[ChecklistEntry]) -> list[ChecklistRow]:
    return sort_rows(taxa, [_row(taxa, entry) for entry in entries])


def add_species(
    taxa: EntryTaxa, rows: list[ChecklistRow], display_taxon_id: str
) -> tuple[list[ChecklistRow], int]:
    """``addResolved``: the rows with the species added (as native), and its index; a
    species already on the list stays as it is."""
    stored = taxa.stored(display_taxon_id)
    if stored is None:
        raise ValueError(f"{display_taxon_id} can't be stored")
    taxon = stored.taxon
    ids = taxon.ids if taxon.is_multiple else (taxon.ids[0],)
    entry = ChecklistEntry(_KIND[taxon.type], tuple(ids), taxon.subspecies)
    for index, row in enumerate(rows):
        if row.entry.identity == entry.identity:
            return rows, index
    added = sort_rows(taxa, [*rows, _row(taxa, entry)])
    return added, next(i for i, row in enumerate(added) if row.entry.identity == entry.identity)


def with_status(row: ChecklistRow, status: str | None) -> ChecklistRow:
    return replace(row, entry=replace(row.entry, status=status))

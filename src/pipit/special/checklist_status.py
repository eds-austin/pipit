"""Checklist status report: the species seen at places with a checklist whose status there is
the one asked about (not on the checklist, a rarity, endemic, ...), place by place.

Ported from Scythebill ``ui/.../panels/reports/ChecklistStatusReportPanel.java``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipit.query.checklists import Checklists
from pipit.query.engine import Resolver
from pipit.query.model import QueryList
from pipit.query.results import taxonomy_index
from pipit.taxa.model import Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

#: ``ReportChoice``, in Scythebill's order, with its label.
CHOICES = (
    ("NOT_FOUND", "Not on the checklist"),
    ("RARITY", "Rarity"),
    ("ENDEMIC", "Endemic"),
    ("ESCAPED", "Escaped"),
    ("EXTINCT", "Extinct"),
    ("INTRODUCED", "Introduced"),
    ("PROVISIONAL", "Provisional"),
)
#: Sighting statuses the report leaves out.
_SKIPPED = frozenset({"notEstablished", "idUncertain", "domestic", "notAccepted"})
_SINGLE = (SightingTaxonType.SINGLE, SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES)


@dataclass(frozen=True, slots=True)
class StatusPlace:
    xml_id: str
    custom: bool  # the list's own checklist, not a built-in one
    species: list[Taxon]  # taxonomic order


def matches(choice: str, status: str | None) -> bool:
    """``ReportChoice.matches``."""
    if choice == "NOT_FOUND":
        return status is None
    if choice == "RARITY":
        return status in ("RARITY", "RARITY_FROM_INTRODUCED")
    return status == choice


def checklist_status(query_list: QueryList, checklists: Checklists, taxonomy: Taxonomy,
                     choice: str, resolver: Resolver | None = None,
                     ) -> list[StatusPlace]:  # fmt: skip
    """``showReport``: each place with a checklist (built-in or the list's own, not one
    merged from others), in the list's place order, with the species seen there or inside it
    (as species; a sp. or hybrid of several species is left out) that have that status."""
    resolve = resolver or Resolver(taxonomy)
    with_checklist: dict[str, list[str]] = {}  # place -> it and its parents with checklists

    def checklist_places(xml_id: str) -> list[str]:
        if xml_id not in with_checklist:
            parent = query_list.parent.get(xml_id)
            above = [] if parent is None else checklist_places(parent)
            has = checklists.checklist(taxonomy, xml_id) is not None
            with_checklist[xml_id] = [xml_id, *above] if has else above
        return with_checklist[xml_id]

    by_place: dict[str, dict[SightingTaxon, None]] = {}
    for sighting in query_list.sightings:
        if sighting.taxonomy_id is not None or sighting.location_xml_id is None:
            continue
        if sighting.status in _SKIPPED:
            continue
        for place in checklist_places(sighting.location_xml_id):
            by_place.setdefault(place, {})[sighting.taxon] = None
    found: dict[str, tuple[bool, dict[str, Taxon]]] = {}
    for place, taxa in by_place.items():
        checklist = checklists.checklist(taxonomy, place)
        if checklist is None or checklists.is_synthetic(place):
            continue
        for taxon in taxa:
            resolved = _as_species(resolve(taxon), taxonomy)
            if resolved is None or resolved.type not in _SINGLE:
                continue
            if matches(choice, checklist.status(resolved.sighting_taxon)):
                species = found.setdefault(place, (not checklist.built_in, {}))[1]
                species.setdefault(resolved.taxon.id, resolved.taxon)
    index = taxonomy_index(taxonomy)
    return [StatusPlace(place, found[place][0],
                        sorted(found[place][1].values(), key=lambda t: index[t.id]))
            for place in _tree_order(query_list) if place in found]  # fmt: skip


def _as_species(resolved: Resolved | None, taxonomy: Taxonomy) -> Resolved | None:
    if resolved is None:
        return None
    if resolved.smallest_type is not TaxonType.SPECIES:
        return resolved.parent_of_at_least_type(TaxonType.SPECIES).resolve_internal(taxonomy)
    return resolved


def _tree_order(query_list: QueryList) -> list[str]:
    """Places as ``appendChecklistIssues`` walks them: each root, then depth first."""
    children: dict[str | None, list[str]] = {}
    for xml_id, place in query_list.places.items():
        children.setdefault(place.parent, []).append(xml_id)
    order: list[str] = []
    stack = list(reversed(children.get(None, [])))
    while stack:
        xml_id = stack.pop()
        order.append(xml_id)
        stack.extend(reversed(children.get(xml_id, [])))
    return order

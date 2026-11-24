"""Localized names for a mapped taxonomy (AviList), derived from base (Clements) names.

Ported from Scythebill ``model/src/jvmMain/.../taxa/names/AviListNamesLoader.java``. For a
locale other than ``en`` and ``en_AVI`` (which use AviList's own names):

- a species that maps directly to exactly one base species gets that species' name;
- a family or order gets the name of the base family or order with the same scientific
  name (taxon IDs are never compared across the two taxonomies);
- everything else has no entry, so the mapped taxonomy's own name is used.
"""

from __future__ import annotations

from collections.abc import Mapping

from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import SightingTaxonType

OWN_NAME_LOCALES = frozenset({"en", "en_AVI"})


def mapped_names(
    mapped: MappedTaxonomy, locale: str, base_names: Mapping[str, str]
) -> dict[str, str]:
    """Names by mapped taxon ID for ``locale``, given the base names for that locale."""
    if locale in OWN_NAME_LOCALES or not base_names:
        return {}
    family_names: dict[str, str] = {}
    order_names: dict[str, str] = {}
    for base_taxon in mapped.base.walk():
        base_name = base_names.get(base_taxon.id)
        if base_name is None:
            continue
        if base_taxon.type is TaxonType.FAMILY:
            family_names[base_taxon.name] = base_name
        elif base_taxon.type is TaxonType.ORDER:
            order_names[base_taxon.name] = base_name

    names: dict[str, str] = {}
    for taxon in mapped.walk():
        name: str | None = None
        if taxon.type is TaxonType.SPECIES:
            mapping = mapped.exact_mapping(taxon)
            if mapping is not None and mapping.type is SightingTaxonType.SINGLE:
                target = mapped.base.get(mapping.id)
                if target is not None and target.type is TaxonType.SPECIES:
                    name = base_names.get(target.id)
        elif taxon.type is TaxonType.FAMILY:
            name = family_names.get(taxon.name)
        elif taxon.type is TaxonType.ORDER:
            name = order_names.get(taxon.name)
        if name is not None:
            names[taxon.id] = name
    return names

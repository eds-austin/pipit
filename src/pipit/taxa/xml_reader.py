"""Read Scythebill taxonomy XML: the bundled ``taxon.xml``, the AviList mapped taxonomy and
``.btxm`` extended taxonomies (the same format, also embedded in ``.bsxm`` files).

Ported from Scythebill ``model/src/commonMain/kotlin/com/scythebill/birdlist/model/xml/``
``XmlTaxonParsers.kt`` and ``XmlTaxonConstants.kt``, plus ``importMappedTaxa`` in
``model/src/jvmMain/.../xml/XmlTaxonImport.kt``.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO
from xml.etree import ElementTree

from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import IUCN_STATUSES, Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

NAMESPACE = "http://www.adamwiner.com/checklist/1.0"
_TAXON_ELEMENTS = {t.xml_name for t in TaxonType}
_METADATA_FIELDS = {
    "alternate-names",
    "alternate-common-names",
    "range",
    "miscellaneous",
    "status",
    "taxonomy",
}


class TaxonomyFormatError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_taxonomy(source: Path | IO[bytes]) -> Taxonomy:
    """A base or extended taxonomy. Mapping elements, if any, are an error."""
    taxonomy, mappings = _read(source, base=None)
    if mappings:
        raise TaxonomyFormatError(f"{taxonomy.id} has mappings but no base taxonomy")
    return taxonomy


def read_mapped_taxonomy(source: Path | IO[bytes], base: Taxonomy) -> MappedTaxonomy:
    """A mapped taxonomy (AviList) over ``base``: registers mappings, then disables
    every subtree without one, exactly as Scythebill's ``importMappedTaxa``."""
    taxonomy, mappings = _read(source, base=base)
    assert isinstance(taxonomy, MappedTaxonomy)
    taxonomy.set_mappings(mappings)
    taxonomy.disable_unmapped_taxa()
    return taxonomy


def _read(  # noqa: PLR0915
    source: Path | IO[bytes], base: Taxonomy | None
) -> tuple[Taxonomy, dict[Taxon, SightingTaxon]]:
    taxonomy: Taxonomy | None = None
    stack: list[Taxon] = []
    in_metadata = False
    mappings: dict[Taxon, SightingTaxon] = {}

    for event, element in ElementTree.iterparse(source, events=("start", "end")):
        name = _local(element.tag)
        if event == "start":
            if taxonomy is None:
                if name != "taxonomy":
                    raise TaxonomyFormatError(f"expected <taxonomy>, got <{name}>")
                attributes = element.attrib
                taxonomy_id = attributes.get("id", "")
                taxonomy_name = attributes.get("name", taxonomy_id)
                if base is None:
                    taxonomy = Taxonomy(
                        taxonomy_id,
                        taxonomy_name,
                        attributes.get("accountUrlFormat"),
                        attributes.get("accountLinkTitle"),
                    )
                else:
                    taxonomy = MappedTaxonomy(base, taxonomy_id, taxonomy_name)
                    taxonomy.account_url_format = attributes.get("accountUrlFormat")
                    taxonomy.account_link_title = attributes.get("accountLinkTitle")
            elif name == "metadata":
                in_metadata = True
            elif name in _TAXON_ELEMENTS and not in_metadata:
                attributes = element.attrib
                taxon = taxonomy.add(
                    attributes["id"],
                    TaxonType.from_xml_name(name),
                    attributes["name"],
                    stack[-1] if stack else None,
                )
                taxon.account_id = attributes.get("accountId")
                taxon.concept_id = attributes.get("conceptId")
                stack.append(taxon)
            continue

        # event == "end"
        assert taxonomy is not None
        text = element.text or ""
        if name == "metadata":
            in_metadata = False
        elif in_metadata and name in _METADATA_FIELDS:
            _set_metadata(stack[-1], name, text)
        elif name in _TAXON_ELEMENTS:
            stack.pop()
            element.clear()
        elif name == "common-name":
            stack[-1].common_name = text
        elif name == "additional-credit":
            taxonomy.additional_credits.append(text)
        elif name == "checklists":
            stack[-1].checklists = text
        elif name == "map":
            _put_mapping(mappings, stack[-1], SightingTaxon.single(text))
        elif name == "spmap":
            _put_mapping(mappings, stack[-1], SightingTaxon.sp(text.split(",")))
        elif name == "sspmap":
            taxon = stack[-1]
            prior = mappings.get(taxon)
            if prior is None or prior.type is not SightingTaxonType.SINGLE:
                raise TaxonomyFormatError(f"unexpected sspmap {text!r} on {taxon.id}")
            mappings[taxon] = SightingTaxon.with_secondary_subspecies(prior.id, text)
        elif name in ("nomap", "taxonomy"):
            pass
        else:
            raise TaxonomyFormatError(f"unexpected element <{name}>")

    if taxonomy is None:
        raise TaxonomyFormatError("no <taxonomy> element")
    return taxonomy, mappings


def _put_mapping(mappings: dict[Taxon, SightingTaxon], taxon: Taxon, value: SightingTaxon) -> None:
    if taxon in mappings:
        raise TaxonomyFormatError(f"second mapping for {taxon.id}")
    mappings[taxon] = value


def _set_metadata(taxon: Taxon, name: str, text: str) -> None:
    if name == "alternate-names":
        taxon.alternate_names.append(text)
    elif name == "alternate-common-names":
        taxon.alternate_common_names.append(text)
    elif name == "range":
        taxon.range = text
    elif name == "miscellaneous":
        taxon.miscellaneous = text
    elif name == "taxonomy":
        taxon.taxonomic_info = text
    elif name == "status":
        status = text.strip()
        if status not in IUCN_STATUSES:
            raise TaxonomyFormatError(f"unknown IUCN status {status!r} on {taxon.id}")
        taxon.status = status

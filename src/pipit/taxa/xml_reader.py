"""Read Scythebill taxonomy XML: the bundled ``taxon.xml``, the AviList mapped taxonomy and
``.btxm`` extended taxonomies (the same format, also embedded in ``.bsxm`` files).

Ported from Scythebill ``model/src/commonMain/kotlin/com/scythebill/birdlist/model/xml/``
``XmlTaxonParsers.kt`` and ``XmlTaxonConstants.kt``, plus ``importMappedTaxa`` in
``model/src/jvmMain/.../xml/XmlTaxonImport.kt``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import IUCN_STATUSES, Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

NAMESPACE = "http://www.adamwiner.com/checklist/1.0"
_TAXON_ELEMENTS = {t.xml_name for t in TaxonType}
_KNOWN_CHILDREN = {
    "common-name", "metadata", "checklists", "map", "spmap", "sspmap", "nomap",
    "additional-credit",
}  # fmt: skip
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


def own_text(element: Element) -> str:
    """All of an element's own text, as Scythebill's ``StringParser`` collects it: the text
    before, between and after child elements, but not the children's text."""
    return (element.text or "") + "".join(child.tail or "" for child in element)


def walk_events(element: Element) -> Iterator[tuple[str, Element]]:
    """("start", e) / ("end", e) events for an already-parsed element, like iterparse."""
    yield "start", element
    for child in element:
        yield from walk_events(child)
    yield "end", element


def _file_events(source: Path | IO[bytes]) -> Iterator[tuple[str, Element]]:
    yield from ElementTree.iterparse(source, events=("start", "end"))


def read_taxonomy(source: Path | IO[bytes]) -> Taxonomy:
    """A base or extended taxonomy. Mapping elements, if any, are an error."""
    taxonomy, mappings = _read(_file_events(source), base=None)
    if mappings:
        raise TaxonomyFormatError(f"{taxonomy.id} has mappings but no base taxonomy")
    return taxonomy


def read_mapped_taxonomy(source: Path | IO[bytes], base: Taxonomy) -> MappedTaxonomy:
    """A mapped taxonomy (AviList) over ``base``: registers mappings, then disables
    every subtree without one, exactly as Scythebill's ``importMappedTaxa``."""
    taxonomy, mappings = _read(_file_events(source), base=base)
    assert isinstance(taxonomy, MappedTaxonomy)
    taxonomy.set_mappings(mappings)
    taxonomy.disable_unmapped_taxa()
    return taxonomy


def embedded_taxonomy(element: Element, warnings: list[str]) -> Taxonomy:
    """An extended taxonomy embedded in a ``.bsxm`` file. Unknown elements are skipped
    and reported in ``warnings``, as Scythebill does."""
    taxonomy, mappings = _read(walk_events(element), base=None, warnings=warnings)
    if mappings:
        warnings.append(f"mappings in embedded taxonomy {taxonomy.id} ignored")
    return taxonomy


def _read(  # noqa: PLR0915
    events: Iterable[tuple[str, Element]],
    base: Taxonomy | None,
    warnings: list[str] | None = None,
) -> tuple[Taxonomy, dict[Taxon, SightingTaxon]]:
    """Strict unless ``warnings`` is given; then unknown elements are skipped."""
    taxonomy: Taxonomy | None = None
    stack: list[Taxon] = []
    in_metadata = False
    mappings: dict[Taxon, SightingTaxon] = {}
    skipping: Element | None = None

    for event, element in events:
        if skipping is not None:
            if event == "end" and element is skipping:
                skipping = None
            continue
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
            elif (
                warnings is not None
                and not in_metadata
                and stack
                and name not in _TAXON_ELEMENTS
                and name not in _KNOWN_CHILDREN
            ):
                warnings.append(f"unknown element <{name}> in taxonomy {taxonomy.id} skipped")
                skipping = element
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
        text = own_text(element)
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

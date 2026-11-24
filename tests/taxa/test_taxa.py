"""The taxon tree, sighting taxa, XML reading and the mapped-taxonomy rules, on a small
hand-made base taxonomy and a mapped view over it."""

from __future__ import annotations

import io

import pytest

from pipit.taxa.avilist_names import mapped_names
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxonomy, TaxonType, full_name, parent_of_at_least_type
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType
from pipit.taxa.xml_reader import TaxonomyFormatError, read_mapped_taxonomy, read_taxonomy

NS = 'xmlns="http://www.adamwiner.com/checklist/1.0"'

BASE = f"""<?xml version="1.0" encoding="UTF-8"?>
<taxonomy {NS} id="base2026" name="Base 2026" accountUrlFormat="https://e/{{id}}">
  <additional-credit>Thanks</additional-credit>
  <class name="Aves" id="classAve"><common-name>Birds</common-name>
    <order name="Testiformes" id="ordTes"><common-name>Testers</common-name>
      <family name="Testidae" id="famTes"><common-name>Test birds</common-name>
        <genus name="Testus" id="geTes">
          <species name="alpha" id="spA" accountId="alpha1" conceptId="AAAA0001">
            <common-name>Alpha Bird</common-name>
            <metadata>
              <status>VU</status>
              <range>everywhere</range>
              <alternate-common-names>Old Alpha - in part</alternate-common-names>
              <alternate-names>Testus alfa</alternate-names>
            </metadata>
            <group name="one" id="grA1"><common-name>Alpha Bird (One)</common-name>
              <subspecies name="x" id="sspA1x"/>
            </group>
            <group name="two" id="grA2"><common-name>Alpha Bird (Two)</common-name>
              <subspecies name="y" id="sspA2y"/>
            </group>
          </species>
          <species name="beta" id="spB"><common-name>Beta Bird</common-name>
            <subspecies name="b1" id="sspB1"/><subspecies name="b2" id="sspB2"/>
            <subspecies name="b3" id="sspB3"/>
          </species>
          <species name="gamma" id="spC"><common-name>Gamma Bird</common-name></species>
          <species name="delta" id="spD"><common-name>Delta Bird</common-name></species>
          <species name="epsilon" id="spE"><common-name>Epsilon Bird</common-name></species>
          <species name="phi" id="spF"><common-name>Phi Bird</common-name></species>
          <species name="eta" id="spG"><common-name>Eta Bird</common-name>
            <subspecies name="g1" id="sspG1"/><subspecies name="g2" id="sspG2"/>
            <subspecies name="g3" id="sspG3"/><subspecies name="g4" id="sspG4"/>
          </species>
        </genus>
      </family>
    </order>
  </class>
</taxonomy>
"""

MAPPED = f"""<?xml version="1.0" encoding="UTF-8"?>
<taxonomy {NS} id="mapped2026" name="Mapped 2026">
  <class name="Aves" id="mclassAve"><common-name>Birds</common-name>
    <order name="Testiformes" id="mordTes"><common-name>Testers</common-name>
      <family name="Testidae" id="mfamTes"><common-name>Test birds</common-name>
        <genus name="Testus" id="mgeTes">
          <species name="alpha" id="avA"><common-name>Alpha Bird</common-name>
            <map>spA</map>
            <subspecies name="x" id="avAx"><map>grA1</map></subspecies>
            <subspecies name="y" id="avAy"><map>grA2</map></subspecies>
            <subspecies name="z" id="avAz"><map>spA</map><sspmap>z</sspmap></subspecies>
          </species>
          <species name="beta" id="avB"><common-name>Beta Bird</common-name><map>spB</map>
            <subspecies name="b1" id="avB1"><map>sspB1</map></subspecies>
            <subspecies name="b2" id="avB2"><map>sspB2</map></subspecies>
            <subspecies name="b3" id="avB3"><map>sspB3</map></subspecies>
          </species>
          <species name="gammadelta" id="avCD"><common-name>Gamma-Delta Bird</common-name>
            <spmap>spD,spC</spmap>
          </species>
          <species name="phi" id="avF1"><common-name>Phi Bird</common-name><map>spF</map></species>
          <species name="phi2" id="avF2"><common-name>Phi 2</common-name><map>spF</map></species>
          <species name="eta" id="avG"><common-name>Eta Bird</common-name>
            <subspecies name="g1" id="avG1"><map>sspG1</map></subspecies>
            <subspecies name="g2" id="avG2"><map>sspG2</map></subspecies>
            <subspecies name="g3" id="avG3"><map>sspG3</map></subspecies>
            <subspecies name="g4" id="avG4"><map>sspG4</map></subspecies>
          </species>
        </genus>
        <genus name="Nullus" id="mgeNul">
          <species name="nihil" id="avZ"><common-name>Unmapped Bird</common-name></species>
        </genus>
      </family>
    </order>
  </class>
</taxonomy>
"""


@pytest.fixture
def base() -> Taxonomy:
    return read_taxonomy(io.BytesIO(BASE.encode()))


@pytest.fixture
def mapped(base: Taxonomy) -> MappedTaxonomy:
    return read_mapped_taxonomy(io.BytesIO(MAPPED.encode()), base)


def ids(resolved: Resolved | None) -> tuple[str, tuple[str, ...]] | None:
    if resolved is None:
        return None
    return resolved.type.value, resolved.sighting_taxon.ids


# ------------------------------------------------------------ tree and XML


def test_xml_fields(base: Taxonomy) -> None:
    assert base.id == "base2026"
    assert base.account_url_format == "https://e/{id}"
    assert base.additional_credits == ["Thanks"]
    alpha = base["spA"]
    assert (alpha.account_id, alpha.concept_id, alpha.status) == ("alpha1", "AAAA0001", "VU")
    assert alpha.range == "everywhere"
    assert alpha.alternate_common_names == ["Old Alpha - in part"]
    assert alpha.alternate_names == ["Testus alfa"]
    assert [child.id for child in alpha.children] == ["grA1", "grA2"]
    assert base.count(TaxonType.SPECIES) == 7
    assert [taxon.id for taxon in base.walk()][:5] == [
        "classAve", "ordTes", "famTes", "geTes", "spA"
    ]  # fmt: skip


def test_names_and_parents(base: Taxonomy) -> None:
    assert full_name(base["spA"]) == "Testus alpha"
    assert full_name(base["sspA1x"]) == "Testus alpha x"
    assert parent_of_at_least_type(base["sspA1x"], TaxonType.SPECIES).id == "spA"
    assert parent_of_at_least_type(base["spA"], TaxonType.SPECIES).id == "spA"


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        ('<species name="a" id="sp1"><metadata><status>XX</status></metadata></species>',
         "unknown IUCN status"),
        ('<species name="a" id="sp1"/><species name="b" id="sp1"/>', "duplicate taxon id"),
        ('<species name="a" id="sp1"><sspmap>z</sspmap></species>', "unexpected sspmap"),
        ('<species name="a" id="sp1"><colour/></species>', "unexpected element"),
    ],
)  # fmt: skip
def test_xml_errors(xml: str, message: str) -> None:
    document = f'<taxonomy {NS} id="t" name="t"><class name="A" id="c">{xml}</class></taxonomy>'
    with pytest.raises((TaxonomyFormatError, ValueError), match=message):
        if "sspmap" in xml:
            read_mapped_taxonomy(io.BytesIO(document.encode()), Taxonomy("b", "b"))
        else:
            read_taxonomy(io.BytesIO(document.encode()))


def test_mappings_without_base_are_rejected() -> None:
    document = (
        f'<taxonomy {NS} id="t" name="t"><class name="A" id="c"><map>x</map></class></taxonomy>'
    )
    with pytest.raises(TaxonomyFormatError, match="no base"):
        read_taxonomy(io.BytesIO(document.encode()))


# ------------------------------------------------------------ sighting taxa


def test_sighting_taxon_forms() -> None:
    assert SightingTaxon.sp(["b", "a", "b"]).ids == ("a", "b")
    assert SightingTaxon.possibly_sp(["a", "a"]) == SightingTaxon.single("a")
    with pytest.raises(ValueError, match="at least two"):
        SightingTaxon.sp(["a"])
    with pytest.raises(ValueError, match="no single id"):
        _ = SightingTaxon.hybrid(["a", "b"]).id
    ssp = SightingTaxon.with_secondary_subspecies("spA", "z")
    assert (ssp.type, ssp.id, ssp.subspecies) == (
        SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES, "spA", "z"
    )  # fmt: skip


def test_resolved_parents(base: Taxonomy) -> None:
    sp = SightingTaxon.sp(["sspB1", "sspB2"]).resolve_internal(base)
    assert sp.parent() == SightingTaxon.single("spB")
    assert sp.parent_of_at_least_type(TaxonType.SPECIES) == SightingTaxon.single("spB")
    mixed = SightingTaxon.sp(["sspA1x", "spC"]).resolve_internal(base)
    assert mixed.largest_type is TaxonType.SPECIES
    assert mixed.parent() == SightingTaxon.single("geTes")


# ------------------------------------------------------------ mapped taxonomy


def resolve(mapped: MappedTaxonomy, *base_ids: str) -> tuple[str, tuple[str, ...]] | None:
    taxon = SightingTaxon.single(base_ids[0]) if len(base_ids) == 1 else SightingTaxon.sp(base_ids)
    return ids(mapped.resolve_into(taxon))


def test_exact_and_group_mappings(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "spA") == ("single", ("avA",))
    assert resolve(mapped, "grA1") == ("single", ("avAx",))
    # An unmapped subspecies maps up to its group's counterpart.
    assert resolve(mapped, "sspA1x") == ("single", ("avAx",))


def test_lump_is_a_partial_mapping(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "spC") == ("single", ("avCD",))
    assert resolve(mapped, "spD") == ("single", ("avCD",))


def test_duplicate_exact_mappings_become_a_sp(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "spF") == ("sp", ("avF1", "avF2"))


def test_unmapped_taxon_has_no_counterpart(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "spE") is None


def test_more_than_three_subspecies_raise_to_species(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "spG") == ("single", ("avG",))


def test_family_maps_through_its_first_species(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "famTes") == ("single", ("mfamTes",))


def test_sp_of_some_or_all_children(mapped: MappedTaxonomy) -> None:
    assert resolve(mapped, "sspB1", "sspB2") == ("sp", ("avB1", "avB2"))
    assert resolve(mapped, "sspB1", "sspB2", "sspB3") == ("single", ("avB",))


def test_secondary_subspecies(mapped: MappedTaxonomy) -> None:
    resolved = mapped.resolve_into(SightingTaxon.with_secondary_subspecies("spA", "z"))
    assert ids(resolved) == ("single", ("avAz",))
    unknown = mapped.resolve_into(SightingTaxon.with_secondary_subspecies("spA", "nope"))
    assert ids(unknown) == ("single", ("avA",))


def test_mapping_back_to_base(mapped: MappedTaxonomy) -> None:
    assert mapped.mapping(mapped["avCD"]) == SightingTaxon.sp(["spC", "spD"])
    assert mapped.mapping(mapped["avAz"]) == SightingTaxon.with_secondary_subspecies("spA", "z")
    # No exact mapping: synthesized from children (ssp. mappings skipped).
    assert mapped.mapping(mapped["avG"]) == SightingTaxon.sp(["sspG1", "sspG2", "sspG3", "sspG4"])
    assert mapped.mapping(mapped["mfamTes"]) == SightingTaxon.single("famTes")
    assert mapped.mapping(mapped["avZ"]) is None
    # A mapped sp. covering all of a base parent's children becomes that parent.
    assert mapped.mapping_of(SightingTaxon.sp(["avB1", "avB2", "avB3"])) == SightingTaxon.single(
        "spB"
    )


def test_unmapped_subtrees_are_disabled(mapped: MappedTaxonomy) -> None:
    assert mapped["avZ"].disabled
    assert mapped["mgeNul"].disabled
    assert not mapped["mgeTes"].disabled
    assert not mapped["mfamTes"].disabled


def test_mapped_names(mapped: MappedTaxonomy) -> None:
    base_names = {"spA": "Alphavogel", "spC": "Gammavogel", "famTes": "Testvögel"}
    names = mapped_names(mapped, "de", base_names)
    assert names == {"avA": "Alphavogel", "mfamTes": "Testvögel"}  # avCD maps to a sp.
    assert mapped_names(mapped, "en_AVI", base_names) == {}

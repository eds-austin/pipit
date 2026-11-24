"""Reading and writing .bsxm files exactly as Scythebill does.

Expected outputs were produced by Scythebill itself (tools/oracle/RoundTrip.java: its own
load, upgrades and save): ``edge_cases.expected.bsxm`` from ``edge_cases.bsxm``, and
``large_sample.scythebill.bsxm.gz`` from Scythebill's ``large_sample.bsxm``.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from pipit.bsxm.reader import BsxmError, VersionTooNewError, read_bsxm
from pipit.bsxm.upgrades import (
    ONE_TIME_UPGRADERS,
    UpgradeRefusedError,
    apply_upgrades,
    check_upgradable,
    is_photo_link,
)
from pipit.bsxm.writer import XmlOut, normalized_checklist_codes, write_bsxm
from pipit.domain.report import Link
from pipit.taxa.model import Taxonomy, TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bsxm"
BASE = "clements2026"


class AnyTaxon:
    """Accepts every taxon ID (format tests don't need the data pack)."""

    def __contains__(self, item: object) -> bool:
        return True


def round_trip(data: bytes) -> bytes:
    result = read_bsxm(data, BASE, AnyTaxon())
    check_upgradable(result.report, BASE)
    apply_upgrades(result.report)
    return write_bsxm(result.report)


def test_edge_cases_match_scythebill() -> None:
    source = (FIXTURES / "edge_cases.bsxm").read_bytes()
    expected = (FIXTURES / "edge_cases.expected.bsxm").read_bytes()
    assert round_trip(source) == expected


def test_scythebill_output_is_a_fixed_point() -> None:
    expected = gzip.decompress((FIXTURES / "large_sample.scythebill.bsxm.gz").read_bytes())
    assert round_trip(expected) == expected


def test_second_load_matches_scythebill_too() -> None:
    """Scythebill's own output is not always a fixed point: a latitude of -0.0000000 reads
    back as 0, and an area written as 0.0 is dropped. Its second pass is recorded too."""
    first = (FIXTURES / "edge_cases.expected.bsxm").read_bytes()
    second = (FIXTURES / "edge_cases.expected2.bsxm").read_bytes()
    assert round_trip(first) == second
    assert round_trip(second) == second


def test_edge_case_warnings() -> None:
    result = read_bsxm((FIXTURES / "edge_cases.bsxm").read_bytes(), BASE, AnyTaxon())
    text = "\n".join(result.warnings)
    for expected in ("<futureThing>", "missingLoc", "spaceship", "nowhere2", "not a uri"):
        assert expected in text


def _minimal(body: str, version: str = "21.5.0", taxonomy: str = BASE) -> bytes:
    upgrades = "".join(
        f"<one-time-upgrade>{name}</one-time-upgrade>" for name in ONE_TIME_UPGRADERS
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<report-set version="{version}" '
        f'taxonomy="{taxonomy}"><locations><location id="a" name="A"/></locations>'
        f"{body}{upgrades}</report-set>"
    ).encode()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('<sighting taxon="x" loc="a" date="garbage"/>', "Abbreviation|invalid syntax"),
        ('<sighting sp="x" loc="a"/>', "at least two"),
        ('<sighting loc="a"/>', "none of the taxon"),
        ('<sighting taxon="x" taxonomy="nope" loc="a"/>', "invalid taxonomy"),
        ('<visit-info loc="a" date="bad" observationType="historical"/>', "invalid syntax"),
        ('<user id="u"/>', "neither a name"),
        ('<trip id="t" startDate="2025"/>', "endDate"),
    ],
)
def test_files_scythebill_refuses_are_refused(body: str, message: str) -> None:
    with pytest.raises(BsxmError, match=message):
        read_bsxm(_minimal(body), BASE, AnyTaxon())


def test_unknown_base_taxon_is_refused() -> None:
    with pytest.raises(BsxmError, match="unknown taxon"):
        read_bsxm(_minimal('<sighting taxon="spNope" loc="a"/>'), BASE, {"spAnaspla"})


def test_renamed_taxon_hack() -> None:
    data = _minimal('<sighting taxon="sspCarpo3davwal" loc="a"/>')
    result = read_bsxm(data, BASE, {"sspCarpo3eoswal"})
    assert result.report.sightings[0].taxon.id == "sspCarpo3eoswal"


def test_newer_files_are_refused() -> None:
    with pytest.raises(VersionTooNewError):
        read_bsxm(_minimal("", version="99.0.0"), BASE, AnyTaxon())


def test_not_a_list() -> None:
    with pytest.raises(BsxmError, match="not a Scythebill list"):
        read_bsxm(b"<taxonomy/>", BASE, AnyTaxon())
    with pytest.raises(BsxmError, match="well-formed"):
        read_bsxm(b"<report-set>", BASE, AnyTaxon())


def test_utf8_bom_is_ignored() -> None:
    data = _minimal("")
    assert round_trip(b"\xef\xbb\xbf" + data) == round_trip(data)


@pytest.mark.parametrize(
    ("version", "taxonomy", "upgrades", "message"),
    [
        ("21.5.0", "clements2025", ONE_TIME_UPGRADERS, "taxonomy"),
        ("15.0.0", BASE, ONE_TIME_UPGRADERS, "old Scythebill"),
        ("21.5.0", BASE, ONE_TIME_UPGRADERS[1:], "TaxonFixesForIoc101"),
    ],
)
def test_upgrades_only_scythebill_can_do_are_refused(
    version: str, taxonomy: str, upgrades: tuple[str, ...], message: str
) -> None:
    names = "".join(f"<one-time-upgrade>{name}</one-time-upgrade>" for name in upgrades)
    data = (
        f'<report-set version="{version}" taxonomy="{taxonomy}"><locations/>{names}</report-set>'
    ).encode()
    report = read_bsxm(data, BASE, AnyTaxon()).report
    with pytest.raises(UpgradeRefusedError, match=message):
        check_upgradable(report, BASE)


def test_ported_upgrade_is_applied_and_recorded() -> None:
    names = "".join(
        f"<one-time-upgrade>{name}</one-time-upgrade>" for name in ONE_TIME_UPGRADERS[:-1]
    )
    data = (
        '<report-set version="21.0.0" taxonomy="clements2026"><locations/>'
        '<trip id="t" startDate="2025" endDate="2025"><link>https://x.org/a.png</link>'
        f"<link>https://ebird.org/a.png</link></trip>{names}</report-set>"
    ).encode()
    report = read_bsxm(data, BASE, AnyTaxon()).report
    check_upgradable(report, BASE)
    assert apply_upgrades(report) == ["moveImageTripLinksToPhotos"]
    assert [photo.uri for photo in report.trips[0].photos] == ["https://x.org/a.png"]
    assert [link.uri for link in report.trips[0].links] == ["https://ebird.org/a.png"]
    assert report.one_time_upgrades[-1] == "moveImageTripLinksToPhotos"


@pytest.mark.parametrize(
    ("uri", "photo"),
    [("https://www.flickr.com/photos/me/123", True), ("https://flickr.com/photos/me", False),
     ("https://macaulaylibrary.org/asset/12345", True), ("https://x.org/a.HEIC", True),
     ("https://www.instagram.com/a.jpg", False), ("file:/x/a.nef", True),
     ("file:/x/a.xmp", False), ("file:/x/README", False), ("https://x.org/", False)],
)  # fmt: skip
def test_photo_links(uri: str, photo: bool) -> None:
    assert is_photo_link(Link(uri)) is photo


def test_writer_escaping_and_layout() -> None:
    out = XmlOut()
    out.start("a")
    out.attribute("q", 'x"<>&\t\n\x01é🐦')
    out.start("b")
    out.text('t<>&"\x7f')
    out.end("b")
    out.start("c")
    out.end("c")
    out.end("a")
    assert out.getvalue() == (
        '<a q="x&quot;&lt;&gt;&amp;&#x9;\n&#xe9;&#x1f426;">\n'
        '  <b>t&lt;&gt;&amp;"&#x7f;</b>\n  <c/>\n</a>'
    )


def test_checklist_codes_are_normalized_like_scythebill() -> None:
    taxonomy = Taxonomy("t", "t")
    root = taxonomy.add("c", TaxonType.CLASS, "C", None)
    taxon = taxonomy.add("s", TaxonType.SPECIES, "s", root)
    taxon.checklists = "KE,TZ(I),IN(V),ID,XX(?)"
    assert normalized_checklist_codes(taxon) == [
        "ID-Asia", "ID-Australasia", "IN(R)", "KE", "TZ(I)", "XX"
    ]  # fmt: skip
    taxon.checklists = "BR"
    assert normalized_checklist_codes(taxon) == ["BR(E)"]
    taxon.status = "EW"
    taxon.checklists = "RU,FR(E)"
    assert normalized_checklist_codes(taxon) == ["FR(EX)", "RU-Asia(EX)", "RU-Europe(EX)"]

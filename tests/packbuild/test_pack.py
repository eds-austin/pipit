"""Data pack: source readers, building, validation, loading and the CLI."""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from pathlib import Path
from typing import Any

import pytest

from pipit.datapack.pack import DataPack, PackError
from pipit.packbuild import readers
from pipit.packbuild.build import BuildError, upgrade_rows
from pipit.packbuild.cli import main as cli_main
from pipit.packbuild.readers import UpgradeRow
from pipit.packbuild.sources import ScythebillSources
from pipit.packbuild.validate import validate

# ---------------------------------------------------------------- readers


def test_names_and_checklists(tmp_path: Path) -> None:
    names = tmp_path / "names.csv"
    names.write_text('"spA","Alpha, the bird"\n"spB","Béta"\n', encoding="utf-8")
    assert list(readers.read_names(names)) == [("spA", "Alpha, the bird"), ("spB", "Béta")]

    checklist = tmp_path / "XX.csv"
    checklist.write_text('"Name","ID","Status"\n"Alpha","spA",""\n"Beta","spB","rarity"\n')
    assert [(e.taxon_id, e.status) for e in readers.read_checklist(checklist)] == [
        ("spA", ""), ("spB", "rarity")
    ]  # fmt: skip
    checklist.write_text('"Name","Id"\n')
    with pytest.raises(readers.ReadError, match="header"):
        readers.read_checklist(checklist)


def test_transpose(tmp_path: Path) -> None:
    path = tmp_path / "x.transpose"
    path.write_text("spA=US,CA\nspB/rarity=GB-ENG\n\n")
    assert list(readers.read_transpose(path)) == [
        ("spA", "", ["US", "CA"]), ("spB", "rarity", ["GB-ENG"])
    ]  # fmt: skip


def test_properties(tmp_path: Path) -> None:
    path = tmp_path / "p.properties"
    path.write_text("# comment\n\nNORTH_AMERICA = Nordamerika\nA=b = c\n", encoding="utf-8")
    assert readers.read_properties(path) == [("NORTH_AMERICA", "Nordamerika"), ("A", "b = c")]
    path.write_text("A = \\u00e9\n")
    with pytest.raises(readers.ReadError, match="escapes"):
        readers.read_properties(path)


def test_upgrade_rows_follow_the_mapping_loader() -> None:
    rows = [
        UpgradeRow("SAME", "spA", "spA", "", ""),
        UpgradeRow("SPLT", "spB", "spB2", "", ""),
        UpgradeRow("MULT", "spC", "spC1,spC2", "", ""),
        UpgradeRow("NEW", "", "spN", "", ""),  # no from id: ignored
        UpgradeRow("WARN", "spW", "spW", "", ""),
    ]
    mappings, warnings = upgrade_rows("clements2025", rows)
    assert mappings == [
        ("clements2025", "spA", "SAME", None),
        ("clements2025", "spB", "SPLT", "spB2"),
        ("clements2025", "spC", "MULT", "spC1,spC2"),
        ("clements2025", "spW", "WARN", None),
    ]
    assert warnings == [("clements2025", "spW")]
    with pytest.raises(BuildError, match="two mappings"):
        upgrade_rows("x", [rows[0], rows[0]])


def _java_utf(text: str) -> bytes:
    """DataOutputStream.writeUTF: modified UTF-8 with NUL as C0 80 and surrogates apart."""
    encoded = bytearray()
    for unit in struct.unpack(f"<{len(text.encode('utf-16-le')) // 2}H", text.encode("utf-16-le")):
        if unit == 0:
            encoded += b"\xc0\x80"
        else:
            encoded += chr(unit).encode("utf-8", errors="surrogatepass")
    return struct.pack(">H", len(encoded)) + bytes(encoded)


def _wkb_multipolygon() -> bytes:
    return struct.pack("<BI", 1, 6) + struct.pack("<I", 0)


def test_mapbin(tmp_path: Path) -> None:
    data = struct.pack(">ii", readers.MAPBIN_MAGIC, readers.MAPBIN_VERSION)
    data += struct.pack(">i", 2) + _java_utf("NAME") + _java_utf("CODE")
    data += struct.pack(">i", 1)
    data += b"\x01" + _java_utf("Nüll\0🐦") + b"\x00"  # NAME set, CODE null
    wkb = _wkb_multipolygon()
    data += struct.pack(">i", len(wkb)) + wkb + struct.pack(">i", 0)
    path = tmp_path / "layer.mapbin"
    path.write_bytes(data)
    [feature] = readers.read_mapbin(path)
    assert feature.attributes == {"NAME": "Nüll\0🐦", "CODE": None}
    assert readers.wkb_type(feature.geometry) == 6
    assert feature.water is None
    path.write_bytes(data + b"x")
    with pytest.raises(readers.ReadError, match="trailing"):
        readers.read_mapbin(path)


# ---------------------------------------------------------------- loader errors


def test_rejects_files_that_are_not_packs(tmp_path: Path) -> None:
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).execute("CREATE TABLE t(x)").connection.close()
    with pytest.raises(PackError, match="not a Pipit data pack"):
        DataPack(other)
    with pytest.raises(PackError, match="no data pack"):
        DataPack(tmp_path / "missing.sqlite")


# ---------------------------------------------------------------- built from Scythebill


@pytest.mark.scythebill
def test_built_pack_validates_against_sources(built_pack: Path, scythebill: Path) -> None:
    report = validate(built_pack, ScythebillSources(scythebill))
    assert report.ok, report.errors
    assert report.facts["size_mb"] < 120  # type: ignore[operator]
    assert report.facts["taxa"]["clements2026"]["species"] == 11250  # type: ignore[index]


@pytest.mark.scythebill
def test_build_is_deterministic(built_pack: Path, scythebill: Path, tmp_path: Path) -> None:
    from pipit.packbuild.build import build_pack

    again = build_pack(ScythebillSources(scythebill), tmp_path)
    first = hashlib.sha256(built_pack.read_bytes()).hexdigest()
    assert hashlib.sha256(again.read_bytes()).hexdigest() == first
    assert not list(tmp_path.glob("*.building"))


@pytest.mark.scythebill
def test_pack_tree_equals_the_xml(pack: Any, scythebill: Path) -> None:
    """Loading from the pack gives the same taxa, fields and mappings as the XML."""
    from pipit.packbuild.build import load_taxonomies

    from_xml = load_taxonomies(ScythebillSources(scythebill))
    base, avilist = pack.load_base_and_avilist()
    fields = (
        "id", "type", "name", "common_name", "account_id", "concept_id", "status", "range",
        "taxonomic_info", "miscellaneous", "alternate_names", "alternate_common_names",
        "disabled",
    )  # fmt: skip
    for loaded, parsed in ((base, from_xml.base), (avilist, from_xml.avilist)):
        loaded_taxa = list(loaded.walk())
        parsed_taxa = list(parsed.walk())
        assert len(loaded_taxa) == len(parsed_taxa)
        for a, b in zip(loaded_taxa, parsed_taxa, strict=True):
            assert [getattr(a, f) for f in fields] == [getattr(b, f) for f in fields], a.id
            assert (a.parent.id if a.parent else None) == (b.parent.id if b.parent else None)
    assert avilist.exact_mappings() == from_xml.avilist.exact_mappings()


@pytest.mark.scythebill
def test_pack_queries(pack: Any) -> None:
    assert pack.pack_id == "2026.1"
    regions = pack.checklist_regions("clements2026")
    assert len(regions) == 520 and "US-CA" in regions
    california = pack.checklist("clements2026", "US-CA")
    assert {row.status for row in california} <= {"", "rarity", "introduced", "extinct",
                                                  "endemic", "escaped", "provisional",
                                                  "rarity-from-introduced"}  # fmt: skip
    assert "de" in pack.locales()
    assert pack.names("de")["spStrutcam"] == "Strauß"
    same = dict((f, t) for f, _, t in pack.iter_upgrade_mappings("clements2025"))
    assert same["spStrutcam"] == "spStrutcam"


@pytest.mark.scythebill
def test_cli_validates_a_pack(built_pack: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["--validate", str(built_pack), "--no-sources"]) == 0
    assert capsys.readouterr().out.startswith("OK")

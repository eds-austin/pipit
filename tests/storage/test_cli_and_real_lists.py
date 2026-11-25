"""The pipit-list command, and real lists checked against the data pack.

The ``private`` test reads Eric's own list through ``PIPIT_PRIVATE_BSXM`` (never copied);
set ``PIPIT_PRIVATE_EXPECTED`` to Scythebill's re-save of it (tools/oracle/RoundTrip.java)
to require a byte-for-byte match.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import pytest

from pipit.storage.cli import main
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bsxm"


@pytest.mark.scythebill
def test_command_line_flow(
    built_pack: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "large.bsxm"
    source.write_bytes(gzip.decompress((FIXTURES / "large_sample.scythebill.bsxm.gz").read_bytes()))
    target = tmp_path / "large.pipit"
    pack = ["--pack", str(built_pack), "--backups", str(tmp_path / "backups")]
    assert main([*pack, "import", str(source), str(target)]) == 0
    assert "imported 30000 sightings" in capsys.readouterr().out
    assert main([*pack, "check", str(target)]) == 0
    assert main([*pack, "export", str(target), str(tmp_path / "out.bsxm")]) == 0
    assert (tmp_path / "out.bsxm").read_bytes() == source.read_bytes()
    assert main([*pack, "backup", str(target)]) == 0
    assert main([*pack, "undo", str(target)]) == 0
    assert "nothing to undo" in capsys.readouterr().out
    assert main([*pack, "import", str(source), str(target)]) == 1  # never overwrites


@pytest.mark.scythebill
def test_edge_cases_need_every_taxon_in_the_pack(pack: object, tmp_path: Path) -> None:
    """The edge-case file uses real 2026 taxa: it imports against the real pack."""
    connection = pack.connection  # type: ignore[attr-defined]
    base = pack.base_taxonomy_id  # type: ignore[attr-defined]
    ids = {
        row[0] for row in connection.execute("SELECT id FROM taxa WHERE taxonomy_id = ?", (base,))
    }
    result = import_bsxm(FIXTURES / "edge_cases.bsxm", tmp_path / "e.pipit", base, ids)
    assert result.sightings == 13


@pytest.mark.private
@pytest.mark.scythebill
def test_private_list_round_trips(pack: object, tmp_path: Path) -> None:
    configured = os.environ.get("PIPIT_PRIVATE_BSXM")
    if not configured:
        pytest.skip("set PIPIT_PRIVATE_BSXM to run")
    source = Path(configured)
    base = pack.base_taxonomy_id  # type: ignore[attr-defined]
    ids = {
        row[0]
        for row in pack.connection.execute(  # type: ignore[attr-defined]
            "SELECT id FROM taxa WHERE taxonomy_id = ?", (base,)
        )
    }
    predefined = pack.predefined_locations()  # type: ignore[attr-defined]
    first = import_bsxm(source, tmp_path / "private.pipit", base, ids, predefined)
    with ListDatabase.open(first.list_path) as opened:
        export_bsxm(opened, tmp_path / "once.bsxm")
    once = (tmp_path / "once.bsxm").read_bytes()
    expected = os.environ.get("PIPIT_PRIVATE_EXPECTED")
    if expected:
        assert once == Path(expected).read_bytes()
    second = import_bsxm(tmp_path / "once.bsxm", tmp_path / "again.pipit", base, ids, predefined)
    with ListDatabase.open(second.list_path) as opened:
        export_bsxm(opened, tmp_path / "twice.bsxm")
    assert (tmp_path / "twice.bsxm").read_bytes() == once  # a fixed point

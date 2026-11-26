"""eBird My Data imports exactly as Scythebill's (tools/oracle/ImportOracle.java: the
importer and ImportController's steps with the choices made in advance), on the made-up
exports in tests/fixtures/imports: the list each case imports into must come out
byte-identical, with the same counts along the way. Each import is also stored in a Pipit
list, which must then export the same, and undo must restore the list exactly."""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pipit.bsxm.writer import write_bsxm
from pipit.imports.commit import store
from pipit.imports.formats import open_source
from pipit.imports.session import ImportOutcome, ImportRefusedError, ImportRun
from pipit.query.checklists import Checklists
from pipit.query.model import load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.storage.repository import load_report
from pipit.taxa.sighting_taxon import SightingTaxon

FIXTURES = Path(__file__).parents[1] / "fixtures"
IMPORTS = FIXTURES / "imports"
ORACLE = FIXTURES / "oracle" / "imports"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


@dataclass
class Imported:
    summary: dict[str, Any]
    database: ListDatabase
    run: ImportRun | None = None
    outcome: ImportOutcome | None = None


def run_case(pack: Any, case: dict[str, Any], base: Path, tmp_path: Path) -> Imported:
    """``_run_case``; a refusal at any step is ``{"error": true}``, as ImportOracle writes."""
    try:
        return _run_case(pack, case, base, tmp_path)
    except ImportRefusedError:
        return Imported({"error": True}, ListDatabase.open(tmp_path / f"{case['name']}.pipit"))


def _run_case(pack: Any, case: dict[str, Any], base: Path, tmp_path: Path) -> Imported:
    """The steps ImportOracle takes, with the case's choices; the summary it writes."""
    result = import_bsxm(base / case["list"], tmp_path / f"{case['name']}.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    database = ListDatabase.open(result.list_path)
    connection = database.connection
    clements, avilist = pack.load_base_and_avilist()
    taxonomy = avilist if case.get("display") == "avilist" else clements
    run = ImportRun(load_report(connection), open_source(base / case["file"], case["format"]),
                    taxonomy=taxonomy,
                    pack=pack, checklists=Checklists(pack, connection,
                                                     load_query_list(connection)))  # fmt: skip
    summary: dict[str, Any] = {}
    run.check()
    if run.source.mass_export:
        dates = run.dates()
        summary["newDates"] = len(dates.new)
        summary["datesInFile"] = dates.in_file
        if 0 < len(dates.new) < dates.in_file and case.get("onlyNewDates", True):
            run.only_dates(dates.new)
    left = run.read_places_and_taxa()
    summary["taxaToResolve"] = list(left)
    summary["resolvedTaxa"] = run.resolved_taxa
    run.resolve({key: SightingTaxon.single(taxon) for key, taxon in case.get("taxa", {}).items()})
    duplicates = run.read_sightings()
    counts = run.counts
    summary.update(sightingsFound=counts.found, failed=counts.failed, merged=counts.merged,
                   spuhsDropped=counts.spuhs_dropped, imported=len(run.imports),
                   duplicatesFlagged=duplicates)  # fmt: skip
    outcome = run.finish(case.get("duplicates", "importAll"))
    summary.update(
        removed=len(outcome.removed),
        added=len(outcome.added),
        spToResolve=["/".join(taxon.ids) for taxon in outcome.sp_to_resolve],
    )
    return Imported(summary, database, run, outcome)


def _expected(oracle: Path, name: str) -> bytes:
    zipped = oracle / f"{name}.bsxm.gz"
    if zipped.exists():
        return gzip.decompress(zipped.read_bytes())
    return (oracle / f"{name}.bsxm").read_bytes()


def check_case(pack: Any, case: dict[str, Any], base: Path, oracle: Path,
               tmp_path: Path) -> list[str]:  # fmt: skip
    """What differs from Scythebill (by name only, for private lists)."""
    imported = run_case(pack, case, base, tmp_path)
    expected = json.loads((oracle / f"{case['name']}.json").read_text())
    problems = [] if imported.summary == expected else ["counts"]
    if imported.run is None or imported.outcome is None:
        imported.database.close()
        return problems
    before = write_bsxm(load_report(imported.database.connection))
    result = write_bsxm(imported.run.report)
    if result != _expected(oracle, case["name"]):
        problems.append("list")
    database = imported.database
    store(database, imported.run, imported.outcome, "Import")
    if write_bsxm(load_report(database.connection)) != result:
        problems.append("stored")
    database.undo()
    if write_bsxm(load_report(database.connection)) != before:
        problems.append("undo")
    database.close()
    return problems


CASES = _jsonl(IMPORTS / "cases.jsonl")


@pytest.mark.scythebill
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_imports_match_scythebill(pack: Any, tmp_path: Path, case: dict[str, Any]) -> None:
    assert check_case(pack, case, IMPORTS, ORACLE, tmp_path) == []


@pytest.mark.private
def test_real_list_imports(pack: Any, tmp_path: Path) -> None:
    """``PIPIT_PRIVATE_IMPORT``: a folder with cases.jsonl (made like the fixtures', with
    tools/oracle/my_data_from_list.py's file of Eric's list), and ImportOracle's output for
    them in ``out/``. Only the names of differing cases are reported."""
    folder = os.environ.get("PIPIT_PRIVATE_IMPORT")
    if not folder:
        pytest.skip("set PIPIT_PRIVATE_IMPORT to run")
    base = Path(folder)
    differing = {}
    for case in _jsonl(base / "cases.jsonl"):
        problems = check_case(pack, case, base, base / "out", tmp_path)
        if problems:
            differing[case["name"]] = problems
    assert differing == {}

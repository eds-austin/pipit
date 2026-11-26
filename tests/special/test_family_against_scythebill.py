"""The family report's counts exactly as Scythebill's (tools/oracle/PrintOracle.java's family
mode: FamilyReportPanel's computation with default preferences, on
tests/fixtures/bsxm/trip_report.bsxm): the checklist's places, and each order's, family's and
genus's seen and possible species, in both taxonomies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext, parse_query
from pipit.query.model import load_query_list
from pipit.special.family import FamilyReport, family_report
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
FAMILY = FIXTURES / "oracle" / "family"
CASES = [json.loads(line) for line in (FAMILY / "cases.jsonl").read_text().splitlines()
         if line.strip()]  # fmt: skip


@pytest.fixture(scope="module")
def reports(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    folder = tmp_path_factory.mktemp("family")
    result = import_bsxm(FIXTURES / "bsxm" / "trip_report.bsxm", folder / "list.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    database = ListDatabase.open(result.list_path)
    query_list = load_query_list(database.connection)
    checklists = Checklists(pack, database.connection, query_list)
    clements, avilist = pack.load_base_and_avilist()
    contexts = {name: EngineContext(query_list, taxonomy, TaxonType.SPECIES)
                for name, taxonomy in (("clements", clements), ("avilist", avilist))}  # fmt: skip

    def run(case: dict[str, Any]) -> FamilyReport:
        query = parse_query(case["query"], query_list)
        return family_report(contexts[case["display"]], checklists, query)

    yield run
    database.close()


def summary(report: FamilyReport, name: str) -> dict[str, Any]:
    found: dict[str, Any] = {"name": name, "scope": sorted(report.scope.places),
                             "checklist": report.scope.checklist is not None}  # fmt: skip
    for level in ("ORDER", "FAMILY", "GENUS"):
        totals = report.totals(level)
        found[level] = [[group.group.id, group.seen, group.total] for group in totals.groups]
        found["seen"] = totals.seen_species
        found["total"] = totals.total_species
    return found


@pytest.mark.scythebill
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_family_report_matches_scythebill(reports: Any, case: dict[str, Any]) -> None:
    expected = json.loads((FAMILY / f"{case['name']}.json").read_text())
    found = summary(reports(case), case["name"])
    for level in ("ORDER", "FAMILY", "GENUS"):
        differing = [row for row in found[level] if row not in expected[level]]
        missing = [row for row in expected[level] if row not in found[level]]
        assert (differing[:5], missing[:5]) == ([], []), level
    assert found == expected

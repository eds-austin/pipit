"""Scythebill CSV exports exactly as Scythebill's Save as Scythebill CSV writes them
(tools/oracle/PrintOracle.java's csv mode: FullReportExport as ScythebillCsvExportAction
runs it), on the 30 reference queries in queries.bsxm and everything (both taxonomies, every
depth, Excel-compatible) in it, trip_report.bsxm and edge_cases.bsxm. Byte-identical."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from pipit.csvio.scythebill_csv import export, load_csv_data
from pipit.output.print_html import list_place_names, run_report_query
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
CSV = FIXTURES / "oracle" / "csv"
LISTS = [("queries", "cases"), ("trip_report", "cases.everything"),
         ("edge_cases", "cases.everything")]  # fmt: skip


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


class Exporter:
    def __init__(self, pack: Any, bsxm: Path, tmp_path: Path) -> None:
        result = import_bsxm(bsxm, tmp_path / "list.pipit", pack.base_taxonomy_id,
                             pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
        self.database = ListDatabase.open(result.list_path)
        connection = self.database.connection
        self.query_list = load_query_list(connection)
        self.checklists = Checklists(pack, connection, self.query_list)
        self.places = list_place_names(self.query_list, self.checklists)
        self.data = load_csv_data(connection)
        self.clements, self.avilist = pack.load_base_and_avilist()
        self.predefined = pack.predefined_locations()

    def export(self, case: dict[str, Any]) -> bytes:
        taxonomy = self.avilist if case["display"] == "avilist" else self.clements
        context = EngineContext(self.query_list, taxonomy, TaxonType[case["depth"].upper()],
                                users=frozenset(self.data.users))  # fmt: skip
        _query, results, _root = run_report_query(context, self.checklists,
                                                  json.dumps(case["query"]), self.data.users,
                                                  only_countable=False)  # fmt: skip
        return export(results, self.query_list, self.places, self.data, self.predefined,
                      excel_compatible=case.get("excel", False))  # fmt: skip


@pytest.mark.scythebill
@pytest.mark.parametrize(("bsxm", "cases"), LISTS)
def test_exports_match_scythebill(pack: Any, tmp_path: Path, bsxm: str, cases: str) -> None:
    exporter = Exporter(pack, FIXTURES / "bsxm" / f"{bsxm}.bsxm", tmp_path)
    expected = {line["name"]: line["files"] for line in _jsonl(CSV / f"{bsxm}.jsonl")}
    differing = []
    for case in _jsonl(CSV / f"{cases}.jsonl"):
        data = exporter.export(case)
        got = [{"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]
        if got != expected[case["name"]]:
            differing.append(case["name"])
    assert differing == []


@pytest.mark.private
def test_real_list_exports(pack: Any, tmp_path: Path) -> None:
    """Eric's list (never copied): ``PIPIT_PRIVATE_BSXM``, and in ``PIPIT_PRIVATE_CSV``
    PrintOracle's csv-mode output for it: ``cases.jsonl`` and each case's file."""
    bsxm = os.environ.get("PIPIT_PRIVATE_BSXM")
    oracle = os.environ.get("PIPIT_PRIVATE_CSV")
    if not bsxm or not oracle:
        pytest.skip("set PIPIT_PRIVATE_BSXM and PIPIT_PRIVATE_CSV to run")
    exporter = Exporter(pack, Path(bsxm), tmp_path)
    differing = []
    for case in _jsonl(Path(oracle) / "cases.jsonl"):
        if exporter.export(case) != (Path(oracle) / f"{case['name']}.csv").read_bytes():
            differing.append(case["name"])
    assert differing == []

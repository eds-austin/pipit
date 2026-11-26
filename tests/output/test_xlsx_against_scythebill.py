"""Spreadsheets with the same content as Scythebill's Save as spreadsheet (tools/oracle/
PrintOracle.java's xlsx mode: ReportXlsOutput as SaveAsXlsAction sets it up, on
tests/fixtures/bsxm/queries.bsxm). The files are openpyxl's, not POI's, so they are compared
by content: tools/oracle/summarize_xlsx.py's snapshot (cells, bold and italic, number
formats, merges, column widths). To see a difference, run the oracle (tools/oracle/run.sh)
and compare its snapshot with Pipit's."""

from __future__ import annotations

import importlib.util
import json
import os
import warnings
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pipit.output.xlsx_report import SpreadsheetOptions, report_spreadsheet
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
XLSX = FIXTURES / "oracle" / "xlsx"


def _summarizer() -> ModuleType:
    path = ROOT / "tools" / "oracle" / "summarize_xlsx.py"
    spec = importlib.util.spec_from_file_location("summarize_xlsx", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUMMARIZE = _summarizer()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def _options(options: dict[str, Any]) -> SpreadsheetOptions:
    return SpreadsheetOptions(
        include_scientific=options["includeScientific"], show_families=options["showFamilies"],
        show_status=options["showStatus"], show_notes=options["showNotes"],
        only_countable=options["onlyCountable"], omit_sp_and_hybrid=options["omitSpAndHybrid"],
        maximum_sightings=options["maximumSightings"], sort_type=options["sortType"],
        sort_sightings_type=options["sortSightingsType"], user_output=options["userOutput"],
        subspecies_in_separate_column=options["subspeciesInSeparateColumn"],
    )  # fmt: skip


class _Writer:
    def __init__(self, pack: Any, bsxm: Path, tmp_path: Path) -> None:
        result = import_bsxm(bsxm, tmp_path / "list.pipit", pack.base_taxonomy_id,
                             pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
        self.database = ListDatabase.open(result.list_path)
        connection = self.database.connection
        self.query_list = load_query_list(connection)
        self.checklists = Checklists(pack, connection, self.query_list)
        rows = connection.execute("SELECT xml_id, name, abbreviation FROM users")
        self.users = {xml_id: (name, abbreviation) for xml_id, name, abbreviation in rows}
        self.clements, self.avilist = pack.load_base_and_avilist()
        self.contexts: dict[tuple[str, str], EngineContext] = {}

    def xlsx(self, case: dict[str, Any]) -> bytes:
        key = (case["display"], case["depth"])
        if key not in self.contexts:
            taxonomy = self.avilist if case["display"] == "avilist" else self.clements
            self.contexts[key] = EngineContext(self.query_list, taxonomy,
                                               TaxonType[case["depth"].upper()],
                                               users=frozenset(self.users))  # fmt: skip
        report = report_spreadsheet(context=self.contexts[key], checklists=self.checklists,
                                    query_json=json.dumps(case["query"]), users=self.users,
                                    options=_options(case["options"]),
                                    names_preference=case["namesOrder"])  # fmt: skip
        data: bytes = report.xlsx()
        return data


@pytest.fixture(scope="module")
def writer(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> _Writer:
    return _Writer(pack, FIXTURES / "bsxm" / "queries.bsxm", tmp_path_factory.mktemp("xlsx"))


def _summary(name: str, data: bytes) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # POI's files have no default style
        result: dict[str, Any] = SUMMARIZE.summary(name, data)
        return result


@pytest.mark.scythebill
def test_spreadsheets_match_scythebill(writer: _Writer) -> None:
    expected = {sheet["name"]: sheet for sheet in _jsonl(XLSX / "sheets.jsonl")}
    differing = [
        case["name"]
        for case in _jsonl(XLSX / "cases.jsonl")
        if _summary(case["name"], writer.xlsx(case)) != expected[case["name"]]
    ]
    assert differing == []


def test_bold_is_written_bare(writer: _Writer) -> None:
    """Scythebill's ``SpreadsheetFonts``: macOS Numbers ignores ``<b val="1"/>``."""
    import io
    import zipfile

    case = _jsonl(XLSX / "cases.jsonl")[1]
    styles = zipfile.ZipFile(io.BytesIO(writer.xlsx(case))).read("xl/styles.xml")
    assert b"<b/>" in styles
    assert b'<b val="1"/>' not in styles


@pytest.mark.private
def test_real_list_spreadsheets(pack: Any, tmp_path: Path) -> None:
    """Eric's list (never copied): ``PIPIT_PRIVATE_BSXM``, and in ``PIPIT_PRIVATE_XLSX``
    PrintOracle's xlsx output for it: ``cases.jsonl`` with a workbook per case."""
    bsxm = os.environ.get("PIPIT_PRIVATE_BSXM")
    oracle = os.environ.get("PIPIT_PRIVATE_XLSX")
    if not bsxm or not oracle:
        pytest.skip("set PIPIT_PRIVATE_BSXM and PIPIT_PRIVATE_XLSX to run")
    writer = _Writer(pack, Path(bsxm), tmp_path)
    differing = []
    for case in _jsonl(Path(oracle) / "cases.jsonl"):
        want = (Path(oracle) / f"{case['name']}.xlsx").read_bytes()
        if _summary(case["name"], writer.xlsx(case)) != _summary(case["name"], want):
            differing.append(case["name"])
    assert differing == []

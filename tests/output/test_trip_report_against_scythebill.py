"""Trip reports exactly as Scythebill writes them (tools/oracle/PrintOracle.java's trip mode:
TripReportDocOutput as SaveAsTripReportAction sets it up, on
tests/fixtures/bsxm/trip_report.bsxm). The HTML and its plain-text copy must be
byte-identical: the fixtures keep each one's size and SHA-256. So must the Word document's
``word/document.xml`` and its relationships (the package's metadata says who wrote it and
when). To see a difference, run the oracle (tools/oracle/run.sh) and diff its files with
Pipit's."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pipit.output.trip_report import TripReport, TripReportOptions, load_report_data, trip_report
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
TRIP = FIXTURES / "oracle" / "trip_report"


def _docx_summarizer() -> ModuleType:
    path = Path(__file__).parents[2] / "tools" / "oracle" / "summarize_docx.py"
    spec = importlib.util.spec_from_file_location("summarize_docx", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUMMARIZE_DOCX = _docx_summarizer()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def _options(case: dict[str, Any]) -> TripReportOptions:
    options = case["options"]
    return TripReportOptions(
        include_scientific=options["includeScientific"], itinerary=options["includeItinerary"],
        species_table=options["includeSpeciesTable"], species_list=options["includeSpeciesList"],
        show_status=options["showStatus"], lifers_in_bold=options["lifersInBold"],
        use_miles=case["useMiles"],
    )  # fmt: skip


class Reporter:
    def __init__(self, pack: Any, bsxm: Path, tmp_path: Path) -> None:
        result = import_bsxm(bsxm, tmp_path / "list.pipit", pack.base_taxonomy_id,
                             pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
        self.database = ListDatabase.open(result.list_path)
        connection = self.database.connection
        self.query_list = load_query_list(connection)
        self.checklists = Checklists(pack, connection, self.query_list)
        self.data = load_report_data(connection, self.query_list)
        self.clements, self.avilist = pack.load_base_and_avilist()
        self.contexts: dict[tuple[str, str], EngineContext] = {}

    def report(self, case: dict[str, Any]) -> TripReport:
        key = (case["display"], case["depth"])
        if key not in self.contexts:
            taxonomy = self.avilist if case["display"] == "avilist" else self.clements
            self.contexts[key] = EngineContext(self.query_list, taxonomy,
                                               TaxonType[case["depth"].upper()],
                                               users=frozenset(self.data.users))  # fmt: skip
        trips = None
        if "trips" in case:
            trips = [self.query_list.trips[xml_id] for xml_id in case["trips"]]
        return trip_report(context=self.contexts[key], checklists=self.checklists,
                           data=self.data, query_json=json.dumps(case["query"]),
                           options=_options(case), names_preference=case["namesOrder"],
                           trips=trips)  # fmt: skip


def _summary(name: str, data: bytes) -> dict[str, Any]:
    return {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture(scope="module")
def reporter(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> Reporter:
    return Reporter(pack, FIXTURES / "bsxm" / "trip_report.bsxm",
                    tmp_path_factory.mktemp("trip"))  # fmt: skip


@pytest.mark.scythebill
def test_reports_match_scythebill(reporter: Reporter) -> None:
    html_expected = {line["name"]: line for line in _jsonl(TRIP / "html.jsonl")}
    text_expected = {line["name"]: line for line in _jsonl(TRIP / "text.jsonl")}
    docx_expected = {line["name"]: line for line in _jsonl(TRIP / "docx.jsonl")}
    differing = []
    for case in _jsonl(TRIP / "cases.jsonl"):
        report = reporter.report(case)
        html, text = report.html()
        name = case["name"]
        if _summary(name, html.encode()) != html_expected[name]:
            differing.append(f"{name}.html")
        if _summary(name, text.encode()) != text_expected[name]:
            differing.append(f"{name}.txt")
        if SUMMARIZE_DOCX.summary(name, report.word()[0]) != docx_expected[name]:
            differing.append(f"{name}.docx")
    assert differing == []


@pytest.mark.private
def test_real_list_reports(pack: Any, tmp_path: Path) -> None:
    """Eric's list (never copied): ``PIPIT_PRIVATE_BSXM``, and in ``PIPIT_PRIVATE_TRIP``
    PrintOracle's trip-mode output for it: ``cases.jsonl`` with the files of each case."""
    bsxm = os.environ.get("PIPIT_PRIVATE_BSXM")
    oracle = os.environ.get("PIPIT_PRIVATE_TRIP")
    if not bsxm or not oracle:
        pytest.skip("set PIPIT_PRIVATE_BSXM and PIPIT_PRIVATE_TRIP to run")
    reporter = Reporter(pack, Path(bsxm), tmp_path)
    differing = []
    for case in _jsonl(Path(oracle) / "cases.jsonl"):
        name = case["name"]
        if (Path(oracle) / f"{name}.error").exists():
            continue  # Scythebill fails on it (a synthetic region as the report's place)
        report = reporter.report(case)
        html, text = report.html()
        if html.encode() != (Path(oracle) / f"{name}.html").read_bytes():
            differing.append(f"{name}.html")
        if text.encode() != (Path(oracle) / f"{name}.txt").read_bytes():
            differing.append(f"{name}.txt")
        theirs = zipfile.ZipFile(Path(oracle) / f"{name}.docx")
        mine = zipfile.ZipFile(io.BytesIO(report.word()[0]))
        for part in ("word/document.xml", "word/_rels/document.xml.rels"):
            if mine.read(part) != theirs.read(part):
                differing.append(f"{name}.docx")
                break
    assert differing == []

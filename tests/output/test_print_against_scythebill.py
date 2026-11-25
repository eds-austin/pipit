"""Printed reports and checklists exactly as Scythebill makes them (tools/oracle/
PrintOracle.java: HtmlOutput as PrintAction sets it up, and Checklists.getChecklist, on
tests/fixtures/bsxm/queries.bsxm). Each page must be byte-identical: same size and SHA-256.
To see a difference, run the oracle (tools/oracle/run.sh) and diff its page with Pipit's."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from pipit.output.print_html import PrintOptions, print_report
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
PRINT = FIXTURES / "oracle" / "print"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def _options(options: dict[str, Any]) -> PrintOptions:
    return PrintOptions(
        include_scientific=options["includeScientific"], show_families=options["showFamilies"],
        show_status=options["showStatus"], maximum_sightings=options["maximumSightings"],
        sort_type=options["sortType"], sort_sightings_type=options["sortSightingsType"],
        compact=options["compactPrinting"], only_countable=options["onlyCountable"],
        omit_sp_and_hybrid=options["omitSpAndHybrid"],
    )  # fmt: skip


class _Printer:
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

    def page(self, case: dict[str, Any]) -> bytes:
        key = (case["display"], case["depth"])
        if key not in self.contexts:
            taxonomy = self.avilist if case["display"] == "avilist" else self.clements
            self.contexts[key] = EngineContext(self.query_list, taxonomy,
                                               TaxonType[case["depth"].upper()],
                                               users=frozenset(self.users))  # fmt: skip
        html = print_report(context=self.contexts[key], checklists=self.checklists,
                            query_json=json.dumps(case["query"]), users=self.users,
                            file_name=case["fileName"], date=case["date"],
                            options=_options(case["options"]),
                            names_preference=case["namesOrder"])  # fmt: skip
        return html.html.encode("utf-8")

    def checklist_summary(self, place: str, display: str) -> dict[str, Any]:
        taxonomy = self.avilist if display == "avilist" else self.clements
        checklist = self.checklists.checklist(taxonomy, place)
        if checklist is None:
            return {}
        entries = sorted("/".join(taxon.ids) + "=" + status
                         for taxon, status in checklist.statuses.items())  # fmt: skip
        return {"size": len(entries),
                "sha256": hashlib.sha256("\n".join(entries).encode()).hexdigest()}  # fmt: skip


@pytest.fixture(scope="module")
def printer(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> _Printer:
    return _Printer(pack, FIXTURES / "bsxm" / "queries.bsxm", tmp_path_factory.mktemp("print"))


@pytest.mark.scythebill
def test_pages_match_scythebill(printer: _Printer) -> None:
    expected = {page["name"]: page for page in _jsonl(PRINT / "pages.jsonl")}
    differing = []
    for case in _jsonl(PRINT / "cases.jsonl"):
        data = printer.page(case)
        got = {"name": case["name"], "size": len(data),
               "sha256": hashlib.sha256(data).hexdigest()}  # fmt: skip
        if got != expected[case["name"]]:
            differing.append(case["name"])
    assert differing == []


@pytest.mark.scythebill
def test_checklists_match_scythebill(printer: _Printer) -> None:
    differing = []
    for line in _jsonl(PRINT / "checklists.queries.jsonl"):
        want = {key: line[key] for key in ("size", "sha256") if key in line}
        if printer.checklist_summary(line["place"], line["taxonomy"]) != want:
            differing.append((line["place"], line["taxonomy"]))
    assert differing == []


@pytest.mark.private
def test_real_list_pages(pack: Any, tmp_path: Path) -> None:
    """Eric's list (never copied): ``PIPIT_PRIVATE_BSXM``, and in ``PIPIT_PRIVATE_PRINT``
    PrintOracle's output for it: ``cases.jsonl`` with a page per case, and
    ``checklists.jsonl``."""
    bsxm = os.environ.get("PIPIT_PRIVATE_BSXM")
    oracle = os.environ.get("PIPIT_PRIVATE_PRINT")
    if not bsxm or not oracle:
        pytest.skip("set PIPIT_PRIVATE_BSXM and PIPIT_PRIVATE_PRINT to run")
    printer = _Printer(pack, Path(bsxm), tmp_path)
    differing = [
        case["name"]
        for case in _jsonl(Path(oracle) / "cases.jsonl")
        if printer.page(case) != (Path(oracle) / f"{case['name']}.html").read_bytes()
    ]
    assert differing == []
    for line in _jsonl(Path(oracle) / "checklists.jsonl"):
        want = {key: line[key] for key in ("size", "sha256") if key in line}
        assert printer.checklist_summary(line["place"], line["taxonomy"]) == want

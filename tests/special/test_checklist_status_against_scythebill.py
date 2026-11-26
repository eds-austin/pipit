"""The checklist status report exactly as Scythebill's (tools/oracle/PrintOracle.java's
status mode: ChecklistStatusReportPanel.showReport for each choice, in both taxonomies) on
tests/fixtures/bsxm/checklist_status.bsxm (tools/oracle/make_checklist_status_fixture.py):
the same places in the same order, custom or built-in, with the same species in the same
order."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipit.query.checklists import Checklists
from pipit.query.model import load_query_list
from pipit.special.checklist_status import checklist_status
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm

FIXTURES = Path(__file__).parents[1] / "fixtures"
EXPECTED = [json.loads(line) for line in
            (FIXTURES / "oracle" / "checklist_status" / "expected.jsonl").read_text().splitlines()
            if line.strip()]  # fmt: skip


@pytest.fixture(scope="module")
def listed(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    folder = tmp_path_factory.mktemp("status")
    result = import_bsxm(FIXTURES / "bsxm" / "checklist_status.bsxm", folder / "list.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    database = ListDatabase.open(result.list_path)
    query_list = load_query_list(database.connection)
    checklists = Checklists(pack, database.connection, query_list)
    clements, avilist = pack.load_base_and_avilist()
    taxonomies = {"clements": clements, "avilist": avilist}

    def run(taxonomy: str, choice: str) -> list[dict[str, Any]]:
        places = checklist_status(query_list, checklists, taxonomies[taxonomy], choice)
        return [{"id": place.xml_id, "custom": place.custom,
                 "taxa": [taxon.id for taxon in place.species]} for place in places]  # fmt: skip

    yield run
    database.close()


@pytest.mark.scythebill
@pytest.mark.parametrize("expected", EXPECTED,
                         ids=[f"{e['taxonomy']}-{e['choice']}" for e in EXPECTED])  # fmt: skip
def test_checklist_status_matches_scythebill(listed: Any, expected: dict[str, Any]) -> None:
    assert listed(expected["taxonomy"], expected["choice"]) == expected["places"]

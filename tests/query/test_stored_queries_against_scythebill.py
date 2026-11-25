"""Stored queries read and written exactly as Scythebill does (tools/oracle/
StoredQueriesOracle.java: StoredQueries and ReportPreferencesManager on
tests/fixtures/bsxm/stored_queries.bsxm). Pipit restores the same queries (names, canonical
JSON, types), and after the same edits writes the same file, byte for byte."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipit.domain import gson
from pipit.query import stored
from pipit.query.stored import StoredQuery
from pipit.storage import integrity
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.storage.stored_query_ops import save_stored_queries, stored_queries

FIXTURES = Path(__file__).parents[1] / "fixtures"
OPS = FIXTURES / "oracle" / "stored_queries"
# The same cases as tools/oracle/run.sh: name -> the list they start from.
CASES = {
    name: "stored_queries"
    for name in ("unchanged", "add", "replace", "ticks", "remove", "rename", "move", "all")
}
CASES["first"] = "visits"


def _apply(queries: list[StoredQuery], op: dict[str, Any]) -> list[StoredQuery]:
    kind = op["op"]
    if kind == "add":
        return stored.add(queries, op["name"], op["json"])
    if kind == "ticks":
        return stored.add(queries, op["name"], op["ticks"] + "/" + op["json"], stored.TOTAL_TICKS)
    if kind == "remove":
        return stored.remove(queries, op["name"])
    if kind == "rename":
        return stored.rename(queries, op["name"], op["to"])
    assert kind == "move"
    return stored.move(queries, op["from"], op["to"])


@pytest.mark.scythebill
@pytest.mark.parametrize("case", sorted(CASES))
def test_stored_queries_match_scythebill(case: str, pack: Any, tmp_path: Path) -> None:
    result = import_bsxm(FIXTURES / "bsxm" / f"{CASES[case]}.bsxm", tmp_path / "s.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    ops = [json.loads(line) for line in (OPS / f"{case}.jsonl").read_text().split("\n")
           if line.strip()]  # fmt: skip
    restored = [json.loads(line) for line in
                (OPS / f"{case}.restored.jsonl").read_text().split("\n") if line]  # fmt: skip
    with ListDatabase.open(result.list_path) as database:
        queries = stored_queries(database.connection)
        before = _prefs(database)
        assert [{"name": q.name, "persisted": q.persisted, "type": q.type}
                for q in queries] == restored  # fmt: skip
        for op in ops:
            queries = _apply(queries, op)
            save_stored_queries(database, queries, f"Stored query: {op['op']}")
        assert integrity.check(database.connection) == []
        assert stored_queries(database.connection) == queries
        export_bsxm(database, tmp_path / "out.bsxm")
        for _op in ops:
            database.undo()
        assert _prefs(database) == before
    expected = FIXTURES / "bsxm" / f"stored_queries.{case}.scythebill.bsxm"
    assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes()


def _prefs(database: ListDatabase) -> str | None:
    row = database.connection.execute("SELECT json FROM report_prefs WHERE id = 1").fetchone()
    return row[0] if row else None


def test_gson_writes_as_gson() -> None:
    assert gson.dumps({"a": "x=<y>&'z'\u2028é\"\\\n\x01", "b": None, "c": [None, 1.5]}) == (
        '{"a":"x\\u003d\\u003cy\\u003e\\u0026\\u0027z\\u0027\\u2028é\\"\\\\\\n\\u0001",'
        '"c":[null,1.5]}'
    )
    assert gson.dumps(gson.parse('{"n": 1.50, "e": {}, "l": []}'), pretty=True) == (
        '{\n  "n": 1.50,\n  "e": {},\n  "l": []\n}'
    )
    assert stored.canonicalize_query_json('{"type":"ANY","fields":[{"type":"DATE","value":'
                                          '{"type":"TODAY"}}]}') == (
        '{"fields":[{"type":"DATE","value":{"type":"TODAY"},"bool":"ANY"}]}'
    )  # fmt: skip
    assert stored.canonicalize_query_json("{nope") == "{nope"


@pytest.mark.private
def test_real_list_stored_queries(pack: Any, tmp_path: Path) -> None:
    """Eric's list (never copied): ``PIPIT_PRIVATE_BSXM``, and in ``PIPIT_PRIVATE_STORED``
    StoredQueriesOracle's output for each ``<case>.jsonl`` there (``<case>.restored.jsonl``,
    ``<case>.scythebill.bsxm``)."""
    import os

    bsxm = os.environ.get("PIPIT_PRIVATE_BSXM")
    oracle = os.environ.get("PIPIT_PRIVATE_STORED")
    if not bsxm or not oracle:
        pytest.skip("set PIPIT_PRIVATE_BSXM and PIPIT_PRIVATE_STORED to run")
    result = import_bsxm(Path(bsxm), tmp_path / "real.pipit", pack.base_taxonomy_id,
                         pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    cases = sorted(Path(oracle).glob("*.restored.jsonl"))
    assert cases
    for restored_path in cases:
        case = restored_path.name.removesuffix(".restored.jsonl")
        ops_text = (Path(oracle) / f"{case}.jsonl").read_text()
        ops = [json.loads(line) for line in ops_text.split("\n") if line.strip()]
        restored = [json.loads(line) for line in restored_path.read_text().split("\n") if line]
        with ListDatabase.open(result.list_path) as database:
            queries = stored_queries(database.connection)
            assert [{"name": q.name, "persisted": q.persisted, "type": q.type}
                    for q in queries] == restored, case  # fmt: skip
            for op in ops:
                queries = _apply(queries, op)
                save_stored_queries(database, queries, op["op"])
            export_bsxm(database, tmp_path / "out.bsxm")
            for _op in ops:
                database.undo()
        expected = Path(oracle) / f"{case}.scythebill.bsxm"
        assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes(), case

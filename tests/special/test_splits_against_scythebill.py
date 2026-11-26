"""Splits and lumps exactly as Scythebill's (tools/oracle/PrintOracle.java's splits mode:
SplitsAndLumpsProcessor for every version each taxonomy offers) on
tests/fixtures/bsxm/queries.bsxm: the same splits, lumps and possible ones, with their
current species and old names in the same order, and the same counts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from pipit.query.engine import EngineContext, parse_query
from pipit.query.model import load_query_list
from pipit.special.splits_lumps import (
    SingleResult,
    SplitsAndLumps,
    SplitsUnavailableError,
    splits_report,
    versions_for,
)
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
SPLITS = FIXTURES / "oracle" / "splits"
CASES = [json.loads(line) for line in (SPLITS / "cases.jsonl").read_text().splitlines()
         if line.strip()]  # fmt: skip


def _single(result: SingleResult) -> dict[str, Any]:
    return {"current": result.current,
            "old": [[o.scientific, o.common] for o in result.old],
            "possibleOld": [[o.scientific, o.common] for o in result.possible_old],
            "unresolvedSp": result.unresolved_sp}  # fmt: skip


def summary(version: str, found: SplitsAndLumps) -> dict[str, Any]:
    counts = asdict(found)
    return {
        "version": version,
        "splits": [_single(r) for r in found.splits],
        "lumps": [_single(r) for r in found.lumps],
        "possibleSplits": [_single(r) for r in found.possible_splits],
        "possibleLumps": [_single(r) for r in found.possible_lumps],
        "possibleLumpOrSplit": [_single(r) for r in found.possible_lump_or_split],
        "knownSplitCount": counts["known_split_count"],
        "knownLumpCount": counts["known_lump_count"],
        "possibleSplitCount": counts["possible_split_count"],
        "possibleLumpCount": counts["possible_lump_count"],
        "unresolvedSpMinimum": counts["unresolved_sp_minimum"],
        "unresolvedSpMaximum": counts["unresolved_sp_maximum"],
    }


def run_versions(pack: Any, context: EngineContext, query_json: Any) -> list[dict[str, Any]]:
    query = parse_query(query_json, context.query_list)
    found = []
    for version, _label in versions_for(context.taxonomy):
        try:
            result = splits_report(context, query, pack.split_report_rows(version))
        except SplitsUnavailableError:
            found.append({"version": version, "error": True})
            continue
        found.append(summary(version, result))
    return found


@pytest.fixture(scope="module")
def contexts(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    folder = tmp_path_factory.mktemp("splits")
    result = import_bsxm(FIXTURES / "bsxm" / "queries.bsxm", folder / "list.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    database = ListDatabase.open(result.list_path)
    query_list = load_query_list(database.connection)
    clements, avilist = pack.load_base_and_avilist()
    yield {name: EngineContext(query_list, taxonomy, TaxonType.SPECIES)
           for name, taxonomy in (("clements", clements), ("avilist", avilist))}  # fmt: skip
    database.close()


@pytest.mark.scythebill
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_splits_match_scythebill(pack: Any, contexts: Any, case: dict[str, Any]) -> None:
    expected = [json.loads(line) for line in
                (SPLITS / f"{case['name']}.jsonl").read_text().splitlines()]  # fmt: skip
    found = run_versions(pack, contexts[case["display"]], case["query"])
    assert [f["version"] for f in found] == [e["version"] for e in expected]
    for got, want in zip(found, expected, strict=True):
        assert got == want, got["version"]

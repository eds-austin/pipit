"""Stored queries give exactly Scythebill's totals and taxa.

tests/fixtures/oracle/queries.txt (30 queries over every field type and operation) and
regions.txt (every synthetic region) were run through Scythebill's own headless query path
(tools/oracle/QueryOracle.java: ``StoredQueries.restore`` parsing,
``CompositeQueryDefinition``, the countable predicate, ``QueryProcessor`` and the Reports
screen's totals). Pipit must give the same species, species-with-sp., group, subspecies,
spuh, family and sighting counts, and the same taxa in the same order, each marked
countable or not, in Clements and AviList, at species, group and subspecies depth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipit.query.engine import EngineContext, parse_query, run_query
from pipit.query.fields_simple import QueryJsonError
from pipit.query.model import QueryList, load_query_list
from pipit.query.synthetic import regions_for
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

pytestmark = pytest.mark.scythebill
FIXTURES = Path(__file__).parents[1] / "fixtures"
CONFIGS = [("clements", "species"), ("avilist", "species"), ("clements", "subspecies"),
           ("avilist", "group")]  # fmt: skip


def _query_list(pack: Any, tmp_path: Path, name: str) -> tuple[QueryList, frozenset[str]]:
    result = import_bsxm(FIXTURES / "bsxm" / f"{name}.bsxm", tmp_path / f"{name}.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    with ListDatabase.open(result.list_path, read_only=True) as database:
        users = frozenset(u for (u,) in database.connection.execute("SELECT xml_id FROM users"))
        return load_query_list(database.connection), users


@pytest.fixture(scope="module")
def taxonomies(pack: Any) -> dict[str, Any]:
    base, avilist = pack.load_base_and_avilist()
    return {"clements": base, "avilist": avilist}


def _totals(results: Any) -> dict[str, Any]:
    return {
        "species": results.countable_species_size(False),
        "speciesWithSp": results.countable_species_size(True),
        "groups": results.countable_groups_size(False),
        "subspecies": results.countable_subspecies_size(False),
        "spuh": results.spuh_count(),
        "families": results.family_count(),
        "sightings": results.sightings_count(),
        "taxa": [
            ("" if results.is_countable(r) else "~") + "/".join(r.sighting_taxon.ids)
            for r in results.taxa
        ],
    }


def _check(query_list: QueryList, users: frozenset[str], taxonomy: Any, depth: str,
           queries: Path, expected: Path) -> None:  # fmt: skip
    lines = [line for line in queries.read_text().splitlines() if line.strip()]
    wanted = [json.loads(line) for line in expected.read_text().splitlines() if line.strip()]
    assert len(wanted) == len(lines), "the oracle results don't match the queries"
    context = EngineContext(query_list, taxonomy, TaxonType[depth.upper()], users=users)
    for number, (line, want) in enumerate(zip(lines, wanted, strict=True), start=1):
        got = _totals(run_query(parse_query(line, query_list, users), context))
        assert got == want, f"query {number}: {line}"


@pytest.mark.parametrize(("display", "depth"), CONFIGS)
def test_reference_queries(display: str, depth: str, pack: Any, taxonomies: dict[str, Any],
                           tmp_path: Path) -> None:  # fmt: skip
    query_list, users = _query_list(pack, tmp_path, "queries")
    _check(query_list, users, taxonomies[display], depth, FIXTURES / "oracle" / "queries.txt",
           FIXTURES / "oracle" / f"queries.{display}.{depth}.jsonl")  # fmt: skip


def test_synthetic_regions(pack: Any, taxonomies: dict[str, Any], tmp_path: Path) -> None:
    query_list, users = _query_list(pack, tmp_path, "visits")
    _check(query_list, users, taxonomies["clements"], "species",
           FIXTURES / "oracle" / "regions.txt",
           FIXTURES / "oracle" / "regions.clements.species.jsonl")  # fmt: skip
    regions = regions_for(query_list)
    assert "_usst_califo" in regions["***aba***"] and "_usst_califo" in regions["***us48***"]
    assert "_scyco_GB-ENG-KEN" in regions["***wepale***"]


def test_queries_scythebill_refuses_are_refused(pack: Any, tmp_path: Path) -> None:
    query_list, users = _query_list(pack, tmp_path, "queries")
    for bad in (
        '{"fields":[{"type":"LOCATION","value":{"type":"IN","id":"nowhere"}}]}',
        '{"fields":[{"type":"USER","value":{"type":"INCLUDES","id":"nobody"}}]}',
        '{"fields":[{"type":"SIGHTING_STATUS","value":{"type":"IS","statusId":"odd"}}]}',
        '{"fields":[{"type":"NOT_A_FIELD","value":{}}]}',
        '{"fields":[{"type":"DATE","value":{"type":"DURING"}}],"type":"SOMETIMES"}',
    ):
        with pytest.raises(QueryJsonError):
            parse_query(bad, query_list, users)

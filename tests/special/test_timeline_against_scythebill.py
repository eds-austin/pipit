"""The timeline exactly as Scythebill's (tools/oracle/PrintOracle.java's timeline mode:
TimelineData for the query, as TimelinePanel runs it) on tests/fixtures/bsxm/queries.bsxm and
trip_report.bsxm: the same lifers in order, years and days (species, shared place, lifers),
decades, milestones and undated counts."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from pipit.domain.partial_date import PartialDate, PartialField
from pipit.query.engine import EngineContext, parse_query
from pipit.query.model import load_query_list
from pipit.special.timeline import Period, Timeline, decade_of, timeline
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
TIMELINE = FIXTURES / "oracle" / "timeline"
CASES = [(list_name, json.loads(line))
         for list_name in ("queries", "trip_report")
         for line in (TIMELINE / f"cases.{list_name}.jsonl").read_text().splitlines()
         if line.strip()]  # fmt: skip


def _date(when: PartialDate) -> list[int | None]:
    return [when.get(PartialField.YEAR), when.get(PartialField.MONTH), when.get(PartialField.DAY)]


def _periods(periods: list[Period]) -> list[list[Any]]:
    return [[_date(p.when), sorted(p.species), p.place, p.lifers] for p in periods]


def summary(found: Timeline) -> dict[str, Any]:
    decades = []
    if found.first_day is not None and found.latest_day is not None:
        for start in range(decade_of(found.first_day.year) - 100,
                           decade_of(found.latest_day.year) + 101, 10):  # fmt: skip
            decade = found.decade(start)
            if decade.count > 0:
                decades.append([start, decade.count, decade.lifers])
    return {
        "lifers": [[lifer.species_id, lifer.day.isoformat()] for lifer in found.lifers],
        "years": _periods(found.years),
        "days": _periods(found.days),
        "decades": decades,
        "milestones": [
            [m.number, m.lifer.species_id, m.lifer.day.isoformat()] for m in found.milestones()
        ],
        "lifeListTotal": found.life_list_total,
        "undatedSpecies": found.undated_species,
        "sightingsInNoYear": found.sightings_in_no_year,
        "sightingsOnNoDay": found.sightings_on_no_day,
        "latestDay": None if found.latest_day is None else found.latest_day.isoformat(),
    }


@pytest.fixture(scope="module")
def contexts(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    folder = tmp_path_factory.mktemp("timeline")
    clements, avilist = pack.load_base_and_avilist()
    found = {}
    databases = []
    for list_name in ("queries", "trip_report"):
        result = import_bsxm(FIXTURES / "bsxm" / f"{list_name}.bsxm",
                             folder / f"{list_name}.pipit", pack.base_taxonomy_id,
                             pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
        database = ListDatabase.open(result.list_path)
        databases.append(database)
        query_list = load_query_list(database.connection)
        for name, taxonomy in (("clements", clements), ("avilist", avilist)):
            found[(list_name, name)] = EngineContext(query_list, taxonomy, TaxonType.SPECIES)
    yield found
    for database in databases:
        database.close()


@pytest.mark.scythebill
@pytest.mark.parametrize(("list_name", "case"), CASES, ids=[case["name"] for _, case in CASES])
def test_timeline_matches_scythebill(contexts: Any, list_name: str, case: dict[str, Any]) -> None:
    expected = json.loads(gzip.decompress((TIMELINE / f"{case['name']}.json.gz").read_bytes()))
    context = contexts[(list_name, case["display"])]
    found = summary(timeline(context, parse_query(case["query"], context.query_list)))
    for key in expected:
        assert found[key] == expected[key], key

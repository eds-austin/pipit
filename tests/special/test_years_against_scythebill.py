"""The year comparison exactly as Scythebill's (tools/oracle/PrintOracle.java's years mode:
YearComparisonProcessor with the panel's year range) on tests/fixtures/bsxm/queries.bsxm:
the same years, and for every species its sightings, earliest and latest dates per year and
half year, totals, first year ever and drawn days, and the species counted per year."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from pipit.domain.partial_date import PartialDate, PartialField
from pipit.query.engine import EngineContext, parse_query
from pipit.query.model import load_query_list
from pipit.special.year_comparison import Half, YearComparison, YearResult, compare_years
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType

FIXTURES = Path(__file__).parents[1] / "fixtures"
YEARS = FIXTURES / "oracle" / "years"
CASES = [json.loads(line) for line in (YEARS / "cases.jsonl").read_text().splitlines()
         if line.strip()]  # fmt: skip
_JAVA_HALF = {Half.WHOLE_YEAR: "WHOLE_YEAR", Half.H1: "H1", Half.H2: "H2"}


def _date(when: PartialDate | None) -> list[int | None] | None:
    if when is None:
        return None
    return [when.get(PartialField.YEAR), when.get(PartialField.MONTH), when.get(PartialField.DAY)]


def _row(result: YearResult) -> list[Any]:
    return [result.frequency, _date(result.earliest), _date(result.latest)]


def summary(found: YearComparison) -> dict[str, Any]:
    species = []
    for result in found.species:
        taxon = result.resolved.sighting_taxon
        item: dict[str, Any] = {
            "taxon": f"{taxon.type.name}:{','.join(taxon.ids)}",
            "firstYearEver": (result.first_year_ever if result.first_year_ever is not None
                              else 2**31 - 1),
            "yearsPresent": result.years_present,
            "totalSightings": result.total_sightings,
        }  # fmt: skip
        for half, name in _JAVA_HALF.items():
            item[name] = [
                [year, *_row(year_result)]
                for year, year_result in sorted(result.years.get(half, {}).items())
            ]
            item[f"{name}_total"] = _row(result.total(half))
        item["days"] = [[year, sorted(days)] for year, days in sorted(result.days.items())]
        species.append(item)
    counts: dict[str, Any] = {}
    for half, name in _JAVA_HALF.items():
        counts[name] = [found.species_count(half, year) for year in found.years]
        counts[f"{name}_all"] = found.species_count_all_years(half)
    return {"firstYear": found.first_year, "lastYear": found.last_year, "species": species,
            "counts": counts, "firstSeenDays": found.first_seen_days()}  # fmt: skip


@pytest.fixture(scope="module")
def contexts(pack: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    folder = tmp_path_factory.mktemp("years")
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
def test_years_match_scythebill(contexts: Any, case: dict[str, Any]) -> None:
    expected = json.loads(gzip.decompress((YEARS / f"{case['name']}.json.gz").read_bytes()))
    context = contexts[case["display"]]
    found = summary(compare_years(context, parse_query(case["query"], context.query_list),
                                  from_year=case.get("from"), to_year=case.get("to")))  # fmt: skip
    assert (found["firstYear"], found["lastYear"]) == (expected["firstYear"],
                                                       expected["lastYear"])  # fmt: skip
    assert [s["taxon"] for s in found["species"]] == [s["taxon"] for s in expected["species"]]
    differing = [(got["taxon"], key) for got, want in zip(found["species"], expected["species"],
                                                          strict=True)
                 for key in want if got.get(key) != want[key]]  # fmt: skip
    assert differing[:5] == []
    assert found["counts"] == expected["counts"]
    assert found["firstSeenDays"] == expected["firstSeenDays"]

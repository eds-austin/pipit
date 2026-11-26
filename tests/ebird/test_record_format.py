"""eBird Record Format exports exactly as Scythebill's Save for eBird writes them
(tools/oracle/PrintOracle.java's ebird mode: EbirdExportAction and EBirdCsvExport), on three
lists: the 30 reference queries on queries.bsxm, and everything in trip_report.bsxm and
edge_cases.ebird.bsxm (edge_cases.bsxm without its February 30 sighting, which Scythebill's
export fails on). Every file must be byte-identical, split at the same line. Also Scythebill's
own EBirdCsvExportTest cases."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from pipit.domain.partial_date import parse_partial_date
from pipit.ebird.record_format import (
    EBirdExport,
    EBirdListData,
    JavaWriterBytes,
    export,
    is_acceptable,
    is_list_building,
    load_ebird_data,
)
from pipit.output.print_html import run_report_query
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import QPlace, QSighting, load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon

FIXTURES = Path(__file__).parents[1] / "fixtures"
EBIRD = FIXTURES / "oracle" / "ebird"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


class Exporter:
    def __init__(self, pack: Any, bsxm: Path, tmp_path: Path) -> None:
        result = import_bsxm(bsxm, tmp_path / "list.pipit", pack.base_taxonomy_id,
                             pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
        self.database = ListDatabase.open(result.list_path)
        connection = self.database.connection
        query_list = load_query_list(connection)
        self.checklists = Checklists(pack, connection, query_list)
        self.data = load_ebird_data(connection, query_list)
        rows = connection.execute("SELECT xml_id, name, abbreviation FROM users")
        self.users = {xml_id: (name, abbreviation) for xml_id, name, abbreviation in rows}
        clements, _avilist = pack.load_base_and_avilist()
        self.context = EngineContext(query_list, clements, TaxonType.GROUP,
                                     users=frozenset(self.users))  # fmt: skip

    def export(self, case: dict[str, Any]) -> EBirdExport:
        _query, results, _root = run_report_query(self.context, self.checklists,
                                                  json.dumps(case["query"]), self.users,
                                                  only_countable=False)  # fmt: skip
        return export(results, self.data)


def _summary(found: EBirdExport) -> list[dict[str, Any]]:
    return [{"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for data in found.files]  # fmt: skip


LISTS = [("queries", "cases"), ("trip_report", "cases.everything"),
         ("edge_cases.ebird", "cases.everything")]  # fmt: skip


@pytest.mark.scythebill
@pytest.mark.parametrize(("bsxm", "cases"), LISTS)
def test_exports_match_scythebill(pack: Any, tmp_path: Path, bsxm: str, cases: str) -> None:
    exporter = Exporter(pack, FIXTURES / "bsxm" / f"{bsxm}.bsxm", tmp_path)
    expected = {line["name"]: line["files"] for line in _jsonl(EBIRD / f"{bsxm}.jsonl")}
    differing = [case["name"] for case in _jsonl(EBIRD / f"{cases}.jsonl")
                 if _summary(exporter.export(case)) != expected[case["name"]]]  # fmt: skip
    assert differing == []


@pytest.mark.private
def test_real_list_exports(pack: Any, tmp_path: Path) -> None:
    """Eric's list (never copied): ``PIPIT_PRIVATE_BSXM``, and in ``PIPIT_PRIVATE_EBIRD``
    PrintOracle's ebird-mode output for it: ``cases.jsonl`` and each case's files."""
    bsxm = os.environ.get("PIPIT_PRIVATE_BSXM")
    oracle = os.environ.get("PIPIT_PRIVATE_EBIRD")
    if not bsxm or not oracle:
        pytest.skip("set PIPIT_PRIVATE_BSXM and PIPIT_PRIVATE_EBIRD to run")
    exporter = Exporter(pack, Path(bsxm), tmp_path)
    differing = []
    for case in _jsonl(Path(oracle) / "cases.jsonl"):
        files = exporter.export(case).files
        for index, data in enumerate(files):
            name = case["name"] if index == 0 else f"{case['name']}-{index}"
            if data != (Path(oracle) / f"{name}.csv").read_bytes():
                differing.append(name)
        if (Path(oracle) / f"{case['name']}-{len(files)}.csv").exists():
            differing.append(f"{case['name']}: fewer files")
    assert differing == []


# ------------------------------------------------------------------ EBirdCsvExportTest


def _sighting(*, location: str | None = "place", date: str | None = "2020-05-01",
              status: str = "none") -> QSighting:  # fmt: skip
    return QSighting(row=1, order=1, taxonomy_id=None, taxon=SightingTaxon.single("spAnaspla"),
                     location_xml_id=location,
                     date=None if date is None else parse_partial_date(date), time=None,
                     trip=None, count=None, heard_only=False, photographed=False, male=False,
                     female=False, adult=False, immature=False, status=status, breeding="",
                     description="")  # fmt: skip


def _data(place_type: str | None = "country", built_in: bool = True) -> EBirdListData:
    places = {"place": QPlace("place", "Place", place_type, None, None, built_in, None, None)}
    from pipit.ebird.record_format import _place

    return EBirdListData({xml_id: _place(place, False, None, None)
                          for xml_id, place in places.items()})  # fmt: skip


def test_missing_location_is_not_acceptable() -> None:
    assert not is_acceptable(_sighting(location=None), _data())


def test_country_location_is_acceptable() -> None:
    assert is_acceptable(_sighting(), _data("country"))


def test_built_in_region_is_not_acceptable() -> None:
    assert not is_acceptable(_sighting(), _data("region"))
    assert is_acceptable(_sighting(), _data("region", built_in=False))


def test_record_not_accepted_is_not_acceptable() -> None:
    assert not is_acceptable(_sighting(status="notAccepted"), _data())


def test_id_uncertain_is_not_acceptable() -> None:
    assert not is_acceptable(_sighting(status="idUncertain"), _data())


def test_list_building_dates() -> None:
    assert is_list_building(None)
    assert not is_list_building(parse_partial_date("2020-05-01"))
    assert is_list_building(parse_partial_date("2020"))


def test_writer_bytes_lag_behind() -> None:
    """Nothing reaches the file until the 10,240-character buffer fills."""
    writer = JavaWriterBytes()
    writer.write("x" * 10239)
    assert writer.count == 0
    writer.write("x")
    assert writer.count == 8192

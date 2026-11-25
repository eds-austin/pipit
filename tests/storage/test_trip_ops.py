"""Trip edits and deletes give exactly Scythebill's file (tools/oracle/TripOps.java on
tests/fixtures/bsxm/trips.bsxm), and one undo takes each back."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_storage import FIXTURES, dump

from pipit.domain.partial_date import (
    after_or_equals,
    before_or_equals,
    common_partial_date,
    compare_partial_dates,
    parse_partial_date,
)
from pipit.storage import integrity
from pipit.storage import trip_ops as ops
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.storage.trip_ops import TripError

Operation = Callable[[sqlite3.Connection], None]


def _row(connection: sqlite3.Connection, xml_id: str) -> int:
    return int(connection.execute("SELECT id FROM trips WHERE xml_id = ?", (xml_id,)).fetchone()[0])


def _delete(xml_id: str) -> Operation:
    return lambda c: (ops.delete_trip(c, _row(c, xml_id)), None)[1]


def _edit(xml_id: str, **changes: Any) -> Operation:
    def apply(c: sqlite3.Connection) -> None:
        current = c.execute(
            "SELECT name, start_date, end_date, location_xml_id, notes FROM trips WHERE xml_id = ?",
            (xml_id,),
        ).fetchone()
        values = {"name": current[0] or "", "start": current[1], "end": current[2],
                  "location_xml_id": current[3], "notes": current[4] or "", **changes}  # fmt: skip
        ops.update_trip(c, _row(c, xml_id), **values)

    return apply


# The same as tools/oracle/run.sh.
CASES: dict[str, Operation] = {
    "delete_coast": _delete("coast"),  # undated ones get 2026-07
    "delete_spring": _delete("spring"),  # 2025-05..2025-06: 2025
    "delete_oneday": _delete("oneday"),  # the day itself
    "delete_span": _delete("span"),  # 2024-12-30..2025-01-02 shares nothing: the start year
    "edit": _edit(
        "coast", name="Oregon coast", start="2026-06-30", end="2026-07-09", notes="Fog, then sun"
    ),
    "move": _edit("coast", location_xml_id="bayare1"),  # Dunes, inside the Coast, stays
    "clear_notes": _edit("coast", notes=""),
}


@pytest.mark.scythebill
@pytest.mark.parametrize("case", sorted(CASES))
def test_trip_changes_match_scythebill(case: str, pack: Any, tmp_path: Path) -> None:
    result = import_bsxm(FIXTURES / "trips.bsxm", tmp_path / "t.pipit", pack.base_taxonomy_id,
                         pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    with ListDatabase.open(result.list_path) as database:
        before = dump(database.connection)
        with database.action(case) as connection:
            CASES[case](connection)
        assert integrity.check(database.connection) == []
        export_bsxm(database, tmp_path / "out.bsxm")
        database.undo()
        assert dump(database.connection) == before
    expected = FIXTURES / f"trips.{case}.scythebill.bsxm"
    assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes()


@pytest.mark.scythebill
def test_refused_edits_change_nothing(pack: Any, tmp_path: Path) -> None:
    result = import_bsxm(FIXTURES / "trips.bsxm", tmp_path / "t.pipit", pack.base_taxonomy_id,
                         pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    with ListDatabase.open(result.list_path) as database:
        before = dump(database.connection)
        refusals = [
            _edit("coast", name="  "),
            _edit("coast", start="2026-07-10"),  # after the end
            _edit("coast", end="banana"),
            _edit("coast", location_xml_id="nowhere"),
        ]
        for refused in refusals:
            with pytest.raises(TripError), database.action("refused") as connection:
                refused(connection)
        assert dump(database.connection) == before


def test_partial_date_rules() -> None:
    p = parse_partial_date
    assert str(common_partial_date(p("2026-07-01"), p("2026-07-08"))) == "2026-07"
    assert common_partial_date(p("2024-12-30"), p("2025-01-02")) is None
    assert compare_partial_dates(p("2026-07-10"), p("2026-07-08")) > 0
    assert compare_partial_dates(p("2010"), p("2010-05")) < 0  # fewer fields first
    # afterOrEquals / beforeOrEquals compare only the bound's fields; a date missing one
    # of them never matches.
    assert after_or_equals(p("2026-07"), p("2026-07-03"))
    assert before_or_equals(p("2026-07-08"), p("2026-07-08"))
    assert not after_or_equals(p("2026-07-01"), p("2026-07"))
    assert not before_or_equals(p("2026-07-08"), p("2026-07-09"))

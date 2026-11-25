"""The Reports screen in the real window (offscreen): conditions change the results at once,
with Scythebill's totals (the same numbers as tools/oracle/QueryOracle.java), the query is
kept as Scythebill's JSON, and choosing a species shows its sightings."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until
from test_enter_screen import Running, _start, _stop, alt, ctrl, key, type_text, wait_focus

from pipit.query import stored
from pipit.storage.lists import import_bsxm
from pipit.storage.stored_query_ops import stored_queries

pytestmark = [pytest.mark.ui, pytest.mark.scythebill]
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "queries.pipit"
    import_bsxm(FIXTURES / "bsxm" / "queries.bsxm", path, pack.base_taxonomy_id,
                pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def _expected(config: str, number: int) -> dict[str, Any]:
    lines = (FIXTURES / "oracle" / f"queries.{config}.jsonl").read_text().splitlines()
    return dict(json.loads(lines[number - 1]))


def test_reports_screen(running: Running) -> None:
    from PySide6.QtCore import Qt

    window = running.window
    reports = running.reports
    ctrl(window, "Key_6")
    wait_until(lambda: running.shell.currentKey == "reports")
    reports.run_now()
    # The empty query: everything (AviList, species), Scythebill's numbers and words.
    everything = _expected("avilist.species", 1)
    wait_until(lambda: reports.totals.startswith("Total species:"))
    assert reports.totals == (f"Total species: {everything['species']:,d} "
                              f"({everything['spuh']} \"sp.\")")  # fmt: skip
    assert reports.sightingCount == everything["sightings"]
    assert reports.results_model.rowCount() == len(everything["taxa"])

    # Location is in Washington: the stored JSON is Scythebill's.
    reports.setRowValue(0, "id", "wa")
    reports.run_now()
    assert reports.query_json() == (
        '{"fields":[{"type":"LOCATION","value":{"type":"IN","id":"wa"},"bool":"ALL"}]}'
    )
    assert reports.totals.startswith(
        f"Total species: {_expected('avilist.species', 2)['species']:,d}"
    )

    # Ctrl+Shift+A adds the next condition (Date), "during 2010": query 7's numbers with WA.
    key(window, "Key_A", Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    wait_until(lambda: reports.rows_model.rowCount() == 2)
    assert reports.rows_model.rows()[1]["type"] == "DATE"
    reports.setRowValue(1, "from", "2010")
    reports.run_now()
    in_wa = reports.totals

    # Never in Oregon (reference query 25), at group depth.
    reports.resetQuery()
    reports.setRowValue(0, "id", "wa")
    reports.addRow()
    reports.setRowType(1, "LOCATION")
    reports.setRowValue(1, "id", "oregon")
    reports.setRowOperation(1, "NEVER")
    reports.run_now()
    assert reports.totals.startswith(
        f"Total species: {_expected('avilist.species', 25)['species']:,d}"
    )
    reports.setDepth("group")
    reports.run_now()
    assert reports.totals.startswith(
        f"Total species: {_expected('avilist.group', 25)['species']:,d}"
    )
    assert in_wa  # the dated query ran too

    # Ctrl+R into the results: the first species is chosen, with its sightings.
    ctrl(window, "Key_R")
    wait_focus(running, "reportResults")
    wait_until(lambda: reports.selectedIndex >= 0)
    assert reports.sightings_model.rowCount() > 0
    first = reports.selectedIndex
    key(window, "Key_Down")
    wait_until(lambda: reports.selectedIndex > first)
    assert not reports.results_model.rows()[reports.selectedIndex]["heading"]

    # A place Scythebill doesn't know: the query is refused, not miscounted.
    reports.set_query_json('{"fields":[{"type":"LOCATION","value":{"type":"IN","id":"nowhere"}}]}')
    reports.run_now()
    assert reports.error and reports.results_model.rowCount() == 0


@pytest.fixture
def with_saved(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "saved.pipit"
    import_bsxm(FIXTURES / "bsxm" / "stored_queries.bsxm", path, pack.base_taxonomy_id,
                pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def _names(running: Running) -> list[str]:
    return [row["name"] for row in running.reports.saved_model.rows()]


def test_saved_reports(with_saved: Running) -> None:
    running = with_saved
    window = running.window
    reports = running.reports
    ctrl(window, "Key_6")
    wait_until(lambda: running.shell.currentKey == "reports")
    wait_until(lambda: reports.saved_model.rowCount() == 8)
    database = running.app.database
    original = stored_queries(database.connection)

    # Every report query loads into the builder unchanged: the builder writes back exactly
    # the JSON Scythebill stored (legacy forms canonical, Gson's escapes, numbers).
    for index, query in enumerate(original):
        reports.loadSaved(index)
        if query.type != stored.REPORTS or query.name == "Broken":
            assert reports.currentSaved != query.name
            continue
        assert reports.currentSaved == query.name
        assert not reports.savedEdited, query.name
        assert stored.canonicalize_query_json(reports.query_json()) == query.persisted

    # Change the loaded query: it is marked edited; Ctrl+S saves it under a new name.
    reports.loadSaved(0)
    reports.setRowOperation(0, "NEVER")
    assert reports.savedEdited
    ctrl(window, "Key_S")
    wait_focus(running, "saveReportName")
    type_text(window, "Never at the lake")
    key(window, "Key_Return")
    wait_until(lambda: len(_names(running)) == 9)
    assert _names(running)[-1] == "Never at the lake"
    assert reports.currentSaved == "Never at the lake" and not reports.savedEdited
    saved = stored_queries(database.connection)[-1]
    assert saved.persisted == reports.query_json()

    # Saving under a taken name replaces that report in its place.
    assert reports.saveAs("Lake Merritt")
    assert _names(running)[0] == "Lake Merritt"
    assert stored_queries(database.connection)[0].persisted == reports.query_json()

    # Ctrl+L into the list; Alt+Down moves; rename and delete; each is one undo.
    ctrl(window, "Key_L")
    wait_focus(running, "savedReports")
    alt(window, "Key_Down")
    wait_until(lambda: _names(running)[:2] == ["Legacy any", "Lake Merritt"])
    assert reports.renameSaved(1, "The lake")
    assert not reports.renameSaved(1, "Legacy any")  # taken
    reports.deleteSaved(0)
    wait_until(lambda: _names(running)[0] == "The lake")
    for _step in range(5):  # delete, rename, move, replace, save
        running.app.undo()
    wait_until(lambda: stored_queries(database.connection) == original)
    assert _names(running) == [query.name for query in original]

"""Importing eBird My Data from the window: the file into the trip report list (without its
observers), answering every question from the keyboard and the dialog's buttons — only the
new dates, a species for the name Pipit doesn't know, leave out duplicates — then the review,
Import, and Ctrl+Z to take it all back. What the import makes is checked against Scythebill
in tests/imports."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until
from test_enter_screen import Running, _start, _stop, ctrl, key, type_text

from pipit.storage.lists import import_bsxm

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "trips.pipit"
    import_bsxm(FIXTURES / "bsxm" / "trip_report.no_observers.bsxm", path,
                pack.base_taxonomy_id, pack.base_taxon_ids(),
                pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def _dialog(running: Running) -> Any:
    from PySide6.QtCore import QObject

    return running.window.findChild(QObject, "importDialog")


def test_import_my_data(running: Running, tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    imports = running.imports
    app = running.app
    before = app.sightingCount
    wait_until(lambda: app.taxaReady, timeout=60)
    imports.start(QUrl.fromLocalFile(str(FIXTURES / "imports" / "my_data.csv")))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "dates", timeout=60)
    assert imports.details["new"] == 9
    key(running.window, "Key_Return")  # "Only new dates" has the focus
    wait_until(lambda: imports.stage == "names", timeout=60)
    assert imports.currentName["common"] == "Pinkish Warbler"
    type_text(running.window, "pink-headed warb")
    wait_until(lambda: imports.matches.rowCount() > 0)
    key(running.window, "Key_Return")
    wait_until(lambda: imports.stage == "review", timeout=60)
    details = imports.details
    assert details["added"] == 26
    assert details["failed"] == 0
    assert details["spuhsDropped"] == 2
    assert details["newPlaces"] == 11  # 8 of the file's own, and 3 built-in counties first used
    assert "Madrona Marsh Preserve, Los Angeles, California, United States" in details["places"]
    assert details["updatedPlaces"] == 1  # Muir Woods gets coordinates and a hotspot
    key(running.window, "Key_Return")  # Import
    wait_until(lambda: imports.stage == "done", timeout=60)
    assert not _dialog(running).property("visible")
    wait_until(lambda: app.sightingCount == before + 26)
    assert app.undoLabel == "Import my_data.csv"
    assert list((tmp_path / "backups").rglob("pre-import-*.zip"))
    ctrl(running.window, "Key_Z")
    wait_until(lambda: app.sightingCount == before)


def test_cancel_and_refusal(running: Running, tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    imports = running.imports
    app = running.app
    wait_until(lambda: app.taxaReady, timeout=60)
    before = app.sightingCount
    imports.start(QUrl.fromLocalFile(str(FIXTURES / "imports" / "my_data.csv")))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "dates", timeout=60)
    key(running.window, "Key_Escape")
    wait_until(lambda: imports.stage == "idle")
    assert app.sightingCount == before
    bad = tmp_path / "bad.csv"
    bad.write_text("Submission ID,Common Name\nS1,Mallard\n", encoding="utf-8")
    imports.start(QUrl.fromLocalFile(str(bad)))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "failed", timeout=60)
    assert "Date" in imports.error
    key(running.window, "Key_Escape")
    wait_until(lambda: imports.stage == "idle")

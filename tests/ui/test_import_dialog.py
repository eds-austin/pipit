"""Importing eBird My Data from the window: the file into the trip report list (without its
observers), answering every question from the keyboard and the dialog's buttons — only the
new dates, a species for the name Pipit doesn't know, leave out duplicates — then the review,
Import, and Ctrl+Z to take it all back. What the import makes is checked against Scythebill
in tests/imports."""

from __future__ import annotations

import sys
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
    bad.write_text("Submission ID,Common Name,Checklist Comments\nS1,Mallard,\n", encoding="utf-8")
    imports.start(QUrl.fromLocalFile(str(bad)))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "failed", timeout=60)
    assert "Date" in imports.error
    key(running.window, "Key_Escape")
    wait_until(lambda: imports.stage == "idle")


def test_import_record_format(running: Running) -> None:
    """The trip list's own Save for eBird file, imported back: every date is in the list
    already (Import anyway), and nearly every sighting (Leave them out). There is no "only
    new dates?" for this format: Scythebill imports every date anyway."""
    from PySide6.QtCore import QUrl

    imports = running.imports
    app = running.app
    wait_until(lambda: app.taxaReady, timeout=60)
    before = app.sightingCount
    imports.start(QUrl.fromLocalFile(str(FIXTURES / "imports" / "trip_report.ebird.csv")))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "allDates", timeout=60)
    key(running.window, "Key_Return")  # Import anyway
    wait_until(lambda: imports.stage == "duplicates", timeout=60)
    # The window counts in AviList: as Scythebill does (record_export_back_avilist)
    assert imports.details["duplicates"] == 77
    key(running.window, "Key_Return")  # Leave them out
    wait_until(lambda: imports.stage == "review", timeout=60)
    assert imports.details["added"] == 6
    key(running.window, "Key_Return")
    wait_until(lambda: imports.stage == "done", timeout=60)
    wait_until(lambda: app.sightingCount == before + 6)


def test_import_life_list(running: Running) -> None:
    """A life list: no question about dates (it isn't a mass export), straight to the name
    Pipit doesn't know, left out with Ctrl+L, then the review."""
    from PySide6.QtCore import QUrl

    imports = running.imports
    app = running.app
    wait_until(lambda: app.taxaReady, timeout=60)
    before = app.sightingCount
    imports.start(QUrl.fromLocalFile(str(FIXTURES / "imports" / "life_list.csv")))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "names", timeout=60)
    ctrl(running.window, "Key_L")
    wait_until(lambda: imports.stage in ("duplicates", "review"), timeout=60)
    if imports.stage == "duplicates":
        key(running.window, "Key_Return")  # Leave them out
        wait_until(lambda: imports.stage == "review", timeout=60)
    assert imports.details["failed"] == 1
    added = imports.details["added"]
    key(running.window, "Key_Return")
    wait_until(lambda: imports.stage == "done", timeout=60)
    wait_until(lambda: app.sightingCount == before + added)


def test_import_scythebill_csv(running: Running) -> None:
    """Scythebill CSV with a name Pipit doesn't know (left out), an unnamed trip and a place
    it can't make (rows Scythebill doesn't import either): three rows not imported."""
    from PySide6.QtCore import QUrl

    imports = running.imports
    app = running.app
    wait_until(lambda: app.taxaReady, timeout=60)
    before = app.sightingCount
    imports.start(QUrl.fromLocalFile(str(FIXTURES / "imports" / "scythebill.csv")))
    _dialog(running).show()
    wait_until(lambda: imports.stage == "names", timeout=60)
    assert imports.formatName == "Scythebill CSV"
    ctrl(running.window, "Key_L")
    wait_until(lambda: imports.stage == "review", timeout=60)
    assert imports.details["failed"] == 3
    added = imports.details["added"]
    key(running.window, "Key_Return")
    wait_until(lambda: imports.stage == "done", timeout=60)
    wait_until(lambda: app.sightingCount == before + added)


def test_import_checklist_download(running: Running) -> None:
    """A checklist downloaded from eBird: refused while eBird access is off (Pipit can't tell
    where it is), imported once it's on (eBird answering from recordings)."""
    from PySide6.QtCore import QUrl

    sys.path.insert(0, str(Path(__file__).parents[1] / "imports"))
    from test_my_data_against_scythebill import recorded_api

    imports = running.imports
    app = running.app
    wait_until(lambda: app.taxaReady, timeout=60)
    before = app.sightingCount
    checklist = QUrl.fromLocalFile(str(FIXTURES / "imports" / "checklists" / "S1004.csv"))
    imports.start(checklist)
    _dialog(running).show()
    wait_until(lambda: imports.stage == "failed", timeout=60)
    assert "eBird access" in imports.error
    key(running.window, "Key_Escape")
    wait_until(lambda: imports.stage == "idle")

    app.update_settings(ebird_online=True)
    imports._make_api = lambda: recorded_api(FIXTURES / "imports" / "ebird_api")
    imports.start(checklist)
    _dialog(running).show()
    wait_until(lambda: imports.stage == "review", timeout=60)
    assert imports.formatName == "eBird checklist"
    assert imports.details["added"] == 2
    key(running.window, "Key_Return")
    wait_until(lambda: imports.stage == "done", timeout=60)
    wait_until(lambda: app.sightingCount == before + 2)


def _item(running: Running, name: str) -> Any:
    """A screen's item by object name (screens load in Loaders: walk the visual tree)."""
    stack = [running.window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return None


def test_settings_turns_ebird_on(running: Running) -> None:
    running.shell.go("settings")
    wait_until(lambda: _item(running, "ebirdOnline") is not None)
    switch = _item(running, "ebirdOnline")
    assert not switch.property("checked")
    switch.setProperty("checked", True)
    switch.toggled.emit()
    wait_until(lambda: running.app.settings.ebird_online)
    assert _item(running, "ebirdKey") is not None

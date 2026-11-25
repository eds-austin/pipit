"""A place's own checklist edited by keyboard in the Locations screen (offscreen): status
digits, Delete, adding by typing, Ctrl+S, undo; Esc twice discards; deleting a checklist."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until
from test_enter_screen import (
    Running,
    _start,
    _stop,
    ctrl,
    database_rows,
    key,
    type_text,
    wait_focus,
)

from pipit.storage.lists import import_bsxm

pytestmark = [pytest.mark.ui, pytest.mark.scythebill]
CHECKLISTS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "checklists.bsxm"
ENTRIES = (
    "SELECT count(*) FROM checklist_entries e JOIN checklists c ON c.id = e.checklist_id "
    "WHERE c.location_xml_id = ?"
)


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "checklists.pipit"
    import_bsxm(CHECKLISTS, path, pack.base_taxonomy_id, pack.base_taxon_ids(),
                pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def _entries(running: Running, place: str) -> int:
    return int(running.app.database.connection.execute(ENTRIES, (place,)).fetchone()[0])


def _choose(running: Running, place_name: str, xml_id: str) -> None:
    ctrl(running.window, "Key_F")
    wait_focus(running, "placeFilter")
    from PySide6.QtCore import Qt

    key(running.window, "Key_A", Qt.KeyboardModifier.ControlModifier)
    type_text(running.window, place_name)
    key(running.window, "Key_Return")
    wait_until(lambda: running.locations.details.get("xmlId") == xml_id)


def test_edit_a_checklist_by_keyboard(running: Running) -> None:
    window = running.window
    checklist = running.checklist
    ctrl(window, "Key_4")
    wait_focus(running, "placeTree")
    _choose(running, "bay area", "bayare")
    assert _entries(running, "bayare") == 152

    ctrl(window, "Key_L")
    wait_focus(running, "checklistRows")
    assert checklist.count == 152 and not checklist.dirty
    key(window, "Key_Down")
    key(window, "Key_6", text="6")  # Endemic
    assert checklist.rows_model.rows()[1]["status"] == "Endemic"
    key(window, "Key_Delete")
    assert checklist.count == 151
    type_text(window, "snowy egret")  # typing goes to the add field
    wait_focus(running, "checklistAdd")
    wait_until(lambda: checklist.matches_model.rowCount() > 0)
    key(window, "Key_Return")
    wait_until(lambda: checklist.count == 152)
    assert checklist.dirty
    ctrl(window, "Key_S")
    wait_until(lambda: not checklist.isOpen)
    assert database_rows(
        running,
        "SELECT count(*) FROM checklist_entries WHERE taxon_ids = 'spEgretthu'",
    ) == [(1,)]
    wait_focus(running, "placeTree")
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(
        running, "SELECT count(*) FROM checklist_entries WHERE taxon_ids = 'spEgretthu'"
    ) == [(0,)])  # fmt: skip

    # Esc once warns about unsaved changes, twice discards them.
    ctrl(window, "Key_L")
    wait_focus(running, "checklistRows")
    key(window, "Key_Delete")
    key(window, "Key_Escape")
    assert checklist.isOpen
    key(window, "Key_Escape")
    wait_until(lambda: not checklist.isOpen)
    assert _entries(running, "bayare") == 152


def test_delete_and_start_checklists(running: Running) -> None:
    window = running.window
    checklist = running.checklist
    ctrl(window, "Key_4")
    wait_focus(running, "placeTree")
    _choose(running, "point reyes", "poirey")
    ctrl(window, "Key_L")
    wait_focus(running, "checklistRows")
    assert checklist.exists
    checklist.deleteChecklist()  # what the dialog's Delete runs
    wait_until(lambda: not checklist.isOpen)
    assert _entries(running, "poirey") == 0
    assert not running.locations.details["hasChecklist"]
    ctrl(window, "Key_Z")
    wait_until(lambda: _entries(running, "poirey") == 1)

    # A place with no checklist starts an empty one; saving needs a species.
    _choose(running, "lake merritt", "lakmer")
    ctrl(window, "Key_L")
    wait_focus(running, "checklistAdd")
    assert not checklist.exists and checklist.count == 0
    assert not checklist.save()
    type_text(window, "mallard")
    wait_until(lambda: checklist.matches_model.rowCount() > 0)
    key(window, "Key_Return")
    wait_until(lambda: checklist.count == 1)
    ctrl(window, "Key_S")
    wait_until(lambda: _entries(running, "lakmer") == 1)

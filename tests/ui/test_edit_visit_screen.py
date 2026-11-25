"""Editing a recorded visit by keyboard: from its place in Locations into Enter sightings,
add a bird, save (replacing the visit's sightings as Scythebill does), undo."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until
from test_enter_screen import Running, _start, _stop, ctrl, database_rows, key, wait_focus
from test_locations_screen import filter_to

from pipit.storage.lists import import_bsxm

pytestmark = [pytest.mark.ui, pytest.mark.scythebill]
VISITS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "visits.bsxm"
AT_VISIT = (
    "SELECT taxon_id, count FROM sightings WHERE location_xml_id = 'lakmer' "
    "AND date = '2026-08-08' AND time = '08:00' ORDER BY ord"
)


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "visits.pipit"
    import_bsxm(VISITS, path, pack.base_taxonomy_id, pack.base_taxon_ids(),
                pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def test_open_a_visit_from_locations_edit_and_undo(running: Running) -> None:
    window = running.window
    entry = running.entry
    before = database_rows(running, AT_VISIT)
    assert len(before) == 7  # six loaded, plus the second Great Egret left alone

    ctrl(window, "Key_4")
    wait_focus(running, "placeTree")
    filter_to(running, "lake")
    wait_until(lambda: running.locations.visits_model.rowCount() == 2)
    ctrl(window, "Key_E")
    wait_focus(running, "visitList")
    key(window, "Key_Return")  # the newest visit: 2026-08-08 08:00

    wait_until(lambda: running.shell.currentKey == "enter")
    wait_until(lambda: entry.rows_model.rowCount() == 6)
    assert entry.dateText == "2026-08-08"
    slot = entry.slots_model.rows()[0]
    assert slot["editing"] == 6 and slot["startTime"] == "08:00"
    assert slot["comments"] == "Calm morning" and slot["duration"]  # the visit record too

    from test_enter_screen import type_text

    ctrl(window, "Key_J")
    wait_focus(running, "speciesField")
    type_text(window, "snowy egret 2")
    wait_until(lambda: entry.matches_model.rowCount() > 0)
    key(window, "Key_Return")
    wait_until(lambda: entry.rows_model.rowCount() == 7)
    ctrl(window, "Key_Return")
    wait_until(lambda: entry.rows_model.rowCount() == 0)

    after = database_rows(running, AT_VISIT)
    assert len(after) == 8
    assert ("spEgretthu", "2") in after
    assert after[0] == ("spArdeaalb", "2")  # the untouched second Great Egret stays first

    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, AT_VISIT) == before)

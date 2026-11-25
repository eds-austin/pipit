"""The Trips screen driven by the keyboard (offscreen): choose a trip, edit it, move it to
another place, delete it, and undo each."""

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
TRIPS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "trips.bsxm"
COAST = "SELECT name, notes, location_xml_id FROM trips WHERE xml_id = 'coast'"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "trips.pipit"
    import_bsxm(TRIPS, path, pack.base_taxonomy_id, pack.base_taxon_ids(),
                pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def test_trips_by_keyboard(running: Running) -> None:
    from PySide6.QtCore import Qt

    window = running.window
    trips = running.trips
    ctrl(window, "Key_5")
    wait_focus(running, "tripList")
    assert trips.trip["name"] == "Coast week"  # the newest
    assert trips.speciesCount == 5 and trips.sightingCount == 6

    # Down chooses the next trip; Up comes back.
    key(window, "Key_Down")
    wait_until(lambda: trips.trip["name"] == "Kent day")
    key(window, "Key_Up")
    wait_until(lambda: trips.trip["name"] == "Coast week")

    # F2 edits: a new name, Enter saves (and returns to the list).
    key(window, "Key_F2")
    wait_focus(running, "tripName")
    key(window, "Key_A", Qt.KeyboardModifier.ControlModifier)
    type_text(window, "Oregon coast")
    key(window, "Key_Return")
    wait_until(lambda: database_rows(running, COAST)[0][0] == "Oregon coast")
    wait_focus(running, "tripList")
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, COAST)[0][0] == "Coast week")

    # Ctrl+P: a new place, then Ctrl+S saves; its sightings at the Coast move along.
    ctrl(window, "Key_P")
    wait_focus(running, "tripPlaceFilter")
    type_text(window, "yaquina")
    key(window, "Key_Return")
    wait_focus(running, "tripName")
    ctrl(window, "Key_S")
    wait_until(lambda: database_rows(running, COAST)[0][2] == "yaqbay")
    assert database_rows(
        running,
        "SELECT count(*) FROM sightings WHERE trip_xml_id = 'coast' AND location_xml_id = 'yaqbay'",
    ) == [(3,)]
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, COAST)[0][2] == "coast")

    # Ctrl+Delete, Enter: the trip goes, its sightings stay; Ctrl+Z brings it back.
    sightings = database_rows(running, "SELECT count(*) FROM sightings")
    key(window, "Key_Delete", Qt.KeyboardModifier.ControlModifier)
    wait_focus(running, "confirmDeleteTrip")
    key(window, "Key_Return")
    wait_until(lambda: database_rows(running, COAST) == [])
    assert database_rows(running, "SELECT count(*) FROM sightings") == sightings
    assert trips.trip["name"] == "Kent day"
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, COAST) != [])

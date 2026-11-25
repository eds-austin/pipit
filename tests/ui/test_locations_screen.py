"""The Locations screen driven by the keyboard in the real window (offscreen): filter the
tree, read what was seen, add, delete and merge places, and undo with Ctrl+Z."""

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

from pipit.storage import integrity
from pipit.storage.lists import import_bsxm

pytestmark = [pytest.mark.ui, pytest.mark.scythebill]
LOCATIONS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "locations.bsxm"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "places.pipit"
    import_bsxm(LOCATIONS, path, pack.base_taxonomy_id, pack.base_taxon_ids())
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def place(running: Running) -> str:
    return str(running.locations.details.get("name", ""))


def species_ready(running: Running) -> None:
    wait_until(lambda: running.locations.speciesReady)


def filter_to(running: Running, text: str) -> None:
    ctrl(running.window, "Key_F")
    wait_focus(running, "placeFilter")
    type_text(running.window, text)
    key(running.window, "Key_Return")
    wait_focus(running, "placeTree")


def test_browse_and_change_places_by_keyboard(running: Running) -> None:  # noqa: PLR0915
    window = running.window
    locations = running.locations
    ctrl(window, "Key_4")
    wait_focus(running, "placeTree")

    # Filter by typing: the first match is chosen, with what was seen there.
    filter_to(running, "lake")
    assert place(running) == "Lake Merritt"
    species_ready(running)
    assert locations.speciesCount == 2  # Mallard and American Black Duck
    assert locations.visits_model.rowCount() == 1

    # Left goes up to the place it is in (its sightings include Lake Merritt's).
    key(window, "Key_Escape")  # nothing to leave in the tree; stays put
    ctrl(window, "Key_F")
    key(window, "Key_Escape")  # clears the filter, back to the tree
    wait_focus(running, "placeTree")
    assert locations.filterText == ""
    key(window, "Key_Left")
    assert place(running) == "Bay Area"
    species_ready(running)
    assert locations.details["sightings"] == 4

    # Enter goes into the species list; Esc comes back.
    key(window, "Key_Return")
    wait_focus(running, "speciesTable")
    key(window, "Key_Escape")
    wait_focus(running, "placeTree")

    # Insert: a new place inside Bay Area.
    key(window, "Key_Insert")
    wait_focus(running, "newPlaceName")
    type_text(window, "Boathouse")
    key(window, "Key_Return")
    wait_until(lambda: place(running) == "Boathouse")
    wait_focus(running, "placeTree")
    assert database_rows(
        running,
        "SELECT p.xml_id FROM locations l JOIN locations p ON p.id = l.parent_id "
        "WHERE l.name = 'Boathouse'",
    ) == [("bayare",)]

    # Delete it again (Enter confirms).
    key(window, "Key_Delete")
    wait_focus(running, "confirmDelete")
    key(window, "Key_Return")
    wait_until(lambda: place(running) == "Bay Area")
    assert database_rows(running, "SELECT 1 FROM locations WHERE name = 'Boathouse'") == []

    # A place with places inside can't be deleted: the dialog doesn't open.
    key(window, "Key_Delete")
    assert locations.details["deleteBlocked"]
    assert place(running) == "Bay Area"

    # Merge Point Reyes into Oregon's Coast: both have a Lighthouse, merged as well.
    sightings = database_rows(running, "SELECT count(*) FROM sightings")
    filter_to(running, "point")
    assert place(running) == "Point Reyes"
    from PySide6.QtCore import Qt

    key(window, "Key_M", Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    wait_focus(running, "pickFilter")
    type_text(window, "coast")
    key(window, "Key_Return")
    wait_until(lambda: place(running) == "Coast")
    wait_focus(running, "placeTree")
    assert database_rows(running, "SELECT 1 FROM locations WHERE xml_id = 'poirey'") == []
    assert database_rows(running, "SELECT count(*) FROM sightings") == sightings
    assert integrity.check(running.app.database.connection) == []
    assert locations.details["sightings"] == 3  # its own 2, plus Point Reyes' Lighthouse

    # One Ctrl+Z undoes the whole merge.
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, "SELECT 1 FROM locations WHERE xml_id = 'poirey'"))
    assert integrity.check(running.app.database.connection) == []
    assert locations.details["sightings"] == 2

"""The Species screen driven by the keyboard (offscreen): filter to a species, go into its
sightings, change a count and save, undo, delete a sighting, and open one's visit."""

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
VISITS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "visits.bsxm"
RUDDY = "SELECT count FROM sightings WHERE taxon_id = 'spOxyurjam'"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "visits.pipit"
    import_bsxm(VISITS, path, pack.base_taxonomy_id, pack.base_taxon_ids(),
                pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def test_species_screen_by_keyboard(running: Running) -> None:
    from PySide6.QtCore import Qt

    window = running.window
    species = running.species
    ctrl(window, "Key_3")
    wait_focus(running, "taxonList")

    # Typing filters; the first match is chosen with its sightings.
    type_text(window, "ruddy")
    wait_focus(running, "speciesFilter")
    wait_until(lambda: species.entry.get("common") == "Ruddy Duck")
    key(window, "Key_Return")
    wait_focus(running, "taxonList")
    # In AviList (the default), Scythebill's Andean Duck is a sp. of two Ruddy Duck
    # subspecies, so it is listed here too, with what was recorded.
    assert species.sightings_model.rowCount() == 2
    assert all(row["asRecorded"] for row in species.sightings_model.rows())

    # Enter: the sightings (Down: the Ruddy Duck one); Enter again: the editor's count.
    key(window, "Key_Return")
    wait_focus(running, "sightingList")
    key(window, "Key_Down")
    wait_until(lambda: species.sighting.get("count") == "12")
    key(window, "Key_Return")
    wait_focus(running, "sightingCount")
    key(window, "Key_A", Qt.KeyboardModifier.ControlModifier)  # select the count
    type_text(window, "15")
    key(window, "Key_Return")  # saves, and goes back to the sightings
    wait_until(lambda: database_rows(running, RUDDY) == [("15",)])

    # Ctrl+Z undoes the edit.
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, RUDDY) == [("12",)])
    assert species.sighting["count"] == "12"

    # Every species, not only those seen: still filtered, still chosen.
    wait_focus(running, "sightingList")  # saving went back to the sightings
    key(window, "Key_A", Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    wait_until(lambda: not species.onlySeen)
    assert species.entry.get("common") == "Ruddy Duck"
    assert species.taxa_model.rowCount() > 1  # unseen ruddy birds too

    # Ctrl+Delete, Enter: the sighting is gone; Ctrl+Z brings it back.
    key(window, "Key_Delete", Qt.KeyboardModifier.ControlModifier)
    wait_focus(running, "confirmDeleteSighting")
    key(window, "Key_Return")
    wait_until(lambda: database_rows(running, RUDDY) == [])
    assert species.entry.get("sightings") == 1
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, RUDDY) == [("12",)])

    # Ctrl+E opens its visit in Enter sightings.
    wait_until(lambda: species.sighting.get("canOpenVisit") is True)
    assert species.sighting["place"].startswith("Lake Merritt")
    ctrl(window, "Key_E")
    wait_until(lambda: running.shell.currentKey == "enter")
    wait_until(lambda: running.entry.rows_model.rowCount() == 6)


def test_every_species_scrolls_smoothly(running: Running) -> None:
    """M4 acceptance: the longest list (all 11,000+ species) moves by key without stalls.
    Each step includes a full redraw; the limits are generous so a busy machine passes."""
    import time

    window = running.window
    ctrl(window, "Key_3")
    wait_focus(running, "taxonList")
    running.species.setOnlySeen(False)
    assert running.species.taxa_model.rowCount() > 10_000

    def step(name: str) -> float:
        started = time.perf_counter()
        key(window, name)
        window.grabWindow()  # forces the frame
        return (time.perf_counter() - started) * 1000

    jumps = [step("Key_End"), step("Key_Home")]
    pages = sorted(step("Key_PageDown") for _ in range(40))
    lines = sorted(step("Key_Down") for _ in range(60))
    assert max(jumps) < 250
    assert pages[len(pages) // 2] < 50 and pages[-1] < 250
    assert lines[len(lines) // 2] < 50 and lines[-1] < 250

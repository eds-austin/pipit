"""Enter Sightings driven only by the keyboard, in the real window (offscreen).

The M3 acceptance test: a two-location day (41 species, one sp., one new place) entered
without the mouse, saved with Ctrl+Enter as two visits, undone with one Ctrl+Z; and an
unsaved session that survives closing the app.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until

from pipit.config.settings import AppSettings
from pipit.storage.lists import import_bsxm

pytestmark = [pytest.mark.ui, pytest.mark.scythebill]
NEW_LIST = Path(__file__).parents[1] / "fixtures" / "bsxm" / "new_list.scythebill.bsxm"

SPECIES = [
    "mallard 12", "gadwall a3 b2", "american wigeon", "northern shoveler a6",
    "bufflehead b4", "ruddy duck", "pied-billed grebe", "eared grebe a2",
    "double-crested cormorant", "brown pelican b7", "great blue heron a1 b1", "great egret",
    "snowy egret", "turkey vulture", "osprey b1", "red-tailed hawk", "red-shouldered hawk",
    "american kestrel", "american coot a40", "killdeer", "black-necked stilt",
    "american avocet ~30", "willet", "marbled godwit", "long-billed curlew",
    "least sandpiper", "western sandpiper", "ring-billed gull", "california gull",
    "western gull b9", "forster's tern", "rock pigeon", "mourning dove",
    "anna's hummingbird a2 b3", "belted kingfisher", "black phoebe", "american crow",
    "common raven", "bushtit b8", "california towhee", "western grebe/clark's grebe b2",
]  # fmt: skip


@dataclass
class Running:
    window: Any
    app: Any
    entry: Any
    shell: Any
    engine: Any
    locations: Any = None
    species: Any = None
    trips: Any = None
    checklist: Any = None
    reports: Any = None
    home: Any = None


def _start(list_path: Path, pack_path: Path, backups: Path) -> Running:
    from PySide6.QtQml import QQmlApplicationEngine

    from pipit.app import QML_DIR
    from pipit.ui.backend.app_controller import AppController
    from pipit.ui.backend.checklist_backend import ChecklistBackend
    from pipit.ui.backend.entry_backend import EntryBackend
    from pipit.ui.backend.home_backend import HomeBackend
    from pipit.ui.backend.locations_backend import LocationsBackend
    from pipit.ui.backend.reports_backend import ReportsBackend
    from pipit.ui.backend.shell import Shell
    from pipit.ui.backend.species_backend import SpeciesBackend
    from pipit.ui.backend.theme import IconProvider
    from pipit.ui.backend.trips_backend import TripsBackend

    settings = AppSettings()
    app = AppController(settings, save=lambda _s: None, pack_path=pack_path,
                        backups_root=backups, load_in_background=False)  # fmt: skip
    assert app.open_path(list_path)
    entry = EntryBackend(app, date(2026, 11, 24))
    locations = LocationsBackend(app)
    species = SpeciesBackend(app)
    trips = TripsBackend(app)
    checklist = ChecklistBackend(app)
    reports = ReportsBackend(app)
    home = HomeBackend(app)
    shell = Shell(settings, save=lambda _s: None)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    engine.addImageProvider("icon", IconProvider())
    for name, value in (("shell", shell), ("app", app), ("entry", entry),
                        ("locations", locations), ("species", species),
                        ("trips", trips), ("checklist", checklist),
                        ("reports", reports), ("home", home)):  # fmt: skip
        engine.rootContext().setContextProperty(name, value)
    engine.setInitialProperties({"appVersion": "test", "maximized": False})
    errors: list[str] = []
    engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    engine.load(QML_DIR / "Main.qml")
    assert engine.rootObjects(), errors
    window = engine.rootObjects()[0]
    window.setProperty("width", 1600)
    window.setProperty("height", 1000)
    window.requestActivate()
    wait_until(window.isActive)
    running = Running(
        window, app, entry, shell, engine, locations, species, trips, checklist, reports, home
    )
    running.errors = errors  # type: ignore[attr-defined]
    return running


def _stop(running: Running) -> None:
    errors = running.errors  # type: ignore[attr-defined]
    running.window.close()
    running.app.close_list()
    del running.engine
    assert not errors, "\n".join(errors)


@pytest.fixture
def list_path(pack: Any, tmp_path: Path) -> Path:
    path = tmp_path / "day.pipit"
    import_bsxm(NEW_LIST, path, pack.base_taxonomy_id, pack.base_taxon_ids())
    return path


@pytest.fixture
def running(qapp: object, list_path: Path, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    started = _start(list_path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


# ------------------------------------------------------------------ keyboard helpers

_SPECIAL = {" ": "Key_Space", "/": "Key_Slash", "'": "Key_Apostrophe", "~": "Key_AsciiTilde",
            "-": "Key_Minus", ".": "Key_Period", "+": "Key_Plus"}  # fmt: skip


def key(window: Any, name: str, modifiers: Any = None, text: str = "") -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QGuiApplication, QKeyEvent

    code = getattr(Qt.Key, name)
    mods = modifiers or Qt.KeyboardModifier.NoModifier
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QGuiApplication.sendEvent(window, QKeyEvent(kind, code, mods, text))
    QGuiApplication.processEvents()


def type_text(window: Any, text: str) -> None:
    for character in text:
        if character in _SPECIAL:
            key(window, _SPECIAL[character], text=character)
        elif character.isdigit():
            key(window, f"Key_{character}", text=character)
        else:
            key(window, f"Key_{character.upper()}", text=character)


def ctrl(window: Any, name: str) -> None:
    from PySide6.QtCore import Qt

    key(window, name, Qt.KeyboardModifier.ControlModifier)


def alt(window: Any, name: str) -> None:
    from PySide6.QtCore import Qt

    key(window, name, Qt.KeyboardModifier.AltModifier)


def focused(running: Running) -> str:
    item = running.window.activeFocusItem()
    while item is not None and not item.objectName():
        item = item.parentItem()
    return "" if item is None else item.objectName()


def wait_focus(running: Running, name: str) -> None:
    try:
        wait_until(lambda: focused(running) == name, timeout=5)
    except AssertionError:
        raise AssertionError(f"expected focus on {name}, got {focused(running)!r}") from None


def database_rows(running: Running, sql: str) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = running.app.database.connection.execute(sql).fetchall()
    return rows


# ------------------------------------------------------------------ the test


def test_two_location_day_by_keyboard_only(running: Running) -> None:  # noqa: PLR0915
    from PySide6.QtCore import QObject

    window = running.window
    ctrl(window, "Key_2")
    wait_until(lambda: running.shell.property("currentKey") == "enter")
    wait_focus(running, "dateField")

    ctrl(window, "Key_A")
    type_text(window, "2026-11-20")
    key(window, "Key_Tab")
    wait_focus(running, "placeField_A")
    assert running.entry.property("dateText") == "2026-11-20"

    # Location A: a built-in county not yet in the list, traveling, with effort.
    type_text(window, "alameda")
    key(window, "Key_Return")
    wait_focus(running, "protocolField_A")
    type_text(window, "t")
    for field, value in (("startTimeField_A", "0730"), ("durationField_A", "90"),
                         ("distanceField_A", "3.2"), ("partyField_A", "2")):  # fmt: skip
        key(window, "Key_Tab")
        wait_focus(running, field)
        type_text(window, value)
    key(window, "Key_Tab")
    wait_focus(running, "completeBox_A")
    key(window, "Key_Space")
    key(window, "Key_Tab")
    wait_focus(running, "commentsField_A")
    type_text(window, "lake loop")
    key(window, "Key_Tab")
    wait_focus(running, "speciesField")

    # Location B: a new place inside California, incidental.
    alt(window, "Key_2")
    wait_focus(running, "placeField_B")
    type_text(window, "lake merritt")
    ctrl(window, "Key_Return")
    type_text(window, "california")
    key(window, "Key_Return")
    wait_focus(running, "protocolField_B")
    type_text(window, "i")

    ctrl(window, "Key_J")
    wait_focus(running, "speciesField")
    for text in SPECIES:
        type_text(window, text)
        try:
            wait_until(lambda: running.entry.matches.rowCount() > 0, timeout=5)
        except AssertionError:
            field = running.window.findChild(QObject, "speciesField")
            raise AssertionError(
                f"no suggestions for {text!r}; focus {focused(running)!r}, "
                f"field {field.property('text')!r}"
            ) from None
        key(window, "Key_Return")
    session = running.entry.session
    assert len(session.rows) == len(SPECIES)
    assert any("/" in row.taxon_id for row in session.rows)
    slot_a, slot_b = session.slots
    assert slot_a.location.code == "US-CA-001" and slot_a.start_time.hour == 7
    assert slot_a.duration_minutes == 90 and slot_a.party_size == 2 and slot_a.complete
    assert slot_b.location.kind.value == "new" and slot_b.location.name == "lake merritt"

    # Adjust one count in the grid: Down from the species field, type, Enter.
    key(window, "Key_Down")
    wait_focus(running, "entryGrid")
    active = running.entry.property("activeSlot")
    type_text(window, "5")
    key(window, "Key_Return")
    wait_focus(running, "entryGrid")
    sp_row = session.rows[-1]
    assert "/" in sp_row.taxon_id and str(sp_row.seen[active].count) == "5"
    # Some AviList species are lumps stored as a Clements sp., so count by storage.
    taxa = running.app.entry_taxa
    sp_sightings = sum(
        len(row.seen) for row in session.rows
        if taxa.stored(row.taxon_id).taxon.type.value == "sp"
    )  # fmt: skip

    expected = sum(len(row.seen) for row in session.rows)
    ctrl(window, "Key_Return")
    wait_until(lambda: running.entry.session is not None and not running.entry.session.rows)
    visits = database_rows(
        running,
        "SELECT location_xml_id, observation_type, start_time, duration_minutes, party_size, "
        "complete FROM visits",
    )
    assert sorted(visits) == sorted([
        ("_scyco_US-CA-001", "traveling", "07:30", 90, 2, 1),
        ("lakmer", "incidental", "", None, None, 0),
    ])  # fmt: skip
    assert database_rows(running, "SELECT count(*) FROM sightings")[0][0] == expected
    sp_count = database_rows(running, "SELECT count(*) FROM sightings WHERE kind = 'sp'")[0][0]
    assert sp_count == sp_sightings
    place = database_rows(running, "SELECT l.name, p.name FROM locations l JOIN locations p "
                                   "ON p.id = l.parent_id WHERE l.xml_id = 'lakmer'")  # fmt: skip
    assert place == [("lake merritt", "California")]

    # One Ctrl+Z takes back the whole day.
    key(window, "Key_Escape")
    ctrl(window, "Key_Z")
    wait_until(lambda: database_rows(running, "SELECT count(*) FROM sightings")[0][0] == 0)
    assert database_rows(running, "SELECT count(*) FROM visits")[0][0] == 0
    assert not database_rows(running, "SELECT 1 FROM locations WHERE xml_id = 'lakmer'")


def test_unsaved_session_survives_closing(
    qapp: object, list_path: Path, built_pack: Path, tmp_path: Path
) -> None:
    first = _start(list_path, built_pack, tmp_path / "backups")
    ctrl(first.window, "Key_2")
    ctrl(first.window, "Key_J")
    wait_focus(first, "speciesField")
    type_text(first.window, "mallard 3")
    key(first.window, "Key_Return")
    end = time.monotonic() + 2  # the draft is written half a second after the change
    from PySide6.QtCore import QCoreApplication

    while time.monotonic() < end and (first.app.load_draft() or "").count("taxon_id") == 0:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    _stop(first)

    second = _start(list_path, built_pack, tmp_path / "backups")
    session = second.entry.session
    assert session is not None and len(session.rows) == 1
    assert str(session.rows[0].seen["A"].count) == "3"
    _stop(second)

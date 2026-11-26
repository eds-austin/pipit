"""Wait for the Qt event loop to reach a state."""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    from PySide6.QtCore import QCoreApplication, QEventLoop

    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the UI")
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.005)


def add_app_context(engine: object, tmp: object) -> list[object]:
    """The ``app``, ``entry``, ``locations`` and ``species`` objects Main.qml expects, with
    no data pack and no list. Returns them so the caller keeps them alive."""
    from pathlib import Path

    from pipit.config.settings import AppSettings
    from pipit.ui.backend.app_controller import AppController
    from pipit.ui.backend.checklist_backend import ChecklistBackend
    from pipit.ui.backend.entry_backend import EntryBackend
    from pipit.ui.backend.home_backend import HomeBackend
    from pipit.ui.backend.imports_backend import ImportsBackend
    from pipit.ui.backend.locations_backend import LocationsBackend
    from pipit.ui.backend.reports_backend import ReportsBackend
    from pipit.ui.backend.settings_backend import SettingsBackend
    from pipit.ui.backend.species_backend import SpeciesBackend
    from pipit.ui.backend.trips_backend import TripsBackend

    app = AppController(
        AppSettings(),
        save=lambda _settings: None,
        pack_path=Path(str(tmp)) / "no-pack.sqlite",
        load_in_background=False,
    )
    entry = EntryBackend(app)
    locations = LocationsBackend(app)
    species = SpeciesBackend(app)
    trips = TripsBackend(app)
    checklist = ChecklistBackend(app)
    reports = ReportsBackend(app, open_url=lambda _url: True)  # never a real browser
    home = HomeBackend(app)
    imports = ImportsBackend(app)
    # Never the real keyring in tests
    settings_backend = SettingsBackend(app, read_key=lambda: None, write_key=lambda _key: None)
    context = engine.rootContext()  # type: ignore[attr-defined]
    context.setContextProperty("app", app)
    context.setContextProperty("entry", entry)
    context.setContextProperty("locations", locations)
    context.setContextProperty("species", species)
    context.setContextProperty("trips", trips)
    context.setContextProperty("checklist", checklist)
    context.setContextProperty("reports", reports)
    context.setContextProperty("home", home)
    context.setContextProperty("imports", imports)
    context.setContextProperty("settings", settings_backend)
    return [
        app,
        entry,
        locations,
        species,
        trips,
        checklist,
        reports,
        home,
        imports,
        settings_backend,
    ]

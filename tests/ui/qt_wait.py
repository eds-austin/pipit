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
    """The ``app`` and ``entry`` objects Main.qml expects, with no data pack and no list.
    Returns them so the caller keeps them alive."""
    from pathlib import Path

    from pipit.config.settings import AppSettings
    from pipit.ui.backend.app_controller import AppController
    from pipit.ui.backend.entry_backend import EntryBackend

    app = AppController(
        AppSettings(),
        save=lambda _settings: None,
        pack_path=Path(str(tmp)) / "no-pack.sqlite",
        load_in_background=False,
    )
    entry = EntryBackend(app)
    context = engine.rootContext()  # type: ignore[attr-defined]
    context.setContextProperty("app", app)
    context.setContextProperty("entry", entry)
    return [app, entry]

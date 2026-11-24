"""Running work off the GUI thread and getting results back onto it."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot

log = logging.getLogger(__name__)


class Dispatcher(QObject):
    """``post(fn)`` from any thread runs ``fn()`` on the thread that created this object
    (the GUI thread)."""

    _call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception:  # never let a UI update kill the event loop
            log.exception("error in GUI-thread callback")

    def post(self, fn: Callable[[], Any]) -> None:
        self._call.emit(fn)


def run_in_thread(name: str, fn: Callable[[], Any]) -> threading.Thread:
    t = threading.Thread(target=fn, name=name, daemon=True)
    t.start()
    return t

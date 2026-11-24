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

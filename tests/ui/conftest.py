from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> Iterator[object]:
    pytest.importorskip("PySide6")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

    QQuickStyle.setStyle("Basic")
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    from PySide6.QtCore import QCoreApplication, QEventLoop

    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the UI")
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.005)

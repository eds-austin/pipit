"""Drive the real main window by keyboard: shortcuts, palette, sidebar, back."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from qt_wait import wait_until

from pipit.config.settings import AppSettings

pytestmark = pytest.mark.ui


@dataclass
class Running:
    shell: Any
    window: Any
    saved: list[AppSettings]


@pytest.fixture
def running(qapp: object) -> Iterator[Running]:
    from PySide6.QtQml import QQmlApplicationEngine

    from pipit.app import QML_DIR
    from pipit.ui.backend.shell import Shell
    from pipit.ui.backend.theme import IconProvider

    saved: list[AppSettings] = []
    shell = Shell(AppSettings(), save=saved.append)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    engine.addImageProvider("icon", IconProvider())
    engine.rootContext().setContextProperty("shell", shell)
    engine.setInitialProperties({"appVersion": "test", "maximized": False})
    errors: list[str] = []
    engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    engine.load(QML_DIR / "Main.qml")
    assert engine.rootObjects(), errors
    window = engine.rootObjects()[0]
    window.requestActivate()
    wait_until(window.isActive)
    yield Running(shell, window, saved)
    assert not errors, "\n".join(errors)
    window.close()
    del engine


def press(window: Any, key: Any, modifier: Any = None) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(window, key, modifier or Qt.KeyboardModifier.NoModifier)


def type_text(window: Any, text: str) -> None:
    """Type lowercase letters (QTest.keyClicks only accepts widgets)."""
    from PySide6.QtCore import Qt

    for character in text:
        press(window, Qt.Key(ord(character.upper())))


def test_ctrl_number_switches_screens(running: Running) -> None:
    from PySide6.QtCore import Qt

    ctrl = Qt.KeyboardModifier.ControlModifier
    press(running.window, Qt.Key.Key_3, ctrl)
    wait_until(lambda: running.shell.property("currentKey") == "species")
    press(running.window, Qt.Key.Key_8, ctrl)
    wait_until(lambda: running.shell.property("currentKey") == "taxonomies")
    press(running.window, Qt.Key.Key_Comma, ctrl)
    wait_until(lambda: running.shell.property("currentKey") == "settings")
    press(running.window, Qt.Key.Key_N, ctrl)
    wait_until(lambda: running.shell.property("currentKey") == "enter")


def test_alt_left_goes_back(running: Running) -> None:
    from PySide6.QtCore import Qt

    press(running.window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: running.shell.property("currentKey") == "locations")
    press(running.window, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: running.shell.property("currentKey") == "home")


def test_palette_runs_a_command_by_keyboard(running: Running) -> None:
    from PySide6.QtCore import Qt

    press(running.window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    type_text(running.window, "spre")
    press(running.window, Qt.Key.Key_Return)
    wait_until(lambda: running.shell.property("currentKey") == "special")


def test_palette_arrow_keys_choose_a_row(running: Running) -> None:
    from PySide6.QtCore import Qt

    press(running.window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    type_text(running.window, "s")  # Species, Settings, Special reports, ...
    press(running.window, Qt.Key.Key_Down)
    press(running.window, Qt.Key.Key_Return)
    wait_until(lambda: running.shell.property("currentKey") not in ("home", "species"))


def test_ctrl_b_collapses_sidebar_and_saves(running: Running) -> None:
    from PySide6.QtCore import Qt

    press(running.window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: running.shell.property("sidebarCollapsed") is True)
    assert running.saved[-1].sidebar_collapsed is True


def test_window_opens_maximized(qapp: object) -> None:
    from PySide6.QtGui import QWindow
    from PySide6.QtQml import QQmlApplicationEngine

    from pipit.app import QML_DIR
    from pipit.ui.backend.shell import Shell

    shell = Shell(AppSettings(), save=lambda _settings: None)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    engine.rootContext().setContextProperty("shell", shell)
    engine.setInitialProperties({"appVersion": "test", "maximized": True})
    engine.load(QML_DIR / "Main.qml")
    window = engine.rootObjects()[0]
    wait_until(lambda: window.visibility() == QWindow.Visibility.Maximized)
    window.close()
    del engine

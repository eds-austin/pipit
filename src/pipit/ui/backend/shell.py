"""The app shell exposed to QML: current screen, back history, sidebar and palette."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
    Slot,
)

from pipit.config.settings import AppSettings, save_settings
from pipit.navigation import COMMANDS, SCREENS, Command, Navigator, filter_commands

_COMMAND_ROLES = {
    Qt.ItemDataRole.UserRole + 1: "key",
    Qt.ItemDataRole.UserRole + 2: "title",
    Qt.ItemDataRole.UserRole + 3: "category",
    Qt.ItemDataRole.UserRole + 4: "shortcut",
}


class CommandListModel(QAbstractListModel):
    """Palette results: roles ``key``, ``title``, ``category``, ``shortcut``."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[Command] = list(COMMANDS)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name.encode()) for role, name in _COMMAND_ROLES.items()}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = _COMMAND_ROLES.get(role)
        return getattr(self._rows[index.row()], name) if name else None

    def set_query(self, query: str) -> None:
        self.beginResetModel()
        self._rows = filter_commands(query)
        self.endResetModel()

    def key_at(self, row: int) -> str:
        return self._rows[row].key if 0 <= row < len(self._rows) else ""


class Shell(QObject):
    """Navigation state for ``Main.qml``. Actions QML must perform itself (opening
    the palette or the key overlay, quitting) arrive as ``actionRequested``."""

    currentChanged = Signal()
    sidebarChanged = Signal()
    actionRequested = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        save: Callable[[AppSettings], None] = save_settings,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._save = save
        self._navigator = Navigator()
        self._palette = CommandListModel()
        self._screens = [
            {
                "key": screen.key,
                "title": screen.title,
                "icon": screen.icon,
                "shortcut": screen.shortcut,
                "description": screen.description,
            }
            for screen in SCREENS
        ]

    # -------------------------------------------------------------- properties

    @Property("QVariantList", constant=True)
    def screens(self) -> list[dict[str, str]]:
        return self._screens

    @Property(int, notify=currentChanged)
    def currentIndex(self) -> int:
        return self._navigator.current_index

    @Property(str, notify=currentChanged)
    def currentKey(self) -> str:
        return self._navigator.current

    @Property(bool, notify=currentChanged)
    def canGoBack(self) -> bool:
        return self._navigator.can_go_back

    @Property(bool, notify=sidebarChanged)
    def sidebarCollapsed(self) -> bool:
        return self._settings.sidebar_collapsed

    @Property(QObject, constant=True)
    def palette(self) -> CommandListModel:
        return self._palette

    # ------------------------------------------------------------------- slots

    @Slot(str)
    def go(self, key: str) -> None:
        if self._navigator.go(key):
            self.currentChanged.emit()

    @Slot()
    def back(self) -> None:
        if self._navigator.back():
            self.currentChanged.emit()

    @Slot()
    def toggleSidebar(self) -> None:
        self._settings = replace(self._settings, sidebar_collapsed=not self.sidebarCollapsed)
        self._save(self._settings)
        self.sidebarChanged.emit()

    @Slot(str)
    def setPaletteQuery(self, query: str) -> None:
        self._palette.set_query(query)

    @Slot(int)
    def runPaletteRow(self, row: int) -> None:
        key = self._palette.key_at(row)
        if key:
            self.runCommand(key)

    @Slot(str)
    def runCommand(self, key: str) -> None:
        if key == "go.back":
            self.back()
        elif key.startswith("go."):
            self.go(key.removeprefix("go."))
        elif key == "app.new-entry":
            self.go("enter")
        elif key == "app.toggle-sidebar":
            self.toggleSidebar()
        else:
            self.actionRequested.emit(key)

"""A list model of plain dicts, with role names taken from the keys (camelCase for QML)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QPersistentModelIndex, Qt


class DictListModel(QAbstractListModel):
    def __init__(self, roles: list[str]) -> None:
        super().__init__()
        self._roles = {Qt.ItemDataRole.UserRole + 1 + i: name for i, name in enumerate(roles)}
        self._rows: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name.encode()) for role, name in self._roles.items()}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self._roles.get(role)
        return self._rows[index.row()].get(name) if name else None

    def reset(self, rows: list[dict[str, Any]]) -> None:
        """Replace the rows without recreating delegates: changed rows are updated in place,
        and rows are added or removed at the end, so views keep focus and position."""
        common = min(len(rows), len(self._rows))
        for index in range(common):
            if self._rows[index] != rows[index]:
                self._rows[index] = rows[index]
                model_index = self.index(index)
                self.dataChanged.emit(model_index, model_index)
        if len(rows) > len(self._rows):
            self.beginInsertRows(QModelIndex(), len(self._rows), len(rows) - 1)
            self._rows.extend(rows[common:])
            self.endInsertRows()
        elif len(rows) < len(self._rows):
            self.beginRemoveRows(QModelIndex(), len(rows), len(self._rows) - 1)
            del self._rows[len(rows) :]
            self.endRemoveRows()

    def rows(self) -> list[dict[str, Any]]:
        return self._rows

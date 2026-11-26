"""The Settings screen's eBird section: whether Pipit may ask eBird's web service (off until
turned on), and the user's eBird API key, kept in the system keyring (never in Pipit's
settings file)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from pipit.ebird import api

log = logging.getLogger(__name__)


class SettingsBackend(QObject):
    changed = Signal()

    def __init__(self, app: Any, *, read_key: Callable[[], str | None] = api.stored_key,
                 write_key: Callable[[str | None], None] = api.store_key) -> None:  # fmt: skip
        super().__init__()
        self._app = app
        self._read_key = read_key
        self._write_key = write_key
        self._has_key: bool | None = None

    @Property(bool, notify=changed)
    def ebirdOnline(self) -> bool:
        return bool(self._app.settings.ebird_online)

    @Slot(bool)
    def setEbirdOnline(self, online: bool) -> None:
        self._app.update_settings(ebird_online=online)
        self.changed.emit()

    @Property(bool, notify=changed)
    def hasEbirdKey(self) -> bool:
        if self._has_key is None:
            self._has_key = self._read_key() is not None
        return self._has_key

    @Slot(str, result=bool)
    def saveEbirdKey(self, key: str) -> bool:
        key = key.strip()
        if not key:
            return False
        try:
            self._write_key(key)
        except Exception as error:  # a keyring backend failing, or none at all
            log.warning("could not store the eBird API key: %s", error)
            self._app.message.emit(f"Could not keep the key in the system keyring: {error}")
            return False
        self._has_key = True
        self.changed.emit()
        self._app.message.emit("eBird API key saved in the system keyring")
        return True

    @Slot()
    def forgetEbirdKey(self) -> None:
        try:
            self._write_key(None)
        except Exception as error:
            log.warning("could not remove the eBird API key: %s", error)
        self._has_key = False
        self.changed.emit()
        self._app.message.emit("eBird API key removed")

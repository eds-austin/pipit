"""XDG Base Directory locations for settings, lists, backups and data packs.

- settings: ``$XDG_CONFIG_HOME/pipit`` (~/.config/pipit)
- lists, backups, data packs: ``$XDG_DATA_HOME/pipit`` (~/.local/share/pipit)
- disposable caches: ``$XDG_CACHE_HOME/pipit``
"""

from __future__ import annotations

import os
from pathlib import Path

from pipit import APP_SLUG


def _xdg(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    # The spec says relative paths are invalid and must be ignored.
    base = Path(value) if value and os.path.isabs(value) else Path.home() / fallback
    return base / APP_SLUG


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def lists_dir() -> Path:
    return data_dir() / "lists"


def backups_dir() -> Path:
    return data_dir() / "backups"


def packs_dir() -> Path:
    return data_dir() / "packs"


def ensure_dirs() -> None:
    """Create all application directories (idempotent)."""
    for directory in (config_dir(), cache_dir(), lists_dir(), backups_dir(), packs_dir()):
        directory.mkdir(parents=True, exist_ok=True)

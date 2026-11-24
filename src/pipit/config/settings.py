"""App-wide settings, stored in ``settings.toml`` in the config directory.

Per-list preferences live in the list database, not here. Unknown keys are ignored
and missing keys take their defaults, so the file survives upgrades both ways.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from pipit.config import paths
from pipit.config.tomlw import dumps

MIN_UI_SCALE = 0.9
MAX_UI_SCALE = 1.6


@dataclass(frozen=True, slots=True)
class AppSettings:
    ui_scale: float = 1.15  # 1.15 gives 15px body text (Scythebill's text is too small)
    sidebar_collapsed: bool = False
    last_list: str = ""

    def validated(self) -> AppSettings:
        """Clamp or replace invalid values (hand-edited files)."""
        return replace(self, ui_scale=min(MAX_UI_SCALE, max(MIN_UI_SCALE, self.ui_scale)))


def settings_path() -> Path:
    return paths.config_dir() / "settings.toml"


def _coerce(default: Any, value: Any) -> Any | None:
    """``value`` if it has the default's type (ints accepted for floats), else None."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, float):
        is_number = isinstance(value, int | float) and not isinstance(value, bool)
        return float(value) if is_number else None
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if isinstance(default, str):
        return value if isinstance(value, str) else None
    return None


def load_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    if not path.exists():
        return AppSettings()
    try:
        with path.open("rb") as file:
            data: dict[str, Any] = tomllib.load(file).get("settings", {})
    except (OSError, tomllib.TOMLDecodeError):
        return AppSettings()
    defaults = AppSettings()
    values: dict[str, Any] = {}
    for field in fields(AppSettings):
        if field.name in data:
            coerced = _coerce(getattr(defaults, field.name), data[field.name])
            if coerced is not None:
                values[field.name] = coerced
    return AppSettings(**values).validated()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    """Write atomically: a crash mid-write leaves the previous file intact."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "# Pipit settings (written by the app).\n\n" + dumps({"settings": asdict(settings)}),
        encoding="utf-8",
    )
    temporary.replace(path)

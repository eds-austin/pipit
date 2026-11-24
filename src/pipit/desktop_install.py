"""Desktop integration for per-user installs (``uv tool install`` / ``pipx``), which
do not install launchers: ``pipit --install-desktop``.

Copies the launcher, icon and AppStream metadata into ``$XDG_DATA_HOME``
(``~/.local/share``), pointing the launcher at the installed command. A system
package installs the same files system-wide instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from pipit import APP_ID, APP_SLUG

PACKAGE_DIR = Path(__file__).resolve().parent
DESKTOP_DIR = PACKAGE_DIR / "ui" / "desktop"
ICON = PACKAGE_DIR / "ui" / "icons" / f"{APP_ID}.svg"
APP_FILE = f"{APP_ID}.desktop"
METAINFO_FILE = f"{APP_ID}.metainfo.xml"


def data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME", "")
    return Path(value) if value and os.path.isabs(value) else Path.home() / ".local" / "share"


def _targets(base: Path) -> dict[str, Path]:
    return {
        "app": base / "applications" / APP_FILE,
        "metainfo": base / "metainfo" / METAINFO_FILE,
        "icon": base / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
    }


def command_path() -> str:
    """Absolute path of the ``pipit`` command being run, so a pipx/uv install points
    at itself even if another copy comes first on PATH."""
    argv0 = Path(sys.argv[0])
    if argv0.name == APP_SLUG:
        return os.path.abspath(argv0)
    return shutil.which(APP_SLUG) or APP_SLUG


def with_exec(text: str, command: str) -> str:
    """Point ``Exec=`` at ``command``, keeping field codes such as ``%f``."""
    quoted = f'"{command}"' if " " in command else command
    lines = []
    for line in text.splitlines():
        if line.startswith("Exec="):
            field_codes = [part for part in line.split()[1:] if part.startswith("%")]
            lines.append(" ".join([f"Exec={quoted}", *field_codes]))
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def install(base: Path | None = None, command: str | None = None) -> list[Path]:
    base = base or data_home()
    command = command or command_path()
    targets = _targets(base)
    for path in targets.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    launcher = (DESKTOP_DIR / APP_FILE).read_text(encoding="utf-8")
    targets["app"].write_text(with_exec(launcher, command), encoding="utf-8")
    shutil.copyfile(DESKTOP_DIR / METAINFO_FILE, targets["metainfo"])
    shutil.copyfile(ICON, targets["icon"])
    _refresh(base)
    return list(targets.values())


def uninstall(base: Path | None = None) -> list[Path]:
    base = base or data_home()
    removed = []
    for path in _targets(base).values():
        if path.exists():
            path.unlink()
            removed.append(path)
    _refresh(base)
    return removed


def _refresh(base: Path) -> None:
    """Let the desktop notice the change (best effort; the tools may be missing)."""
    for command in (
        ["update-desktop-database", str(base / "applications")],
        ["gtk-update-icon-cache", "-qtf", str(base / "icons" / "hicolor")],
        ["kbuildsycoca6"],
    ):
        if shutil.which(command[0]):
            subprocess.run(command, capture_output=True, check=False, timeout=60)

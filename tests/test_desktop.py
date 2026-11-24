"""Per-user desktop integration."""

from __future__ import annotations

import configparser
from pathlib import Path

from pipit import APP_ID, desktop_install


def test_exec_keeps_field_codes() -> None:
    text = "[Desktop Entry]\nExec=pipit %f\nName=Pipit\n"
    assert "Exec=/opt/my apps/pipit" not in desktop_install.with_exec(text, "/opt/my apps/pipit")
    assert 'Exec="/opt/my apps/pipit" %f' in desktop_install.with_exec(text, "/opt/my apps/pipit")
    assert "Exec=/usr/bin/pipit %f" in desktop_install.with_exec(text, "/usr/bin/pipit")


def test_install_and_uninstall(tmp_path: Path) -> None:
    installed = desktop_install.install(base=tmp_path, command="/usr/bin/pipit")
    assert all(path.exists() for path in installed)
    entry = configparser.ConfigParser(interpolation=None)
    entry.read(tmp_path / "applications" / f"{APP_ID}.desktop")
    assert entry["Desktop Entry"]["Exec"] == "/usr/bin/pipit %f"
    assert entry["Desktop Entry"]["Icon"] == APP_ID
    removed = desktop_install.uninstall(base=tmp_path)
    assert sorted(removed) == sorted(installed)
    assert not any(path.exists() for path in installed)

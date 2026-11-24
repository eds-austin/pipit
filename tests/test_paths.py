"""XDG locations honour the environment and ignore relative paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipit.config import paths


def test_absolute_xdg_values_are_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert paths.data_dir() == tmp_path / "data" / "pipit"
    assert paths.lists_dir() == tmp_path / "data" / "pipit" / "lists"
    assert paths.config_dir() == tmp_path / "config" / "pipit"


def test_relative_xdg_values_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "relative/dir")
    assert paths.data_dir() == Path.home() / ".local/share" / "pipit"


def test_ensure_dirs_creates_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable.lower()))
    paths.ensure_dirs()
    for directory in (paths.lists_dir(), paths.backups_dir(), paths.packs_dir()):
        assert directory.is_dir()

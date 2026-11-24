"""App settings load, validate and save atomically."""

from __future__ import annotations

from pathlib import Path

from pipit.config.settings import (
    MAX_UI_SCALE,
    MIN_UI_SCALE,
    AppSettings,
    load_settings,
    save_settings,
)


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "missing.toml") == AppSettings()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    settings = AppSettings(ui_scale=1.3, sidebar_collapsed=True, last_list="/lists/a.pipit")
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert not path.with_suffix(".tmp").exists()


def test_invalid_values_fall_back_or_clamp(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[settings]\nui_scale = 9\nsidebar_collapsed = "yes"\nunknown = 1\n', encoding="utf-8"
    )
    settings = load_settings(path)
    assert settings.ui_scale == MAX_UI_SCALE
    assert settings.sidebar_collapsed is False


def test_integer_scale_is_accepted_and_clamped(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[settings]\nui_scale = 0\n", encoding="utf-8")
    assert load_settings(path).ui_scale == MIN_UI_SCALE


def test_corrupt_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[settings\n", encoding="utf-8")
    assert load_settings(path) == AppSettings()

"""M0 smoke tests: packaging, layering rules and the UI launching cleanly."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import pipit
from pipit.navigation import SCREEN_KEYS

#: Modules that must stay Qt-free so they are testable headless and reusable.
CORE_MODULES = [
    "config",
    "config.paths",
    "config.settings",
    "navigation",
    "desktop_install",
    "taxa.model",
    "taxa.mapped",
    "taxa.xml_reader",
    "taxa.avilist_names",
    "search.indexer",
    "search.taxon_index",
    "datapack.pack",
    "packbuild.build",
    "packbuild.validate",
    "packbuild.cli",
    "domain.report",
    "bsxm.reader",
    "bsxm.writer",
    "bsxm.upgrades",
    "storage.database",
    "storage.lists",
    "storage.cli",
    "storage.drafts",
    "domain.locations",
    "entry.session",
    "entry.commit",
    "entry.taxa",
    "entry.context",
    "browse.locations",
    "storage.location_ops",
]


def test_version_is_set() -> None:
    assert pipit.__version__
    assert pipit.__version__ != "0.0.0+unknown", "package is not installed"


@pytest.mark.parametrize("name", CORE_MODULES)
def test_core_modules_do_not_import_qt(name: str) -> None:
    code = (
        f"import sys, pipit.{name}; "
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6')); "
        "print(','.join(bad)); sys.exit(1 if bad else 0)"
    )
    process = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert process.returncode == 0, f"{name} imported Qt modules: {process.stdout.strip()}"


def test_cli_version() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "pipit", "--version"], capture_output=True, text=True, check=False
    )
    assert process.returncode == 0
    assert pipit.__version__ in process.stdout


def _run(*arguments: str, style: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    environment.pop("QT_QUICK_CONTROLS_STYLE", None)
    if style is not None:
        environment["QT_QUICK_CONTROLS_STYLE"] = style
    return subprocess.run(
        [sys.executable, "-m", "pipit", *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=90,
        check=False,
    )


def _qml_warnings(process: subprocess.CompletedProcess[str]) -> list[str]:
    # QML warnings mean broken bindings or imports even when loading "succeeds".
    return [line for line in process.stderr.splitlines() if ".qml:" in line]


@pytest.mark.ui
def test_ui_launches_offscreen() -> None:
    pytest.importorskip("PySide6")
    process = _run("--smoke-test")
    assert process.returncode == 0, process.stderr
    assert "smoke-test ok" in process.stdout
    assert not _qml_warnings(process), "\n".join(_qml_warnings(process))


@pytest.mark.ui
def test_ui_uses_its_own_themed_style() -> None:
    """Pipit draws from its own tokens on the Basic style whatever the desktop uses."""
    pytest.importorskip("PySide6")
    process = _run("--smoke-test", style="Fusion")
    assert process.returncode == 0, process.stderr
    assert "style=Basic" in process.stdout


@pytest.mark.ui
@pytest.mark.parametrize("screen", SCREEN_KEYS)
def test_every_screen_renders_without_qml_warnings(screen: str, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    shot = tmp_path / f"{screen}.png"
    process = _run("--screen", screen, "--size", "1600x900", "--screenshot", str(shot))
    assert process.returncode == 0, process.stderr
    assert not _qml_warnings(process), "\n".join(_qml_warnings(process))
    assert shot.stat().st_size > 10_000


@pytest.mark.ui
@pytest.mark.parametrize("overlay", ["palette", "keys"])
def test_overlays_render_without_qml_warnings(overlay: str, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    shot = tmp_path / f"{overlay}.png"
    process = _run("--overlay", overlay, "--size", "1600x900", "--screenshot", str(shot))
    assert process.returncode == 0, process.stderr
    assert not _qml_warnings(process), "\n".join(_qml_warnings(process))

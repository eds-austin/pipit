"""Shared fixtures. Tests marked ``scythebill`` need a Scythebill checkout: set
``PIPIT_SCYTHEBILL`` or keep one at ~/Projects/scythebill-birdlist; otherwise they skip."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


def scythebill_root() -> Path | None:
    configured = os.environ.get("PIPIT_SCYTHEBILL")
    root = Path(configured) if configured else Path.home() / "Projects" / "scythebill-birdlist"
    return root if (root / "model").is_dir() else None


@pytest.fixture(scope="session")
def scythebill() -> Path:
    root = scythebill_root()
    if root is None:
        pytest.skip("no Scythebill checkout (set PIPIT_SCYTHEBILL)")
    return root


@pytest.fixture(scope="session")
def built_pack(scythebill: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    from pipit.packbuild.build import build_pack
    from pipit.packbuild.sources import ScythebillSources

    return build_pack(ScythebillSources(scythebill), tmp_path_factory.mktemp("pack"))


@pytest.fixture(scope="session")
def pack(built_pack: Path) -> Iterator[object]:
    from pipit.datapack.pack import DataPack

    with DataPack(built_pack) as opened:
        yield opened

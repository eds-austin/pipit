"""The Special screen's family report in the real window (offscreen): the Reports screen's
query counted by family, order or genus with Scythebill's numbers (the same as
tools/oracle/PrintOracle.java's family mode), sorted, and a group's species listed."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until
from test_enter_screen import Running, _start, _stop, ctrl, key

from pipit.storage.lists import import_bsxm

pytestmark = [pytest.mark.ui, pytest.mark.scythebill]
FIXTURES = Path(__file__).parents[1] / "fixtures"
FAMILY = FIXTURES / "oracle" / "family"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "trip_report.pipit"
    import_bsxm(FIXTURES / "bsxm" / "trip_report.bsxm", path, pack.base_taxonomy_id,
                pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def _expected(name: str) -> dict[str, Any]:
    return dict(json.loads((FAMILY / f"{name}.json").read_text()))


def test_family_report(running: Running) -> None:
    from PySide6.QtCore import Qt

    window = running.window
    special = running.special
    reports = running.reports
    reports.setRowValue(0, "id", "_ct_cosric")  # Costa Rica, as the oracle's case
    ctrl(window, "Key_7")
    wait_until(lambda: running.shell.currentKey == "special")
    special.run_now()
    expected = _expected("costa_rica_avilist")
    families = expected["FAMILY"]
    seen_families = sum(1 for _id, seen, _total in families if seen > 0)
    assert special.checklistName == "Costa Rica"
    assert special.speciesSummary == f"Species: {expected['seen']} of {expected['total']}"
    assert special.groupsSummary == f"Families: {seen_families} of {len(families)}"
    rows = special.groups_model.rows()
    assert [[r["groupId"], r["seen"], r["total"]] for r in rows] == families

    # Ctrl+G: by genus next
    ctrl(window, "Key_G")
    wait_until(lambda: special.groupBy == "GENUS")
    assert special.groups_model.rowCount() == len(expected["GENUS"])
    special.setGroupBy("ORDER")
    assert special.groups_model.rowCount() == len(expected["ORDER"])

    # Most seen first; ties by total, then taxonomic order
    special.setSort("SPECIES_SEEN")
    orders = expected["ORDER"]
    by_seen = sorted(range(len(orders)), key=lambda i: (-orders[i][1], -orders[i][2], i))
    assert [r["groupId"] for r in special.groups_model.rows()] == [orders[i][0] for i in by_seen]

    # Ctrl+R into the groups: the first one's species, seen ones marked
    ctrl(window, "Key_R")
    wait_until(lambda: special.selectedIndex == 0)
    species = special.species_model.rows()
    first = orders[by_seen[0]]
    assert len(species) == first[2]
    assert sum(1 for row in species if row["seen"]) == first[1]
    key(window, "Key_Down", Qt.KeyboardModifier.NoModifier)
    wait_until(lambda: special.selectedIndex == 1)

    # A query change on Reports counts again: the whole world
    reports.resetQuery()
    special.run_now()
    world = _expected("everything_avilist")
    assert special.checklistName == ""
    assert special.speciesSummary == f"Species: {world['seen']:,} of {world['total']:,}"

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
from test_import_dialog import _item

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


@pytest.fixture
def status_running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "checklist_status.pipit"
    import_bsxm(FIXTURES / "bsxm" / "checklist_status.bsxm", path, pack.base_taxonomy_id,
                pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def test_checklist_status(status_running: Running) -> None:
    from PySide6.QtCore import Qt

    running = status_running
    window = running.window
    special = running.special
    expected = {
        (line["taxonomy"], line["choice"]): line["places"]
        for line in map(json.loads, (FIXTURES / "oracle" / "checklist_status" / "expected.jsonl")
                        .read_text().splitlines())
    }  # fmt: skip
    ctrl(window, "Key_7")
    wait_until(lambda: running.shell.currentKey == "special")
    key(window, "Key_2", Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: special.report == "status")
    special.run_now()
    places = expected[("avilist", "NOT_FOUND")]
    rows = special.status_model.rows()
    assert [row["placeId"] for row in rows if row["heading"]] == [p["id"] for p in places]
    assert len(rows) == len(places) + sum(len(p["taxa"]) for p in places)
    assert special.statusNote != ""
    species = sum(len(p["taxa"]) for p in places)
    assert special.statusSummary == f"{species} species at {len(places)} places"

    # Rarities: Costa Rica's checklist, then the list's own at Carara
    special.setStatusChoice("RARITY")
    special.run_now()
    rows = special.status_model.rows()
    headings = [row for row in rows if row["heading"]]
    assert [(r["placeId"], r["custom"]) for r in headings] == [
        (p["id"], p["custom"]) for p in expected[("avilist", "RARITY")]]  # fmt: skip
    assert special.statusNote == ""

    # Ctrl+R into the list (headings skipped); Enter shows the place on Locations
    ctrl(window, "Key_R")
    first = 1  # the row after the first heading
    status_list = _item(running, "statusList")
    wait_until(lambda: status_list.property("currentIndex") == first)
    key(window, "Key_Return", Qt.KeyboardModifier.NoModifier)
    wait_until(lambda: running.shell.currentKey == "locations")
    assert running.locations.details["xmlId"] == rows[0]["placeId"]


@pytest.fixture
def queries_running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "queries.pipit"
    import_bsxm(FIXTURES / "bsxm" / "queries.bsxm", path, pack.base_taxonomy_id,
                pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def test_splits_and_lumps(queries_running: Running) -> None:
    from PySide6.QtCore import Qt

    running = queries_running
    window = running.window
    special = running.special
    ctrl(window, "Key_7")
    wait_until(lambda: running.shell.currentKey == "special")
    key(window, "Key_3", Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: special.report == "splits")
    special.run_now()
    # AviList (the list's display taxonomy): its two versions, the first chosen
    assert [v[0] for v in special.splitsVersions] == ["vs-clements-2026", "avilist-2025"]
    recorded = FIXTURES / "oracle" / "splits" / "everything_avilist.jsonl"
    expected = [json.loads(line) for line in recorded.read_text().splitlines()]
    first = expected[0]
    assert special.splitsTotals.startswith(f"Gained: {first['knownSplitCount']} ")
    rows = special.splits_model.rows()
    sections = ("splits", "possibleSplits", "lumps", "possibleLumps", "possibleLumpOrSplit")
    assert sum(1 for row in rows if not row["heading"]) == sum(len(first[k]) for k in sections)
    special.setSplitsVersion("avilist-2025")
    special.run_now()
    second = expected[1]
    assert special.splitsTotals.startswith(f"Gained: {second['knownSplitCount']} ")
    assert special.splitsError == ""


def test_year_comparison(queries_running: Running) -> None:
    import gzip

    from PySide6.QtCore import Qt

    running = queries_running
    window = running.window
    special = running.special
    ctrl(window, "Key_7")
    wait_until(lambda: running.shell.currentKey == "special")
    key(window, "Key_4", Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: special.report == "years")
    special.run_now()
    recorded = FIXTURES / "oracle" / "years" / "everything_avilist.json.gz"
    expected = json.loads(gzip.decompress(recorded.read_bytes()))
    span = list(range(expected["firstYear"], expected["lastYear"] + 1))
    assert special.yearsSpan == span
    assert special.speciesPerYear == expected["counts"]["WHOLE_YEAR"]
    assert special.yearsRowCount == len(expected["species"])
    # Most sightings first (ties in taxonomic order)
    most = max(s["totalSightings"] for s in expected["species"])
    assert special.years_model.rows()[0]["total"] == most

    # A year: new and missing species in it
    year = span[-1]
    special.selectYear(year)
    special.setYearsFilter("NEW")
    assert special.yearsRowCount == sum(
        1 for s in expected["species"] if s["firstYearEver"] == year
    )
    special.setYearsFilter("MISSING")
    missing = [s for s in expected["species"]
               if not any(row[0] == year for row in s["WHOLE_YEAR"])
               and not s["taxon"].startswith(("SP:", "HYBRID:"))]  # fmt: skip
    assert special.yearsRowCount == len(missing)
    assert special.yearsCellText(0, len(span) - 1).endswith(f"not seen in {year}")

    # A range of years: counted again
    assert special.setYearRange("2000", "2010")
    special.run_now()
    assert special.yearsSpan == list(range(2000, 2011))
    assert not special.setYearRange("2010", "2000")


def test_timeline(queries_running: Running) -> None:
    import gzip

    from PySide6.QtCore import Qt

    running = queries_running
    window = running.window
    special = running.special
    ctrl(window, "Key_7")
    wait_until(lambda: running.shell.currentKey == "special")
    key(window, "Key_5", Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: special.report == "timeline")
    special.run_now()
    recorded = FIXTURES / "oracle" / "timeline" / "everything_avilist.json.gz"
    expected = json.loads(gzip.decompress(recorded.read_bytes()))
    assert special.timelineSummary.startswith(f"Life list: {expected['lifeListTotal']:,} species")
    points = special.lifeListPoints
    assert points[-1][1] == expected["lifeListTotal"]
    assert len(special.milestonePoints) == len(expected["milestones"])
    # Years, most species first
    rows = special.timeline_model.rows()
    assert len(rows) == len(expected["years"])
    assert rows[0]["count"] == max(len(year[1]) for year in expected["years"])
    # Days, newest first; Ctrl+R into them and a day's species, lifers first
    special.setTimelineMode("DAYS")
    special.setTimelineSort("NEWEST_FIRST")
    assert len(special.timeline_model.rows()) == len(expected["days"])
    ctrl(window, "Key_R")
    wait_until(lambda: special.timelineSelected == 0)
    newest = expected["days"][-1]
    species = special.period_species_model.rows()
    assert len(species) == len(newest[1])
    assert sum(1 for row in species if row["lifer"]) == newest[3]
    # Years newest first: decades between them
    special.setTimelineMode("YEARS")
    rows = special.timeline_model.rows()
    assert rows[0]["heading"] and rows[0]["label"].endswith("new")
    special.setTimelineLifersOnly(True)
    assert all(row["lifers"] > 0 for row in special.timeline_model.rows() if not row["heading"])

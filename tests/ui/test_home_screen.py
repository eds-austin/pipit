"""Home in the real window (offscreen): figures are real queries (the life list equals the
Reports screen's empty query; saved reports in their saved order, one Scythebill can run
and Pipit can't marked as such), Enter opens a figure in Reports, and a recent visit opens
in Enter Sightings."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qt_wait import wait_until
from test_enter_screen import Running, _start, _stop, ctrl, key, wait_focus

from pipit.query import stored
from pipit.storage.lists import import_bsxm
from pipit.storage.stored_query_ops import stored_queries

pytestmark = [pytest.mark.ui]
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def running(qapp: object, pack: Any, built_pack: Path, tmp_path: Path) -> Iterator[Running]:
    path = tmp_path / "home.pipit"
    import_bsxm(FIXTURES / "bsxm" / "stored_queries.bsxm", path, pack.base_taxonomy_id,
                pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    started = _start(path, built_pack, tmp_path / "backups")
    yield started
    _stop(started)


def _species(totals: str) -> str:
    """The species figure of Scythebill's totals line ("Total species: 1,234 (…)")."""
    return totals.removeprefix("Total species: ").split(" ")[0]


def test_home(running: Running) -> None:
    window = running.window
    home = running.home
    reports = running.reports
    ctrl(window, "Key_1")
    wait_until(lambda: running.shell.currentKey == "home")
    saved = [q for q in stored_queries(running.app.database.connection)
             if q.type == stored.REPORTS]  # fmt: skip
    wait_until(lambda: home.cards_model.rowCount() == 2 + len(saved))
    cards = home.cards_model.rows()
    assert [card["label"] for card in cards[2:]] == [query.name for query in saved]
    assert next(c for c in cards if c["label"] == "Broken")["value"] == "—"

    # The life list is the Reports screen's whole list.
    reports.resetQuery()
    reports.run_now()
    assert _species(reports.totals) == cards[0]["value"]
    assert home.visits_model.rowCount() > 0
    assert home.backup  # opening the list made today's backup

    # Enter on the third figure (the first saved report) opens it in Reports.
    wait_focus(running, "homeCards")
    key(window, "Key_Right")
    key(window, "Key_Right")
    key(window, "Key_Return")
    wait_until(lambda: running.shell.currentKey == "reports")
    assert reports.currentSaved == saved[0].name
    reports.run_now()
    assert _species(reports.totals) == cards[2]["value"]

    # Ctrl+R on Home, then Enter: the newest visit opens in Enter Sightings.
    ctrl(window, "Key_1")
    wait_until(lambda: running.shell.currentKey == "home")
    ctrl(window, "Key_R")
    wait_focus(running, "homeVisits")
    key(window, "Key_Return")
    wait_until(lambda: running.shell.currentKey == "enter")

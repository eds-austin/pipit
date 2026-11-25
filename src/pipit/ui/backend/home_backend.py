"""Home for QML: figures that matter at a glance, each a real query with Scythebill's
counting (the life list, this year, and every saved report in its saved order), recent
visits, and the latest backup.

The figures are counted on a worker thread with its own read-only connection and query
context (a list of 24,000 sightings takes about half a second to load and count); the
previous figures stay up meanwhile, and a result older than the latest change is dropped.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from pipit.browse.dates import display_date
from pipit.browse.species import place_labels
from pipit.query import stored
from pipit.query.engine import EngineContext, parse_query, run_query
from pipit.query.fields_place_time import UnsupportedQueryError
from pipit.query.fields_simple import QueryJsonError
from pipit.query.model import load_query_list
from pipit.storage.backup import latest_backup
from pipit.storage.stored_query_ops import stored_queries
from pipit.taxa.model import Taxonomy, TaxonType
from pipit.ui.backend.app_controller import AppController
from pipit.ui.backend.dispatch import Dispatcher, run_in_thread
from pipit.ui.backend.list_model import DictListModel

log = logging.getLogger(__name__)
REFRESH_DELAY_MS = 100
RECENT_VISITS = 8
MAX_REPORT_CARDS = 12
LIFE_QUERY = '{"fields":[]}'
YEAR_QUERY = '{"fields":[{"type":"DATE","value":{"type":"THIS_YEAR"},"bool":"ALL"}]}'


class HomeBackend(QObject):
    changed = Signal()

    def __init__(self, app: AppController) -> None:
        super().__init__()
        self._app = app
        self._dispatcher = Dispatcher()
        self._generation = 0
        self._counting = False
        self._backup = ""
        self.cards_model = DictListModel(["key", "label", "value", "sub", "query", "saved"])
        self.visits_model = DictListModel(["date", "time", "place", "placeId", "dateRaw",
                                           "sightings"])  # fmt: skip
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY_MS)
        self._timer.timeout.connect(self.refresh)
        self._active = False
        self._stale = True
        app.listChanged.connect(self._changed)
        app.dataChanged.connect(self._changed)
        app.taxaReadyChanged.connect(self._changed)

    def _changed(self) -> None:
        """Refresh soon if Home is showing; otherwise when it next shows."""
        self._stale = True
        if self._active:
            self._timer.start()

    @Slot(bool)
    def setActive(self, active: bool) -> None:
        self._active = active
        if active and self._stale:
            self._timer.start()

    @Slot()
    def refresh(self) -> None:
        self._stale = False
        self._generation += 1
        database = self._app.database
        if database is None:
            self.cards_model.replace_all([])
            self.visits_model.replace_all([])
            self._backup = ""
            self._counting = False
            self.changed.emit()
            return
        connection = database.connection
        self.visits_model.reset(self._recent_visits(connection))
        newest = latest_backup(self._app.backups_root, database.path)
        self._backup = "" if newest is None else datetime.fromtimestamp(
            newest.stat().st_mtime).strftime("%Y-%m-%d %H:%M")  # fmt: skip
        taxa = self._app.entry_taxa
        if taxa is not None:
            year = datetime.now(UTC).astimezone().year
            wanted = [
                ("life", "Life list", LIFE_QUERY, -1),
                ("year", f"This year \u00b7 {year}", YEAR_QUERY, -1),
            ]
            for index, query in enumerate(stored_queries(connection)):
                if query.type == stored.REPORTS and len(wanted) < MAX_REPORT_CARDS + 2:
                    wanted.append((f"saved:{query.name}", query.name, query.query_json, index))
            generation = self._generation
            path = database.path
            display = taxa.display
            self._counting = True
            run_in_thread("home-figures",
                          lambda: self._count(generation, path, display, wanted))  # fmt: skip
        self.changed.emit()

    def _count(self, generation: int, path: Path, display: Taxonomy,
               wanted: list[tuple[str, str, str, int]]) -> None:  # fmt: skip
        """On a worker thread: every figure, from the list as last committed."""
        cards: list[dict[str, Any]] = []
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                query_list = load_query_list(connection)
                users = frozenset(u for (u,) in connection.execute("SELECT xml_id FROM users"))
            finally:
                connection.close()
            context = EngineContext(query_list, display, TaxonType.SPECIES, users=users)
            cards = [_card(context, users, item) for item in wanted]
        except Exception:
            log.exception("counting Home's figures failed")
        self._dispatcher.post(lambda: self._counted(generation, cards))

    def _counted(self, generation: int, cards: list[dict[str, Any]]) -> None:
        if generation != self._generation:
            return  # the list changed again since: a newer count is on its way
        self._counting = False
        self.cards_model.reset(cards)
        self.changed.emit()

    @Property(bool, notify=changed)
    def counting(self) -> bool:
        return self._counting

    @staticmethod
    def _recent_visits(connection: Any) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT location_xml_id, date, date_y, date_m, date_d, coalesce(time, ''), count(*)
            FROM sightings
            WHERE location_xml_id IS NOT NULL AND date_y IS NOT NULL
            GROUP BY location_xml_id, date, coalesce(time, '')
            ORDER BY date_y DESC, coalesce(date_m, 0) DESC, coalesce(date_d, 0) DESC,
                     coalesce(time, '') DESC
            LIMIT ?
            """,
            (RECENT_VISITS,),
        ).fetchall()
        labels = place_labels(connection) if rows else {}
        return [
            {"date": display_date(year, month, day), "time": time,
             "place": labels.get(place, place), "placeId": place, "dateRaw": date,
             "sightings": sightings}
            for place, date, year, month, day, time, sightings in rows
        ]  # fmt: skip

    @Property(str, notify=changed)
    def backup(self) -> str:
        """When the newest backup was made ("" if none)."""
        return self._backup

    @Property(QObject, constant=True)
    def cards(self) -> DictListModel:
        return self.cards_model

    @Property(QObject, constant=True)
    def visits(self) -> DictListModel:
        return self.visits_model


def _card(context: EngineContext, users: frozenset[str],
          wanted: tuple[str, str, str, int]) -> dict[str, Any]:  # fmt: skip
    """One figure: (key, label, query JSON, index among the saved reports or -1)."""
    key, label, query, saved = wanted
    try:
        results = run_query(parse_query(query, context.query_list, users), context)
    except (QueryJsonError, UnsupportedQueryError, ValueError, KeyError) as error:
        log.info("Home figure %s can't run: %s", label, error)
        value = "\u2014"
        sub = "Can't run in Pipit"
    else:
        value = f"{results.countable_species_size(False):,d}"
        families = results.family_count()
        sub = f"{families:,d} {'family' if families == 1 else 'families'}"
    return {"key": key, "label": label, "value": value, "sub": sub, "query": query,
            "saved": saved}  # fmt: skip

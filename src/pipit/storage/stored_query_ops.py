"""Stored queries ("saved reports") in a Pipit list: read from and written to the list's
preferences exactly as Scythebill keeps them (``pipit.query.stored``), each change one undo
step. Only ``storedQueries`` changes; the rest of the preferences is kept as it was."""

from __future__ import annotations

import sqlite3

from pipit.query import stored
from pipit.query.stored import StoredQuery
from pipit.storage.database import ListDatabase


def preferences_json(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT json FROM report_prefs WHERE id = 1").fetchone()
    return row[0] if row else None


def stored_queries(connection: sqlite3.Connection) -> list[StoredQuery]:
    return stored.read(preferences_json(connection))


def save_stored_queries(database: ListDatabase, queries: list[StoredQuery], label: str) -> None:
    """Write the whole list of stored queries (Scythebill's ``updatePreferences``)."""
    with database.action(label) as connection:
        text = stored.write(preferences_json(connection), queries)
        connection.execute(
            "INSERT INTO report_prefs (id, json) VALUES (1, ?) "
            "ON CONFLICT (id) DO UPDATE SET json = excluded.json",
            (text,),
        )

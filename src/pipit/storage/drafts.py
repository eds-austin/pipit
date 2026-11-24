"""The unsaved Enter Sightings session of a list (one per list)."""

from __future__ import annotations

from datetime import UTC, datetime

from pipit.storage.database import ListDatabase


def save_draft(database: ListDatabase, session_json: str) -> None:
    """Store the draft at once (its own tiny transaction; never part of undo)."""
    if database.read_only:
        return
    database.connection.execute(
        "INSERT INTO entry_drafts VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "saved_at = excluded.saved_at, session = excluded.session",
        (datetime.now(UTC).isoformat(), session_json),
    )


def load_draft(database: ListDatabase) -> str | None:
    row = database.connection.execute("SELECT session FROM entry_drafts WHERE id = 1").fetchone()
    return None if row is None else str(row[0])


def clear_draft(database: ListDatabase) -> None:
    if not database.read_only:
        database.connection.execute("DELETE FROM entry_drafts")

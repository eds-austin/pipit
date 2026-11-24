"""A list database: connection settings, one transaction per user action, undo and redo.

- WAL journal, ``synchronous=FULL``, foreign keys on: a committed action survives a crash.
- ``action(label)`` wraps one user action in ``BEGIN IMMEDIATE`` ... ``COMMIT``; any error
  rolls back everything, and the action is recorded for undo.
- ``undo()`` and ``redo()`` replay the recorded inverse statements in reverse order, inside
  one transaction, while recording the inverse of *that* for the opposite stack.
- ``bulk(label)`` is for imports: one transaction, not journaled (too large); callers
  take a backup snapshot first instead.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pipit.storage import migrate

#: Undo history kept per list.
UNDO_LIMIT = 200


class ReadOnlyError(RuntimeError):
    pass


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None
        )
    else:
        connection = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


class ListDatabase:
    """An open list. Use ``ListDatabase.create`` or ``ListDatabase.open``."""

    def __init__(self, path: Path, connection: sqlite3.Connection, read_only: bool) -> None:
        self.path = path
        self.connection = connection
        self.read_only = read_only

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def create(cls, path: Path) -> ListDatabase:
        if path.exists():
            raise FileExistsError(f"{path} already exists")
        connection = connect(path)
        migrate.migrate(connection)
        return cls(path, connection, read_only=False)

    @classmethod
    def open(cls, path: Path, read_only: bool = False) -> ListDatabase:
        """Open an existing list, migrating it if needed (unless read-only)."""
        if not path.is_file():
            raise FileNotFoundError(f"no list at {path}")
        connection = connect(path, read_only)
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        if application_id != migrate.APPLICATION_ID:
            connection.close()
            raise migrate.SchemaError(f"{path.name} is not a Pipit list")
        if not read_only:
            migrate.migrate(connection)
        elif migrate.pending(connection):
            connection.close()
            raise migrate.SchemaError(f"{path.name} needs a schema upgrade; open it normally")
        return cls(path, connection, read_only)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ListDatabase:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    # ------------------------------------------------------------ transactions

    def _writable(self) -> None:
        if self.read_only:
            raise ReadOnlyError(f"{self.path.name} is open read-only")

    @contextmanager
    def bulk(self, label: str) -> Iterator[sqlite3.Connection]:
        """One unjournaled transaction (imports)."""
        self._writable()
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            self._set_meta(connection, "last_change", label)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    @contextmanager
    def action(self, label: str) -> Iterator[sqlite3.Connection]:
        """One user action: atomic, and recorded for undo."""
        self._writable()
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            action_id = self._new_action(connection, "undo", label)
            connection.execute(
                "UPDATE undo_state SET recording_action = ? WHERE id = 1", (action_id,)
            )
            yield connection
            connection.execute("UPDATE undo_state SET recording_action = NULL WHERE id = 1")
            if not connection.execute(
                "SELECT 1 FROM undo_log WHERE action_id = ? LIMIT 1", (action_id,)
            ).fetchone():
                connection.execute("DELETE FROM undo_actions WHERE id = ?", (action_id,))
            else:
                connection.execute("DELETE FROM undo_actions WHERE stack = 'redo'")
                self._prune(connection)
            self._set_meta(connection, "last_change", label)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _new_action(connection: sqlite3.Connection, stack: str, label: str) -> int:
        cursor = connection.execute(
            "INSERT INTO undo_actions(stack, label, created_at) VALUES (?, ?, ?)",
            (stack, label, datetime.now(UTC).isoformat()),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        connection.execute(
            "DELETE FROM undo_actions WHERE stack = 'undo' AND id NOT IN "
            "(SELECT id FROM undo_actions WHERE stack = 'undo' ORDER BY id DESC LIMIT ?)",
            (UNDO_LIMIT,),
        )

    @staticmethod
    def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ------------------------------------------------------------ undo / redo

    def undo_label(self) -> str | None:
        return self._top("undo")

    def redo_label(self) -> str | None:
        return self._top("redo")

    def _top(self, stack: str) -> str | None:
        row = self.connection.execute(
            "SELECT label FROM undo_actions WHERE stack = ? ORDER BY id DESC LIMIT 1", (stack,)
        ).fetchone()
        return row[0] if row else None

    def undo(self) -> str | None:
        """Undo the latest action; returns its label, or None if there is nothing to undo."""
        return self._replay("undo", "redo")

    def redo(self) -> str | None:
        return self._replay("redo", "undo")

    def _replay(self, source: str, target: str) -> str | None:
        self._writable()
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT id, label FROM undo_actions WHERE stack = ? ORDER BY id DESC LIMIT 1",
                (source,),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return None
            action_id, label = row
            statements = [
                statement
                for (statement,) in connection.execute(
                    "SELECT statement FROM undo_log WHERE action_id = ? ORDER BY id DESC",
                    (action_id,),
                )
            ]
            connection.execute("PRAGMA defer_foreign_keys = ON")
            inverse_id = self._new_action(connection, target, label)
            connection.execute(
                "UPDATE undo_state SET recording_action = ? WHERE id = 1", (inverse_id,)
            )
            for statement in statements:
                connection.execute(statement)
            connection.execute("UPDATE undo_state SET recording_action = NULL WHERE id = 1")
            connection.execute("DELETE FROM undo_actions WHERE id = ?", (action_id,))
            self._set_meta(connection, "last_change", f"{source}: {label}")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return str(label)

    # ------------------------------------------------------------ meta

    def meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

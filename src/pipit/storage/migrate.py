"""Schema migrations and the generated undo triggers.

Migrations are numbered SQL files in ``storage/migrations``; each is applied once, in a
transaction, and recorded with its SHA-256 so an edited migration is detected. After
migrating, the undo triggers are regenerated from the live table definitions, so a new
table or column can never be left out of the journal.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
APPLICATION_ID = 0x50495049  # "PIPI": a Pipit list
#: Tables the undo journal never records.
UNJOURNALED = frozenset({
    "undo_actions", "undo_log", "undo_state", "schema_migrations", "entry_drafts",
    "location_closure",  # derived from locations by its own triggers
})  # fmt: skip


class SchemaError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def migrations() -> list[Migration]:
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        found.append(Migration(int(path.name[:4]), path))
    versions = [migration.version for migration in found]
    if versions != list(range(1, len(found) + 1)):
        raise SchemaError(f"migrations must be numbered 1..n, found {versions}")
    return found


def latest_version() -> int:
    return len(migrations())


def current_version(connection: sqlite3.Connection) -> int:
    version: int = connection.execute("PRAGMA user_version").fetchone()[0]
    return version


def pending(connection: sqlite3.Connection) -> list[Migration]:
    version = current_version(connection)
    if version > latest_version():
        raise SchemaError(
            f"this list was made by a newer Pipit (schema {version}; this version reads "
            f"up to {latest_version()})"
        )
    return [migration for migration in migrations() if migration.version > version]


def migrate(connection: sqlite3.Connection) -> list[int]:
    """Apply pending migrations; returns the versions applied. One transaction each."""
    applied = []
    for migration in pending(connection):
        connection.execute("BEGIN IMMEDIATE")
        try:
            if migration.version == 1:
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute(
                    "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, "
                    "applied_at TEXT NOT NULL, sha256 TEXT NOT NULL) STRICT"
                )
            for statement in _statements(migration.sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                (migration.version, datetime.now(UTC).isoformat(), migration.sha256),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            install_undo_triggers(connection)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        applied.append(migration.version)
    return applied


def verify_applied(connection: sqlite3.Connection) -> list[str]:
    """Problems with recorded migrations (an applied file that has since changed)."""
    problems = []
    by_version = {migration.version: migration for migration in migrations()}
    for version, sha256 in connection.execute("SELECT version, sha256 FROM schema_migrations"):
        migration = by_version.get(version)
        if migration is not None and migration.sha256 != sha256:
            problems.append(f"migration {version} changed after it was applied")
    return problems


def _statements(script: str) -> list[str]:
    """Split a migration into statements with SQLite's own tokenizer (which understands
    comments, strings and trigger bodies)."""
    statements = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement.rstrip(";").strip():
                statements.append(statement)
    if buffer.strip() and not all(
        part.strip().startswith("--") or not part.strip() for part in buffer.splitlines()
    ):
        raise SchemaError("a migration ends with an incomplete statement")
    return statements


def journaled_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        if name not in UNJOURNALED
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def install_undo_triggers(connection: sqlite3.Connection) -> None:
    """(Re)create the AFTER INSERT/UPDATE/DELETE triggers that log inverse statements."""
    for (name,) in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'trigger' AND name LIKE 'undo_%'"
    ).fetchall():
        connection.execute(f'DROP TRIGGER "{name}"')
    recording = "(SELECT recording_action FROM undo_state WHERE id = 1)"
    for table in journaled_tables(connection):
        columns = _columns(connection, table)
        quoted = [f'"{column}"' for column in columns]
        log = f"INSERT INTO undo_log(action_id, statement) VALUES ({recording}, "
        when = f"WHEN {recording} IS NOT NULL"
        insert_inverse = f"'DELETE FROM \"{table}\" WHERE rowid = ' || NEW.rowid"
        update_inverse = (
            f'\'UPDATE "{table}" SET '
            + " || ', ".join(f"{q} = ' || quote(OLD.{q})" for q in quoted)
            + " || ' WHERE rowid = ' || OLD.rowid"
        )
        delete_inverse = (
            f'\'INSERT INTO "{table}"(rowid, {", ".join(quoted)}) '
            "VALUES (' || OLD.rowid || ', ' || "
            + " || ', ' || ".join(f"quote(OLD.{q})" for q in quoted)
            + " || ')'"
        )
        for event, inverse in (
            ("INSERT", insert_inverse),
            ("UPDATE", update_inverse),
            ("DELETE", delete_inverse),
        ):
            connection.execute(
                f'CREATE TRIGGER "undo_{table}_{event.lower()}" AFTER {event} ON "{table}" '
                f"{when} BEGIN {log}{inverse}); END"
            )

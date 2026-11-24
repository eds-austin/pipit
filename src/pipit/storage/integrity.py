"""Checks run when a list is opened. Any problem opens the list read-only ("repair mode"),
so nothing is written on top of damage; the user can then restore a backup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Container

from pipit.storage import migrate

_CHECKS = (
    ("sp. or hybrid sightings with fewer than two taxa",
     "SELECT s.id FROM sightings s WHERE s.kind IN ('sp', 'hybrid') AND "
     "(SELECT count(*) FROM sighting_taxa t WHERE t.sighting_id = s.id) < 2"),
    ("single sightings with sp. parts",
     "SELECT s.id FROM sightings s WHERE s.kind IN ('single', 'ssp') AND EXISTS "
     "(SELECT 1 FROM sighting_taxa t WHERE t.sighting_id = s.id)"),
    ("sightings of unknown extended taxa",
     "SELECT s.id FROM sightings s WHERE s.taxonomy_id IS NOT NULL AND s.kind = 'single' AND "
     "NOT EXISTS (SELECT 1 FROM ext_taxa x WHERE x.taxonomy_id = s.taxonomy_id "
     "AND x.taxon_id = s.taxon_id)"),
    ("duplicate sighting order",
     "SELECT ord FROM sightings GROUP BY ord HAVING count(*) > 1"),
    ("an undo action still recording",
     "SELECT 1 FROM undo_state WHERE recording_action IS NOT NULL"),
)  # fmt: skip


def check(
    connection: sqlite3.Connection,
    base_taxon_ids: Container[str] | None = None,
    full: bool = False,
) -> list[str]:
    """Problems found; empty when the list is healthy. ``full`` runs SQLite's complete
    integrity check instead of the quick one."""
    problems = []
    pragma = "integrity_check" if full else "quick_check"
    result = connection.execute(f"PRAGMA {pragma}").fetchall()
    if result != [("ok",)]:
        problems.append(f"SQLite {pragma}: " + "; ".join(row[0] for row in result[:5]))
        return problems  # nothing else can be trusted
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        problems.append(f"{len(violations)} broken references, e.g. {violations[0]}")
    problems += migrate.verify_applied(connection)
    for description, sql in _CHECKS:
        rows = connection.execute(sql).fetchmany(3)
        if rows:
            problems.append(f"{description} (e.g. {rows[0][0]})")
    problems += _check_location_tree(connection)
    if base_taxon_ids is not None:
        problems += _check_base_taxa(connection, base_taxon_ids)
    return problems


def _check_location_tree(connection: sqlite3.Connection) -> list[str]:
    parents = dict(connection.execute("SELECT id, parent_id FROM locations").fetchall())
    for start in parents:
        seen = set()
        current = start
        while current is not None:
            if current in seen:
                return [f"the location tree has a cycle at location row {start}"]
            seen.add(current)
            current = parents.get(current)
    return []


def _check_base_taxa(connection: sqlite3.Connection, known: Container[str]) -> list[str]:
    unknown = [
        taxon_id
        for (taxon_id,) in connection.execute(
            "SELECT taxon_id FROM sightings WHERE taxonomy_id IS NULL AND taxon_id IS NOT NULL "
            "UNION SELECT t.taxon_id FROM sighting_taxa t JOIN sightings s ON s.id = t.sighting_id "
            "WHERE s.taxonomy_id IS NULL"
        )
        if taxon_id not in known
    ]
    if unknown:
        return [f"{len(unknown)} sightings of taxa missing from the data pack, e.g. {unknown[0]}"]
    return []

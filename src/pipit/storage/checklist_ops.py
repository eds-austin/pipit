"""Custom checklists: reading, saving and deleting one, written exactly as Scythebill writes
them (each call runs inside the caller's ``ListDatabase.action``, so it is one undo step).

Scythebill's checklist editor (``EditChecklistPanel``) keeps its rows in taxonomic order and,
on OK, rebuilds the checklist as ``Maps.newHashMapWithExpectedSize(rows)`` filled in that
order, which ``ClementsChecklist`` copies keeping the hash order. So a saved checklist's
entries come out in Java ``HashMap`` order (``pipit.domain.java_hash``), not in the order
shown, and that is the order Pipit stores and exports. A list that is new goes after the
others (``LinkedHashMap.put``); an edited one keeps its place.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pipit.domain.java_hash import guava_capacity, hashmap_order, sighting_taxon_hash
from pipit.domain.report import CHECKLIST_STATUS_TEXTS

STATUSES = (None, *CHECKLIST_STATUS_TEXTS)  # None: native


class ChecklistError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChecklistEntry:
    kind: str  # "single", "ssp", "sp" or "hybrid"
    taxon_ids: tuple[str, ...]  # sorted for sp. and hybrid
    subspecies: str | None = None
    status: str | None = None  # None: native

    @property
    def identity(self) -> tuple[str, tuple[str, ...], str | None]:
        return (self.kind, self.taxon_ids, self.subspecies)

    def java_hash(self) -> int:
        return sighting_taxon_hash(self.kind, self.taxon_ids, self.subspecies)


def has_checklist(connection: sqlite3.Connection, location_xml_id: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM checklists WHERE location_xml_id = ?", (location_xml_id,)
        ).fetchone()
        is not None
    )


def read_checklist(connection: sqlite3.Connection, location_xml_id: str) -> list[ChecklistEntry]:
    """The entries in stored (file) order; empty if the place has no checklist."""
    return [
        ChecklistEntry(kind, tuple(ids.split(",")), subspecies, status)
        for kind, ids, subspecies, status in connection.execute(
            "SELECT e.kind, e.taxon_ids, e.subspecies, e.status FROM checklist_entries e "
            "JOIN checklists c ON c.id = e.checklist_id WHERE c.location_xml_id = ? "
            "ORDER BY e.ord",
            (location_xml_id,),
        )
    ]


def save_checklist(
    connection: sqlite3.Connection, location_xml_id: str, entries: list[ChecklistEntry]
) -> None:
    """Save the checklist with ``entries`` given in the editor's (taxonomic) order."""
    seen = set()
    for entry in entries:
        if entry.status not in STATUSES:
            raise ChecklistError(f"Unknown checklist status {entry.status}.")
        if entry.identity in seen:
            raise ChecklistError("A species is on the checklist twice.")
        seen.add(entry.identity)
    if not connection.execute(
        "SELECT 1 FROM locations WHERE xml_id = ?", (location_xml_id,)
    ).fetchone():
        raise ChecklistError("That place no longer exists.")
    ordered = hashmap_order(
        entries, [entry.java_hash() for entry in entries], guava_capacity(len(entries))
    )
    found = connection.execute(
        "SELECT id FROM checklists WHERE location_xml_id = ?", (location_xml_id,)
    ).fetchone()
    if found is None:
        order = connection.execute("SELECT coalesce(max(ord), -1) + 1 FROM checklists").fetchone()
        cursor = connection.execute(
            "INSERT INTO checklists(location_xml_id, ord) VALUES (?, ?)",
            (location_xml_id, order[0]),
        )
        checklist_id = cursor.lastrowid
    else:
        checklist_id = found[0]
        connection.execute("DELETE FROM checklist_entries WHERE checklist_id = ?", (checklist_id,))
    connection.executemany(
        "INSERT INTO checklist_entries(checklist_id, ord, kind, taxon_ids, subspecies, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(checklist_id, index, entry.kind, ",".join(entry.taxon_ids), entry.subspecies,
          entry.status) for index, entry in enumerate(ordered)],
    )  # fmt: skip


def delete_checklist(connection: sqlite3.Connection, location_xml_id: str) -> None:
    """``ReportSetExtensions.removeChecklist`` (its entries go with it)."""
    cursor = connection.execute(
        "DELETE FROM checklists WHERE location_xml_id = ?", (location_xml_id,)
    )
    if cursor.rowcount == 0:
        raise ChecklistError("That place has no checklist of its own.")

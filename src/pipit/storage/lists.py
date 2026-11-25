"""Opening, importing and exporting lists.

Import is all-or-nothing and self-checking: the ``.bsxm`` is read and upgraded, every taxon
is checked against the data pack, the list is written in one transaction, and then the
stored list is exported and compared byte for byte with the in-memory export. Any
difference deletes the new list and raises, so an import can never quietly lose data.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Container
from dataclasses import dataclass, field
from pathlib import Path

from pipit.bsxm.reader import BsxmError, read_bsxm
from pipit.bsxm.upgrades import apply_upgrades, check_upgradable
from pipit.bsxm.writer import write_bsxm
from pipit.domain.locations import PredefinedLocations
from pipit.domain.report import ReportSet
from pipit.storage import backup, integrity
from pipit.storage.database import ListDatabase
from pipit.storage.location_ops import reassign_new_built_in_locations
from pipit.storage.repository import load_report, save_report
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

LIST_SUFFIX = ".pipit"


class ImportFailedError(RuntimeError):
    pass


@dataclass
class ImportResult:
    list_path: Path
    sightings: int
    locations: int
    visits: int
    upgrades_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class OpenedList:
    database: ListDatabase
    problems: list[str]

    @property
    def read_only(self) -> bool:
        return self.database.read_only


def unknown_taxa(report: ReportSet, base_taxon_ids: Container[str]) -> list[str]:
    """Taxon IDs the list uses that neither the data pack nor its own taxonomies know."""
    extended = {taxonomy.id: taxonomy for taxonomy in report.extended_taxonomies}
    unknown: dict[str, None] = {}

    def check(taxon: SightingTaxon, taxonomy_id: str | None) -> None:
        ids = taxon.ids
        if taxonomy_id is None:
            missing = [taxon_id for taxon_id in ids if taxon_id not in base_taxon_ids]
        else:
            missing = [t for t in ids if extended[taxonomy_id].get(t) is None]
        for taxon_id in missing:
            unknown[taxon_id if taxonomy_id is None else f"{taxonomy_id}:{taxon_id}"] = None

    for sighting in report.sightings:
        check(sighting.taxon, sighting.taxonomy_id)
    for checklist in report.checklists:
        for entry in checklist.entries:
            if entry.taxon.type is not SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
                check(entry.taxon, None)
    return list(unknown)


def import_bsxm(
    source: Path,
    target: Path,
    base_taxonomy_id: str,
    base_taxon_ids: Container[str],
    predefined: PredefinedLocations | None = None,
) -> ImportResult:
    """Create the list ``target`` from the Scythebill file ``source``.

    With ``predefined``, Scythebill's on-load ``ReassignNewBuiltInLocations`` runs too
    (after the stored list has been checked against the file), so the list matches what
    Scythebill shows after opening the same file."""
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    try:
        result = read_bsxm(source, base_taxonomy_id, base_taxon_ids)
    except BsxmError as error:
        raise ImportFailedError(f"{source.name}: {error}") from error
    report = result.report
    check_upgradable(report, base_taxonomy_id)
    applied = apply_upgrades(report)
    unknown = unknown_taxa(report, base_taxon_ids)
    if unknown:
        raise ImportFailedError(
            f"{source.name} uses {len(unknown)} taxa this data pack doesn't have, "
            f"e.g. {', '.join(unknown[:5])}"
        )
    expected = write_bsxm(report)
    database = ListDatabase.create(target)
    try:
        with database.bulk(f"Import {source.name}") as connection:
            save_report(connection, report)
            stored = write_bsxm(load_report(connection))
            if stored != expected:
                raise ImportFailedError(
                    "the stored list does not export identically; import cancelled"
                )
            if predefined is not None:
                reassigned = reassign_new_built_in_locations(connection, predefined)
                if reassigned:
                    result.warnings.append(
                        "places replaced by new built-in ones: " + ", ".join(reassigned)
                    )
        problems = integrity.check(database.connection, base_taxon_ids)
        if problems:
            raise ImportFailedError("the stored list failed its checks: " + "; ".join(problems))
    except BaseException:
        database.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        raise
    database.close()
    return ImportResult(
        target,
        sightings=len(report.sightings),
        locations=len(report.iter_locations()),
        visits=len(report.visits),
        upgrades_applied=applied,
        warnings=result.warnings,
    )


def export_bsxm(database: ListDatabase, target: Path) -> int:
    """Write the list as a Scythebill file (atomically). Returns the number of bytes."""
    data = write_bsxm(load_report(database.connection))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".partial") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.chmod(_file_mode(target))
    temporary.replace(target)
    return len(data)


def _file_mode(target: Path) -> int:
    """Keep an existing file's permissions; otherwise the usual 0o666 less the umask."""
    if target.exists():
        return target.stat().st_mode & 0o777
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def open_list(
    path: Path,
    base_taxon_ids: Container[str] | None = None,
    backups_root: Path | None = None,
) -> OpenedList:
    """Open a list. If any check fails it is reopened read-only ("repair mode") and the
    problems are returned; otherwise today's backup is made (when ``backups_root`` is set)."""
    try:
        database = ListDatabase.open(path)
    except Exception as error:  # a damaged file may fail even to open
        with contextlib.suppress(Exception):
            return OpenedList(ListDatabase.open(path, read_only=True), [str(error)])
        raise
    problems = integrity.check(database.connection, base_taxon_ids)
    if problems:
        database.close()
        return OpenedList(ListDatabase.open(path, read_only=True), problems)
    if backups_root is not None:
        backup.daily_backup(database.connection, path, backups_root)
    return OpenedList(database, [])

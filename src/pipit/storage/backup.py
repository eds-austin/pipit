"""Backups of a list: a zip with a consistent copy of the database and the same list as a
Scythebill ``.bsxm``, so every backup can also be opened in Scythebill.

- ``daily_backup``: at most one per day, rotated to keep 7 daily, 5 weekly and 12 monthly.
- ``snapshot``: before an import, a taxonomy upgrade, a merge or a schema migration; named
  ``pre-<operation>-<time>`` and never rotated away.
- ``restore``: replace a list with the database inside a backup (the current list is
  snapshotted first).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from pipit.bsxm.writer import write_bsxm
from pipit.storage.repository import load_report

KEEP_DAILY = 7
KEEP_WEEKLY = 5
KEEP_MONTHLY = 12


@dataclass(frozen=True, slots=True)
class Backup:
    path: Path

    @property
    def day(self) -> date | None:
        """The day of a dated (rotating) backup; None for snapshots."""
        try:
            return date.fromisoformat(self.path.stem)
        except ValueError:
            return None


def backup_folder(backups_root: Path, list_path: Path) -> Path:
    return backups_root / list_path.stem


def _write_zip(connection: sqlite3.Connection, list_path: Path, target: Path) -> Path:
    """Write the zip next to its final name, then rename: never a half-written backup."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
        copy_path = Path(scratch) / list_path.name
        copy = sqlite3.connect(copy_path)
        try:
            connection.backup(copy)
        finally:
            copy.close()
        exported = write_bsxm(load_report(connection))
        partial = target.with_name(target.name + ".partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy_path, list_path.name)
            archive.writestr(list_path.stem + ".bsxm", exported)
        with zipfile.ZipFile(partial) as check:
            if check.testzip() is not None:
                raise OSError(f"backup {target.name} failed its check")
        partial.replace(target)
    return target


def snapshot(
    connection: sqlite3.Connection, list_path: Path, backups_root: Path, operation: str
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"pre-{operation}-{stamp}.zip"
    return _write_zip(connection, list_path, backup_folder(backups_root, list_path) / name)


def daily_backup(
    connection: sqlite3.Connection,
    list_path: Path,
    backups_root: Path,
    today: date | None = None,
) -> Path | None:
    """Make today's backup if there is none yet, then rotate. Returns the new backup."""
    today = today or datetime.now(UTC).date()
    folder = backup_folder(backups_root, list_path)
    target = folder / f"{today.isoformat()}.zip"
    created = None
    if not target.exists():
        created = _write_zip(connection, list_path, target)
    rotate(folder)
    return created


def dated_backups(folder: Path) -> list[Backup]:
    backups = [Backup(path) for path in folder.glob("*.zip")] if folder.is_dir() else []
    return sorted((b for b in backups if b.day is not None), key=lambda b: b.path.stem)


def to_keep(days: list[date]) -> set[date]:
    """7 most recent days, the latest backup of each of the 5 most recent weeks, and of
    each of the 12 most recent months."""
    ordered = sorted(days, reverse=True)
    keep = set(ordered[:KEEP_DAILY])
    weeks: dict[tuple[int, int], date] = {}
    months: dict[tuple[int, int], date] = {}
    for day in ordered:
        week = day.isocalendar()
        weeks.setdefault((week.year, week.week), day)
        months.setdefault((day.year, day.month), day)
    keep |= set(sorted(weeks.values(), reverse=True)[:KEEP_WEEKLY])
    keep |= set(sorted(months.values(), reverse=True)[:KEEP_MONTHLY])
    return keep


def rotate(folder: Path) -> list[Path]:
    backups = dated_backups(folder)
    keep = to_keep([b.day for b in backups if b.day is not None])
    removed = []
    for backup in backups:
        if backup.day not in keep:
            backup.path.unlink()
            removed.append(backup.path)
    return removed


def restore(backup: Path, list_path: Path) -> None:
    """Replace ``list_path`` with the database in ``backup``. The list must be closed."""
    with zipfile.ZipFile(backup) as archive:
        names = [name for name in archive.namelist() if name.endswith(".pipit")]
        if len(names) != 1:
            raise ValueError(f"{backup.name} does not contain one list")
        with tempfile.NamedTemporaryFile(dir=list_path.parent, delete=False) as handle:
            handle.write(archive.read(names[0]))
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
    for suffix in ("-wal", "-shm"):
        Path(str(list_path) + suffix).unlink(missing_ok=True)
    temporary.replace(list_path)


def latest_backup(backups_root: Path, list_path: Path) -> Path | None:
    folder = backup_folder(backups_root, list_path)
    if not folder.is_dir():
        return None
    candidates = sorted(folder.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None

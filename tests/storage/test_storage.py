"""The list database: lossless storage, undo/redo, integrity checks, backups."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipit.storage import backup, database, integrity, migrate
from pipit.storage import lists as lists_module
from pipit.storage.database import ListDatabase, ReadOnlyError
from pipit.storage.lists import ImportFailedError, export_bsxm, import_bsxm, open_list

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bsxm"
BASE = "clements2026"


class AnyTaxon:
    def __contains__(self, item: object) -> bool:
        return True


@pytest.fixture
def edge_list(tmp_path: Path) -> Path:
    return import_bsxm(
        FIXTURES / "edge_cases.bsxm", tmp_path / "edge.pipit", BASE, AnyTaxon()
    ).list_path


def dump(connection: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    """Every journaled table's rows (meta's last_change aside)."""
    tables = {}
    for table in migrate.journaled_tables(connection):
        rows = connection.execute(f'SELECT rowid, * FROM "{table}" ORDER BY rowid').fetchall()
        if table == "meta":
            rows = [row for row in rows if row[1] != "last_change"]
        tables[table] = rows
    return tables


# ------------------------------------------------------------------ import and export


def test_import_then_export_matches_scythebill(edge_list: Path, tmp_path: Path) -> None:
    with ListDatabase.open(edge_list) as opened:
        export_bsxm(opened, tmp_path / "out.bsxm")
    assert (tmp_path / "out.bsxm").read_bytes() == (
        FIXTURES / "edge_cases.expected.bsxm"
    ).read_bytes()


def test_large_list_is_fast_and_lossless(tmp_path: Path) -> None:
    source = tmp_path / "large.bsxm"
    source.write_bytes(gzip.decompress((FIXTURES / "large_sample.scythebill.bsxm.gz").read_bytes()))
    started = time.perf_counter()
    result = import_bsxm(source, tmp_path / "large.pipit", BASE, AnyTaxon())
    imported = time.perf_counter()
    with ListDatabase.open(result.list_path) as opened:
        export_bsxm(opened, tmp_path / "out.bsxm")
    exported = time.perf_counter()
    assert result.sightings == 30_000
    assert (tmp_path / "out.bsxm").read_bytes() == source.read_bytes()
    assert imported - started < 5.0
    assert exported - imported < 3.0


def test_import_refuses_unknown_taxa_and_leaves_nothing(tmp_path: Path) -> None:
    target = tmp_path / "x.pipit"
    with pytest.raises(ImportFailedError, match=r"unknown taxon|taxa this data pack"):
        import_bsxm(FIXTURES / "edge_cases.bsxm", target, BASE, {"spAnaspla"})
    assert not target.exists()


def test_import_is_cancelled_if_the_stored_list_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_load = lists_module.load_report

    def lossy_load(connection: sqlite3.Connection):  # type: ignore[no-untyped-def]
        report = real_load(connection)
        report.sightings.pop()
        return report

    monkeypatch.setattr(lists_module, "load_report", lossy_load)
    target = tmp_path / "x.pipit"
    with pytest.raises(ImportFailedError, match="does not export identically"):
        import_bsxm(FIXTURES / "edge_cases.bsxm", target, BASE, AnyTaxon())
    assert not list(tmp_path.glob("x.pipit*"))


def test_existing_list_is_never_overwritten(edge_list: Path) -> None:
    with pytest.raises(FileExistsError):
        import_bsxm(FIXTURES / "edge_cases.bsxm", edge_list, BASE, AnyTaxon())


def test_export_keeps_normal_permissions(edge_list: Path, tmp_path: Path) -> None:
    with ListDatabase.open(edge_list) as opened:
        export_bsxm(opened, tmp_path / "out.bsxm")
    assert (tmp_path / "out.bsxm").stat().st_mode & 0o044  # readable by others, as usual


# ------------------------------------------------------------------ undo and redo


def test_every_table_is_journaled(edge_list: Path) -> None:
    with ListDatabase.open(edge_list) as opened:
        tables = set(migrate.journaled_tables(opened.connection))
        triggers = {
            name
            for (name,) in opened.connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'trigger'"
            )
        }
    assert {"sightings", "locations", "visits", "photos", "meta"} <= tables
    assert not tables & migrate.UNJOURNALED
    for table in tables:
        for event in ("insert", "update", "delete"):
            assert f"undo_{table}_{event}" in triggers


def test_undo_and_redo_restore_exact_states(edge_list: Path) -> None:
    with ListDatabase.open(edge_list) as opened:
        connection = opened.connection
        before = dump(connection)
        with opened.action("Edit several things") as tx:
            tx.execute("UPDATE sightings SET count = '99', description = 'changed' WHERE ord = 0")
            tx.execute("DELETE FROM sightings WHERE ord = 1")  # cascades to sighting_taxa
            tx.execute("INSERT INTO users(xml_id, name, ord) VALUES ('new', 'New', 9)")
            tx.execute("UPDATE visits SET area_hectares = '0.1' WHERE ord = 3")
        after = dump(connection)
        assert after != before
        assert opened.undo_label() == "Edit several things"
        assert opened.undo() == "Edit several things"
        assert dump(connection) == before
        assert opened.redo_label() == "Edit several things"
        assert opened.redo() == "Edit several things"
        assert dump(connection) == after
        assert opened.undo() is not None
        assert dump(connection) == before
        with opened.action("Another change") as tx:
            tx.execute("UPDATE sightings SET count = '1' WHERE ord = 0")
        assert opened.redo_label() is None  # a new action clears redo
        assert opened.undo() == "Another change"
        assert opened.undo() is None


def test_failed_action_changes_nothing(edge_list: Path) -> None:
    with ListDatabase.open(edge_list) as opened:
        before = dump(opened.connection)
        with pytest.raises(sqlite3.IntegrityError), opened.action("Bad"):
            opened.connection.execute("UPDATE sightings SET count = '5' WHERE ord = 0")
            opened.connection.execute("INSERT INTO sightings(ord, kind) VALUES (0, 'nonsense')")
        assert dump(opened.connection) == before
        assert opened.undo_label() is None


def test_actions_that_change_nothing_are_not_recorded(edge_list: Path) -> None:
    with ListDatabase.open(edge_list) as opened, opened.action("Nothing"):
        pass
    with ListDatabase.open(edge_list) as opened:
        assert opened.undo_label() is None


def test_undo_history_is_bounded(edge_list: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "UNDO_LIMIT", 3)
    with ListDatabase.open(edge_list) as opened:
        for count in range(5):
            with opened.action(f"Change {count}") as tx:
                tx.execute("UPDATE sightings SET count = ? WHERE ord = 0", (str(count + 1),))
        labels = [row[0] for row in opened.connection.execute("SELECT label FROM undo_actions")]
    assert labels == ["Change 2", "Change 3", "Change 4"]


def test_read_only_lists_refuse_changes(edge_list: Path) -> None:
    with ListDatabase.open(edge_list, read_only=True) as opened:
        with pytest.raises(ReadOnlyError), opened.action("x"):
            pass
        with pytest.raises(ReadOnlyError):
            opened.undo()


# ------------------------------------------------------------------ schema


def test_newer_schema_is_refused(edge_list: Path) -> None:
    connection = sqlite3.connect(edge_list)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(migrate.SchemaError, match="newer Pipit"):
        ListDatabase.open(edge_list)


def test_other_sqlite_files_are_refused(tmp_path: Path) -> None:
    other = tmp_path / "other.pipit"
    sqlite3.connect(other).execute("CREATE TABLE t(x)").connection.close()
    with pytest.raises(migrate.SchemaError, match="not a Pipit list"):
        ListDatabase.open(other)


def test_statement_splitting_respects_comments() -> None:
    script = "CREATE TABLE a(x TEXT); -- a; comment\nCREATE TABLE b(\n  y TEXT  -- note; here\n);\n"
    assert migrate._statements(script) == [
        "CREATE TABLE a(x TEXT); -- a; comment",
        "CREATE TABLE b(\n  y TEXT  -- note; here\n);",
    ]


def test_changed_migrations_are_detected(edge_list: Path) -> None:
    connection = sqlite3.connect(edge_list)
    connection.execute("UPDATE schema_migrations SET sha256 = 'x' WHERE version = 1")
    connection.commit()
    assert integrity.check(connection) == ["migration 1 changed after it was applied"]
    connection.close()


# ------------------------------------------------------------------ integrity and repair


def test_healthy_list_opens_writable_and_backs_up(edge_list: Path, tmp_path: Path) -> None:
    opened = open_list(edge_list, AnyTaxon(), tmp_path / "backups")
    assert opened.problems == []
    assert not opened.read_only
    opened.database.close()
    assert list((tmp_path / "backups" / "edge").glob("*.zip"))


def test_inconsistent_list_opens_read_only(edge_list: Path) -> None:
    connection = sqlite3.connect(edge_list)
    connection.execute("DELETE FROM sighting_taxa WHERE ord = 1")  # a sp. with one taxon
    connection.commit()
    connection.close()
    opened = open_list(edge_list, AnyTaxon())
    assert opened.read_only
    assert any("fewer than two taxa" in problem for problem in opened.problems)
    opened.database.close()


def test_corrupted_list_opens_read_only(edge_list: Path, tmp_path: Path) -> None:
    with ListDatabase.open(edge_list) as opened:
        opened.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    corrupted = tmp_path / "corrupted.pipit"
    shutil.copy(edge_list, corrupted)
    data = bytearray(corrupted.read_bytes())
    page_size = 4096
    for page in range(2, len(data) // page_size, 3):
        data[page * page_size + 100 : page * page_size + 400] = b"\xff" * 300
    corrupted.write_bytes(bytes(data))
    opened = open_list(corrupted, AnyTaxon())
    assert opened.read_only
    assert opened.problems
    opened.database.close()


def test_unknown_base_taxa_are_reported(edge_list: Path) -> None:
    with ListDatabase.open(edge_list, read_only=True) as opened:
        problems = integrity.check(opened.connection, {"spAnaspla"})
    assert any("missing from the data pack" in problem for problem in problems)


# ------------------------------------------------------------------ backups


def test_daily_backup_once_per_day_with_both_formats(edge_list: Path, tmp_path: Path) -> None:
    root = tmp_path / "backups"
    with ListDatabase.open(edge_list) as opened:
        first = backup.daily_backup(opened.connection, edge_list, root, date(2026, 11, 24))
        again = backup.daily_backup(opened.connection, edge_list, root, date(2026, 11, 24))
        export_bsxm(opened, tmp_path / "now.bsxm")
    assert first is not None and again is None
    with zipfile.ZipFile(first) as archive:
        assert sorted(archive.namelist()) == ["edge.bsxm", "edge.pipit"]
        assert archive.read("edge.bsxm") == (tmp_path / "now.bsxm").read_bytes()


def test_rotation_keeps_daily_weekly_and_monthly() -> None:
    start = date(2026, 1, 1)
    days = [start + timedelta(days=i) for i in range(400)]
    keep = backup.to_keep(days)
    newest = sorted(days, reverse=True)
    assert set(newest[:7]) <= keep
    assert len(keep) <= backup.KEEP_DAILY + backup.KEEP_WEEKLY + backup.KEEP_MONTHLY
    assert len({(d.year, d.month) for d in keep}) >= 12


def test_rotation_deletes_old_backups(tmp_path: Path) -> None:
    folder = tmp_path / "b"
    folder.mkdir()
    for i in range(60):
        (folder / f"{(date(2026, 1, 1) + timedelta(days=i)).isoformat()}.zip").write_bytes(b"x")
    (folder / "pre-import-1.zip").write_bytes(b"x")
    removed = backup.rotate(folder)
    assert removed
    assert (folder / "pre-import-1.zip").exists()  # snapshots are never rotated
    assert len(list(folder.glob("*.zip"))) < 30


def test_snapshot_and_restore(edge_list: Path, tmp_path: Path) -> None:
    root = tmp_path / "backups"
    with ListDatabase.open(edge_list) as opened:
        before = dump(opened.connection)
        saved = backup.snapshot(opened.connection, edge_list, root, "test")
        with opened.action("Delete everything visible") as tx:
            tx.execute("DELETE FROM sightings")
    backup.restore(saved, edge_list)
    with ListDatabase.open(edge_list) as reopened:
        assert dump(reopened.connection) == before
    assert backup.latest_backup(root, edge_list) == saved

"""Location operations: Scythebill's results byte for byte, undo, and a random-tree fuzz."""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from test_storage import BASE, FIXTURES, AnyTaxon, dump

from pipit.storage import integrity
from pipit.storage import location_ops as ops
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.storage.location_ops import LocationError, row_of

Operation = Callable[[sqlite3.Connection], None]


def _delete(xml_id: str) -> Operation:
    return lambda c: ops.delete_location(c, row_of(c, xml_id))


def _merge(old: str, new: str) -> Operation:
    return lambda c: ops.merge_location(c, row_of(c, old), row_of(c, new))


def _move(xml_id: str, parent: str) -> Operation:
    return lambda c: ops.move_location(c, row_of(c, xml_id), row_of(c, parent))


# Each case matches tools/oracle/run.sh (LocationOps.java on locations.bsxm).
CASES: dict[str, Operation | None] = {
    "reassign": None,  # Marin County and Kent become the built-in places on import
    "delete": _delete("lighth"),
    "merge": _merge("lakmer", "bayare"),  # the parent already has a visit at that time
    "move": _move("bayare1", "_usst_califo"),  # California already has a Bay Area
    "merge_recursive": _merge("coast", "poirey"),  # both have a Lighthouse
}


@pytest.mark.scythebill
@pytest.mark.parametrize("case", sorted(CASES))
def test_operations_match_scythebill(case: str, pack: object, tmp_path: Path) -> None:
    from pipit.datapack.pack import DataPack

    assert isinstance(pack, DataPack)
    path = tmp_path / "l.pipit"
    import_bsxm(
        FIXTURES / "locations.bsxm",
        path,
        pack.base_taxonomy_id,
        pack.base_taxon_ids(),
        pack.predefined_locations(),
    )
    operation = CASES[case]
    with ListDatabase.open(path) as database:
        if operation is not None:
            before = dump(database.connection)
            with database.action(case) as connection:
                operation(connection)
            assert integrity.check(database.connection) == []
            export_bsxm(database, tmp_path / "out.bsxm")
            database.undo()
            assert dump(database.connection) == before
        else:
            export_bsxm(database, tmp_path / "out.bsxm")
    expected = FIXTURES / f"locations.{case}.scythebill.bsxm"
    assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes()


@pytest.fixture
def location_list(tmp_path: Path) -> ListDatabase:
    path = import_bsxm(
        FIXTURES / "locations.bsxm", tmp_path / "l.pipit", BASE, AnyTaxon()
    ).list_path
    return ListDatabase.open(path)


def test_refusals_change_nothing(location_list: ListDatabase) -> None:
    refused: list[Operation] = [
        _delete("_usst_califo"),  # built in
        _delete("bayare"),  # has places inside
        _merge("bayare", "lighth"),  # into a place inside it
        _merge("bayare", "bayare"),
        _move("bayare", "poirey"),  # inside itself
        lambda c: ops.add_location(c, row_of(c, "bayare"), "Point Reyes"),
        lambda c: ops.add_location(c, row_of(c, "bayare"), "  "),
        lambda c: ops.rename_location(c, row_of(c, "_usst_califo"), "Cali"),
        lambda c: ops.rename_location(c, row_of(c, "lakmer"), "Point Reyes"),
        lambda c: ops.edit_location(c, row_of(c, "lakmer"), latitude="95", longitude="0"),
    ]
    before = dump(location_list.connection)
    for operation in refused:
        with pytest.raises(LocationError), location_list.action("refused") as connection:
            operation(connection)
    assert dump(location_list.connection) == before
    assert location_list.undo_label() is None


def test_add_rename_and_edit(location_list: ListDatabase) -> None:
    with location_list.action("add") as connection:
        new_id = ops.add_location(connection, row_of(connection, "bayare"), "Berkeley Marina")
        ops.rename_location(connection, row_of(connection, new_id), "Berkeley Pier")
        ops.edit_location(
            connection,
            row_of(connection, new_id),
            latitude="37.86",
            longitude="-122.32",
            description=" Windy ",
            private=True,
        )
    row = location_list.connection.execute(
        "SELECT xml_id, name, latitude, longitude, description, private FROM locations "
        "WHERE xml_id = ?",
        (new_id,),
    ).fetchone()
    assert row == ("bermar", "Berkeley Pier", "37.8600000", "-122.3200000", "Windy", 1)
    location_list.undo()
    assert row_of_or_none(location_list.connection, new_id) is None


def row_of_or_none(connection: sqlite3.Connection, xml_id: str) -> int | None:
    try:
        return row_of(connection, xml_id)
    except LocationError:
        return None


def _custom_ids(connection: sqlite3.Connection) -> list[str]:
    return [
        xml_id
        for (xml_id,) in connection.execute(
            "SELECT xml_id FROM locations WHERE xml_id NOT LIKE '\\_%' ESCAPE '\\' ORDER BY id"
        )
    ]


def _all_ids(connection: sqlite3.Connection) -> list[str]:
    return [xml_id for (xml_id,) in connection.execute("SELECT xml_id FROM locations ORDER BY id")]


@pytest.mark.parametrize("seed", range(6))
def test_random_operations_keep_the_tree_valid(
    seed: int, location_list: ListDatabase, tmp_path: Path
) -> None:
    """Random adds, moves, merges and deletes: the tree stays consistent after each, every
    sighting survives, export and re-import is a fixed point, and undoing everything
    restores the original exactly."""
    generator = random.Random(seed)
    database = location_list
    original = dump(database.connection)
    sightings = database.connection.execute("SELECT count(*) FROM sightings").fetchone()[0]
    names = ["Lighthouse", "Dunes", "Marsh", "Bay Area", "Pond", "Coast"]
    applied = 0
    for step in range(40):
        connection = database.connection
        custom = _custom_ids(connection)
        everything = _all_ids(connection)
        kinds = ["add", "move", "merge", "delete", "rename"] if custom else ["add"]
        kind = generator.choice(kinds)
        try:
            with database.action(f"{kind} {step}") as c:
                if kind == "add":
                    ops.add_location(
                        c, row_of(c, generator.choice(everything)), generator.choice(names)
                    )
                elif kind == "rename":
                    ops.rename_location(
                        c, row_of(c, generator.choice(custom)), generator.choice(names)
                    )
                elif kind == "move":
                    _move(generator.choice(custom), generator.choice(everything))(c)
                elif kind == "merge":
                    _merge(generator.choice(custom), generator.choice(everything))(c)
                else:
                    _delete(generator.choice(custom))(c)
            applied += 1
        except LocationError:
            pass
        assert integrity.check(database.connection) == [], (kind, step)
        assert (
            database.connection.execute("SELECT count(*) FROM sightings").fetchone()[0] == sightings
        )
    assert applied > 10

    first = tmp_path / "first.bsxm"
    second = tmp_path / "second.bsxm"
    export_bsxm(database, first)
    with ListDatabase.open(
        import_bsxm(first, tmp_path / "again.pipit", BASE, AnyTaxon()).list_path
    ) as again:
        export_bsxm(again, second)
    assert second.read_bytes() == first.read_bytes()

    finished = dump(database.connection)
    while database.undo() is not None:
        assert integrity.check(database.connection) == []  # the closure follows undo
    assert dump(database.connection) == original
    while database.redo() is not None:
        assert integrity.check(database.connection) == []  # and redo
    assert dump(database.connection) == finished


def test_closure_lists_every_ancestor(location_list: ListDatabase) -> None:
    connection = location_list.connection
    inside_california = {
        xml_id
        for (xml_id,) in connection.execute(
            "SELECT l.xml_id FROM location_closure c JOIN locations l ON l.id = c.descendant "
            "WHERE c.ancestor = ? AND c.depth > 0",
            (row_of(connection, "_usst_califo"),),
        )
    }
    assert {"bayare", "poirey", "lighth", "lakmer"} <= inside_california
    assert "_usst" not in inside_california


def test_stale_closure_is_detected(location_list: ListDatabase) -> None:
    connection = location_list.connection
    connection.execute("DELETE FROM location_closure WHERE depth = 1")
    connection.commit()
    assert any("location index" in problem for problem in integrity.check(connection))


def test_migration_fills_the_closure_for_older_lists(location_list: ListDatabase) -> None:
    path = location_list.path
    connection = location_list.connection
    expected = set(connection.execute("SELECT * FROM location_closure"))
    for (name,) in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'trigger' AND name LIKE 'closure_%'"
    ).fetchall():
        connection.execute(f'DROP TRIGGER "{name}"')
    connection.execute("DROP TABLE location_closure")
    connection.execute("DELETE FROM schema_migrations WHERE version = 3")
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    location_list.close()
    with ListDatabase.open(path) as reopened:
        assert set(reopened.connection.execute("SELECT * FROM location_closure")) == expected
        assert integrity.check(reopened.connection) == []

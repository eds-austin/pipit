"""Custom checklist edits give exactly Scythebill's file (tools/oracle/ChecklistOps.java on
tests/fixtures/bsxm/checklists.bsxm): after any edit, even none, Scythebill writes the
entries in Java HashMap order, and so does Pipit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_storage import FIXTURES, dump

from pipit.browse.checklists import add_species, checklist_rows, with_status
from pipit.domain.java_hash import guava_capacity, hashmap_order, string_hash, table_size
from pipit.entry.taxa import EntryTaxa
from pipit.storage import checklist_ops as ops
from pipit.storage import integrity
from pipit.storage.checklist_ops import ChecklistError
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm

# name -> (display, place, changes); the same as tools/oracle/run.sh.
CASES: dict[str, tuple[str, str, list[str]]] = {
    "unchanged": ("clements", "bayare", []),
    "unchanged_avilist": ("avilist", "bayare", []),
    "edit": (
        "clements",
        "bayare",
        [
            "status=spStrutcam=endemic",
            "remove=spCasuacas",
            "add=spArdeaalb",
            "status=spStrutmol=native",
        ],
    ),
    "small": ("clements", "poirey", ["add=spEgretthu", "add=spAnaspla"]),
}


@pytest.fixture(scope="module")
def taxa(pack: Any) -> dict[str, EntryTaxa]:
    base, avilist = pack.load_base_and_avilist()
    return {"clements": EntryTaxa(base, base), "avilist": EntryTaxa(base, avilist)}


def _open(pack: Any, tmp_path: Path) -> ListDatabase:
    result = import_bsxm(FIXTURES / "checklists.bsxm", tmp_path / "c.pipit",
                         pack.base_taxonomy_id, pack.base_taxon_ids(),
                         pack.predefined_locations())  # fmt: skip
    return ListDatabase.open(result.list_path)


def _edit(taxa: EntryTaxa, entries: list[ops.ChecklistEntry], changes: list[str]) -> list[Any]:
    rows = checklist_rows(taxa, entries)
    for change in changes:
        kind, _, rest = change.partition("=")
        if kind == "add":
            rows, _index = add_species(taxa, rows, rest)
            continue
        taxon, _, status = rest.partition("=")
        index = next(i for i, row in enumerate(rows) if row.row_id == taxon)
        if kind == "remove":
            del rows[index]
        else:
            rows[index] = with_status(rows[index], None if status == "native" else status)
    return rows


@pytest.mark.scythebill
@pytest.mark.parametrize("case", sorted(CASES))
def test_checklist_edits_match_scythebill(
    case: str, pack: Any, taxa: dict[str, EntryTaxa], tmp_path: Path
) -> None:
    display, place, changes = CASES[case]
    with _open(pack, tmp_path) as database:
        before = dump(database.connection)
        rows = _edit(taxa[display], ops.read_checklist(database.connection, place), changes)
        with database.action(case) as connection:
            ops.save_checklist(connection, place, [row.entry for row in rows])
        assert integrity.check(database.connection) == []
        export_bsxm(database, tmp_path / "out.bsxm")
        database.undo()
        assert dump(database.connection) == before
    expected = FIXTURES / f"checklists.{case}.scythebill.bsxm"
    assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes()


@pytest.mark.scythebill
def test_delete_matches_scythebill(pack: Any, tmp_path: Path) -> None:
    with _open(pack, tmp_path) as database:
        with database.action("delete") as connection:
            ops.delete_checklist(connection, "bayare")
        export_bsxm(database, tmp_path / "out.bsxm")
        with pytest.raises(ChecklistError), database.action("again") as connection:
            ops.delete_checklist(connection, "bayare")
    expected = FIXTURES / "checklists.delete.scythebill.bsxm"
    assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes()


@pytest.mark.scythebill
def test_new_checklists_go_last_and_bad_ones_are_refused(pack: Any, tmp_path: Path) -> None:
    with _open(pack, tmp_path) as database:
        with database.action("new") as connection:
            ops.save_checklist(connection, "lakmer", [ops.ChecklistEntry("single", ("spAnaspla",))])
        places = [place for (place,) in database.connection.execute(
            "SELECT location_xml_id FROM checklists ORDER BY ord")]  # fmt: skip
        assert places[-1] == "lakmer"
        twice = [ops.ChecklistEntry("single", ("spAnaspla",))] * 2
        for bad in (twice, [ops.ChecklistEntry("single", ("spAnaspla",), status="bogus")]):
            with pytest.raises(ChecklistError), database.action("bad") as connection:
                ops.save_checklist(connection, "lakmer", bad)


def test_java_hashing() -> None:
    assert string_hash("hello") == 99162322
    assert string_hash("polygenelubricants") == -(2**31)
    assert [guava_capacity(n) for n in (0, 2, 3, 150)] == [1, 3, 5, 201]
    assert table_size(201) == 256
    # Two keys in the same bucket keep their insertion order.
    assert hashmap_order(["a", "b", "c"], [1, 2, 1], 16) == ["a", "c", "b"]
    assert hashmap_order(["a", "b", "c"], [1, 17, 1], 16) == ["a", "b", "c"]  # 17 & 15 = 1

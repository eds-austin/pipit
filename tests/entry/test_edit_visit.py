"""Editing a recorded visit gives exactly Scythebill's file.

Each case loads a visit of tests/fixtures/bsxm/visits.bsxm into Enter Sightings, makes the
same changes as tools/oracle/EditVisit.java makes through Scythebill's SingleLocationEdit,
saves, and compares the exported file with Scythebill's byte for byte. Also: one undo
restores the list, edited slots keep observers and photos, and drafts keep what was loaded.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Any

import pytest

from pipit.domain.partial_date import parse_partial_date
from pipit.entry.commit import StoredTaxon, commit_session
from pipit.entry.existing import is_unedited, load_existing, load_into, unload, visit_key
from pipit.entry.session import EntrySession, LocationChoice, LocationKind
from pipit.entry.taxa import EntryTaxa
from pipit.storage import integrity
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.taxa.sighting_taxon import SightingTaxon

pytestmark = pytest.mark.scythebill
BSXM = Path(__file__).parents[1] / "fixtures" / "bsxm"

# name -> (display, place, date, start time, ops); the same as tools/oracle/run.sh.
CASES: dict[str, tuple[str, str, str, str | None, list[str]]] = {
    "unchanged": ("clements", "lakmer", "2026-08-08", "08:00", []),
    "unchanged_avilist": ("avilist", "lakmer", "2026-08-08", "08:00", []),
    "edit": ("clements", "lakmer", "2026-08-08", "08:00",
             ["count:spAnaspla:7", "remove:spArdeaalb", "add:spEgretthu:2", "heard:spOxyurjam",
              "comments:Calm, then windy"]),
    "edit_avilist": ("avilist", "lakmer", "2026-08-08", "08:00",
                     ["count:spAnaspla:7", "add:spEgretthu:2"]),
    "add_time": ("clements", "muiwoo", "2026-09-09", "06:30", ["add:spAnasrub:1"]),
    "remove_all": ("clements", "_scyco_GB-ENG-KEN", "2026-06-06", None, ["remove:spAnaspla"]),
}  # fmt: skip


@pytest.fixture(scope="module")
def taxa(pack: Any) -> dict[str, EntryTaxa]:
    base, avilist = pack.load_base_and_avilist()
    return {"clements": EntryTaxa(base, base), "avilist": EntryTaxa(base, avilist)}


def _open(pack: Any, tmp_path: Path) -> ListDatabase:
    """Imported as Scythebill loads it (its built-in Kent replaces the fixture's own)."""
    result = import_bsxm(BSXM / "visits.bsxm", tmp_path / "v.pipit", pack.base_taxonomy_id,
                         pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    return ListDatabase.open(result.list_path)


def _resolver(taxa: EntryTaxa) -> Any:
    def resolve(taxonomy_id: str, taxon_id: str) -> StoredTaxon | None:
        if taxonomy_id != taxa.display.id:
            return StoredTaxon(SightingTaxon.single(taxon_id), taxonomy_id, 10**9)
        return taxa.stored(taxon_id)

    return resolve


def _session(database: ListDatabase, taxa: EntryTaxa, place: str, date: str,
             start: str | None) -> EntrySession:  # fmt: skip
    session = EntrySession(taxa.display.id, parse_partial_date(date))
    slot = session.slot("A")
    slot.location = LocationChoice(LocationKind.EXISTING, place, place, xml_id=place)
    slot.start_time = None if start is None else time.fromisoformat(start)
    existing = load_existing(
        database.connection, taxa, place, parse_partial_date(date), slot.start_time
    )
    load_into(session, "A", existing, visit_key(place, parse_partial_date(date), slot.start_time))
    return session


def _apply(session: EntrySession, ops: list[str]) -> None:
    display = session.display_taxonomy_id
    for op in ops:
        kind, _, rest = op.partition(":")
        if kind == "comments":
            session.slot("A").comments = rest
            continue
        taxon, _, count = rest.partition(":")
        row = session.find_row(display, taxon)
        if kind == "remove":
            assert row is not None
            session.untick(row, "A")
            session.rows = [entry for entry in session.rows if entry.seen]
        elif kind == "add":
            index, created = session.add_species(display, taxon)
            assert created
            assert session.set_count(index, "A", count)
        elif kind == "count":
            assert row is not None and session.set_count(row, "A", count)
        elif kind == "heard":
            assert row is not None
            session.rows[row].seen["A"].heard_only = True


@pytest.mark.parametrize("case", sorted(CASES))
def test_edit_matches_scythebill(
    case: str, pack: Any, taxa: dict[str, EntryTaxa], tmp_path: Path
) -> None:
    display, place, date, start, ops = CASES[case]
    with _open(pack, tmp_path) as database:
        session = _session(database, taxa[display], place, date, start)
        assert session.slot("A").replaces
        _apply(session, ops)
        assert session.can_save(), session.problems()
        commit_session(database, session, _resolver(taxa[display]))
        assert integrity.check(database.connection) == []
        export_bsxm(database, tmp_path / "out.bsxm")
    expected = BSXM / f"visits.{case}.scythebill.bsxm"
    assert (tmp_path / "out.bsxm").read_bytes() == expected.read_bytes()


def test_loading_follows_scythebill(pack: Any, taxa: dict[str, EntryTaxa], tmp_path: Path) -> None:
    with _open(pack, tmp_path) as database:
        connection = database.connection
        date = parse_partial_date("2026-08-08")
        existing = load_existing(connection, taxa["clements"], "lakmer", date, time(8, 0))
        rows = [(row.taxon_id, str(row.sighting.count)) for row in existing.rows]
        # The second Great Egret is left alone; the 17:00 visit isn't part of it.
        assert rows == [("spAnaspla", "4"), ("sspAnasplapla", "1"), ("spArdeaalb", "1"),
                        ("spAnaspla/spAnasrub", "None"), ("spOxyurjam", "12"),
                        ("spOxyurfer", "1")]  # fmt: skip
        assert existing.rows[0].sighting.heard_only
        assert existing.rows[0].sighting.notes == "Pair by the boathouse"
        assert existing.visit is not None and existing.visit.comments == "Calm morning"
        assert existing.visit.duration_minutes == 45 and existing.visit.complete
        # In AviList, Ruddy Duck is shown as an AviList subspecies, Andean Duck as a sp.
        avilist = load_existing(connection, taxa["avilist"], "lakmer", date, time(8, 0))
        shown = {row.taxon_id for row in avilist.rows}
        assert "sspOxyurjamjam" in shown
        assert any("/" in taxon for taxon in shown if "Oxyur" in taxon)
        # No sightings at 06:30, so the untimed ones are loaded (to be given a time).
        untimed = load_existing(connection, taxa["clements"], "muiwoo",
                                parse_partial_date("2026-09-09"), time(6, 30))  # fmt: skip
        assert len(untimed.sighting_ids) == 2
        nothing = load_existing(connection, taxa["clements"], "lakmer",
                                parse_partial_date("2026-08-09"), None)  # fmt: skip
        assert nothing.sighting_ids == [] and nothing.visit is None


def test_edit_keeps_observers_and_undo_restores(
    pack: Any, taxa: dict[str, EntryTaxa], tmp_path: Path
) -> None:
    with _open(pack, tmp_path) as database:
        connection = database.connection
        with database.action("observer") as c:
            c.execute("INSERT INTO users(xml_id, name, ord) VALUES ('u1', 'Eve', 0)")
            mallard = c.execute(
                "SELECT id FROM sightings WHERE location_xml_id = 'lakmer' AND date = "
                "'2026-08-08' AND time = '08:00' AND taxon_id = 'spAnaspla'"
            ).fetchone()[0]
            c.execute(
                "INSERT INTO sighting_users(sighting_id, ord, user_xml_id) VALUES (?, 0, 'u1')",
                (mallard,),
            )
        export_bsxm(database, tmp_path / "before.bsxm")
        session = _session(database, taxa["clements"], "lakmer", "2026-08-08", "08:00")
        _apply(session, CASES["edit"][4])
        commit_session(database, session, _resolver(taxa["clements"]))
        users = connection.execute("SELECT sighting_id FROM sighting_users").fetchall()
        assert users == [(mallard,)]  # the same row, re-added at the end with its observer
        assert database.undo_label() is not None
        database.undo()
        export_bsxm(database, tmp_path / "after.bsxm")
    assert (tmp_path / "after.bsxm").read_bytes() == (tmp_path / "before.bsxm").read_bytes()


def test_unedited_loads_can_be_swapped_and_drafts_keep_them(
    pack: Any, taxa: dict[str, EntryTaxa], tmp_path: Path
) -> None:
    with _open(pack, tmp_path) as database:
        session = _session(database, taxa["clements"], "lakmer", "2026-08-08", "08:00")
        assert is_unedited(session, "A")
        restored = EntrySession.from_json(session.to_json())
        assert restored.slot("A").replaces == session.slot("A").replaces
        assert restored.rows[0].seen["A"].source_id == session.rows[0].seen["A"].source_id
        assert is_unedited(restored, "A")
        unload(session, "A")
        assert session.rows == [] and session.slot("A").replaces is None
        assert session.slot("A").comments == ""
        # Once edited, a changed date means moving the visit: saving says so.
        edited = _session(database, taxa["clements"], "lakmer", "2026-08-08", "08:00")
        edited.set_count(0, "A", "9")
        assert not is_unedited(edited, "A")
        edited.date = parse_partial_date("2026-08-09")
        assert any("moves" in problem.message for problem in edited.problems())

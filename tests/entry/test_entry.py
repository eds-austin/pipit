"""Enter Sightings without the UI: session rules, ranking, saving, drafts.

Uses a brand-new list exactly as Scythebill creates one (tests/fixtures/bsxm/
new_list.scythebill.bsxm) and the real data pack.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import pytest

from pipit.bsxm.reader import read_bsxm
from pipit.domain.partial_date import PartialDate
from pipit.domain.report import ObservationType
from pipit.entry.commit import CommitError, commit_session
from pipit.entry.context import ListContext
from pipit.entry.session import (
    EntrySession,
    LocationChoice,
    LocationKind,
    parse_clock,
    parse_count,
    parse_duration,
    parse_species_input,
)
from pipit.entry.taxa import EntryTaxa, match_quality
from pipit.storage.database import ListDatabase
from pipit.storage.drafts import clear_draft, load_draft, save_draft
from pipit.storage.lists import export_bsxm, import_bsxm

NEW_LIST = Path(__file__).parents[1] / "fixtures" / "bsxm" / "new_list.scythebill.bsxm"

# ------------------------------------------------------------------ pure session rules


@pytest.mark.parametrize(
    ("text", "query", "counts"),
    [
        ("mall", "mall", {}),
        ("mall 12", "mall", {None: "12"}),
        ("amro a3 b1", "amro", {"A": "3", "B": "1"}),
        ("he gu c~12", "he gu", {"C": "~12"}),
        ("wiwa bx", "wiwa", {"B": "x"}),
        ("12", "12", {}),  # a lone token is always the query
    ],
)
def test_species_input(text: str, query: str, counts: dict[str | None, str]) -> None:
    assert parse_species_input(text) == (query, counts)


def test_small_parsers() -> None:
    assert parse_count("x") == (True, None)
    assert parse_count("~20")[1] is not None
    assert parse_count("-3")[0] is False
    assert parse_duration("90") == 90
    assert parse_duration("1h30") == 90
    assert parse_duration("1:05") == 65
    assert parse_duration("0") is None
    assert parse_clock("0730") == time(7, 30)
    assert parse_clock("7:30") == time(7, 30)
    assert parse_clock("2530") is None


def _choice(name: str) -> LocationChoice:
    return LocationChoice(LocationKind.EXISTING, name, name, xml_id=name)


def test_session_rows_and_slots() -> None:
    session = EntrySession("t", PartialDate.of(2026, 11, 24))
    assert session.add_slot() == "B"
    row, created = session.add_species("t", "spA")
    assert created and session.add_species("t", "spA") == (row, False)  # never a duplicate
    assert session.set_count(row, "A", "3")
    assert session.set_count(row, "B", "x")
    assert not session.set_count(row, "C", "1")  # no slot C
    assert not session.set_count(row, "A", "-1")
    session.add_slot()
    session.set_count(row, "C", "5")
    session.remove_slot("B")  # C becomes B
    assert set(session.rows[0].seen) == {"A", "B"}
    assert str(session.rows[0].seen["B"].count) == "5"


def test_problems() -> None:
    session = EntrySession("t", PartialDate.of(2026))
    messages = " ".join(p.message for p in session.problems())
    assert "at least one species" in messages
    session.add_slot()
    session.add_species("t", "spA")
    session.set_count(0, "A", "1")
    session.slots[0].observation_type = ObservationType.TRAVELING
    messages = " ".join(p.message for p in session.problems())
    assert "full date" in messages
    assert "no place" in messages
    assert "needs a start time" in messages and "needs a duration" in messages
    session.date = PartialDate.of(2026, 11, 24)
    session.slots[0].location = _choice("x")
    session.slots[1].location = _choice("x")
    session.set_count(0, "B", "1")
    messages = " ".join(p.message for p in session.problems())
    assert "same place at the same time" in messages


def test_draft_json_round_trip() -> None:
    session = EntrySession("avilist_2026", PartialDate.of(2026, 11, 24))
    session.slots[0].location = _choice("here")
    session.slots[0].start_time = time(6, 5)
    session.slots[0].distance_km = 3.25
    session.add_slot()
    row, _ = session.add_species("avilist_2026", "spX")
    session.set_count(row, "B", "~7")
    session.rows[row].seen["B"].heard_only = True
    restored = EntrySession.from_json(session.to_json())
    assert restored == session


def test_match_quality_prefers_word_starts() -> None:
    assert match_quality("amro", "American Robin") < match_quality(
        "amro", "Amber Mountain Rock Thrush"
    )
    assert match_quality("mall", "Mallard") == (0, 0)
    assert match_quality("zz", "Mallard")[0] == 99


# ------------------------------------------------------------------ with the pack and a list


@dataclass
class Fixture:
    database: ListDatabase
    context: ListContext
    taxa: EntryTaxa
    path: Path


@pytest.fixture(scope="module")
def avilist_taxa(pack: Any) -> EntryTaxa:
    base, avilist = pack.load_base_and_avilist()
    return EntryTaxa(base, avilist)


@pytest.fixture
def entry(pack: Any, avilist_taxa: EntryTaxa, tmp_path: Path) -> Iterator[Fixture]:
    path = tmp_path / "new.pipit"
    import_bsxm(NEW_LIST, path, pack.base_taxonomy_id, pack.base_taxon_ids())
    database = ListDatabase.open(path)
    context = ListContext(database.connection, pack, pack.predefined_locations())
    yield Fixture(database, context, avilist_taxa, path)
    database.close()


def _resolve(taxa: EntryTaxa):  # type: ignore[no-untyped-def]
    return lambda _taxonomy, taxon_id: taxa.stored(taxon_id)


@pytest.mark.scythebill
def test_places_include_built_in_counties(entry: Fixture) -> None:
    found = entry.context.find_places("alameda")
    assert found[0].kind is LocationKind.PREDEFINED
    assert found[0].code == "US-CA-001"
    assert "California" in found[0].label
    assert entry.context.find_places("california")[0].kind is LocationKind.EXISTING


@pytest.mark.scythebill
def test_search_ranks_for_the_place(entry: Fixture) -> None:
    california = entry.context.find_places("california")[0]
    checklist = entry.context.checklist_for(california, entry.taxa.display.id)
    assert checklist is not None and len(checklist) > 500

    def first(query: str) -> str:
        return entry.taxa.search(query, checklist)[0].common_name

    assert first("amro") == "American Robin"
    assert first("grbh") == "Great Blue Heron"
    assert first("mall") == "Mallard"
    assert first("wiwa") == "Wilson's Warbler"


@pytest.mark.scythebill
def test_two_location_day_is_saved_and_undone(entry: Fixture, tmp_path: Path) -> None:
    alameda = entry.context.find_places("alameda")[0]
    california = entry.context.find_places("california")[0]
    session = EntrySession(entry.taxa.display.id, PartialDate.of(2026, 11, 20))
    first = session.slots[0]
    first.location = alameda
    first.observation_type = ObservationType.TRAVELING
    first.start_time = time(7, 30)
    first.duration_minutes = 90
    first.distance_km = 3.2
    first.party_size = 2
    first.complete = True
    session.add_slot()
    session.slots[1].location = california
    session.slots[1].observation_type = ObservationType.INCIDENTAL
    checklist = entry.context.checklist_for(alameda, entry.taxa.display.id)
    for text in ("mall 12", "amro a3 b1", "rtha", "wiwa ~5", "grbh a2 b1", "anhu b2"):
        query, counts = parse_species_input(text)
        match = entry.taxa.search(query, checklist)[0]
        row, _ = session.add_species(entry.taxa.display.id, match.taxon_id)
        for letter, count in (counts or {None: ""}).items():
            session.set_count(row, letter or "A", count)
    before = entry.database.connection.execute("SELECT count(*) FROM sightings").fetchone()[0]
    result = commit_session(entry.database, session, _resolve(entry.taxa))
    assert result.visits == 2
    assert result.sightings == 8
    assert result.locations_created == ["_scyco_US-CA-001"]
    export_bsxm(entry.database, tmp_path / "out.bsxm")
    text = (tmp_path / "out.bsxm").read_text()
    assert '<county id="_scyco_US-CA-001" name="Alameda" ebirdCode="US-CA-001"/>' in text
    assert 'loc="_scyco_US-CA-001" date="2026-11-20" time="07:30" count="12"' in text
    assert 'observationType="traveling"' in text and "<complete/>" in text
    # The exported file reads back unchanged (a fixed point, as Scythebill's own output).
    pack_ids = set(entry.taxa.base._by_id)
    reread = read_bsxm(tmp_path / "out.bsxm", entry.taxa.base.id, pack_ids)
    assert len(reread.report.sightings) == 8
    # One undo takes back the whole day, location included.
    assert entry.database.undo() is not None
    connection = entry.database.connection
    assert connection.execute("SELECT count(*) FROM sightings").fetchone()[0] == before
    assert not connection.execute(
        "SELECT 1 FROM locations WHERE xml_id = '_scyco_US-CA-001'"
    ).fetchone()
    assert not connection.execute("SELECT 1 FROM visits").fetchone()


@pytest.mark.scythebill
def test_saving_again_updates_instead_of_duplicating(entry: Fixture) -> None:
    california = entry.context.find_places("california")[0]
    mallard = entry.taxa.search("mall")[0].taxon_id

    def save(count: str) -> None:
        session = EntrySession(entry.taxa.display.id, PartialDate.of(2026, 1, 1))
        session.slots[0].location = california
        row, _ = session.add_species(entry.taxa.display.id, mallard)
        session.set_count(row, "A", count)
        commit_session(entry.database, session, _resolve(entry.taxa))

    save("3")
    save("5")
    rows = entry.database.connection.execute("SELECT count FROM sightings").fetchall()
    assert rows == [("5",)]


@pytest.mark.scythebill
def test_invalid_sessions_are_not_saved(entry: Fixture) -> None:
    session = EntrySession(entry.taxa.display.id, PartialDate.of(2026, 1, 1))
    with pytest.raises(CommitError, match="at least one species"):
        commit_session(entry.database, session, _resolve(entry.taxa))
    assert entry.database.undo_label() is None


@pytest.mark.scythebill
def test_drafts_survive_reopening(entry: Fixture) -> None:
    save_draft(entry.database, '{"draft": 1}')
    entry.database.close()
    with ListDatabase.open(entry.path) as reopened:
        assert load_draft(reopened) == '{"draft": 1}'
        assert reopened.undo_label() is None  # drafts are not undo steps
        clear_draft(reopened)
        assert load_draft(reopened) is None
    entry.database = ListDatabase.open(entry.path)

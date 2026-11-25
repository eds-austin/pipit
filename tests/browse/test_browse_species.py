"""The Species screen's queries and sighting changes, on tests/fixtures/bsxm/visits.bsxm."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pipit.browse.locations import SpeciesRollup, species_at
from pipit.browse.species import sightings_of, taxonomy_rows
from pipit.entry.taxa import EntryTaxa
from pipit.storage import sighting_ops
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.storage.sighting_ops import SightingDetails, SightingError

sys.path.insert(0, str(Path(__file__).parents[1] / "storage"))
from test_storage import dump

pytestmark = pytest.mark.scythebill
VISITS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "visits.bsxm"


@pytest.fixture(scope="module")
def taxa(pack: Any) -> EntryTaxa:
    base, _avilist = pack.load_base_and_avilist()
    return EntryTaxa(base, base)


@pytest.fixture
def database(pack: Any, tmp_path: Path) -> ListDatabase:
    result = import_bsxm(VISITS, tmp_path / "v.pipit", pack.base_taxonomy_id,
                         pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    return ListDatabase.open(result.list_path)


def test_taxonomy_rows(database: ListDatabase, taxa: EntryTaxa) -> None:
    seen = species_at(database.connection, taxa, None, SpeciesRollup(taxa))
    rows = taxonomy_rows(taxa, seen)
    keys = [row.key for row in rows if not row.heading]
    assert set(keys) == {entry.key for entry in seen}
    assert rows[0].heading  # every species comes under its family heading
    for index, row in enumerate(rows):
        if row.heading:
            assert index + 1 < len(rows) and not rows[index + 1].heading  # no empty families
    # The sp. sits in taxonomic order (just after Mallard, its first species) and isn't
    # counted as a species.
    sp = next(row for row in rows if row.key == "spAnaspla/spAnasrub")
    assert not sp.is_species
    assert keys.index("spAnaspla/spAnasrub") == keys.index("spAnaspla") + 1
    mallard = next(row for row in rows if row.key == "spAnaspla")
    assert mallard.sightings == 6  # with its subspecies; the sp. is apart
    # All species, filtered by name.
    every = taxonomy_rows(taxa, seen, only_seen=False)
    assert sum(1 for row in every if not row.heading) > 10_000
    egrets = taxonomy_rows(taxa, seen, only_seen=False, query="egret")
    names = [row.common for row in egrets if not row.heading]
    assert "Snowy Egret" in names and "Little Blue Heron" in names  # Egretta caerulea
    assert all("egret" in f"{row.common} {row.scientific}".lower() for row in egrets
               if not row.heading)  # fmt: skip
    assert taxonomy_rows(taxa, seen, query="no such bird") == []


def test_sightings_of_a_species(database: ListDatabase, taxa: EntryTaxa) -> None:
    connection = database.connection
    seen = {entry.key: entry for entry in species_at(connection, taxa, None)}
    rows = sightings_of(connection, taxa, seen["spAnaspla"])
    assert len(rows) == 6
    assert [row.sort_key for row in rows] == sorted((row.sort_key for row in rows), reverse=True)
    newest = rows[0]
    assert (newest.date_text, newest.count, newest.place) == (
        "10 Sep 2026",
        "8",
        "Bay Area · California, United States",
    )
    by_notes = next(row for row in rows if row.notes)
    assert by_notes.flags == "heard only" and by_notes.time_text == "08:00"
    assert any("platyrhynchos" in row.as_recorded for row in rows)  # the subspecies


def test_edit_and_delete_one_sighting(database: ListDatabase) -> None:
    connection = database.connection
    sighting = connection.execute(
        "SELECT id FROM sightings WHERE taxon_id = 'spOxyurjam'"
    ).fetchone()[0]
    with database.action("observer") as c:
        c.execute("INSERT INTO users(xml_id, name, ord) VALUES ('u1', 'Eve', 0)")
        c.execute("INSERT INTO sighting_users(sighting_id, ord, user_xml_id) VALUES (?, 0, 'u1')",
                  (sighting,))  # fmt: skip
    before = dump(connection)
    changed = SightingDetails(count="~15", heard_only=True, status="intro", breeding="FL",
                              notes=" Raft of ducks ")  # fmt: skip
    with database.action("edit") as c:
        sighting_ops.update_details(c, sighting, changed)
    assert sighting_ops.read_details(connection, sighting) == SightingDetails(
        count="~15", heard_only=True, status="intro", breeding="FL", notes=" Raft of ducks"
    )
    for refused in (SightingDetails(count="lots"), SightingDetails(status="bogus"),
                    SightingDetails(breeding="XX")):  # fmt: skip
        with pytest.raises(SightingError), database.action("refused") as c:
            sighting_ops.update_details(c, sighting, refused)
    assert sighting_ops.read_details(connection, sighting).count == "~15"
    with database.action("delete") as c:
        sighting_ops.delete_sighting(c, sighting)
    assert connection.execute("SELECT count(*) FROM sighting_users").fetchone()[0] == 0
    database.undo()
    database.undo()
    assert dump(connection) == before  # the sighting and its observer are back
    with pytest.raises(SightingError), database.action("gone") as c:
        sighting_ops.delete_sighting(c, -1)

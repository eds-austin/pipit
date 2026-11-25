"""The Trips screen's queries on tests/fixtures/bsxm/trips.bsxm."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pipit.browse.locations import species_at
from pipit.browse.species import sightings_of
from pipit.browse.trips import trip_rows, trip_sighting_ids
from pipit.entry.taxa import EntryTaxa
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm

pytestmark = pytest.mark.scythebill
TRIPS = Path(__file__).parents[1] / "fixtures" / "bsxm" / "trips.bsxm"


@pytest.fixture
def database(pack: Any, tmp_path: Path) -> ListDatabase:
    result = import_bsxm(TRIPS, tmp_path / "t.pipit", pack.base_taxonomy_id,
                         pack.base_taxon_ids(), pack.predefined_locations())  # fmt: skip
    return ListDatabase.open(result.list_path)


def _places(database: ListDatabase, ids: list[int]) -> list[str]:
    return [
        database.connection.execute(
            "SELECT location_xml_id || ' ' || coalesce(date, '-') FROM sightings WHERE id = ?",
            (sighting,),
        ).fetchone()[0]
        for sighting in ids
    ]


def test_trips_newest_first_and_filtered(database: ListDatabase) -> None:
    rows = trip_rows(database.connection)
    assert [row.xml_id for row in rows] == ["coast", "oneday", "spring", "span"]
    assert rows[0].start_text == "1 Jul 2026" and rows[0].notes == "Fog every morning"
    assert [row.xml_id for row in trip_rows(database.connection, "fog")] == ["coast"]
    assert [row.xml_id for row in trip_rows(database.connection, "KENT")] == ["oneday"]


def test_a_trips_sightings(database: ListDatabase) -> None:
    coast = trip_rows(database.connection)[0]
    ids = trip_sighting_ids(database.connection, coast)
    places = _places(database, ids)
    # Its own five (Kent too, though elsewhere), plus the Dunes sighting of 7 July: inside
    # the Coast and within the dates, though not on the trip.
    assert len(ids) == 6
    assert "dunes 2026-07-07" in places
    assert "_scyco_GB-ENG-KEN -" in places
    # A trip with no place takes in any sighting within its dates.
    span = trip_rows(database.connection)[3]
    assert _places(database, trip_sighting_ids(database.connection, span)) == ["muiwoo -"]


def test_undated_trip_sightings_take_the_trips_dates(database: ListDatabase, pack: Any) -> None:
    base, _avilist = pack.load_base_and_avilist()
    taxa = EntryTaxa(base, base)
    coast = trip_rows(database.connection)[0]
    ids = trip_sighting_ids(database.connection, coast)
    seen = {entry.key: entry for entry in species_at(database.connection, taxa, None,
                                                     sighting_ids=ids)}  # fmt: skip
    mallard = seen["spAnaspla"]
    assert (mallard.first_text, mallard.last_text) == ("1 Jul 2026", "8 Jul 2026")
    [row] = sightings_of(database.connection, taxa, mallard)
    assert row.date_text == "1 Jul 2026 – 8 Jul 2026" and row.trip == "Coast week"

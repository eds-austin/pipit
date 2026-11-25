"""The Locations screen's queries on the locations fixture (tools/oracle/make_locations_fixture.py):
subtree totals, roll-up to species, visits and details."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pipit.browse.dates import display_date
from pipit.browse.locations import (
    SpeciesRollup,
    location_tree,
    place_details,
    species_at,
    visits_at,
)
from pipit.entry.taxa import EntryTaxa
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.storage.location_ops import row_of

sys.path.insert(0, str(Path(__file__).parents[1] / "storage"))
from test_storage import BASE, FIXTURES, AnyTaxon

pytestmark = pytest.mark.scythebill  # needs the data pack's taxonomies


@pytest.fixture(scope="module")
def taxa(pack: Any) -> dict[str, EntryTaxa]:
    base, avilist = pack.load_base_and_avilist()
    return {"clements": EntryTaxa(base, base), "avilist": EntryTaxa(base, avilist)}


@pytest.fixture
def database(tmp_path: Path) -> ListDatabase:
    path = import_bsxm(FIXTURES / "locations.bsxm", tmp_path / "l.pipit", BASE, AnyTaxon())
    return ListDatabase.open(path.list_path)


def test_display_dates() -> None:
    assert display_date(2026, 5, 12) == "12 May 2026"
    assert display_date(2026, 5, None) == "May 2026"
    assert display_date(None, 5, 12) == "12 May"
    assert display_date(2026, None, None) == "2026"
    assert display_date(None, None, None) == "No date"


def test_tree_is_pre_order_with_subtree_totals(database: ListDatabase) -> None:
    connection = database.connection
    nodes = location_tree(connection)
    position = {node.row: index for index, node in enumerate(nodes)}
    by_row = {node.row: node for node in nodes}
    for node in nodes:
        if node.parent is not None:
            assert position[node.parent] < position[node.row]
            assert node.depth == by_row[node.parent].depth + 1
        else:
            assert node.depth == 0
    total = connection.execute("SELECT count(*) FROM sightings").fetchone()[0]
    assert sum(node.sightings for node in nodes if node.depth == 0) == total

    def sightings(xml_id: str) -> int:
        return by_row[row_of(connection, xml_id)].sightings

    assert sightings("_usst_califo") == 5  # Lake Merritt 2, Bay Area 1, Lighthouse 1, Muir 1
    assert sightings("bayare") == 4
    assert sightings("_usst_oregon") == 3
    assert sightings("lighth") == 1
    assert by_row[row_of(connection, "_usst_califo")].built_in


def test_species_roll_up_to_the_place_and_everything_inside(
    database: ListDatabase, taxa: dict[str, EntryTaxa]
) -> None:
    connection = database.connection
    seen = species_at(connection, taxa["clements"], row_of(connection, "_usst_califo"))
    by_key = {entry.key: entry for entry in seen}
    assert set(by_key) == {"spAnaspla", "spAnasrub", "spArdeaalb", "spButeo1jam"}
    assert by_key["spAnaspla"].sightings == 2
    assert by_key["spAnaspla"].common == "Mallard"
    assert by_key["spAnaspla"].first_text == by_key["spAnaspla"].last_text == "1 Jan 2026"
    assert [entry.key for entry in seen] == sorted(by_key, key=taxa["clements"].order)
    assert all(entry.is_species for entry in seen)
    # The same birds through the AviList view.
    avilist = species_at(connection, taxa["avilist"], row_of(connection, "_usst_califo"))
    assert len(avilist) == 4 and all(entry.common for entry in avilist)


def test_subspecies_count_as_their_species_and_sp_stays_apart(
    database: ListDatabase, taxa: dict[str, EntryTaxa]
) -> None:
    connection = database.connection
    mallard = taxa["clements"].display.get("spAnaspla")
    assert mallard is not None and mallard.children
    subspecies = mallard.children[0].id
    order = connection.execute("SELECT max(ord) + 1 FROM sightings").fetchone()[0]
    connection.execute(
        "INSERT INTO sightings(ord, kind, taxon_id, location_xml_id, date, date_y, date_m, "
        "date_d) VALUES (?, 'single', ?, 'kent', '2025-03-04', 2025, 3, 4)",
        (order, subspecies),
    )
    cursor = connection.execute(
        "INSERT INTO sightings(ord, kind, location_xml_id) VALUES (?, 'sp', 'kent')",
        (order + 1,),
    )
    for part_order, part in enumerate(("spAnasrub", "spAnaspla")):
        connection.execute(
            "INSERT INTO sighting_taxa(sighting_id, ord, taxon_id) VALUES (?, ?, ?)",
            (cursor.lastrowid, part_order, part),
        )
    connection.commit()
    rollup = SpeciesRollup(taxa["clements"])
    seen = species_at(connection, taxa["clements"], row_of(connection, "kent"), rollup)
    by_key = {entry.key: entry for entry in seen}
    assert by_key["spAnaspla"].sightings == 2  # the species and its subspecies
    assert by_key["spAnaspla"].first_text == "4 Mar 2025"
    assert by_key["spAnaspla"].last_text == "6 Jun 2026"
    sp = next(entry for entry in seen if "/" in entry.key)
    assert not sp.is_species and sp.sightings == 1 and "/" in sp.common


def test_visits_and_details(database: ListDatabase) -> None:
    connection = database.connection
    [visit] = visits_at(connection, "bayare")
    assert (visit.date_text, visit.start_time, visit.protocol, visit.comments) == (
        "1 Jan 2026",
        "08:00",
        "Historical",
        "bay",
    )
    assert visit.sightings == 1  # the Mallard at Bay Area itself, not inside it
    details = place_details(connection, row_of(connection, "lighth"))
    assert details is not None
    assert details.path[-3:] == ["California", "Bay Area", "Point Reyes"]
    merritt = place_details(connection, row_of(connection, "lakmer"))
    assert merritt is not None and merritt.type == "park"
    assert (merritt.latitude, merritt.longitude) == ("37.8000000", "-122.2600000")

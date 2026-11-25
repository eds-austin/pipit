"""Write tests/fixtures/bsxm/locations.bsxm: Scythebill's empty list plus custom places,
visits, a trip and sightings, for checking location operations against Scythebill.

    python -I tools/oracle/make_locations_fixture.py <pack> <out.bsxm>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from pipit.datapack.pack import DataPack
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.storage.location_ops import add_location, row_of

NEW_LIST = Path(__file__).parents[2] / "tests" / "fixtures" / "bsxm" / "new_list.scythebill.bsxm"


def main() -> int:
    pack_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    with DataPack(pack_path) as pack, tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "l.pipit"
        import_bsxm(NEW_LIST, path, pack.base_taxonomy_id, pack.base_taxon_ids())
        with ListDatabase.open(path) as database, database.action("fixture") as c:
            california = row_of(c, "_usst_califo")
            oregon = row_of(c, "_usst_oregon")
            england = row_of(c, "_scyco_GB-ENG")
            ids: dict[str, str] = {}

            def add(key: str, parent: int, name: str, *rest: str) -> int:
                location_type, latitude, longitude = (*rest, None, None, None)[:3]
                ids[key] = add_location(
                    c, parent, name, location_type, latitude=latitude, longitude=longitude
                )
                return row_of(c, ids[key])

            bay = add("bay", california, "Bay Area")
            add("merritt", bay, "Lake Merritt", "park", "37.8", "-122.26")
            reyes = add("reyes", bay, "Point Reyes")
            add("lighthouse", reyes, "Lighthouse")
            marin = add("marin", california, "Marin County", "county")
            add("muir", marin, "Muir Woods")
            add("kent", england, "Kent")
            oregon_bay = add("oregon_bay", oregon, "Bay Area")
            add("yaquina", oregon_bay, "Yaquina Bay")
            coast = add("coast", oregon, "Coast")
            add("coast_lighthouse", coast, "Lighthouse")
            add("dunes", coast, "Dunes")
            sightings = [
                ("spAnaspla", ids["merritt"], "2026-01-01", "08:00", "3"),
                ("spAnasrub", ids["merritt"], "2026-01-01", "08:00", None),
                ("spAnaspla", ids["bay"], "2026-01-01", "08:00", "5"),
                ("spArdeaalb", ids["lighthouse"], "2026-02-02", None, "1"),
                ("spArdeaalb", ids["coast_lighthouse"], "2026-03-03", None, "2"),
                ("spEgretthu", ids["yaquina"], "2026-04-04", "07:00", "4"),
                ("spButeo1jam", ids["muir"], "2026-05-05", None, None),
                ("spAnaspla", ids["kent"], "2026-06-06", None, "9"),
                ("spHirun2rus", ids["dunes"], "2026-07-07", None, "6"),
            ]
            for order, (taxon, location, date, time, count) in enumerate(sightings):
                y, m, d = (int(part) for part in date.split("-"))
                c.execute(
                    "INSERT INTO sightings(ord, kind, taxon_id, location_xml_id, date, date_y, "
                    "date_m, date_d, time, count) VALUES (?, 'single', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (order, taxon, location, date, y, m, d, time, count),
                )
            visits = ((ids["merritt"], "lake"), (ids["bay"], "bay"))
            for order, (location, comments) in enumerate(visits):
                c.execute(
                    "INSERT INTO visits(ord, location_xml_id, date, date_y, date_m, date_d, "
                    "start_time, observation_type, comments) "
                    "VALUES (?, ?, '2026-01-01', 2026, 1, 1, '08:00', 'historical', ?)",
                    (order, location, comments),
                )
            c.execute(
                "INSERT INTO trips(xml_id, location_xml_id, start_date, end_date, name, ord) "
                "VALUES ('coast', ?, '2026-07-01', '2026-07-08', 'Coast week', 0)",
                (ids["coast"],),
            )
            export_bsxm(database, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

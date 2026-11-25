"""Write tests/fixtures/bsxm/queries.bsxm: a list for checking queries against Scythebill
(tools/oracle/QueryOracle.java). Seeded, so it is the same every time.

Starts from Scythebill's 30,000-sighting sample, keeps 6,000 sightings, and spreads them
over custom places under a few built-in states and countries, with every sighting status,
the flags, breeding codes, notes, three observers, visits with comments, trips (with
undated sightings), partial dates, a few undated and unplaced sightings, and photos.

    python -I tools/oracle/make_queries_fixture.py <pack> <large_sample.bsxm> <out.bsxm>
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

from pipit.datapack.pack import DataPack
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.storage.location_ops import add_location, row_of
from pipit.taxa.sighting_taxon import SightingTaxon

STATUSES = ("none",) * 30 + ("notAccepted", "bvd", "intro", "provisional", "notEstablished",
                             "restrained", "domestic", "idUncertain", "unsatisfactoryViews",
                             "notByMe", "dead", "signs")  # fmt: skip
BREEDING = ("",) * 20 + ("NY", "NE", "FL", "NB", "T", "C", "S7", "S", "P", "H", "F", "PE", "B")
NOTES = ("Pair at the pond", "singing", "Flyover, calling", "nest nearby", "Singing male",
         "pond edge", "pair", "Juvenile with adults")  # fmt: skip


def main() -> int:  # noqa: PLR0915 (one long, linear fixture recipe)
    pack_path, sample, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    generator = random.Random(2026)
    with DataPack(pack_path) as pack, tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "q.pipit"
        import_bsxm(sample, path, pack.base_taxonomy_id, pack.base_taxon_ids(),
                    pack.predefined_locations())  # fmt: skip
        with ListDatabase.open(path) as database, database.action("fixture") as c:
            # Keep 6,000 sightings (all the sp. ones among them).
            # Only sightings AviList can show: Scythebill's own QueryProcessor fails on one it
            # can't (resolve() returns null), so they couldn't be checked against it.
            _base, avilist = pack.load_base_and_avilist()
            parts: dict[int, list[str]] = {}
            for sighting, taxon_id in c.execute(
                "SELECT sighting_id, taxon_id FROM sighting_taxa ORDER BY sighting_id, ord"
            ):
                parts.setdefault(sighting, []).append(taxon_id)

            def shown(row: int, kind: str, taxon_id: str | None) -> bool:
                taxon = (SightingTaxon.single(taxon_id) if taxon_id is not None
                         else SightingTaxon.sp(parts[row]))  # fmt: skip
                try:
                    return avilist.resolve_into(taxon) is not None
                except KeyError:
                    return False

            usable = [(row, kind) for row, kind, taxon_id in
                      c.execute("SELECT id, kind, taxon_id FROM sightings").fetchall()
                      if shown(row, kind, taxon_id)]  # fmt: skip
            keep = {row for row, kind in usable if kind == "sp"}
            others = [row for row, kind in usable if kind != "sp"]
            keep.update(generator.sample(others, 6000 - len(keep)))
            for (row,) in c.execute("SELECT id FROM sightings").fetchall():
                if row not in keep:
                    c.execute("DELETE FROM sightings WHERE id = ?", (row,))
            # Places: custom ones under built-in states and countries.
            parents = [
                x
                for (x,) in c.execute(
                    "SELECT xml_id FROM locations WHERE type IN ('country', 'state') ORDER BY id"
                )
            ]
            country = next(
                x
                for (x,) in c.execute(
                    "SELECT xml_id FROM locations WHERE type = 'country' ORDER BY id"
                )
            )
            for name in ("Oregon", "Idaho", "Montana"):
                parents.append(add_location(c, row_of(c, country), name, "state"))
            places = []
            for index in range(24):
                parent = parents[index % len(parents)]
                xml_id = add_location(c, row_of(c, parent), f"Site {index}", "park",
                                      latitude=f"{40 + index * 0.37:.4f}",
                                      longitude=f"{-120 + index * 0.53:.4f}")  # fmt: skip
                places.append(xml_id)
                if index % 4 == 0:
                    places.append(add_location(c, row_of(c, xml_id), f"Trail {index}"))
            for name, abbreviation, order in (("Ann", "AB", 0), ("Ben", "BC", 1), ("Cy", None, 2)):
                c.execute("INSERT INTO users(xml_id, name, abbreviation, ord) VALUES (?, ?, ?, ?)",
                          (name.lower(), name, abbreviation, order))  # fmt: skip
            c.execute(
                "INSERT INTO trips(xml_id, location_xml_id, start_date, end_date, name, ord) "
                "VALUES ('trip1', ?, '2010-05-01', '2010-05-09', 'Spring trip', 0)",
                (parents[0],),
            )
            c.execute(
                "INSERT INTO trips(xml_id, start_date, end_date, name, ord) "
                "VALUES ('trip2', '2015-06', '2015-07', 'Summer', 1)"
            )
            rows = [row for (row,) in c.execute("SELECT id FROM sightings ORDER BY ord")]
            for row in rows:
                place = generator.choice(places)
                roll = generator.random()
                year = generator.randint(1985, 2024)
                month = generator.randint(1, 12)
                day = generator.randint(1, 28)
                if roll < 0.02:
                    date = None  # undated
                elif roll < 0.05:
                    date = (year, None, None)
                elif roll < 0.08:
                    date = (year, month, None)
                elif roll < 0.09:
                    date = (None, month, day)
                else:
                    date = (year, month, day)
                trip = None
                if generator.random() < 0.015:
                    trip, date = "trip1", None
                    place = generator.choice(places[:6])
                elif generator.random() < 0.01:
                    trip, date = "trip2", None
                if generator.random() < 0.005:
                    place = None
                text = None
                if date is not None:
                    fields = [f"{date[0]:04d}" if date[0] else None,
                              f"{date[1]:02d}" if date[1] else None,
                              f"{date[2]:02d}" if date[2] else None]  # fmt: skip
                    text = ("-".join(f for f in fields if f) if date[0]
                            else f"M{fields[1]}-{fields[2]}")  # fmt: skip
                time = (f"{generator.randint(5, 18):02d}:{generator.choice((0, 15, 30, 45)):02d}"
                        if text and date[2] and generator.random() < 0.4 else None)  # fmt: skip
                c.execute(
                    "UPDATE sightings SET location_xml_id = ?, date = ?, date_y = ?, date_m = ?, "
                    "date_d = ?, time = ?, trip_xml_id = ?, status = ?, breeding = ?, "
                    "heard_only = ?, photographed = ?, male = ?, female = ?, adult = ?, "
                    "immature = ?, description = ? WHERE id = ?",
                    (place, text, date[0] if date else None, date[1] if date else None,
                     date[2] if date else None, time, trip, generator.choice(STATUSES),
                     generator.choice(BREEDING), int(generator.random() < 0.12),
                     int(generator.random() < 0.08), int(generator.random() < 0.05),
                     int(generator.random() < 0.05), int(generator.random() < 0.04),
                     int(generator.random() < 0.03),
                     generator.choice(NOTES) if generator.random() < 0.06 else None, row),
                )  # fmt: skip
                for order, user in enumerate(("ann", "ben", "cy")):
                    if generator.random() < (0.5, 0.2, 0.05)[order]:
                        c.execute(
                            "INSERT INTO sighting_users(sighting_id, ord, user_xml_id) "
                            "VALUES (?, ?, ?)",
                            (row, order, user),
                        )
            # Visits with comments for some dated sightings' place, date and time.
            seen = set()
            visits = c.execute(
                "SELECT DISTINCT location_xml_id, date, date_y, date_m, date_d, "
                "coalesce(time, '') FROM sightings WHERE location_xml_id IS NOT NULL "
                "AND date_d IS NOT NULL AND date_y IS NOT NULL ORDER BY ord"
            ).fetchall()
            for order, (place, date, y, m, d, start) in enumerate(visits[:400]):
                if (place, date, start) in seen:
                    continue
                seen.add((place, date, start))
                c.execute(
                    "INSERT INTO visits(ord, location_xml_id, date, date_y, date_m, date_d, "
                    "start_time, observation_type, comments) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'historical', ?)",
                    (order, place, date, y, m, d, start,
                     generator.choice(("Windy, cold", "Calm morning", "rain later", None))),
                )  # fmt: skip
        with ListDatabase.open(path) as database:
            export_bsxm(database, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

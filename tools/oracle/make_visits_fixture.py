"""Write tests/fixtures/bsxm/visits.bsxm: the locations fixture plus visits worth editing,
for checking Enter Sightings' edit of an existing visit against Scythebill's
``SingleLocationEdit`` (tools/oracle/EditVisit.java).

The Lake Merritt visit on 2026-08-08 08:00 has: a species with notes and flags, one of its
subspecies, a sp., two sightings of the same species (Scythebill edits only the first),
Ruddy Duck (a subspecies in AviList) and Andean Duck (a sp. in AviList), and a visit
record. Muir Woods on 2026-09-09 has sightings without a time. Other sightings sit
before and after them in the file, so any reordering shows.

    python -I tools/oracle/make_visits_fixture.py <out.bsxm>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm

BSXM = Path(__file__).parents[2] / "tests" / "fixtures" / "bsxm"


class _AnyTaxon:
    def __contains__(self, item: object) -> bool:
        return True


def main() -> int:
    out = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "v.pipit"
        import_bsxm(BSXM / "locations.bsxm", path, "clements2026", _AnyTaxon())
        with ListDatabase.open(path) as database, database.action("fixture") as c:
            order = c.execute("SELECT max(ord) + 1 FROM sightings").fetchone()[0]

            def sighting(location: str, date: str, time: str | None, taxon: str | None,
                         count: str | None = None, *, parts: tuple[str, ...] = (),
                         heard: int = 0, notes: str | None = None) -> None:  # fmt: skip
                nonlocal order
                y, m, d = (int(part) for part in date.split("-"))
                cursor = c.execute(
                    "INSERT INTO sightings(ord, kind, taxon_id, location_xml_id, date, date_y, "
                    "date_m, date_d, time, count, heard_only, description) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (order, "sp" if parts else "single", taxon, location, date, y, m, d, time,
                     count, heard, notes),
                )  # fmt: skip
                for part_order, part in enumerate(parts):
                    c.execute(
                        "INSERT INTO sighting_taxa(sighting_id, ord, taxon_id) VALUES (?, ?, ?)",
                        (cursor.lastrowid, part_order, part),
                    )
                order += 1

            visit = ("lakmer", "2026-08-08", "08:00")
            sighting("bayare", "2026-08-07", None, "spHirun2rus", "3")
            sighting(*visit, "spAnaspla", "4", heard=1, notes="Pair by the boathouse")
            sighting(*visit, "sspAnasplapla", "1")
            sighting(*visit, "spArdeaalb", "1")
            sighting(*visit, None, parts=("spAnaspla", "spAnasrub"))
            sighting("poirey", "2026-08-08", "08:00", "spEgretthu", "2")  # same time, elsewhere
            sighting(*visit, "spArdeaalb", "2")  # a second Great Egret
            sighting(*visit, "spOxyurjam", "12")
            sighting(*visit, "spOxyurfer", "1")
            sighting("lakmer", "2026-08-08", "17:00", "spAnasrub", "1")  # a later visit
            sighting("muiwoo", "2026-09-09", None, "spButeo1jam", "1")
            sighting("muiwoo", "2026-09-09", None, "spEgretthu", None)
            sighting("bayare", "2026-09-10", None, "spAnaspla", "8")
            c.execute(
                "INSERT INTO visits(ord, location_xml_id, date, date_y, date_m, date_d, "
                "start_time, observation_type, duration_minutes, party_size, comments, complete) "
                "VALUES ((SELECT max(ord) + 1 FROM visits), 'lakmer', '2026-08-08', 2026, 8, 8, "
                "'08:00', 'stationary', 45, 2, 'Calm morning', 1)"
            )
        with ListDatabase.open(path) as database:
            export_bsxm(database, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

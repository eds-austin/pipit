"""Write tests/fixtures/bsxm/trips.bsxm: the locations fixture plus trips with sightings,
for checking trip edits and deletes against Scythebill (tools/oracle/TripOps.java).

- "coast": Oregon's Coast, 2026-07-01 to 2026-07-08, with sightings at the Coast itself
  (dated and undated), inside it (Dunes) and elsewhere (Kent), plus notes;
- "spring": no place, 2025-05 to 2025-06, undated sightings (deleting it dates them 2025);
- "oneday": 2026-03-03 to 2026-03-03, an undated sighting (deleting it dates it that day);
- "span": 2024-12-30 to 2025-01-02, an undated sighting (only the start year is left).

    python -I tools/oracle/make_trips_fixture.py <out.bsxm>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from pipit.domain.partial_date import parse_partial_date
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm

BSXM = Path(__file__).parents[2] / "tests" / "fixtures" / "bsxm"


class _AnyTaxon:
    def __contains__(self, item: object) -> bool:
        return True


def main() -> int:
    out = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "t.pipit"
        import_bsxm(BSXM / "locations.bsxm", path, "clements2026", _AnyTaxon())
        with ListDatabase.open(path) as database, database.action("fixture") as c:
            c.execute(
                "UPDATE trips SET notes = 'Fog every morning', start_time = '06:00' "
                "WHERE xml_id = 'coast'"
            )
            for order, (xml_id, place, start, end, name) in enumerate(
                [("spring", None, "2025-05", "2025-06", "Spring 2025"),
                 ("oneday", "kent", "2026-03-03", "2026-03-03", "Kent day"),
                 ("span", None, "2024-12-30", "2025-01-02", "New Year")], start=1
            ):  # fmt: skip
                c.execute(
                    "INSERT INTO trips(xml_id, location_xml_id, start_date, end_date, name, ord) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (xml_id, place, start, end, name, order),
                )
            ord_ = c.execute("SELECT max(ord) + 1 FROM sightings").fetchone()[0]
            for place, date, taxon, trip in [
                ("coast", None, "spAnaspla", "coast"),
                ("dunes", "2026-07-03", "spHirun2rus", "coast"),
                ("coast", "2026-07-04", "spArdeaalb", "coast"),
                ("bayare", None, "spAnasrub", None),  # not on a trip: in between
                ("kent", None, "spEgretthu", "coast"),  # elsewhere, on the coast trip
                ("coast", None, "spButeo1jam", "coast"),
                ("lakmer", None, "spAnaspla", "spring"),
                ("kent", None, "spAnasrub", "oneday"),
                ("muiwoo", None, "spArdeaalb", "span"),
            ]:
                parsed = None if date is None else parse_partial_date(date)
                c.execute(
                    "INSERT INTO sightings(ord, kind, taxon_id, location_xml_id, date, date_y, "
                    "date_m, date_d, trip_xml_id) VALUES (?, 'single', ?, ?, ?, ?, ?, ?, ?)",
                    (ord_, taxon, place, date, parsed.year if parsed else None,
                     parsed.month if parsed else None, parsed.day if parsed else None, trip),
                )  # fmt: skip
                ord_ += 1
        with ListDatabase.open(path) as database:
            export_bsxm(database, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

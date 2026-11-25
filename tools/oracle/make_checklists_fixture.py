"""Write tests/fixtures/bsxm/checklists.bsxm: the locations fixture plus custom checklists,
for checking checklist edits against Scythebill (tools/oracle/ChecklistOps.java).

- Bay Area: the first 150 base species of the waterfowl to herons (enough for hash
  collisions), every status, a sp. and a species with a subspecies;
- Kent: a few species; Point Reyes: one species.

    python -I tools/oracle/make_checklists_fixture.py <pack> <out.bsxm>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from pipit.datapack.pack import DataPack
from pipit.storage.database import ListDatabase
from pipit.storage.lists import export_bsxm, import_bsxm
from pipit.taxa.model import TaxonType

BSXM = Path(__file__).parents[2] / "tests" / "fixtures" / "bsxm"
STATUSES = (None, "endemic", "introduced", "rarity", "escaped", "extinct", "provisional",
            "rarity-from-introduced")  # fmt: skip


class _AnyTaxon:
    def __contains__(self, item: object) -> bool:
        return True


def main() -> int:
    pack_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    with DataPack(pack_path) as pack:
        base, _avilist = pack.load_base_and_avilist()
    species = [taxon.id for taxon in base.walk() if taxon.type is TaxonType.SPECIES][:150]
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "c.pipit"
        import_bsxm(BSXM / "locations.bsxm", path, "clements2026", _AnyTaxon())
        with ListDatabase.open(path) as database, database.action("fixture") as c:
            lists = {
                "bayare": [("single", taxon, None, STATUSES[i % len(STATUSES)])
                           for i, taxon in enumerate(species)]
                + [("sp", "spAnaspla,spAnasrub", None, "rarity"),
                   ("ssp", "spAnaspla", "conboschas", None)],
                "kent": [("single", taxon, None, None) for taxon in species[:5]],
                "poirey": [("single", "spArdeaalb", None, "rarity")],
            }  # fmt: skip
            for order, (place, entries) in enumerate(lists.items()):
                cursor = c.execute(
                    "INSERT INTO checklists(location_xml_id, ord) VALUES (?, ?)", (place, order)
                )
                for entry_order, (kind, ids, subspecies, status) in enumerate(entries):
                    c.execute(
                        "INSERT INTO checklist_entries(checklist_id, ord, kind, taxon_ids, "
                        "subspecies, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (cursor.lastrowid, entry_order, kind, ids, subspecies, status),
                    )
        with ListDatabase.open(path) as database:
            export_bsxm(database, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

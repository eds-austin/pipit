"""Write a list's sightings as Scythebill CSV with Pipit's Save as Scythebill CSV (which is
byte-identical to Scythebill's: tests/csvio), for testing the import of that format: every
sighting, in Clements, at subspecies depth.

    python -I tools/oracle/export_scythebill_csv.py pack.sqlite list.bsxm out.csv

For a private list, write the file somewhere private (it holds the list's contents).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from pipit.csvio.scythebill_csv import export, load_csv_data
from pipit.datapack.pack import DataPack
from pipit.output.print_html import list_place_names, run_report_query
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import load_query_list
from pipit.storage.database import ListDatabase
from pipit.storage.lists import import_bsxm
from pipit.taxa.model import TaxonType


def main() -> None:
    with DataPack(Path(sys.argv[1])) as pack, tempfile.TemporaryDirectory() as scratch:
        result = import_bsxm(Path(sys.argv[2]), Path(scratch) / "list.pipit",
                             pack.base_taxonomy_id, pack.base_taxon_ids(),
                             pack.predefined_locations())  # fmt: skip
        with ListDatabase.open(result.list_path) as database:
            connection = database.connection
            query_list = load_query_list(connection)
            checklists = Checklists(pack, connection, query_list)
            data = load_csv_data(connection)
            clements, _avilist = pack.load_base_and_avilist()
            context = EngineContext(query_list, clements, TaxonType.SUBSPECIES,
                                    users=frozenset(data.users))  # fmt: skip
            _query, results, _root = run_report_query(context, checklists,
                                                      json.dumps({"fields": []}), data.users,
                                                      only_countable=False)  # fmt: skip
            content = export(results, query_list, list_place_names(query_list, checklists),
                             data, pack.predefined_locations(), excel_compatible=False)  # fmt: skip
    Path(sys.argv[3]).write_bytes(content)
    print(f"{content.count(b'\\n') - 1} rows")


if __name__ == "__main__":
    main()

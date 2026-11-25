"""Write tests/fixtures/bsxm/stored_queries.bsxm: the visits fixture with list preferences
holding stored queries in every form Scythebill has written or might meet: without "type"
(as Scythebill's own restore writes them back), with a legacy top-level ALL/ANY, early
total-ticks queries known only by their prefix, an explicit TOTAL_TICKS, text that Gson
escapes (= < > & ' and U+2028), non-ASCII, a malformed query, and other preference
classes (numbers, lists, an empty object) that must survive untouched.

    make_stored_queries_fixture.py visits.bsxm out.bsxm
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

STORED = "com.scythebill.birdlist.ui.panels.reports.StoredReportSetQueriesPreferences"


def main() -> None:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    location = '{"type":"IN","id":"lakmer"}'
    queries = [
        {
            "name": "Lake Merritt",
            "json": '{"fields":[{"type":"LOCATION","value":' + location + ',"bool":"ALL"}]}',
        },
        {
            "name": "Legacy any",
            "json": '{"type":"ANY","fields":[{"type":"LOCATION","value":'
            + location
            + '},{"type":"DATE","value":{"type":"DURING","from":"2026"}}]}',
        },
        {
            "name": "Notes = <sun & 'wind'>",
            "json": '{"fields":[{"type":"SIGHTING_NOTES","value":{"type":"CONTAINS",'
            '"text":"a = b < c & d \'e\' \u2028 café \\"q\\""},"bool":"ALL"}]}',
        },
        {"name": "Countries", "json": 'COUNTRY/{"fields":[]}'},
        {
            "name": "States 2026",
            "json": 'STATE/{"type":"ALL","fields":[{"type":"DATE",'
            '"value":{"type":"DURING","from":"2026"}}]}',
            "type": "TOTAL_TICKS",
        },
        {"name": "Odd type", "json": '{"fields":[]}', "type": "SOMETHING_NEW"},
        {"name": "Broken", "json": '{"fields":[{"type":'},
        {
            "name": "Times",
            "json": '{"fields":[{"type":"TIMES_SIGHTED","value":{"type":'
            '"AT_LEAST","count":2},"bool":"NEVER"},{"type":"LOCATION","value":{"type":'
            '"IS_NEARER_THAN","id":"lakmer","milesOrKilometers":"MILES","distance":12.5},'
            '"bool":"ANY"}]}',
            "type": "REPORTS",
        },
    ]
    preferences = {
        "com.scythebill.birdlist.ui.events.TaxonomyPreferences.PerReportSet": {
            "lastTaxonomyId": "clements2026"
        },
        STORED: {"storedQueries": json.dumps(queries, separators=(",", ":"))},
        "com.scythebill.birdlist.model.sighting.edits.ChosenUsers": {"userIds": []},
        "com.example.Numbers": {
            "whole": 3,
            "fraction": 1.50,
            "big": 12345678901,
            "flag": True,
            "list": [1, "a", None],
        },
        "com.scythebill.birdlist.ui.panels.location.LocationBrowsePreferences": {},
    }
    text = json.dumps(preferences, indent=2, ensure_ascii=False)
    # Keep 1.50 as written: Gson writes back the number text it read.
    text = text.replace('"fraction": 1.5', '"fraction": 1.50')
    xml = source.read_text(encoding="utf-8")
    end = xml.rindex("</report-set>")
    xml = xml[:end] + "  <prefs>" + escape(text) + "</prefs>\n" + xml[end:]
    target.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    main()

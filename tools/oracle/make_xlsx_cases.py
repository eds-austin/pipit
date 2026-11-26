"""Write the spreadsheet cases for tools/oracle/PrintOracle.java's xlsx mode: the 30 reference
queries with Save as spreadsheet's default options, then every option, sort, names order,
observer column, taxonomy and depth on a few of them.

    python -I tools/oracle/make_xlsx_cases.py queries.txt cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: ``ReportSpreadsheetPreferences``' defaults.
DEFAULTS = {"includeScientific": True, "showFamilies": True, "showStatus": True,
            "showNotes": False, "onlyCountable": False, "omitSpAndHybrid": False,
            "maximumSightings": 1, "sortType": "DEFAULT", "sortSightingsType": "DEFAULT",
            "userOutput": "NONE", "subspeciesInSeparateColumn": False}  # fmt: skip
VARIATIONS: list[tuple[str, dict[str, object], str]] = [
    ("scientific_first", {}, "SCIENTIFIC_FIRST"),
    ("scientific_only", {}, "SCIENTIFIC_ONLY"),
    ("common_only", {"includeScientific": False}, "COMMON_FIRST"),
    ("no_sightings", {"maximumSightings": 0}, "COMMON_FIRST"),
    ("three_sightings", {"maximumSightings": 3}, "COMMON_FIRST"),
    ("notes", {"showNotes": True, "maximumSightings": 2}, "COMMON_FIRST"),
    ("abbreviations", {"userOutput": "USER_ABBREVIATIONS", "maximumSightings": 2},
     "COMMON_FIRST"),
    ("observer_names", {"userOutput": "USER_NAMES"}, "COMMON_FIRST"),
    ("observers_notes", {"userOutput": "BOTH", "showNotes": True}, "COMMON_FIRST"),
    ("newest", {"sortType": "BY_DATE"}, "COMMON_FIRST"),
    ("newest_two", {"sortType": "BY_DATE", "maximumSightings": 2}, "COMMON_FIRST"),
    ("longest", {"sortType": "BY_DATE_DESCENDING", "showNotes": True}, "COMMON_FIRST"),
    ("day_of_year", {"sortType": "BY_DAY_OF_YEAR"}, "SCIENTIFIC_FIRST"),
    ("most_recorded", {"sortType": "BY_SIGHTING_COUNT", "maximumSightings": 0},
     "COMMON_FIRST"),
    ("sightings_latest", {"sortSightingsType": "BY_DATE_DESCENDING", "maximumSightings": 3},
     "COMMON_FIRST"),
    ("sightings_count", {"sortSightingsType": "BY_SIGHTING_COUNT", "maximumSightings": 3},
     "COMMON_FIRST"),
    ("only_countable", {"onlyCountable": True}, "COMMON_FIRST"),
    ("omit_sp", {"omitSpAndHybrid": True}, "COMMON_FIRST"),
    ("no_status", {"showStatus": False}, "COMMON_FIRST"),
    ("no_families", {"showFamilies": False}, "COMMON_FIRST"),
]  # fmt: skip
VARIED_QUERIES = (2, 22, 24, 29)  # Washington, sp.s, seen 3 times in Idaho, lifers highlighted
DEPTH_VARIATIONS: list[tuple[str, dict[str, object], str]] = [
    ("", {}, "COMMON_FIRST"),
    ("_no_sightings", {"maximumSightings": 0}, "COMMON_FIRST"),
    ("_subspecies_column", {"subspeciesInSeparateColumn": True}, "COMMON_FIRST"),
    ("_subspecies_column_scientific", {"subspeciesInSeparateColumn": True},
     "SCIENTIFIC_FIRST"),
    ("_subspecies_column_common_only",
     {"subspeciesInSeparateColumn": True, "includeScientific": False}, "COMMON_FIRST"),
]  # fmt: skip


def case(name: str, query: object, *, display: str = "clements", depth: str = "species",
         options: dict[str, object] | None = None, names: str = "COMMON_FIRST") -> str:  # fmt: skip
    return json.dumps({"name": name, "query": query, "display": display, "depth": depth,
                       "namesOrder": names,
                       "options": {**DEFAULTS, **(options or {})}})  # fmt: skip


def main() -> None:
    queries = [json.loads(line) for line in Path(sys.argv[1]).read_text().split("\n") if line]
    lines = [case(f"q{i:02d}", query) for i, query in enumerate(queries, 1)]
    for number in VARIED_QUERIES:
        for label, options, names in VARIATIONS:
            lines.append(case(f"q{number:02d}_{label}", queries[number - 1], options=options,
                              names=names))  # fmt: skip
    for number in (1, 2, 22, 29):
        lines.append(case(f"q{number:02d}_avilist_species", queries[number - 1],
                          display="avilist"))  # fmt: skip
        for display, depth in (("clements", "subspecies"), ("avilist", "group")):
            for label, options, names in DEPTH_VARIATIONS:
                lines.append(case(f"q{number:02d}_{display}_{depth}{label}", queries[number - 1],
                                  display=display, depth=depth, options=options,
                                  names=names))  # fmt: skip
    Path(sys.argv[2]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

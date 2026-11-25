"""Write the print cases for tools/oracle/PrintOracle.java: the 30 reference queries with
Print's default options, then every option, sort, names order, taxonomy and depth on a few of
them. (Synthetic regions' checklists are checked on their own: PrintOracle's checklists mode.)

    python -I tools/oracle/make_print_cases.py queries.txt cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULTS = {"includeScientific": True, "showFamilies": True, "showStatus": True,
            "maximumSightings": 1, "sortType": "DEFAULT", "sortSightingsType": "DEFAULT",
            "compactPrinting": False, "onlyCountable": False, "omitSpAndHybrid": False}  # fmt: skip
VARIATIONS: list[tuple[str, dict[str, object], str]] = [
    ("compact", {"compactPrinting": True}, "COMMON_FIRST"),
    ("compact_common_only", {"compactPrinting": True, "includeScientific": False}, "COMMON_FIRST"),
    ("scientific_first", {}, "SCIENTIFIC_FIRST"),
    ("scientific_only", {"compactPrinting": True}, "SCIENTIFIC_ONLY"),
    ("common_only", {"includeScientific": False}, "COMMON_FIRST"),
    ("no_sightings", {"maximumSightings": 0}, "COMMON_FIRST"),
    ("three_sightings", {"maximumSightings": 3}, "COMMON_FIRST"),
    ("newest", {"sortType": "BY_DATE"}, "COMMON_FIRST"),
    ("newest_two", {"sortType": "BY_DATE", "maximumSightings": 2}, "COMMON_FIRST"),
    ("longest", {"sortType": "BY_DATE_DESCENDING"}, "COMMON_FIRST"),
    ("day_of_year", {"sortType": "BY_DAY_OF_YEAR"}, "COMMON_FIRST"),
    ("day_of_year_reversed", {"sortType": "BY_DAY_OF_YEAR_DESCENDING"}, "COMMON_FIRST"),
    ("most_recorded", {"sortType": "BY_SIGHTING_COUNT", "compactPrinting": True},
     "COMMON_FIRST"),
    ("sightings_latest", {"sortSightingsType": "BY_DATE_DESCENDING", "maximumSightings": 3},
     "COMMON_FIRST"),
    ("sightings_count", {"sortSightingsType": "BY_SIGHTING_COUNT", "maximumSightings": 3},
     "COMMON_FIRST"),
    ("sightings_day", {"sortSightingsType": "BY_DAY_OF_YEAR", "maximumSightings": 2},
     "COMMON_FIRST"),
    ("only_countable", {"onlyCountable": True}, "COMMON_FIRST"),
    ("omit_sp", {"omitSpAndHybrid": True}, "COMMON_FIRST"),
    ("no_status", {"showStatus": False}, "COMMON_FIRST"),
    ("no_families", {"showFamilies": False}, "COMMON_FIRST"),
]  # fmt: skip
VARIED_QUERIES = (2, 22, 24, 29)  # Washington, sp.s, seen 3 times in Idaho, lifers highlighted


def case(name: str, query: object, *, display: str = "clements", depth: str = "species",
         options: dict[str, object] | None = None, names: str = "COMMON_FIRST") -> str:  # fmt: skip
    return json.dumps({"name": name, "query": query, "display": display, "depth": depth,
                       "fileName": "queries", "date": "11/25/26", "namesOrder": names,
                       "options": {**DEFAULTS, **(options or {})}})  # fmt: skip


def main() -> None:
    queries = [json.loads(line) for line in Path(sys.argv[1]).read_text().split("\n") if line]
    lines = [case(f"q{i:02d}", query) for i, query in enumerate(queries, 1)]
    for number in VARIED_QUERIES:
        for label, options, names in VARIATIONS:
            lines.append(case(f"q{number:02d}_{label}", queries[number - 1], options=options,
                              names=names))  # fmt: skip
    for number in (1, 2, 29):
        for display, depth in (("avilist", "species"), ("clements", "subspecies"),
                               ("avilist", "group")):  # fmt: skip
            lines.append(case(f"q{number:02d}_{display}_{depth}", queries[number - 1],
                              display=display, depth=depth))  # fmt: skip
        lines.append(case(f"q{number:02d}_avilist_subspecies_compact", queries[number - 1],
                          display="avilist", depth="subspecies",
                          options={"compactPrinting": True}))  # fmt: skip
    Path(sys.argv[2]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

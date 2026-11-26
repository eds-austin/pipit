"""Write the year comparison cases for tools/oracle/PrintOracle.java's years mode, on
tests/fixtures/bsxm/queries.bsxm (forty years of sightings, some dated only by month or year):
the whole list, one state, a range of years, a start year only, an end year only, and a
species group, in both taxonomies.

    python -I tools/oracle/make_years_cases.py cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

QUERIES: list[tuple[str, list[dict[str, object]], dict[str, int]]] = [
    ("everything", [], {}),
    ("washington", [{"type": "LOCATION", "value": {"type": "IN", "id": "wa"}, "bool": "ALL"}], {}),
    ("range", [], {"from": 2000, "to": 2010}),
    ("from_2015", [], {"from": 2015}),
    ("to_1990", [], {"to": 1990}),
    ("washington_range",
     [{"type": "LOCATION", "value": {"type": "IN", "id": "wa"}, "bool": "ALL"}],
     {"from": 1995, "to": 2005}),
]  # fmt: skip


def main() -> None:
    lines = []
    for display in ("clements", "avilist"):
        for name, fields, years in QUERIES:
            case = {"name": f"{name}_{display}", "query": {"fields": fields},
                    "display": display, "depth": "species", **years}  # fmt: skip
            lines.append(json.dumps(case))
    Path(sys.argv[1]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

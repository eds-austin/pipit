"""Write the timeline cases for tools/oracle/PrintOracle.java's timeline mode: on
tests/fixtures/bsxm/queries.bsxm (forty years, some dates only a month or a year) the whole
list, one state, and the list without another state; on tests/fixtures/bsxm/trip_report.bsxm
(sightings recorded only on a trip of several days) the whole list. Both taxonomies.

    python -I tools/oracle/make_timeline_cases.py <folder>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _location(place: str, operation: str = "ALL") -> dict[str, object]:
    return {"type": "LOCATION", "value": {"type": "IN", "id": place}, "bool": operation}


LISTS: dict[str, list[tuple[str, list[dict[str, object]]]]] = {
    "queries": [("everything", []), ("washington", [_location("wa")]),
                ("never_oregon", [_location("oregon", "NEVER")])],
    "trip_report": [("trip", [])],
}  # fmt: skip


def main() -> None:
    folder = Path(sys.argv[1])
    for list_name, queries in LISTS.items():
        lines = [json.dumps({"name": f"{name}_{display}", "query": {"fields": fields},
                             "display": display, "depth": "species"})
                 for display in ("clements", "avilist") for name, fields in queries]  # fmt: skip
        (folder / f"cases.{list_name}.jsonl").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

"""Write the splits-and-lumps cases for tools/oracle/PrintOracle.java's splits mode, on
tests/fixtures/bsxm/queries.bsxm: the whole list, one state, and the list without another
state, in both taxonomies (each case runs every version its taxonomy offers).

    python -I tools/oracle/make_splits_cases.py cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _location(place: str, operation: str = "ALL") -> dict[str, object]:
    return {"type": "LOCATION", "value": {"type": "IN", "id": place}, "bool": operation}


QUERIES: list[tuple[str, list[dict[str, object]]]] = [
    ("everything", []),
    ("washington", [_location("wa")]),
    ("never_oregon", [_location("oregon", "NEVER")]),
]


def main() -> None:
    lines = [json.dumps({"name": f"{name}_{display}", "query": {"fields": fields},
                         "display": display, "depth": "species"})
             for display in ("clements", "avilist") for name, fields in QUERIES]  # fmt: skip
    Path(sys.argv[1]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

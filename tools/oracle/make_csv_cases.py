"""Write the Scythebill CSV export cases for tools/oracle/PrintOracle.java's csv mode: the 30
reference queries, everything in both taxonomies and at every depth, and Excel-compatible.

    python -I tools/oracle/make_csv_cases.py queries.txt cases.jsonl everything.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def case(name: str, query: object, display: str = "avilist", depth: str = "species",
         excel: bool = False) -> str:  # fmt: skip
    return json.dumps({"name": name, "query": query, "display": display, "depth": depth,
                       "excel": excel})  # fmt: skip


def main() -> None:
    queries = [json.loads(line) for line in Path(sys.argv[1]).read_text().split("\n") if line]
    everything = {"fields": []}
    common = [case("everything", everything),
              case("everything_clements", everything, "clements"),
              case("everything_subspecies", everything, "clements", "subspecies"),
              case("everything_avilist_group", everything, "avilist", "group"),
              case("everything_excel", everything, excel=True)]  # fmt: skip
    lines = [case(f"q{i:02d}", query) for i, query in enumerate(queries, 1)] + common
    Path(sys.argv[2]).write_text("\n".join(lines) + "\n")
    Path(sys.argv[3]).write_text("\n".join(common) + "\n")


if __name__ == "__main__":
    main()

"""Write the eBird export cases for tools/oracle/PrintOracle.java's ebird mode: each of the
30 reference queries (run in Clements at group depth, as Save for eBird runs them).

    python -I tools/oracle/make_ebird_cases.py queries.txt cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    queries = [json.loads(line) for line in Path(sys.argv[1]).read_text().split("\n") if line]
    lines = [json.dumps({"name": f"q{i:02d}", "query": query, "display": "clements",
                         "depth": "group"})
             for i, query in enumerate(queries, 1)]  # fmt: skip
    lines.append(json.dumps({"name": "everything", "query": {"fields": []},
                             "display": "clements", "depth": "group"}))  # fmt: skip
    Path(sys.argv[2]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

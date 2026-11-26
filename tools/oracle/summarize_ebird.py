"""Summarize PrintOracle's eBird exports: for each case, each file it wrote (name.csv,
name-1.csv...) by size and SHA-256.

python -I tools/oracle/summarize_ebird.py cases.jsonl dir > files.jsonl
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    directory = Path(sys.argv[2])
    for line in Path(sys.argv[1]).read_text().split("\n"):
        if not line.strip():
            continue
        name = json.loads(line)["name"]
        files = []
        index = 0
        while True:
            path = directory / (f"{name}.csv" if index == 0 else f"{name}-{index}.csv")
            if not path.exists():
                break
            data = path.read_bytes()
            files.append({"size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            index += 1
        print(json.dumps({"name": name, "files": files}))


if __name__ == "__main__":
    main()

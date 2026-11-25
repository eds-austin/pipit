"""Summarize PrintOracle's pages as one line per case: its name, size and SHA-256.

python -I tools/oracle/summarize_pages.py cases.jsonl pages_dir > pages.jsonl
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    cases, pages = Path(sys.argv[1]), Path(sys.argv[2])
    for line in cases.read_text().split("\n"):
        if not line.strip():
            continue
        name = json.loads(line)["name"]
        data = (pages / f"{name}.html").read_bytes()
        print(json.dumps({"name": name, "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()}))  # fmt: skip


if __name__ == "__main__":
    main()

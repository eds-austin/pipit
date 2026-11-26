"""Summarize PrintOracle's Word documents: for each case, the size and SHA-256 of its
``word/document.xml`` and ``word/_rels/document.xml.rels`` (the content; the package's
metadata says who wrote it and when), and its title.

python -I tools/oracle/summarize_docx.py cases.jsonl dir > docx.jsonl
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any


def summary(name: str, data: bytes) -> dict[str, Any]:
    archive = zipfile.ZipFile(__import__("io").BytesIO(data))
    found: dict[str, Any] = {"name": name}
    for part, key in (("word/document.xml", "document"),
                      ("word/_rels/document.xml.rels", "relationships")):  # fmt: skip
        content = archive.read(part)
        found[key] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    title = re.search(rb"<dc:title>(.*?)</dc:title>", archive.read("docProps/core.xml"))
    found["title"] = title.group(1).decode("utf-8") if title else None
    return found


def main() -> None:
    directory = Path(sys.argv[2])
    for line in Path(sys.argv[1]).read_text().split("\n"):
        if line.strip():
            name = json.loads(line)["name"]
            print(json.dumps(summary(name, (directory / f"{name}.docx").read_bytes()),
                             ensure_ascii=False))  # fmt: skip


if __name__ == "__main__":
    main()

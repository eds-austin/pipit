"""Turn raw Oracle.java output into the compact fixtures under tests/fixtures/oracle.

    python -I tools/oracle/summarize.py <oracle out dir> <pack> tests/fixtures/oracle

Search results are stored as (count, SHA-1 of the sorted results) per query; ID tables are
gzipped. Only taxon IDs and hashes are committed, never names.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sys
from pathlib import Path

from pipit.datapack.pack import DataPack


def digest(results: str) -> str:
    return hashlib.sha1(results.encode("utf-8")).hexdigest()


def main() -> int:
    raw, pack_path, fixtures = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    fixtures.mkdir(parents=True, exist_ok=True)
    queries = (fixtures / "corpus.txt").read_text(encoding="utf-8").split("\n")[:-1]
    position = {query: i for i, query in enumerate(queries)}
    lines = []
    for line in (raw / "search.tsv").read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        taxonomy_id, kind, query, results = line.split("\t", 3)
        count = len(results.split("\x1f")) if results else 0
        lines.append(f"{taxonomy_id}\t{kind}\t{position[query]}\t{count}\t{digest(results)}")
    (fixtures / "search.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for name in ("resolutions.tsv", "mapping_back.tsv"):
        with (
            (raw / name).open("rb") as source,
            gzip.GzipFile(fixtures / f"{name}.gz", "wb", mtime=0) as target,
        ):
            shutil.copyfileobj(source, target)

    names = {}
    for path in sorted(raw.glob("avilist_names_*.tsv")):
        text = path.read_text(encoding="utf-8")
        locale = path.stem.removeprefix("avilist_names_")
        names[locale] = {"count": text.count("\n"), "sha1": digest(text)}
    with DataPack(pack_path) as pack:
        source = {"pack_id": pack.pack_id, "source_sha256": pack.meta["source_sha256"],
                  "source_revision": pack.meta["source_revision"]}  # fmt: skip
    (fixtures / "meta.json").write_text(
        json.dumps({"source": source, "avilist_names": names}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"fixtures written to {fixtures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

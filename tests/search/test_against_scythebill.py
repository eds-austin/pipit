"""Pipit's ports give exactly Scythebill's answers on the bundled 2026 taxonomies.

Expected results come from Scythebill itself (tools/oracle/run.sh) and are stored as
hashes and ID tables in tests/fixtures/oracle. They are tied to one Scythebill data release;
after a taxonomy update, regenerate them with that script.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import statistics
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pipit.search.taxon_index import IndexKind, TaxonIndex
from pipit.taxa.avilist_names import mapped_names
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxonomy
from pipit.taxa.sighting_taxon import SightingTaxonType

pytestmark = pytest.mark.scythebill
ORACLE = Path(__file__).parents[1] / "fixtures" / "oracle"
_ID_INDEXES = (IndexKind.COMMON, IndexKind.SCIENTIFIC)


@pytest.fixture(scope="module")
def taxonomies(pack: Any) -> tuple[Taxonomy, MappedTaxonomy]:
    meta = json.loads((ORACLE / "meta.json").read_text(encoding="utf-8"))
    if pack.meta["source_sha256"] != meta["source"]["source_sha256"]:
        pytest.skip("oracle fixtures are for other Scythebill data; run tools/oracle/run.sh")
    base, avilist = pack.load_base_and_avilist()
    return base, avilist


@pytest.fixture(scope="module")
def indexes(taxonomies: tuple[Taxonomy, MappedTaxonomy]) -> dict[str, TaxonIndex]:
    return {taxonomy.id: TaxonIndex(taxonomy) for taxonomy in taxonomies}


def _corpus() -> list[str]:
    return (ORACLE / "corpus.txt").read_text(encoding="utf-8").split("\n")[:-1]


def _gz_lines(name: str) -> Iterator[list[str]]:
    with gzip.open(ORACLE / name, "rt", encoding="utf-8") as file:
        for line in file:
            yield line.rstrip("\n").split("\t")


def test_search_results_equal_scythebill(indexes: dict[str, TaxonIndex]) -> None:
    queries = _corpus()
    differences = []
    lines = (ORACLE / "search.tsv").read_text(encoding="utf-8").splitlines()
    for line in lines:
        taxonomy_id, kind_name, position, count, digest = line.split("\t")
        kind = IndexKind(kind_name)
        query = queries[int(position)]
        found = indexes[taxonomy_id].find(kind, query)
        keys = sorted(
            {entry.taxon_id if kind in _ID_INDEXES else f"{entry.name}|{entry.taxon_id}"
             for entry in found}
        )  # fmt: skip
        actual = hashlib.sha1("\x1f".join(keys).encode("utf-8")).hexdigest()
        if actual != digest:
            differences.append((taxonomy_id, kind_name, query, int(count), len(keys)))
    assert len(lines) == len(queries) * 8
    assert not differences, differences[:10]


def test_resolutions_equal_scythebill(
    pack: Any, taxonomies: tuple[Taxonomy, MappedTaxonomy]
) -> None:
    stored = {
        base_id: (kind, ids)
        for base_id, kind, ids in pack.connection.execute(
            "SELECT base_id, kind, ids FROM resolutions"
        )
    }
    expected = {}
    for base_id, *rest in _gz_lines("resolutions.tsv.gz"):
        if rest[0] not in ("NONE", "ERROR"):
            expected[base_id] = (rest[0], rest[1])
    assert stored == expected


def test_mappings_back_and_disabled_flags_equal_scythebill(
    taxonomies: tuple[Taxonomy, MappedTaxonomy],
) -> None:
    _, avilist = taxonomies
    differences = []
    for taxon_id, state, *rest in _gz_lines("mapping_back.tsv.gz"):
        taxon = avilist[taxon_id]
        mapping = avilist.mapping(taxon)
        if mapping is None:
            actual = "NONE"
        else:
            suffix = (
                f"|{mapping.subspecies}"
                if mapping.type is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES
                else ""
            )
            actual = f"{mapping.type.value}\t{','.join(sorted(mapping.ids))}{suffix}"
        if actual != "\t".join(rest) or (state == "disabled") != taxon.disabled:
            differences.append((taxon_id, state, rest, actual, taxon.disabled))
    assert not differences, differences[:10]


def test_avilist_names_equal_scythebill(
    pack: Any, taxonomies: tuple[Taxonomy, MappedTaxonomy]
) -> None:
    _, avilist = taxonomies
    expected = json.loads((ORACLE / "meta.json").read_text(encoding="utf-8"))["avilist_names"]
    for locale, summary in expected.items():
        names = mapped_names(avilist, locale, pack.names(locale))
        text = "".join(f"{taxon_id}\t{name}\n" for taxon_id, name in sorted(names.items()))
        assert len(names) == summary["count"], locale
        assert hashlib.sha1(text.encode("utf-8")).hexdigest() == summary["sha1"], locale


def test_keystroke_search_is_fast(indexes: dict[str, TaxonIndex]) -> None:
    """A keystroke searches all four indexes; p95 must stay under 10 ms."""
    for index in indexes.values():
        timings = []
        for query in _corpus():
            started = time.perf_counter()
            for kind in IndexKind:
                index.find(kind, query)
            timings.append(time.perf_counter() - started)
        p95 = statistics.quantiles(timings, n=20)[-1]
        assert p95 < 0.010, f"{index.taxonomy.id}: p95 {p95 * 1000:.1f} ms"

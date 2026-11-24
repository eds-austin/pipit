"""Check a data pack, on its own and against the Scythebill sources it was built from.

Errors make a pack unusable; warnings are oddities in the source data worth knowing about.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pipit.datapack.pack import DataPack
from pipit.packbuild import readers
from pipit.packbuild.build import (
    CHECKLIST_STATUSES,
    FLAVORS,
    LoadedTaxonomies,
    resolution_rows,
    source_files,
)
from pipit.packbuild.sources import ScythebillSources, sha256_of
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import TaxonType

UPGRADE_KINDS = {"SAME", "SM??", "SPLT", "LUMP", "MULT", "NEW", "NWWR", "WARN"}
_EXAMPLES = 5


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str, examples: Sequence[object] | None = None) -> None:
        self.errors.append(_with_examples(message, examples))

    def warn(self, message: str, examples: Sequence[object] | None = None) -> None:
        self.warnings.append(_with_examples(message, examples))


def _with_examples(message: str, examples: Sequence[object] | None) -> str:
    if not examples:
        return message
    shown = ", ".join(str(example) for example in examples[:_EXAMPLES])
    more = f" (+{len(examples) - _EXAMPLES} more)" if len(examples) > _EXAMPLES else ""
    return f"{message}: {shown}{more}"


def validate(pack_path: Path, sources: ScythebillSources | None = None) -> Report:
    report = Report()
    with DataPack(pack_path) as pack:
        connection = pack.connection
        report.facts["pack_id"] = pack.pack_id
        report.facts["size_mb"] = round(pack_path.stat().st_size / 1e6, 1)
        _check_sqlite(connection, report)
        taxonomy_ids = [row[0] for row in connection.execute("SELECT id FROM taxonomies")]
        for taxonomy_id in taxonomy_ids:
            _check_nested_set(connection, taxonomy_id, report)
        base, avilist = pack.load_base_and_avilist()
        report.facts["taxa"] = {
            taxonomy.id: {t.xml_name: taxonomy.count(t) for t in TaxonType if taxonomy.count(t)}
            for taxonomy in (base, avilist)
        }
        _check_mappings(avilist, report)
        _check_resolutions(pack, LoadedTaxonomies(base, avilist), report)
        _check_checklists(connection, report)
        _check_upgrades(connection, base.id, report)
        _check_names(connection, base.id, report)
        _check_maps(connection, report)
        if sources is not None:
            _check_against_sources(pack, sources, report)
    return report


def _check_sqlite(connection: sqlite3.Connection, report: Report) -> None:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        report.error("SQLite integrity check failed")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        report.error("foreign key violations", list(violations))


def _check_nested_set(connection: sqlite3.Connection, taxonomy_id: str, report: Report) -> None:
    count, lowest, highest = connection.execute(
        "SELECT count(*), min(taxo_ord), max(taxo_ord) FROM taxa WHERE taxonomy_id = ?",
        (taxonomy_id,),
    ).fetchone()
    if (lowest, highest) != (0, count - 1):
        report.error(f"{taxonomy_id}: taxonomic order is not 0..{count - 1}")
    bad = connection.execute(
        "SELECT c.id FROM taxa c JOIN taxa p ON p.taxonomy_id = c.taxonomy_id "
        "AND p.id = c.parent_id WHERE c.taxonomy_id = ? AND NOT "
        "(p.taxo_ord < c.taxo_ord AND c.taxo_ord <= c.subtree_end "
        "AND c.subtree_end <= p.subtree_end)",
        (taxonomy_id,),
    ).fetchall()
    if bad:
        report.error(f"{taxonomy_id}: nested-set order broken", [row[0] for row in bad])
    roots = connection.execute(
        "SELECT id, taxo_ord, subtree_end FROM taxa WHERE taxonomy_id = ? AND parent_id IS NULL",
        (taxonomy_id,),
    ).fetchall()
    if len(roots) != 1 or roots[0][1:] != (0, count - 1):
        report.error(f"{taxonomy_id}: expected one root spanning the tree, got {roots}")


def _check_mappings(avilist: MappedTaxonomy, report: Report) -> None:
    missing = []
    for taxon_id, mapping in avilist.exact_mappings().items():
        missing += [
            f"{taxon_id}->{base_id}" for base_id in mapping.ids if base_id not in avilist.base
        ]
    if missing:
        report.error(f"{avilist.id}: mappings to missing base taxa", missing)
    report.facts["mappings"] = len(avilist.exact_mappings())


def _check_resolutions(pack: DataPack, taxonomies: LoadedTaxonomies, report: Report) -> None:
    stored = {
        base_id: (kind, ids)
        for _, base_id, kind, ids in pack.connection.execute(
            "SELECT taxonomy_id, base_id, kind, ids FROM resolutions"
        )
    }
    recomputed = {base_id: (kind, ids) for _, base_id, kind, ids in resolution_rows(taxonomies)}
    if stored != recomputed:
        differing = sorted(set(stored.items()) ^ set(recomputed.items()))
        report.error("stored resolutions differ from recomputed ones", differing)
    unresolved = [
        taxon.id
        for taxon in taxonomies.base.walk()
        if taxon.type is TaxonType.SPECIES and taxon.id not in stored
    ]
    if unresolved:
        report.warn(f"{len(unresolved)} base species have no AviList counterpart", unresolved)
    report.facts["resolutions"] = len(stored)


def _check_checklists(connection: sqlite3.Connection, report: Report) -> None:
    for taxonomy_id, regions, rows in connection.execute(
        "SELECT taxonomy_id, count(DISTINCT region), count(*) FROM checklists GROUP BY taxonomy_id"
    ):
        report.facts[f"checklists.{taxonomy_id}"] = f"{regions} regions, {rows} entries"
    unknown = connection.execute(
        "SELECT c.taxonomy_id, c.region, c.taxon_id FROM checklists c LEFT JOIN taxa t "
        "ON t.taxonomy_id = c.taxonomy_id AND t.id = c.taxon_id WHERE t.id IS NULL"
    ).fetchall()
    if unknown:
        report.error("checklist entries for unknown taxa", unknown)
    not_species = connection.execute(
        "SELECT c.taxonomy_id, c.region, c.taxon_id, t.rank FROM checklists c JOIN taxa t "
        "ON t.taxonomy_id = c.taxonomy_id AND t.id = c.taxon_id WHERE t.rank != 'species'"
    ).fetchall()
    if not_species:
        report.error("checklist entries that are not species", not_species)
    statuses = Counter(
        dict(connection.execute("SELECT status, count(*) FROM checklists GROUP BY status"))
    )
    odd = {status: n for status, n in statuses.items() if status not in CHECKLIST_STATUSES}
    if odd:
        examples = connection.execute(
            "SELECT taxonomy_id, region, taxon_id, status FROM checklists "
            f"WHERE status NOT IN ({','.join('?' * len(CHECKLIST_STATUSES))})",
            sorted(CHECKLIST_STATUSES),
        ).fetchall()
        report.warn(f"unknown checklist statuses {odd}", examples)


def _check_upgrades(connection: sqlite3.Connection, base_id: str, report: Report) -> None:
    kinds = dict(connection.execute("SELECT kind, count(*) FROM upgrade_mappings GROUP BY kind"))
    unknown_kinds = sorted(set(kinds) - UPGRADE_KINDS)
    if unknown_kinds:
        report.warn("unknown upgrade row kinds", list(unknown_kinds))
    known = {
        row[0]
        for row in connection.execute("SELECT id FROM taxa WHERE taxonomy_id = ?", (base_id,))
    }
    missing = []
    for from_taxonomy, from_id, kind, to_id in connection.execute(
        "SELECT from_taxonomy, from_id, kind, coalesce(to_id, from_id) FROM upgrade_mappings"
    ):
        targets = to_id.split(",") if kind == "MULT" else [to_id]
        missing += [f"{from_taxonomy}:{from_id}->{t}" for t in targets if t not in known]
    if missing:
        report.error(
            f"{len(missing)} upgrade mappings point at taxa missing from {base_id}", missing
        )
    report.facts["upgrade_mappings"] = sum(kinds.values())


def _check_names(connection: sqlite3.Connection, base_id: str, report: Report) -> None:
    unknown = connection.execute(
        "SELECT n.locale, n.taxon_id FROM names n LEFT JOIN taxa t "
        "ON t.taxonomy_id = ? AND t.id = n.taxon_id WHERE t.id IS NULL",
        (base_id,),
    ).fetchall()
    if unknown:
        report.warn(f"{len(unknown)} localized names for taxa not in {base_id}", unknown)
    report.facts["locales"] = connection.execute(
        "SELECT count(DISTINCT locale) FROM names"
    ).fetchone()[0]


def _check_maps(connection: sqlite3.Connection, report: Report) -> None:
    bad = []
    for layer, order, geometry, water in connection.execute(
        "SELECT layer, ord, geometry, water FROM map_features"
    ):
        if readers.wkb_type(geometry) != 6 or (water is not None and readers.wkb_type(water) != 6):
            bad.append(f"{layer}#{order}")
    if bad:
        report.error("map features that are not MultiPolygons", bad)
    report.facts["map_layers"] = dict(
        connection.execute("SELECT layer, count(*) FROM map_features GROUP BY layer")
    )


def _check_against_sources(pack: DataPack, sources: ScythebillSources, report: Report) -> None:
    current = sha256_of(sources.root, source_files(sources))
    if current != pack.meta.get("source_sha256"):
        report.warn("the Scythebill sources have changed since this pack was built")
    for path, taxonomy_id in (
        (sources.base_taxonomy, pack.base_taxonomy_id),
        (sources.avilist_taxonomy, pack.meta["mapped_taxonomies"].split(",")[0]),
    ):
        text = path.read_text(encoding="utf-8")
        for taxon_type in TaxonType:
            expected = len(re.findall(rf"<{taxon_type.xml_name}\s", text))
            actual = pack.connection.execute(
                "SELECT count(*) FROM taxa WHERE taxonomy_id = ? AND rank = ?",
                (taxonomy_id, taxon_type.xml_name),
            ).fetchone()[0]
            if expected != actual:
                report.error(
                    f"{taxonomy_id}: {actual} {taxon_type.xml_name} taxa, source has {expected}"
                )
    taxonomy_by_flavor = dict(
        zip(
            FLAVORS,
            [pack.base_taxonomy_id, pack.meta["mapped_taxonomies"].split(",")[0]],
            strict=True,
        )
    )
    for flavor, taxonomy_id in taxonomy_by_flavor.items():
        from_pack = {
            (taxon_id, status, region)
            for region, taxon_id, status in pack.connection.execute(
                "SELECT region, taxon_id, status FROM checklists WHERE taxonomy_id = ?",
                (taxonomy_id,),
            )
        }
        from_transpose = {
            (taxon_id, status if status in CHECKLIST_STATUSES else "", code)
            for taxon_id, status, codes in readers.read_transpose(sources.transpose_file(flavor))
            for code in codes
        }
        if from_pack != from_transpose:
            only_pack = sorted(from_pack - from_transpose)
            only_transpose = sorted(from_transpose - from_pack)
            report.error(
                f"{flavor}: per-region checklists and {flavor}.transpose disagree "
                f"({len(only_pack)} only in CSVs, {len(only_transpose)} only in transpose)",
                [*only_pack[:3], *only_transpose[:3]],
            )
    normalized = json.loads(pack.meta.get("checklist_statuses_read_as_native", "[]"))
    if normalized:
        report.warn("source checklist statuses read as native, as Scythebill does", normalized)
    report.facts["source_checked"] = True


def format_report(report: Report) -> str:
    lines = [f"{'OK' if report.ok else 'FAILED'}: {len(report.errors)} errors, "
             f"{len(report.warnings)} warnings"]  # fmt: skip
    lines += [f"  {key}: {json.dumps(value) if isinstance(value, dict) else value}"
              for key, value in report.facts.items()]  # fmt: skip
    lines += [f"ERROR {message}" for message in report.errors]
    lines += [f"warning {message}" for message in report.warnings]
    return "\n".join(lines)

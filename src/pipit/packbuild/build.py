"""Build a data pack from a Scythebill checkout.

The pack is written to a temporary file in one transaction, vacuumed, and renamed into
place only when complete, so a failed build never leaves a half-written pack. The output
is deterministic: the same sources give a byte-identical file (no timestamps inside).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pipit.datapack.schema import APPLICATION_ID, PACK_FORMAT, SCHEMA
from pipit.packbuild import readers
from pipit.packbuild.sources import ScythebillSources, sha256_of
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxon, Taxonomy
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType
from pipit.taxa.xml_reader import read_mapped_taxonomy, read_taxonomy

FLAVORS = {"clements": 0, "avilist": 1}  # checklist folder -> taxonomy order
#: Checklist status texts Scythebill knows (Checklist.Status); "" is native. Any other
#: text is read as native by ClementsChecklistReader, so it is stored as "".
CHECKLIST_STATUSES = frozenset(
    {"", "endemic", "extinct", "introduced", "provisional", "rarity",
     "rarity-from-introduced", "escaped"}
)  # fmt: skip
_LOCALE_FILE = re.compile(r"^clements-names-(?P<locale>.+)\.csv$")
_LOCATION_PROPERTIES = re.compile(r"^locations(?:_(?P<locale>.+))?\.properties$")
_SYNTHETIC_NAMES = re.compile(r"^synthetic-locations-(?P<locale>.+)\.csv$")
LOCATION_CSVS = ("countries.csv", "all-states.csv", "us-states.csv", "us-counties.csv")
#: Importers' tables (``LocationAliases``, ``LocationShortcuts``), kept as rows like the above.
IMPORT_CSVS = ("location-aliases.csv", "imported-countries-de.csv", "imported-countries-fr.csv",
               "imported-countries-nl.csv", "ebird-checklist-headers.csv")  # fmt: skip
ATTRIBUTIONS = (
    "eBird/Clements Checklist of Birds of the World, Cornell Lab of Ornithology.",
    "AviList: the global avian checklist, AviList Core Team (CC BY 4.0).",
    "Regional checklists, mappings and names prepared by Scythebill (Adam Winer).",
    "Map data: Natural Earth (public domain).",
)


class BuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedTaxonomies:
    base: Taxonomy
    avilist: MappedTaxonomy


def load_taxonomies(sources: ScythebillSources) -> LoadedTaxonomies:
    base = read_taxonomy(sources.base_taxonomy)
    avilist = read_mapped_taxonomy(sources.avilist_taxonomy, base)
    return LoadedTaxonomies(base, avilist)


def pack_id_for(base: Taxonomy, revision: int) -> str:
    match = re.search(r"(\d{4})$", base.id)
    if match is None:
        raise BuildError(f"cannot tell the year of base taxonomy {base.id!r}")
    return f"{match.group(1)}.{revision}"


def pack_file_name(pack_id: str) -> str:
    return f"pipit-pack-{pack_id}.sqlite"


def build_pack(sources: ScythebillSources, out_dir: Path, revision: int = 1) -> Path:
    sources.check()
    taxonomies = load_taxonomies(sources)
    pack_id = pack_id_for(taxonomies.base, revision)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / pack_file_name(pack_id)
    temporary = target.with_name(target.name + ".building")
    temporary.unlink(missing_ok=True)

    connection = sqlite3.connect(temporary, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {PACK_FORMAT}")
        connection.execute("BEGIN")
        for statement in _statements(SCHEMA):
            connection.execute(statement)
        _write_taxonomy(connection, taxonomies.base, 0, kind="base")
        _write_taxonomy(connection, taxonomies.avilist, 1, kind="mapped")
        _write_mappings(connection, taxonomies.avilist)
        _write_resolutions(connection, taxonomies)
        _write_names(connection, sources)
        normalized_statuses = _write_checklists(connection, sources, taxonomies)
        _write_upgrades(connection, sources)
        _write_locations(connection, sources)
        _write_maps(connection, sources)
        _write_meta(connection, sources, taxonomies, pack_id, normalized_statuses)
        connection.execute("COMMIT")
        connection.execute("VACUUM")
        problems = connection.execute("PRAGMA integrity_check").fetchall()
        if problems != [("ok",)]:
            raise BuildError(f"integrity check failed: {problems}")
    except BaseException:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    temporary.replace(target)
    return target


def _statements(script: str) -> Iterator[str]:
    """Split the schema into statements (it has no semicolons inside strings)."""
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    for statement in "\n".join(lines).split(";"):
        if statement.strip():
            yield statement.strip()


def _write_taxonomy(
    connection: sqlite3.Connection, taxonomy: Taxonomy, order: int, kind: str
) -> None:
    base_id = taxonomy.base.id if isinstance(taxonomy, MappedTaxonomy) else None
    connection.execute(
        "INSERT INTO taxonomies VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            taxonomy.id,
            taxonomy.name,
            kind,
            base_id,
            taxonomy.account_url_format,
            taxonomy.account_link_title,
            order,
        ),
    )
    connection.executemany(
        "INSERT INTO taxonomy_credits VALUES (?, ?, ?)",
        [(taxonomy.id, i, text) for i, text in enumerate(taxonomy.additional_credits)],
    )
    rows = []
    alternates: list[tuple[str, str, str, int, str]] = []
    if taxonomy.root is not None:
        for taxon, order_number, subtree_end in _with_nested_set(taxonomy.root):
            rows.append(
                (
                    taxonomy.id,
                    taxon.id,
                    taxon.parent.id if taxon.parent else None,
                    taxon.type.xml_name,
                    taxon.name,
                    taxon.common_name,
                    taxon.account_id,
                    taxon.concept_id,
                    taxon.status,
                    taxon.range,
                    taxon.taxonomic_info,
                    taxon.miscellaneous,
                    int(taxon.disabled),
                    order_number,
                    subtree_end,
                )
            )
            for kind_name, names in (
                ("common", taxon.alternate_common_names),
                ("scientific", taxon.alternate_names),
            ):
                alternates.extend(
                    (taxonomy.id, taxon.id, kind_name, i, name) for i, name in enumerate(names)
                )
    connection.executemany(f"INSERT INTO taxa VALUES ({', '.join('?' * 15)})", rows)
    connection.executemany("INSERT INTO alternate_names VALUES (?, ?, ?, ?, ?)", alternates)


def _with_nested_set(root: Taxon) -> list[tuple[Taxon, int, int]]:
    """(taxon, pre-order number, last pre-order number in its subtree)."""
    ordered: list[Taxon] = []
    ends: dict[str, int] = {}

    def visit(taxon: Taxon) -> int:
        ordered.append(taxon)
        end = len(ordered) - 1
        for child in taxon.children:
            end = visit(child)
        ends[taxon.id] = end
        return end

    visit(root)  # the tree is only about eight levels deep
    return [(taxon, i, ends[taxon.id]) for i, taxon in enumerate(ordered)]


def _write_mappings(connection: sqlite3.Connection, avilist: MappedTaxonomy) -> None:
    rows = []
    for taxon in avilist.walk():
        mapping = avilist.exact_mapping(taxon)
        if mapping is None:
            continue
        kind = {
            SightingTaxonType.SINGLE: "single",
            SightingTaxonType.SP: "sp",
            SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES: "ssp",
        }[mapping.type]
        rows.append((avilist.id, taxon.id, kind, ",".join(mapping.ids), mapping.subspecies))
    connection.executemany("INSERT INTO mappings VALUES (?, ?, ?, ?, ?)", rows)


def resolution_rows(taxonomies: LoadedTaxonomies) -> list[tuple[str, str, str, str]]:
    """``resolveInto`` for every base taxon below the root."""
    rows = []
    avilist = taxonomies.avilist
    for taxon in taxonomies.base.walk():
        if taxon.parent is None:
            continue  # the root has no counterpart (Scythebill cannot resolve it either)
        resolved = avilist.resolve_into(SightingTaxon.single(taxon.id))
        if resolved is None:
            continue
        ids = ",".join(resolved.sighting_taxon.ids)
        rows.append((avilist.id, taxon.id, resolved.type.value, ids))
    return rows


def _write_resolutions(connection: sqlite3.Connection, taxonomies: LoadedTaxonomies) -> None:
    connection.executemany(
        "INSERT INTO resolutions VALUES (?, ?, ?, ?)", resolution_rows(taxonomies)
    )


def _write_names(connection: sqlite3.Connection, sources: ScythebillSources) -> None:
    for path in sorted(sources.multilingual_dir.glob("clements-names-*.csv")):
        match = _LOCALE_FILE.match(path.name)
        if match is None:
            continue
        locale = match.group("locale")
        seen: dict[str, str] = {}
        for taxon_id, name in readers.read_names(path):
            if taxon_id in seen and seen[taxon_id] != name:
                raise BuildError(f"{path.name}: two names for {taxon_id}")
            seen[taxon_id] = name
        connection.executemany(
            "INSERT INTO names VALUES (?, ?, ?)",
            [(locale, taxon_id, name) for taxon_id, name in seen.items()],
        )


def _write_checklists(
    connection: sqlite3.Connection, sources: ScythebillSources, taxonomies: LoadedTaxonomies
) -> list[str]:
    """Writes the checklists; returns the entries whose status text was read as native."""
    normalized: list[str] = []
    taxonomy_ids = {"clements": taxonomies.base.id, "avilist": taxonomies.avilist.id}
    for flavor, taxonomy_id in taxonomy_ids.items():
        for path in sorted(sources.checklist_dir(flavor).glob("*.csv")):
            region = path.stem
            entries = readers.read_checklist(path)
            ids = [entry.taxon_id for entry in entries]
            if len(set(ids)) != len(ids):
                raise BuildError(f"{flavor}/{path.name}: a taxon is listed twice")
            rows = []
            for i, entry in enumerate(entries):
                status = entry.status
                if status not in CHECKLIST_STATUSES:
                    normalized.append(f"{flavor}/{region}/{entry.taxon_id}={status}")
                    status = ""
                rows.append((taxonomy_id, region, i, entry.taxon_id, status))
            connection.executemany("INSERT INTO checklists VALUES (?, ?, ?, ?, ?)", rows)
    return normalized


def upgrade_rows(
    from_taxonomy: str, rows: list[readers.UpgradeRow]
) -> tuple[list[tuple[str, str, str, str | None]], list[tuple[str, str]]]:
    """Mapping rows as ``TaxonomyMappingLoader`` reads them: rows with an empty from or to
    ID are ignored, except that a WARN row always registers a warning for its to ID."""
    mappings: dict[str, tuple[str, str, str, str | None]] = {}
    warnings: set[str] = set()
    for row in rows:
        if row.from_id and row.to_id:
            if row.from_id in mappings:
                raise BuildError(f"{from_taxonomy}: two mappings for {row.from_id}")
            same = row.kind != "MULT" and row.to_id == row.from_id
            mappings[row.from_id] = (
                from_taxonomy,
                row.from_id,
                row.kind,
                None if same else row.to_id,
            )
        if row.kind == "WARN":
            warnings.add(row.to_id)
    return list(mappings.values()), [(from_taxonomy, to_id) for to_id in sorted(warnings)]


def _write_upgrades(connection: sqlite3.Connection, sources: ScythebillSources) -> None:
    for source in sources.upgrade_sources():
        mappings, warnings = upgrade_rows(
            source.from_taxonomy, readers.read_upgrade_mappings(source.main)
        )
        connection.executemany("INSERT INTO upgrade_mappings VALUES (?, ?, ?, ?)", mappings)
        connection.executemany("INSERT INTO upgrade_warnings VALUES (?, ?)", warnings)
        if source.subspecies is not None:
            connection.executemany(
                "INSERT INTO upgrade_subspecies_mappings VALUES (?, ?, ?, ?, ?)",
                [
                    (source.from_taxonomy, i, species, subspecies, to_id)
                    for i, (species, subspecies, to_id) in enumerate(
                        readers.read_subspecies_mappings(source.subspecies)
                    )
                ],
            )


def _write_locations(connection: sqlite3.Connection, sources: ScythebillSources) -> None:
    csvs = [sources.locations_dir / name for name in LOCATION_CSVS]
    csvs += [sources.imports_dir / name for name in IMPORT_CSVS]
    csvs += sources.split_reports
    for path in csvs:
        rows = readers.read_csv_rows(path)
        connection.executemany(
            "INSERT INTO location_rows VALUES (?, ?, ?)",
            [(path.name, i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(rows)],
        )
    for path in sorted(sources.locations_dir.glob("locations*.properties")):
        match = _LOCATION_PROPERTIES.match(path.name)
        if match is None:
            continue
        locale = match.group("locale") or ""
        _insert_display_names(connection, "location", locale, readers.read_properties(path))
    for path in sorted(sources.i18n_dir.glob("synthetic-locations-*.csv")):
        match = _SYNTHETIC_NAMES.match(path.name)
        if match is None:
            continue
        _insert_display_names(
            connection, "synthetic", match.group("locale"), readers.read_names(path)
        )


def _insert_display_names(
    connection: sqlite3.Connection, kind: str, locale: str, pairs: Iterable[tuple[str, str]]
) -> None:
    connection.executemany(
        "INSERT INTO display_names VALUES (?, ?, ?, ?)",
        [(kind, locale, key, name) for key, name in pairs],
    )


def _write_maps(connection: sqlite3.Connection, sources: ScythebillSources) -> None:
    for path in sorted(sources.mapdata_dir.glob("*.mapbin")):
        connection.executemany(
            "INSERT INTO map_features VALUES (?, ?, ?, ?, ?)",
            [
                (path.stem, i, json.dumps(feature.attributes, ensure_ascii=False),
                 feature.geometry, feature.water)
                for i, feature in enumerate(readers.read_mapbin(path))
            ],
        )  # fmt: skip


def source_files(sources: ScythebillSources) -> list[Path]:
    files = sources.required_files()
    files += sorted(sources.multilingual_dir.glob("clements-names-*.csv"))
    files += sorted(sources.i18n_dir.glob("synthetic-locations-*.csv"))
    for flavor in FLAVORS:
        files += sorted(sources.checklist_dir(flavor).glob("*.csv"))
    files += [sources.locations_dir / name for name in LOCATION_CSVS]
    files += [sources.imports_dir / name for name in IMPORT_CSVS]
    files += sources.split_reports
    files += sorted(sources.locations_dir.glob("locations*.properties"))
    files += sorted(sources.mapdata_dir.glob("*.mapbin"))
    return files


def _write_meta(
    connection: sqlite3.Connection,
    sources: ScythebillSources,
    taxonomies: LoadedTaxonomies,
    pack_id: str,
    normalized_statuses: list[str],
) -> None:
    meta = {
        "checklist_statuses_read_as_native": json.dumps(normalized_statuses),
        "format": str(PACK_FORMAT),
        "pack_id": pack_id,
        "base_taxonomy": taxonomies.base.id,
        "mapped_taxonomies": taxonomies.avilist.id,
        "default_taxonomy": taxonomies.avilist.id,
        "source": "scythebill",
        "source_revision": sources.git_revision(),
        "source_sha256": sha256_of(sources.root, source_files(sources)),
        "attributions": json.dumps(ATTRIBUTIONS),
    }
    connection.executemany("INSERT INTO pack_meta VALUES (?, ?)", sorted(meta.items()))

"""Open an installed data pack (read-only) and load what the app needs from it."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pipit.datapack.schema import APPLICATION_ID, PACK_FORMAT
from pipit.domain.locations import PredefinedLocations
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType


class PackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChecklistRow:
    taxon_id: str
    status: str  # "" = native


class DataPack:
    """A read-only connection to one pack. Not thread-safe; open one per thread."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise PackError(f"no data pack at {path}")
        self.path = path
        uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        self._connection = sqlite3.connect(uri, uri=True)
        application_id = self._scalar("PRAGMA application_id")
        if application_id != APPLICATION_ID:
            self.close()
            raise PackError(f"{path.name} is not a Pipit data pack")
        self.meta: dict[str, str] = {
            str(key): str(value)
            for key, value in self._connection.execute("SELECT key, value FROM pack_meta")
        }
        if self.meta.get("format") != str(PACK_FORMAT):
            self.close()
            raise PackError(
                f"{path.name} has pack format {self.meta.get('format')}; "
                f"this version of Pipit reads format {PACK_FORMAT}"
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> DataPack:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def _scalar(self, sql: str, *parameters: object) -> object:
        row = self._connection.execute(sql, parameters).fetchone()
        return row[0] if row else None

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    @property
    def pack_id(self) -> str:
        return self.meta["pack_id"]

    @property
    def base_taxonomy_id(self) -> str:
        return self.meta["base_taxonomy"]

    # ------------------------------------------------------------ taxonomies

    def load_taxonomy(self, taxonomy_id: str, base: Taxonomy | None = None) -> Taxonomy:
        """Rebuild a taxonomy tree. A mapped taxonomy needs its loaded ``base``."""
        row = self._connection.execute(
            "SELECT name, kind, base_id, account_url_format, account_link_title "
            "FROM taxonomies WHERE id = ?",
            (taxonomy_id,),
        ).fetchone()
        if row is None:
            raise PackError(f"no taxonomy {taxonomy_id!r} in {self.path.name}")
        name, kind, base_id, url_format, link_title = row
        taxonomy: Taxonomy
        if kind == "mapped":
            if base is None or base.id != base_id:
                raise PackError(f"{taxonomy_id} needs its base taxonomy {base_id}")
            taxonomy = MappedTaxonomy(base, taxonomy_id, name)
            taxonomy.account_url_format = url_format
            taxonomy.account_link_title = link_title
        else:
            taxonomy = Taxonomy(taxonomy_id, name, url_format, link_title)
        taxonomy.additional_credits = [
            text
            for (text,) in self._connection.execute(
                "SELECT text FROM taxonomy_credits WHERE taxonomy_id = ? ORDER BY ord",
                (taxonomy_id,),
            )
        ]
        for (
            taxon_id, parent_id, rank, taxon_name, common_name, account_id, concept_id, status,
            range_text, taxonomic_info, miscellaneous, disabled,
        ) in self._connection.execute(
            "SELECT id, parent_id, rank, name, common_name, account_id, concept_id, status, "
            "range, taxonomic_info, miscellaneous, disabled "
            "FROM taxa WHERE taxonomy_id = ? ORDER BY taxo_ord",
            (taxonomy_id,),
        ):  # fmt: skip
            parent = taxonomy[parent_id] if parent_id is not None else None
            taxon = taxonomy.add(taxon_id, TaxonType.from_xml_name(rank), taxon_name, parent)
            taxon.common_name = common_name
            taxon.account_id = account_id
            taxon.concept_id = concept_id
            taxon.status = status
            taxon.range = range_text
            taxon.taxonomic_info = taxonomic_info
            taxon.miscellaneous = miscellaneous
            taxon.disabled = bool(disabled)
        for taxon_id, kind_name, alternate in self._connection.execute(
            "SELECT taxon_id, kind, name FROM alternate_names WHERE taxonomy_id = ? "
            "ORDER BY taxon_id, kind, ord",
            (taxonomy_id,),
        ):
            taxon = taxonomy[taxon_id]
            if kind_name == "common":
                taxon.alternate_common_names.append(alternate)
            else:
                taxon.alternate_names.append(alternate)
        if isinstance(taxonomy, MappedTaxonomy):
            mappings = {}
            for taxon_id, mapping_kind, base_ids, subspecies in self._connection.execute(
                "SELECT m.taxon_id, m.kind, m.base_ids, m.subspecies FROM mappings m "
                "JOIN taxa t ON t.taxonomy_id = m.taxonomy_id AND t.id = m.taxon_id "
                "WHERE m.taxonomy_id = ? ORDER BY t.taxo_ord",
                (taxonomy_id,),
            ):
                mappings[taxonomy[taxon_id]] = _mapping(mapping_kind, base_ids, subspecies)
            taxonomy.set_mappings(mappings)
        return taxonomy

    def load_base_and_avilist(self) -> tuple[Taxonomy, MappedTaxonomy]:
        base = self.load_taxonomy(self.base_taxonomy_id)
        mapped_id = self.meta["mapped_taxonomies"].split(",")[0]
        avilist = self.load_taxonomy(mapped_id, base)
        assert isinstance(avilist, MappedTaxonomy)
        return base, avilist

    def resolutions(self, taxonomy_id: str) -> dict[str, SightingTaxon]:
        """Stored ``resolveInto`` results: base ID -> mapped sighting taxon."""
        result = {}
        for base_id, kind, ids in self._connection.execute(
            "SELECT base_id, kind, ids FROM resolutions WHERE taxonomy_id = ?", (taxonomy_id,)
        ):
            parts = ids.split(",")
            result[base_id] = (
                SightingTaxon.single(parts[0])
                if kind == "single"
                else SightingTaxon(SightingTaxonType(kind), tuple(parts))
            )
        return result

    # ------------------------------------------------------------ checklists

    def checklist_regions(self, taxonomy_id: str) -> list[str]:
        return [
            region
            for (region,) in self._connection.execute(
                "SELECT DISTINCT region FROM checklists WHERE taxonomy_id = ? ORDER BY region",
                (taxonomy_id,),
            )
        ]

    def checklist(self, taxonomy_id: str, region: str) -> list[ChecklistRow]:
        return [
            ChecklistRow(taxon_id, status)
            for taxon_id, status in self._connection.execute(
                "SELECT taxon_id, status FROM checklists WHERE taxonomy_id = ? AND region = ? "
                "ORDER BY ord",
                (taxonomy_id, region),
            )
        ]

    def transposed_checklists(self, taxonomy_id: str) -> list[tuple[str, str, str]]:
        """Every checklist row of a taxonomy: (taxon ID, status, region)."""
        return self._connection.execute(
            "SELECT taxon_id, status, region FROM checklists WHERE taxonomy_id = ? "
            "ORDER BY region, ord",
            (taxonomy_id,),
        ).fetchall()

    def names(self, locale: str) -> dict[str, str]:
        """Localized common names by base taxon ID."""
        return dict(
            self._connection.execute("SELECT taxon_id, name FROM names WHERE locale = ?", (locale,))
        )

    def locales(self) -> list[str]:
        return [
            locale
            for (locale,) in self._connection.execute(
                "SELECT DISTINCT locale FROM names ORDER BY locale"
            )
        ]

    def location_rows(self, source: str) -> list[list[str]]:
        """Rows of one of Scythebill's predefined-location CSVs, header first."""
        return [
            json.loads(fields)
            for (fields,) in self._connection.execute(
                "SELECT fields FROM location_rows WHERE source = ? ORDER BY ord", (source,)
            )
        ]

    def location_display_names(self, locale: str = "") -> dict[str, str]:
        """Scythebill's ``locations.properties`` (``locale`` "": English): display names of
        built-in places by code, and of regions by key."""
        return dict(self._connection.execute(
            "SELECT key, name FROM display_names WHERE kind = 'location' AND locale = ?",
            (locale,),
        ).fetchall())  # fmt: skip

    def predefined_locations(self) -> PredefinedLocations:
        return PredefinedLocations.from_rows(
            self.location_rows("all-states.csv"), self.location_rows("us-counties.csv")
        )

    def base_taxon_ids(self) -> set[str]:
        return {
            taxon_id
            for (taxon_id,) in self._connection.execute(
                "SELECT id FROM taxa WHERE taxonomy_id = ?", (self.base_taxonomy_id,)
            )
        }

    def iter_upgrade_mappings(self, from_taxonomy: str) -> Iterator[tuple[str, str, str]]:
        """(from id, kind, to id) with "same ID" rows expanded."""
        for from_id, kind, to_id in self._connection.execute(
            "SELECT from_id, kind, to_id FROM upgrade_mappings WHERE from_taxonomy = ?",
            (from_taxonomy,),
        ):
            yield from_id, kind, from_id if to_id is None else to_id


def _mapping(kind: str, base_ids: str, subspecies: str | None) -> SightingTaxon:
    if kind == "single":
        return SightingTaxon.single(base_ids)
    if kind == "sp":
        return SightingTaxon.sp(base_ids.split(","))
    if kind == "ssp" and subspecies is not None:
        return SightingTaxon.with_secondary_subspecies(base_ids, subspecies)
    raise PackError(f"bad mapping kind {kind!r}")

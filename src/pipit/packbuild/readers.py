"""Readers for Scythebill's CSV, properties, transpose and ``.mapbin`` resources.

Each reader returns the data as it is on disk; interpretation happens in the app. Formats:

- names (``multilingual/clements-names-<locale>.csv``): ``"taxonId","name"``
- checklists (``checklist/<flavor>/<CODE>.csv``): header ``"Name","ID","Status"``; an empty
  status is native (``ClementsChecklistReader.java``)
- transposes (``checklist/<flavor>.transpose``): ``taxonId[/status]=CODE,CODE,...``
  (``TransposedChecklists.java``)
- upgrade mappings (``<old>to<new>.csv``): ``TYPE,fromId,toId,oldName,newName``; the
  subspecies supplement is ``baseSpeciesId,subspeciesName,newId``
  (``TaxonomyMappingLoader.kt``)
- ``.mapbin`` (``MapLayerFile.java``): Java ``DataOutputStream`` with magic "SBML",
  version 2, attribute names, then per feature: nullable attribute values, WKB geometry,
  and optional WKB water geometry
"""

from __future__ import annotations

import csv
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

MAPBIN_MAGIC = 0x53424D4C  # "SBML"
MAPBIN_VERSION = 2


class ReadError(ValueError):
    pass


def read_csv_rows(path: Path) -> Iterator[list[str]]:
    with path.open(encoding="utf-8", newline="") as file:
        yield from csv.reader(file)


def read_names(path: Path) -> Iterator[tuple[str, str]]:
    for line_number, row in enumerate(read_csv_rows(path), 1):
        if not row:
            continue
        if len(row) != 2:
            raise ReadError(f"{path.name}:{line_number}: expected 2 fields, got {len(row)}")
        yield row[0], row[1]


@dataclass(frozen=True, slots=True)
class ChecklistEntry:
    name: str
    taxon_id: str
    status: str  # "" = native


def read_checklist(path: Path) -> list[ChecklistEntry]:
    rows = read_csv_rows(path)
    header = next(rows, None)
    if header != ["Name", "ID", "Status"]:
        raise ReadError(f"{path.name}: unexpected header {header}")
    entries = []
    for line_number, row in enumerate(rows, 2):
        if not row:
            continue
        if len(row) != 3:
            raise ReadError(f"{path.name}:{line_number}: expected 3 fields, got {len(row)}")
        entries.append(ChecklistEntry(row[0], row[1], row[2]))
    return entries


def read_transpose(path: Path) -> Iterator[tuple[str, str, list[str]]]:
    """(taxon id, status or "", region codes) per line."""
    with path.open(encoding="utf-8") as file:
        for line_number, raw in enumerate(file, 1):
            line = raw.rstrip("\n")
            if not line:
                continue
            key, separator, codes = line.partition("=")
            if not separator:
                raise ReadError(f"{path.name}:{line_number}: no '='")
            taxon_id, _, status = key.partition("/")
            yield taxon_id, status, [code for code in codes.split(",") if code]


@dataclass(frozen=True, slots=True)
class UpgradeRow:
    kind: str
    from_id: str
    to_id: str
    old_name: str
    new_name: str


def read_upgrade_mappings(path: Path) -> list[UpgradeRow]:
    rows = []
    for line_number, row in enumerate(read_csv_rows(path), 1):
        if not row:
            continue
        if len(row) < 3:
            raise ReadError(f"{path.name}:{line_number}: expected at least 3 fields")
        padded = [*row, "", ""][:5]
        rows.append(UpgradeRow(*padded))
    return rows


def read_subspecies_mappings(path: Path) -> list[tuple[str, str, str]]:
    rows = []
    for line_number, row in enumerate(read_csv_rows(path), 1):
        if not row:
            continue
        if len(row) != 3:
            raise ReadError(f"{path.name}:{line_number}: expected 3 fields, got {len(row)}")
        rows.append((row[0], row[1], row[2]))
    return rows


def read_properties(path: Path) -> list[tuple[str, str]]:
    """Simple ``key = value`` Java properties (comments and blank lines skipped).
    The files here are UTF-8 with no escapes or continuations; anything else fails."""
    pairs = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "#!":
            continue
        if line.endswith("\\") or "\\u" in line:
            raise ReadError(f"{path.name}:{line_number}: escapes are not supported")
        key, separator, value = line.partition("=")
        if not separator:
            raise ReadError(f"{path.name}:{line_number}: no '='")
        pairs.append((key.strip(), value.strip()))
    return pairs


# ------------------------------------------------------------------ mapbin


@dataclass(frozen=True, slots=True)
class MapFeature:
    attributes: dict[str, str | None]
    geometry: bytes  # WKB MultiPolygon
    water: bytes | None  # WKB MultiPolygon of water areas that still resolve to it


class _JavaData:
    """Reads what ``java.io.DataOutputStream`` wrote."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def _take(self, count: int) -> bytes:
        end = self._offset + count
        if end > len(self._data):
            raise ReadError("unexpected end of map data")
        chunk = self._data[self._offset : end]
        self._offset = end
        return chunk

    def int(self) -> int:
        value: int = struct.unpack(">i", self._take(4))[0]
        return value

    def boolean(self) -> bool:
        return self._take(1) != b"\0"

    def utf(self) -> str:
        """``readUTF``: 2-byte length, then modified UTF-8 (NUL as C0 80, surrogate
        pairs encoded separately)."""
        length: int = struct.unpack(">H", self._take(2))[0]
        raw = self._take(length).replace(b"\xc0\x80", b"\0")
        text = raw.decode("utf-8", errors="surrogatepass")
        return text.encode("utf-16", errors="surrogatepass").decode("utf-16")

    def blob(self) -> bytes:
        return self._take(self.int())

    @property
    def at_end(self) -> bool:
        return self._offset == len(self._data)


def read_mapbin(path: Path) -> list[MapFeature]:
    data = _JavaData(path.read_bytes())
    if data.int() != MAPBIN_MAGIC:
        raise ReadError(f"{path.name}: not a map layer file")
    version = data.int()
    if version != MAPBIN_VERSION:
        raise ReadError(f"{path.name}: unsupported map layer version {version}")
    names = [data.utf() for _ in range(data.int())]
    features = []
    for _ in range(data.int()):
        attributes = {name: (data.utf() if data.boolean() else None) for name in names}
        geometry = data.blob()
        water = data.blob()
        features.append(MapFeature(attributes, geometry, water or None))
    if not data.at_end:
        raise ReadError(f"{path.name}: trailing bytes after the last feature")
    return features


def wkb_type(wkb: bytes) -> int:
    """Geometry type code of a WKB blob (6 = MultiPolygon)."""
    if len(wkb) < 5:
        raise ReadError("WKB too short")
    order = "<" if wkb[0] == 1 else ">"
    code: int = struct.unpack(order + "I", wkb[1:5])[0]
    return code

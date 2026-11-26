"""Which importer reads a file, as Scythebill's ``EBird.chooseImporter`` decides from its
first row: My Data has a "Checklist Comments" column, life lists start "Row #" and have
"S/P" and "LocID" (and "Countable" since 2023), Scythebill's CSV has Common or Scientific and
Date columns, anything else is the Record Format. (eBird's
checklist download starts with "Species", in one of eBird's languages.)"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pipit.imports.ebird_checklist import EBirdChecklistFile
from pipit.imports.ebird_life_list import EBirdLifeList2023File, EBirdLifeListFile
from pipit.imports.ebird_record import EBirdRecordFile
from pipit.imports.fields import read_rows
from pipit.imports.my_data import MissingHeaderError, MyDataFile
from pipit.imports.scythebill_csv import ScythebillCsvFile
from pipit.imports.source import ImportSource

FORMATS: dict[str, Callable[[Path], ImportSource]] = {
    "myData": MyDataFile,
    "ebirdRecord": EBirdRecordFile,
    "lifeList2023": EBirdLifeList2023File,
    "lifeList": EBirdLifeListFile,
    "scythebillCsv": ScythebillCsvFile,
}


def detect(path: Path, checklist_headers: dict[str, list[str]] | None = None) -> str:
    rows = read_rows(path)
    first = rows[0] if rows else []
    species = (checklist_headers or {}).get("Species", ["Species"])
    if first and first[0] in species:
        return "ebirdChecklist"
    if "Checklist Comments" in first:
        return "myData"
    if first and first[0].lower() == "row #" and "S/P" in first and "LocID" in first:
        return "lifeList2023" if "Countable" in first else "lifeList"
    columns = {"".join(cell.split()).lower() for cell in first}
    if ("common" in columns or "scientific" in columns) and "date" in columns:
        return "scythebillCsv"
    return "ebirdRecord"


def open_source(path: Path, format_key: str | None = None, *,
                checklist_headers: dict[str, list[str]] | None = None) -> ImportSource:  # fmt: skip
    """The file's importer; a checklist download needs ``checklist_headers`` (the pack's
    ``ebird-checklist-headers.csv``, through ``header_names``)."""
    key = format_key or detect(path, checklist_headers)
    if key == "ebirdChecklist":
        if checklist_headers is None:
            raise MissingHeaderError("eBird checklist headers are needed for this file.")
        return EBirdChecklistFile(path, checklist_headers)
    return FORMATS[key](path)

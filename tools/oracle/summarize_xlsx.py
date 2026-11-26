"""Reduce spreadsheets to their content, to compare Scythebill's with Pipit's: each sheet's
name, every non-empty cell (value, bold, italic, number format), merged ranges and column
widths. Cells' fonts other than bold and italic, row heights and the file's own structure
(POI's or openpyxl's) are left out. Bold may be the cell's font or all of a rich text's runs.

    python -I tools/oracle/summarize_xlsx.py cases.jsonl dir > sheets.jsonl

writes, for each case, its row count and the SHA-256 of its canonical snapshot (``snapshot``).
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock


def _value(value: object) -> tuple[str, bool | None]:
    """The cell's text, and whether a rich text is bold throughout (None: not rich text)."""
    if isinstance(value, CellRichText):
        runs = [run for run in value if (run.text if isinstance(run, TextBlock) else run)]
        bold = bool(runs) and all(isinstance(run, TextBlock) and bool(run.font.b)
                                  for run in runs)  # fmt: skip
        return str(value), bold
    if isinstance(value, datetime):
        return f"date:{value.date().isoformat()}" if value.time() == datetime.min.time() \
            else f"datetime:{value.isoformat()}", None  # fmt: skip
    if isinstance(value, (int, float)):
        return f"number:{value!r}", None
    return str(value), None


def snapshot(data: bytes) -> dict[str, Any]:
    workbook = load_workbook(io.BytesIO(data), rich_text=True)
    sheets = []
    for sheet in workbook.worksheets:
        cells = []
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None or cell.value == "":
                    continue
                text, rich_bold = _value(cell.value)
                bold = bool(cell.font.b) or bool(rich_bold)
                number_format = cell.number_format if cell.number_format != "General" else ""
                cells.append([cell.coordinate, text, bold, bool(cell.font.i), number_format])
        widths = {
            letter: [round(dimension.width, 6), bool(dimension.bestFit)]
            for letter, dimension in sorted(sheet.column_dimensions.items())
            if dimension.customWidth
        }  # fmt: skip
        sheets.append({"title": sheet.title, "cells": cells,
                       "merged": sorted(str(r) for r in sheet.merged_cells.ranges),
                       "widths": widths})  # fmt: skip
    return {"sheets": sheets}


def summary(name: str, data: bytes) -> dict[str, Any]:
    content = snapshot(data)
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    rows = max((int("".join(c for c in cell[0] if c.isdigit()))
                for sheet in content["sheets"] for cell in sheet["cells"]), default=0)  # fmt: skip
    return {"name": name, "rows": rows, "sha256": hashlib.sha256(canonical).hexdigest()}


def main() -> None:
    cases = [json.loads(line) for line in Path(sys.argv[1]).read_text().split("\n") if line]
    directory = Path(sys.argv[2])
    for case in cases:
        data = (directory / f"{case['name']}.xlsx").read_bytes()
        print(json.dumps(summary(case["name"], data)))


if __name__ == "__main__":
    main()

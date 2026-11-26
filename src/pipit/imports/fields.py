"""Reading an imported file's rows and fields, as Scythebill's importers do.

Ported from Scythebill:
- ``model/.../io/CsvImportLines.java``: CSV without an escape character (only "" escapes a
  quote), a byte-order mark dropped, empty rows skipped, every field trimmed;
- ``ui/.../imports/LineExtractors.java``: whole, integer, float and true/false fields;
- ``ui/.../imports/PartialDateParsers.java``: Joda-Time patterns such as "yy-MM-dd" (two-digit
  years pivot on 2000; longer ones are years as written; Julian dates before 1582);
- ``model/.../io/TimeDisplay.fromExternalString``: "7:15", "07:15:30", "7:15 AM".
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import time
from pathlib import Path

from pipit.domain.partial_date import PartialDate
from pipit.domain.report import BREEDING_CODES
from pipit.domain.values import parse_float32
from pipit.imports.taxa import WHITESPACE, java_trim


class DateParseError(ValueError):
    """``DateParseException``: no pattern read a date."""


def read_rows(path: Path) -> list[list[str]]:
    """``CsvImportLines.fromFile(...).nextLine()`` until the end: every non-empty row, with
    fields trimmed. A .zip must hold exactly one .csv (as eBird's downloads do)."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".csv")]
            if not names:
                raise ValueError(".zip file does not contain any .csv files.")
            if len(names) > 1:
                raise ValueError(".zip file contains multiple .csv files.")
            data = archive.read(names[0])
    else:
        data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    rows: list[list[str]] = []
    for row in csv.reader(io.StringIO(text, newline=""), strict=False):
        if not any(row):
            continue
        if row[0] == '"':
            row[0] = ""
        if row[0].startswith("﻿"):
            row[0] = row[0][1:]
        rows.append([java_trim(field) for field in row])
    return rows


def string_at(row: list[str], index: int | None) -> str | None:
    """``stringFromIndex``: None past the end of the row."""
    if index is None or len(row) <= index:
        return None
    return java_trim(row[index])


_DIGITS = re.compile(r"^[^0-9]*(.*?)[^0-9]*$", re.DOTALL)


def int_at(row: list[str], index: int | None) -> int | None:
    """``intFromIndex``: anything around the digits dropped ("20+", "~50")."""
    text = string_at(row, index)
    if text is None:
        return None
    match = _DIGITS.match(text)
    entry = match.group(1) if match else ""
    if not entry or entry.lower() == "x":
        return None
    if not re.fullmatch(r"[+-]?[0-9]+", entry):
        return None
    value = int(entry)
    return value if -(2**31) <= value < 2**31 else None


def float_at(row: list[str], index: int | None) -> float | None:
    """``floatFromIndex``: only the digits and periods, as a float."""
    if index is None or len(row) <= index:
        return None
    entry = "".join(c for c in row[index] if "0" <= c <= "9" or c == ".")
    if not entry:
        return None
    return parse_float32(entry)


_TRUE = frozenset({"Y", "y", "T", "t", "TRUE", "True", "true", "1"})


def bool_at(row: list[str], index: int | None) -> bool:
    if index is None or len(row) <= index:
        return False
    return java_trim(row[index]) in _TRUE


# ------------------------------------------------------------------ dates


def _is_leap(year: int) -> bool:
    if year < 1583:  # GJChronology: Julian before the 1582 cutover
        return year % 4 == 0
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _valid_day(year: int, month: int, day: int) -> bool:
    if not 1 <= month <= 12:
        return False
    days = 29 if month == 2 and _is_leap(year) else _DAYS[month - 1]
    if not 1 <= day <= days:
        return False
    return not (year == 1582 and month == 10 and 5 <= day <= 14)


class JodaDateParser:
    """``PartialDateParsers.forPattern`` for numeric patterns of y, M and d separated by
    literals ("yy-MM-dd", "dd/MM/yyyy")."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self._tokens = re.findall(r"y+|M+|d+|[^yMd]+", pattern)

    def parse(self, text: str) -> PartialDate:
        position = 0
        year: int | None = None
        month: int | None = None
        day: int | None = None
        for token in self._tokens:
            letter = token[0]
            if letter not in "yMd":
                if not text.startswith(token, position):
                    raise DateParseError(f"{text!r} is malformed at {position}")
                position += len(token)
                continue
            if letter == "y":
                year, position = self._year(text, position, len(token))
            else:
                value, position = _digits(text, position, max(len(token), 2))
                if letter == "M":
                    month = value
                else:
                    day = value
        if position != len(text):
            raise DateParseError(f"{text!r} is malformed at {position}")
        check_year = 2000 if year is None else year
        if not _valid_day(check_year, month or 1, day or 1):
            raise DateParseError(f"{text!r} is not a valid date")
        return PartialDate.of(year, month, day)

    @staticmethod
    def _year(text: str, position: int, width: int) -> tuple[int, int]:
        if width != 2:
            value, end = _digits(text, position, 9, signed=True)
            return value, end
        # Two-digit years, read leniently: anything but exactly two digits is the year itself.
        start = position
        negative = False
        signed = False
        if position < len(text) and text[position] in "+-":
            signed = True
            negative = text[position] == "-"
            position += 1
        end = position
        while end < len(text) and "0" <= text[end] <= "9":
            end += 1
        if end == position:
            raise DateParseError(f"{text!r} is malformed at {start}")
        value = int(text[position:end])
        if signed or end - position != 2:
            return (-value if negative else value), end
        return (2000 + value if value < 50 else 1900 + value), end


def _digits(text: str, position: int, maximum: int, *, signed: bool = False) -> tuple[int, int]:
    start = position
    negative = False
    if signed and position < len(text) and text[position] in "+-":
        negative = text[position] == "-"
        position += 1
    end = position
    while end < len(text) and end - position < maximum and "0" <= text[end] <= "9":
        end += 1
    if end == position:
        raise DateParseError(f"{text!r} is malformed at {start}")
    value = int(text[position:end])
    return (-value if negative else value), end


def parse_first_match(parsers: list[JodaDateParser], text: str) -> PartialDate:
    """``PartialDateParserFieldMapper.parseFirstMatch``."""
    for parser in parsers:
        try:
            return parser.parse(text)
        except DateParseError:
            continue
    raise DateParseError(f"no date in {text!r}")


# ------------------------------------------------------------------ times

_TWELVE = re.compile(r"(\d+):(\d{2})(?::(\d{2}))? ?(AM|PM)")
_TWENTY_FOUR = re.compile(r"(\d+):(\d{2})(?::(\d{2}))?")


def parse_external_time(text: str) -> time:
    """``TimeDisplay.fromExternalString``; raises ValueError."""
    decimal = text.find(".")
    if decimal >= 0:
        text = text[:decimal]
    text = text.replace("\u202f", " ").replace("\u00a0", " ")
    twelve = text.endswith(("AM", "PM"))
    seconds = text.count(":") > 1
    match = (_TWELVE if twelve else _TWENTY_FOUR).fullmatch(text)
    if match is None or (match.group(3) is not None) != seconds:
        raise ValueError(f"not a time: {text!r}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if match.group(3) is not None and int(match.group(3)) > 59:
        raise ValueError(f"not a time: {text!r}")
    if minute > 59:
        raise ValueError(f"not a time: {text!r}")
    if twelve:
        if not 1 <= hour <= 12:
            raise ValueError(f"not a time: {text!r}")
        hour = hour % 12 + (12 if match.group(4) == "PM" else 0)
    elif hour > 23:
        raise ValueError(f"not a time: {text!r}")
    return time(hour, minute)


# ------------------------------------------------------------------ codes


def breeding_code(text: str | None) -> str | None:
    """``BreedingBirdCodeFieldMapper``: a code, or the first word if that is one."""
    if not text:
        return None
    if text in BREEDING_CODES and text:
        return text
    first_space = next((i for i, c in enumerate(text) if c in WHITESPACE), -1)
    if first_space > 0 and text[:first_space] in BREEDING_CODES:
        return text[:first_space]
    return None

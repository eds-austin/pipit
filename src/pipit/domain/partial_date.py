"""Dates with any fields missing ("2026", "2026-05", "M05-12").

Ported from Scythebill ``model/src/commonMain/kotlin/.../date/PartialDate.kt`` and
``PartialDateIO.kt``. Values are not range-checked, as in Scythebill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

_INT_MAX = 2**31 - 1
_YEAR_MONTH_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DIGITS = re.compile(r"[0-9]+")


class PartialField(IntEnum):
    YEAR = 0
    MONTH = 1
    DAY = 2
    HOUR = 3
    MINUTE = 4
    SECOND = 5


_ABBREVIATIONS = {
    "y": PartialField.YEAR,
    "M": PartialField.MONTH,
    "d": PartialField.DAY,
    "h": PartialField.HOUR,
    "m": PartialField.MINUTE,
    "s": PartialField.SECOND,
}
_FIELD_ABBREVIATIONS = {field: abbreviation for abbreviation, field in _ABBREVIATIONS.items()}


def _next_field(field: PartialField | None) -> PartialField | None:
    if field is None:
        return PartialField.YEAR
    return None if field is PartialField.SECOND else PartialField(field + 1)


@dataclass(frozen=True, slots=True)
class PartialDate:
    """Fields in order; each present at most once."""

    fields: tuple[tuple[PartialField, int], ...] = ()

    @staticmethod
    def of(
        year: int | None = None, month: int | None = None, day: int | None = None
    ) -> PartialDate:
        date = PartialDate()
        for field, value in ((PartialField.YEAR, year), (PartialField.MONTH, month),
                             (PartialField.DAY, day)):  # fmt: skip
            if value is not None:
                date = date.with_field(field, value)
        return date

    def get(self, field: PartialField) -> int | None:
        for present, value in self.fields:
            if present is field:
                return value
        return None

    @property
    def year(self) -> int | None:
        return self.get(PartialField.YEAR)

    @property
    def month(self) -> int | None:
        return self.get(PartialField.MONTH)

    @property
    def day(self) -> int | None:
        return self.get(PartialField.DAY)

    @property
    def is_full_date(self) -> bool:
        return [field for field, _ in self.fields] == [
            PartialField.YEAR, PartialField.MONTH, PartialField.DAY
        ]  # fmt: skip

    def with_field(self, field: PartialField, value: int) -> PartialDate:
        others = [(f, v) for f, v in self.fields if f is not field]
        return PartialDate(tuple(sorted([*others, (field, value)], key=lambda item: item[0])))

    def __str__(self) -> str:
        return format_partial_date(self)


def format_partial_date(date: PartialDate) -> str:
    """``PartialDateIO.toString``: zero-padded fields joined by "-", with a letter before
    any field that doesn't follow the previous one (so month-day is "M05-12")."""
    parts = []
    last: PartialField | None = None
    for field, value in date.fields:
        if value < 0:
            raise ValueError(f"negative {field.name.lower()} in {date}")
        prefix = "" if field is _next_field(last) else _FIELD_ABBREVIATIONS[field]
        parts.append(f"{prefix}{value:02d}")
        last = field
    return "-".join(parts)


def parse_partial_date(text: str) -> PartialDate:
    """``PartialDateIO.fromString``; raises ValueError on invalid text."""
    if _YEAR_MONTH_DAY.fullmatch(text):
        return PartialDate.of(int(text[0:4]), int(text[5:7]), int(text[8:]))
    date = PartialDate()
    last: PartialField | None = None
    current: PartialField | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if "0" <= character <= "9":
            if current is None:
                current = _next_field(last)
                if current is None:
                    raise ValueError(f"couldn't guess the type of a field in {text!r}")
            if date.get(current) is not None:
                raise ValueError(f"field repeated in {text!r}")
            separator = text.find("-", index)
            if separator < 0:
                separator = len(text)
            number = text[index:separator]
            if not _DIGITS.fullmatch(number) or int(number) > _INT_MAX:
                raise ValueError(f"couldn't parse a field in {text!r}")
            date = date.with_field(current, int(number))
            last = current
            current = None
            index = separator + 1
        else:
            if current is not None or character not in _ABBREVIATIONS:
                raise ValueError(f"invalid syntax in {text!r}")
            current = _ABBREVIATIONS[character]
            index += 1
            if index == len(text):
                raise ValueError(f"invalid syntax in {text!r}")
    return date


def parse_with_century_fix(text: str) -> PartialDate:
    """``dateFromStringWithCenturyFix``: two-digit years from old eBird imports become
    20xx (below 50) or 19xx."""
    date = parse_partial_date(text)
    year = date.year
    if year is not None and year < 100:
        date = date.with_field(PartialField.YEAR, year + (2000 if year < 50 else 1900))
    return date

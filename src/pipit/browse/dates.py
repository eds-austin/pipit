"""Partial dates for reading ("12 May 2026", "May 2026", "12 May"), and a sort key."""

from __future__ import annotations

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def display_date(year: int | None, month: int | None, day: int | None) -> str:
    parts = []
    if day is not None:
        parts.append(str(day))
    if month is not None:
        parts.append(_MONTHS[month - 1] if 1 <= month <= 12 else f"M{month:02d}")
    if year is not None:
        parts.append(str(year))
    return " ".join(parts) if parts else "No date"


def date_key(year: int | None, month: int | None, day: int | None) -> tuple[int, int, int]:
    """Sorts missing fields first, so "2026" comes before "May 2026"."""
    return (year or 0, month or 0, day or 0)

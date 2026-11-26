"""Guessing the form of dates in a file: Scythebill's ``LocalDateFormatterChooser``.

Dates are grouped by the separators they use ("/", "-", ",", spaces; most common group
first); each group's first date suggests patterns (a one-digit number is a month or day, more
than two digits a year, two digits a year, day or month by value, letters a month name), the
group's other dates rule out those that don't read them, and what's left is the pattern
whose month and day come in the locale's order (Scythebill's computer's; Pipit uses
month-before-day, as in the US, unless told otherwise).
"""

from __future__ import annotations

from collections.abc import Iterable

from pipit.imports.fields import DateParseError, JodaDateParser
from pipit.imports.taxa import WHITESPACE

_SEPARATORS = frozenset("/-,") | WHITESPACE


def _is_digit(character: str) -> bool:
    return "0" <= character <= "9"


def _formats(component: str) -> list[str]:
    if component and all(_is_digit(c) for c in component):
        if len(component) == 1:
            return ["M", "d"]
        if len(component) > 2:
            return ["yy"]
        value = int(component)
        if value > 31:
            return ["yy"]
        if value > 12:
            return ["yy", "d"]
        return ["yy", "M", "d"]
    return ["MMM"]


def hypotheses(date: str) -> list[str]:
    """``computeHypotheses``: patterns that might read ``date``."""
    found = [""]
    position = 0
    while True:
        if _is_digit(date[position]):
            stop = next((i for i in range(position, len(date)) if date[i] in _SEPARATORS), -1)
        else:
            stop = next((i for i in range(position, len(date))
                         if date[i] in _SEPARATORS or _is_digit(date[i])), -1)  # fmt: skip
        component = date[position:] if stop < 0 else date[position:stop]
        found = [hypothesis + possible for possible in _formats(component)
                 for hypothesis in found if possible not in hypothesis]  # fmt: skip
        if stop < 0:
            break
        after = next((i for i in range(stop, len(date)) if date[i] not in _SEPARATORS), -1)
        separator = date[stop:] if after < 0 else date[stop:after]
        found = [hypothesis + separator for hypothesis in found]
        if after < 0:
            break
        position = after
    return found


def _reads(pattern: str, date: str) -> bool:
    try:
        JodaDateParser(pattern).parse(date)
    except DateParseError:
        return False
    return True


def choose_formats(dates: Iterable[str], *, month_before_day: bool = True) -> list[str]:
    """``chooseFormatters``: a pattern for each group of dates, most common group first."""
    groups: dict[str, list[str]] = {}
    for date in dates:
        groups.setdefault("".join(c for c in date if c in _SEPARATORS), []).append(date)
    order = sorted(groups, key=lambda separators: (-len(groups[separators]),
                                                   len(separators), separators))  # fmt: skip
    chosen: list[str] = []
    for separators in order:
        group = groups[separators]
        candidates = hypotheses(group[0])
        if len(candidates) > 1:
            for date in group:
                reading = [pattern for pattern in candidates if _reads(pattern, date)]
                if len(reading) in (0, len(candidates)):
                    continue
                candidates = reading
                if len(candidates) == 1:
                    break
        if candidates:
            chosen.append(min(candidates, key=lambda found: _order_rank(found, month_before_day)))
    return chosen


def _order_rank(pattern: str, month_before_day: bool) -> int:
    month, day = pattern.find("M"), pattern.find("d")
    if month < 0 or day < 0:
        return 0
    return 0 if (month < day) == month_before_day else 1

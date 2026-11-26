"""A trip report's locations grouped into stops, each with a short name for the species list.

Ported from Scythebill's ``ui/.../io/TripStops.java``. Several locations make one stop when
they are parts of one place: locations inside a park (or an untyped place of the user's
own); eBird hotspots named "Place--Part"; eBird locations named for their coordinates,
"Place (21.9, 120.92)"; and runs of back-to-back visits on a day to places whose names
start with the same words ("Shimen Reservoir Dawangping Section", "Shimen Reservoir Xizhou
Park"). Anything else is a stop of its own.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pipit.output.names import PlaceNames
from pipit.query.model import QPlace

#: Names up to this long are short enough already.
SHORT_NAME_LENGTH = 25
#: Names that start with this many words in common may be one place.
MINIMUM_SHARED_WORDS = 2
# Java's \s is ASCII whitespace only.
_SPACE = "[ \\t\\n\\x0b\\f\\r]"
_TRAILING_COORDINATES = re.compile(
    rf"{_SPACE}*\({_SPACE}*-?\d+(\.\d+)?{_SPACE}*,{_SPACE}*-?\d+(\.\d+)?{_SPACE}*\){_SPACE}*$",
    re.ASCII,
)
_PARENTHETICAL = re.compile(rf"{_SPACE}*\([^)]*\)")
_WORD_SPLIT = re.compile(rf"{_SPACE}+")
PART_SEPARATOR = "--"
#: Guava's ``CharMatcher.whitespace()``.
GUAVA_WHITESPACE = frozenset(chr(code) for code in (
    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003,
    0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A, 0x2028, 0x2029, 0x202F, 0x205F,
    0x3000,
))  # fmt: skip
_SEPARATING_PUNCTUATION = frozenset("-\u2013\u2014,:;/") | GUAVA_WHITESPACE
JOINING_WORDS = frozenset({"the", "of", "at", "and", "&", "el", "la", "los", "las", "de", "del",
                           "y", "der", "die", "das", "am", "im", "an", "bei", "und"})  # fmt: skip
GENERIC_WORDS = JOINING_WORDS | frozenset({
    # English
    "national", "state", "county", "regional", "provincial", "park", "reserve", "preserve",
    "nature", "natural", "wildlife", "refuge", "sanctuary", "forest", "area", "conservation",
    "management", "recreation", "np", "nwr", "wma", "iba",
    # Spanish
    "parque", "nacional", "reserva", "bosque", "estatal", "área", "refugio",
    # German
    "naturschutzgebiet", "nationalpark",
})  # fmt: skip


def java_length(text: str) -> int:
    """``String.length``: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def java_trim(text: str) -> str:
    """``String.trim``: drops characters up to U+0020 at both ends."""
    start = 0
    end = len(text)
    while start < end and text[start] <= " ":
        start += 1
    while end > start and text[end - 1] <= " ":
        end -= 1
    return text[start:end]


def java_lower(text: str) -> str:
    """``toLowerCase(Locale.ROOT)``, close enough for place names (Python's ``lower`` also
    handles the rare special cases differently, such as a final sigma)."""
    return text.lower()


def _split_words(text: str) -> list[str]:
    """``String.split("\\s+")`` on trimmed text: no empty words at the end."""
    words = _WORD_SPLIT.split(text)
    while len(words) > 1 and words[-1] == "":
        words.pop()
    return words


@dataclass(frozen=True)
class Stop:
    """``key`` identifies it, ``name`` is how the itinerary shows it, ``short_name`` how the
    species list refers to it; ``shortened``: the short name says less than the name."""

    key: str
    name: str
    short_name: str
    shortened: bool


@dataclass(frozen=True)
class _Grouping:
    key: str
    name: str
    base_name: str
    part: str | None


def _location_key(location_id: str) -> str:
    return "location:" + location_id


class TripStops:
    def __init__(self, names: PlaceNames, location_ids_by_day: Sequence[Sequence[str]],
                 location_name: Callable[[str], str]) -> None:  # fmt: skip
        places = names.places
        grouping_by_id: dict[str, _Grouping] = {}
        ungrouped_name_by_id: dict[str, str] = {}
        for day in location_ids_by_day:
            for location_id in day:
                if location_id in grouping_by_id:
                    continue
                place = places.get(location_id)
                if place is None:
                    continue
                grouping = _group(place, names, location_name)
                grouping_by_id[location_id] = grouping
                if grouping.key == _location_key(location_id):
                    ungrouped_name_by_id[location_id] = grouping.base_name

        # Runs of visits on a day to places whose names start alike
        for day in location_ids_by_day:
            start = 0
            while start < len(day):
                end = start + 1
                shared: str | None = None
                while end < len(day):
                    run_name = _shared_name(day[start : end + 1], ungrouped_name_by_id)
                    if run_name is None:
                        break
                    shared = run_name
                    end += 1
                if shared is not None:
                    key = "name:" + java_lower(shared)
                    for location_id in day[start:end]:
                        name = ungrouped_name_by_id.pop(location_id, None)
                        if name is not None:
                            part = _trim_leading(name[len(shared) :])
                            grouping_by_id[location_id] = _Grouping(key, shared, shared,
                                                                    part or None)  # fmt: skip
                start = end

        name_by_key: dict[str, str] = {}
        base_name_by_key: dict[str, str] = {}
        part_by_id: dict[str, str] = {}
        for location_id, grouping in grouping_by_id.items():
            name_by_key.setdefault(grouping.key, grouping.name)
            base_name_by_key.setdefault(grouping.key, grouping.base_name)
            if grouping.part is not None:
                part_by_id[location_id] = grouping.part
        short_names = short_names_for(base_name_by_key)
        stop_by_key = {
            key: Stop(key, name, short_names[key], short_names[key] != base_name_by_key[key])
            for key, name in name_by_key.items()
        }
        self._stop_by_id = {location_id: stop_by_key[grouping.key]
                            for location_id, grouping in grouping_by_id.items()}  # fmt: skip
        self._part_by_id = part_by_id

    def __contains__(self, location_id: object) -> bool:
        return location_id in self._stop_by_id

    def stop(self, location_id: str) -> Stop:
        return self._stop_by_id[location_id]

    def part(self, location_id: str) -> str | None:
        """The part of its stop a location is, e.g. "Forest-Road 28.5K", if named."""
        return self._part_by_id.get(location_id)

    def size(self) -> int:
        return len({stop.key for stop in self._stop_by_id.values()})


def _trim_leading(text: str) -> str:
    start = 0
    while start < len(text) and text[start] in _SEPARATING_PUNCTUATION:
        start += 1
    return text[start:]


def _trim_trailing(text: str) -> str:
    end = len(text)
    while end > 0 and text[end - 1] in _SEPARATING_PUNCTUATION:
        end -= 1
    return text[:end]


def _is_place(place: QPlace) -> bool:
    """A place whose locations are its parts: a park, or an untyped place of the user's."""
    return place.type == "park" or (place.type is None and not place.built_in)


def _group(place: QPlace, names: PlaceNames,
           location_name: Callable[[str], str]) -> _Grouping:  # fmt: skip
    narrow_name = names.name(place)
    parent = names.places.get(place.parent) if place.parent else None
    if parent is not None and _is_place(parent):
        return _Grouping(_location_key(parent.xml_id), location_name(parent.xml_id),
                         names.name(parent), narrow_name)  # fmt: skip
    separator = narrow_name.find(PART_SEPARATOR)
    if separator > 0:
        name = java_trim(narrow_name[:separator])
        part = java_trim(narrow_name[separator + len(PART_SEPARATOR) :])
        return _Grouping("name:" + java_lower(name), name, name, part or None)
    coordinates = _TRAILING_COORDINATES.search(narrow_name)
    if coordinates is not None and coordinates.start() > 0:
        name = java_trim(narrow_name[: coordinates.start()])
        return _Grouping("name:" + java_lower(name), name, name, None)
    return _Grouping(_location_key(place.xml_id), location_name(place.xml_id), narrow_name,
                     None)  # fmt: skip


def _shared_name(location_ids: Sequence[str], ungrouped: dict[str, str]) -> str | None:
    words_of_names: list[list[str]] = []
    for location_id in location_ids:
        name = ungrouped.get(location_id)
        if name is None:
            return None
        words_of_names.append(_split_words(java_trim(name)))
    if len(set(location_ids)) < 2:
        return None
    first = words_of_names[0]
    shared_count = len(first)
    for words in words_of_names:
        i = 0
        while i < min(shared_count, len(words)) and words[i] == first[i]:
            i += 1
        shared_count = i
    while shared_count > 0 and java_lower(first[shared_count - 1]) in JOINING_WORDS:
        shared_count -= 1
    shared_words = first[:shared_count]
    all_generic = all(java_lower(word) in GENERIC_WORDS for word in shared_words)
    if shared_count < MINIMUM_SHARED_WORDS or all_generic:
        return None
    return _trim_trailing(" ".join(shared_words))


def short_names_for(names_by_key: dict[str, str]) -> dict[str, str]:
    """``shortNames``: no two alike, none just the start of another (ignoring case)."""
    candidates = {key: _candidates(name) for key, name in names_by_key.items()}
    index = dict.fromkeys(candidates, 0)

    def current(key: str) -> str:
        return candidates[key][index[key]]

    def ambiguous(key: str, candidate: str) -> bool:
        lower = java_lower(candidate)
        for other in candidates:
            if other != key:
                other_name = java_lower(current(other))
                if other_name == lower or other_name.startswith(lower + " "):
                    return True
        return False

    def prefix_of_another(key: str, candidate: str) -> bool:
        lower = java_lower(candidate)
        return any(lower.startswith(java_lower(current(other)) + " ")
                   for other in candidates if other != key)  # fmt: skip

    changed = True
    while changed:
        changed = False
        for key, possible in candidates.items():
            candidate = current(key)
            if index[key] < len(possible) - 1 and (
                ambiguous(key, candidate) or prefix_of_another(key, candidate)
            ):
                index[key] += 1
                changed = True
    changed = True
    while changed:
        changed = False
        for key in candidates:
            for i in range(index[key]):
                candidate = candidates[key][i]
                if not ambiguous(key, candidate) and not prefix_of_another(key, candidate):
                    index[key] = i
                    changed = True
                    break
    uses: dict[str, int] = {}
    result: dict[str, str] = {}
    for key in candidates:
        short = current(key)
        count = uses[java_lower(short)] = uses.get(java_lower(short), 0) + 1
        result[key] = short if count == 1 else f"{short} {count}"
    return result


def _candidates(name: str) -> list[str]:
    """A name's possible short names, shortest first, ending with the name itself."""
    if java_length(name) <= SHORT_NAME_LENGTH:
        return [name]
    words = _split_words(java_trim(_PARENTHETICAL.sub("", name)))
    distinctive = [word for word in words if java_lower(word) not in GENERIC_WORDS]
    if not distinctive:
        distinctive = words
    count = 1
    while (count < len(distinctive)
           and java_length(" ".join(distinctive[: count + 1])) <= SHORT_NAME_LENGTH):  # fmt: skip
        count += 1
    found = [" ".join(distinctive[:i]) for i in range(count, len(distinctive) + 1)]
    found.append(name)
    return found

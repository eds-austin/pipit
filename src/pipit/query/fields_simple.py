"""Stored-query fields that test one sighting at a time: ports of the headless ``Value``
classes of Scythebill's ``SightingStatusQueryField``, ``BooleanQueryField`` (heard only),
``PhotographedQueryField``, ``SexAgeQueryField``, ``BreedingBirdCodeQueryField``,
``DescriptionQueryField`` and ``VisitCommentsQueryField``. JSON is read exactly as Gson
reads it there.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipit.domain.partial_date import format_partial_date
from pipit.domain.values import format_time
from pipit.query.definition import Predicate, QueryContext, QueryDefinition, always
from pipit.query.model import QSighting

STATUS_IDS = frozenset({
    "none", "notAccepted", "bvd", "intro", "provisional", "notEstablished", "restrained",
    "domestic", "idUncertain", "unsatisfactoryViews", "notByMe", "dead", "signs",
})  # fmt: skip


class QueryJsonError(ValueError):
    """A stored query Scythebill itself would refuse (``JsonSyntaxException``)."""


@dataclass(frozen=True)
class FieldValue:
    type: str

    def definition(self, context: QueryContext) -> QueryDefinition:
        raise NotImplementedError

    @property
    def boolean_value(self) -> bool | None:
        """``getBooleanValue``: meaningful only for ALLOW_HEARD_ONLY."""
        return None

    @property
    def is_no_op(self) -> bool:
        return False


def _object(json: Any) -> dict[str, Any]:
    if not isinstance(json, dict):
        raise QueryJsonError(f"expected an object, got {json!r}")
    return json


# ------------------------------------------------------------------ sighting status


@dataclass(frozen=True)
class SightingStatusValue(FieldValue):
    query: str  # IS, IS_NOT, ANY
    status: str

    def definition(self, context: QueryContext) -> QueryDefinition:
        if self.query == "ANY":
            return QueryDefinition()
        status = self.status
        if self.query == "IS_NOT":
            return QueryDefinition(lambda s: s.status != status)
        return QueryDefinition(lambda s: s.status == status)

    @property
    def is_no_op(self) -> bool:
        return self.query == "ANY"


def parse_sighting_status(json: Any) -> SightingStatusValue:
    data = _object(json)
    status = data.get("statusId")
    if status not in STATUS_IDS:
        raise QueryJsonError(f"Invalid sighting status: {status}")
    return SightingStatusValue("SIGHTING_STATUS", data.get("type") or "IS", status)


# ------------------------------------------------------------------ heard only


@dataclass(frozen=True)
class HeardOnlyValue(FieldValue):
    value: bool | None

    def definition(self, context: QueryContext) -> QueryDefinition:
        if self.value is None:
            return QueryDefinition()
        wanted = self.value
        return QueryDefinition(lambda s: s.heard_only == wanted)

    @property
    def boolean_value(self) -> bool | None:
        return self.value

    @property
    def is_no_op(self) -> bool:
        return self.value is None


def parse_heard_only(json: Any) -> HeardOnlyValue:
    if json is None:
        return HeardOnlyValue("ALLOW_HEARD_ONLY", None)
    if not isinstance(json, bool):
        raise QueryJsonError(f"expected true, false or null, got {json!r}")
    return HeardOnlyValue("ALLOW_HEARD_ONLY", json)


# ------------------------------------------------------------------ photographed


@dataclass(frozen=True)
class PhotographedValue(FieldValue):
    query: str  # HAS_PHOTO, HAS_NO_PHOTO, HAS_FAVORITE, HAS_NO_FAVORITE

    def definition(self, context: QueryContext) -> QueryDefinition:
        if self.query in ("HAS_PHOTO", "HAS_NO_PHOTO"):
            wanted = self.query == "HAS_PHOTO"
            return QueryDefinition(lambda s: s.photographed == wanted)
        wanted = self.query == "HAS_FAVORITE"
        return QueryDefinition(lambda s: s.favorite_photo == wanted)


def parse_photographed(json: Any) -> PhotographedValue:
    if isinstance(json, bool):
        return PhotographedValue("PHOTOGRAPHED", "HAS_PHOTO" if json else "HAS_NO_PHOTO")
    if isinstance(json, int | float):
        return PhotographedValue("PHOTOGRAPHED", "HAS_NO_PHOTO" if int(json) == 1 else "HAS_PHOTO")
    if not isinstance(json, dict):
        return PhotographedValue("PHOTOGRAPHED", "HAS_PHOTO")
    return PhotographedValue("PHOTOGRAPHED", json.get("type") or "HAS_PHOTO")


# ------------------------------------------------------------------ sex and age


@dataclass(frozen=True)
class SexAgeValue(FieldValue):
    query: str  # IS_FEMALE, IS_MALE, IS_ADULT, IS_IMMATURE

    def definition(self, context: QueryContext) -> QueryDefinition:
        attribute = {"IS_FEMALE": "female", "IS_MALE": "male", "IS_ADULT": "adult",
                     "IS_IMMATURE": "immature"}[self.query]  # fmt: skip
        return QueryDefinition(lambda s: bool(getattr(s, attribute)))


def parse_sex_age(json: Any) -> SexAgeValue:
    query = _object(json).get("type")
    if query not in ("IS_FEMALE", "IS_MALE", "IS_ADULT", "IS_IMMATURE"):
        raise QueryJsonError(f"Unexpected type: {query}")
    return SexAgeValue("SEX_AGE", query)


# ------------------------------------------------------------------ breeding codes

_CODES = {
    "NEST_WITH_YOUNG": "NY", "NEST_WITH_EGGS": "NE", "CARRYING_FECAL_SAC": "CS",
    "FEEDING_YOUNG": "FY", "CARRYING_FOOD": "CF", "RECENTLY_FLEDGED": "FL", "OCCUPIED_NEST": "ON",
    "USED_NEST": "UN", "DISTRACTION_DISPLAY": "DD", "NEST_BUILDING": "NB",
    "CARRYING_NESTING_MATERIAL": "CN", "PHYSIOLOGICAL_EVIDENCE": "PE",
    "WOODPECKER_WREN_NEST_BUILDING": "B", "AGITATED_BEHAVIOR": "A",
    "VISITING_PROBABLE_NEST_SITE": "N", "COURTSHIP_DISPLAY_OR_COPULATION": "C",
    "TERRITORIAL_DEFENSE": "T", "PAIR_IN_SUITABLE_HABITAT": "P", "MULTIPLE_SINGING_BIRDS": "M",
    "SINGING_BIRD_7_DAYS": "S7", "SINGING_BIRD": "S", "IN_APPROPRIATE_HABITAT": "H",
    "FLYOVER": "F",
}  # fmt: skip
#: ``BreedingBirdLevel`` in enum order: each level's codes.
BREEDING_LEVELS: dict[str, tuple[str, ...]] = {
    "CONFIRMED": ("NY", "NE", "ON", "FL", "FY", "CS", "CF", "DD", "UN"),
    "CONFIRMED_PROBABLE": ("NB", "CN"),
    "PROBABLE": ("T", "C", "N", "A", "PE", "M", "S7", "B"),
    "POSSIBLE": ("P", "S", "H"),
    **{name: (code,) for name, code in _CODES.items()},
}
_ALL_CODES = frozenset({"", *_CODES.values()})


@dataclass(frozen=True)
class BreedingValue(FieldValue):
    query: str  # IS, IS_AT_LEAST, IS_NOT, ANY
    level: str

    def definition(self, context: QueryContext) -> QueryDefinition:
        if self.query == "ANY":
            return QueryDefinition()
        if self.query in ("IS", "IS_NOT"):
            allowed = set(BREEDING_LEVELS[self.level])
            if self.query == "IS_NOT":
                allowed = set(_ALL_CODES) - allowed
        else:  # IS_AT_LEAST: every level up to this one, in enum order
            allowed = set()
            for name, codes in BREEDING_LEVELS.items():
                allowed.update(codes)
                if name == self.level:
                    break
        frozen = frozenset(allowed)
        return QueryDefinition(lambda s: s.breeding in frozen)

    @property
    def is_no_op(self) -> bool:
        return self.query == "ANY"


def parse_breeding(json: Any) -> BreedingValue:
    data = _object(json)
    level = data.get("level")
    if level not in BREEDING_LEVELS:
        raise QueryJsonError(f"Unexpected breeding level: {level}")
    return BreedingValue("BREEDING_CODE", data.get("type") or "IS", level)


# ------------------------------------------------------------------ text: notes and comments

_CASE_SENSITIVE = {"CONTAINS_CASE_SENSITIVE", "DOES_NOT_CONTAIN_CASE_SENSITIVE",
                   "IS_EXACTLY_CASE_SENSITIVE", "STARTS_WTIH_WORD_CASE_SENSITIVE"}  # fmt: skip


def _text_predicate(query: str, text: str, extract: Callable[[QSighting], str | None]) -> Predicate:
    """The shared logic of the description and visit-comments fields; ``extract`` returns
    the text or None (no notes: never matches, except DOES_NOT_CONTAIN)."""
    sensitive = query in _CASE_SENSITIVE
    wanted = text if sensitive else text.lower()

    def get(sighting: QSighting) -> str | None:
        found = extract(sighting)
        if found is None:
            return None
        return found if sensitive else found.lower()

    if query in ("IS_EXACTLY", "IS_EXACTLY_CASE_SENSITIVE"):
        return lambda s: get(s) == wanted

    if query in ("STARTS_WITH_WORD", "STARTS_WTIH_WORD_CASE_SENSITIVE"):

        def starts(sighting: QSighting) -> bool:
            found = get(sighting)
            if found is None or not found.startswith(wanted):
                return False
            return len(found) == len(wanted) or not found[len(wanted)].isalpha()

        return starts

    def contains(sighting: QSighting) -> bool:
        found = get(sighting)
        return found is not None and wanted in found

    if query in ("DOES_NOT_CONTAIN", "DOES_NOT_CONTAIN_CASE_SENSITIVE"):
        return lambda s: not contains(s)
    return contains


@dataclass(frozen=True)
class DescriptionValue(FieldValue):
    query: str
    text: str

    def definition(self, context: QueryContext) -> QueryDefinition:
        return QueryDefinition(
            _text_predicate(self.query, self.text, lambda s: s.description or None)
        )


@dataclass(frozen=True)
class VisitCommentsValue(FieldValue):
    query: str
    text: str

    def definition(self, context: QueryContext) -> QueryDefinition:
        comments = context.query_list.visit_comments

        def extract(sighting: QSighting) -> str | None:
            key = visit_key(sighting)
            if key is None:
                return None
            return comments.get(key) or None

        return QueryDefinition(_text_predicate(self.query, self.text, extract))


def visit_key(sighting: QSighting) -> tuple[str, str, str] | None:
    """``VisitInfoKey.forSighting``: a dated sighting at a place, by its time."""
    if sighting.location_xml_id is None or sighting.date is None:
        return None
    start = format_time(sighting.time) if sighting.time else ""
    return (sighting.location_xml_id, format_partial_date(sighting.date), start)


def parse_text(field_type: str, json: Any) -> DescriptionValue | VisitCommentsValue:
    data = _object(json)
    text = data.get("text") or ""
    query = data.get("type") or "CONTAINS"
    if field_type == "SIGHTING_NOTES":
        return DescriptionValue(field_type, query, text)
    return VisitCommentsValue(field_type, query, text)


__all__ = ["always"]

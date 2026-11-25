"""Stored-query fields for where and when: ports of the headless ``Value`` classes of
Scythebill's ``LocationQueryField`` and ``DateQueryField`` (with ``SightingPredicates``'
date predicates: from-dates use a sighting's start date, to-dates its end date, and a date
missing a field the bound has never matches).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as calendar_date
from typing import Any

from pipit.domain.partial_date import (
    PartialDate,
    after,
    after_or_equals,
    before,
    before_or_equals,
    compare_partial_dates,
    parse_partial_date,
)
from pipit.domain.values import float32
from pipit.query.definition import Predicate, QueryContext, QueryDefinition
from pipit.query.fields_simple import FieldValue, QueryJsonError
from pipit.query.model import QSighting
from pipit.query.synthetic import regions_for

_RADIUS_KM = 6371.0
_KILOMETERS_IN_A_MILE = float32(1.60934)


class UnsupportedQueryError(ValueError):
    """A stored query Pipit can't evaluate yet (so it is never miscounted)."""


# ------------------------------------------------------------------ location


@dataclass(frozen=True)
class LocationValue(FieldValue):
    query: str  # IN, NOT_IN, IS, IS_NOT, IS_NEARER_THAN, IS_NOT_SET
    location_id: str | None
    miles: bool = False
    distance: float | None = None

    @property
    def is_no_op(self) -> bool:
        return self.location_id is None

    def definition(self, context: QueryContext) -> QueryDefinition:
        if self.query == "IS_NOT_SET":
            return QueryDefinition(lambda s: s.location_xml_id is None)
        if self.location_id is None:
            return QueryDefinition()
        place = self.location_id
        query_list = context.query_list
        if place not in query_list.parent:
            regions = regions_for(query_list)
            if place in regions:
                return QueryDefinition(self._synthetic(regions[place]))
            raise UnsupportedQueryError(f"Unknown ID: {place}")
        if self.query in ("IN", "NOT_IN"):
            within = query_list.places_within(place)
            if self.query == "IN":
                return QueryDefinition(lambda s: s.location_xml_id in within)
            return QueryDefinition(lambda s: s.location_xml_id not in within)
        if self.query == "IS":
            return QueryDefinition(lambda s: s.location_xml_id == place)
        if self.query == "IS_NOT":
            return QueryDefinition(lambda s: s.location_xml_id != place)
        if self.query == "IS_NEARER_THAN":
            nearby = self._nearby(context, place)
            if nearby is None:
                return QueryDefinition(lambda _s: False)
            return QueryDefinition(lambda s: s.location_xml_id in nearby)
        raise QueryJsonError(f"Unknown location option: {self.query}")

    def _synthetic(self, places: frozenset[str]) -> Predicate:
        if self.query == "IN":
            return lambda s: s.location_xml_id in places
        if self.query == "NOT_IN":
            return lambda s: s.location_xml_id not in places
        if self.query == "IS_NEARER_THAN":
            return lambda _s: False
        return lambda _s: False  # IS / IS_NOT a synthetic region: never (as Scythebill)

    def _nearby(self, context: QueryContext, place: str) -> frozenset[str] | None:
        """``getLocationSetWithin``: places with coordinates within the distance."""
        coordinates = context.query_list.coordinates
        center = coordinates.get(place)
        if center is None or self.distance is None:
            return None
        distance = float32(self.distance)
        if self.miles:
            distance = float32(distance * _KILOMETERS_IN_A_MILE)
        if distance <= 0.0:
            return frozenset({place})
        return frozenset(
            other for other, point in coordinates.items()
            if km_distance(center, point) <= distance
        )  # fmt: skip


def km_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """``LatLongCoordinates.kmDistance`` (haversine, radius 6371 km)."""
    lat_a, lat_b = math.radians(a[0]), math.radians(b[0])
    lat_delta = lat_a - lat_b
    long_delta = math.radians(a[1] - b[1])
    half = math.sin(lat_delta / 2) ** 2 + (
        math.cos(lat_a) * math.cos(lat_b) * math.sin(long_delta / 2) ** 2
    )
    return 2 * math.atan2(math.sqrt(half), math.sqrt(1 - half)) * _RADIUS_KM


def parse_location(json: Any, known: Callable[[str], bool]) -> LocationValue:
    if not isinstance(json, dict):
        raise QueryJsonError(f"expected an object, got {json!r}")
    place = json.get("id")
    if place is not None and not known(place):
        raise QueryJsonError(f"Unknown ID: {place}")
    distance = json.get("distance")
    return LocationValue(
        "LOCATION", json.get("type") or "IN", place,
        json.get("milesOrKilometers") == "MILES",
        None if distance is None else float(distance),
    )  # fmt: skip


# ------------------------------------------------------------------ date


@dataclass(frozen=True)
class DateValue(FieldValue):
    query: str  # DURING, BETWEEN, AFTER, BEFORE, THIS_YEAR, TODAY, NOT_DURING, NOT_SET
    start: PartialDate | None
    end: PartialDate | None
    today: calendar_date | None = None  # for tests; else the computer's date

    def _from(self) -> Predicate | None:
        if self.query not in ("BETWEEN", "AFTER", "DURING", "NOT_DURING") or self.start is None:
            return None
        bound = self.start
        test = after if self.query == "AFTER" else after_or_equals

        def predicate(sighting: QSighting) -> bool:
            date = sighting.start_date
            return date is not None and test(bound, date)

        return predicate

    def _to(self) -> Predicate | None:
        if self.query not in ("BETWEEN", "BEFORE", "DURING", "NOT_DURING"):
            return None
        bound = self.start if self.query in ("DURING", "NOT_DURING") else self.end
        if bound is None:
            return None
        test = before if self.query == "BEFORE" else before_or_equals

        def predicate(sighting: QSighting) -> bool:
            date = sighting.end_date
            return date is not None and test(bound, date)

        return predicate

    @property
    def is_no_op(self) -> bool:
        return self._from() is None and self._to() is None

    def definition(self, context: QueryContext) -> QueryDefinition:
        now = self.today or calendar_date.today()
        if self.query == "TODAY":

            def today(sighting: QSighting) -> bool:
                date = sighting.single_date
                return date is not None and (date.year, date.month, date.day) == (
                    now.year, now.month, now.day
                )  # fmt: skip

            return QueryDefinition(today)
        if self.query == "THIS_YEAR":

            def this_year(sighting: QSighting) -> bool:
                start = sighting.start_date
                if start is None or start.year != now.year:
                    return False
                if sighting.date is not None:  # start and end are the same date
                    return True
                end = sighting.end_date
                return end is not None and end.year == now.year

            return QueryDefinition(this_year)
        if self.query == "NOT_SET":
            return QueryDefinition(lambda s: s.date is None)
        if (self.query == "BETWEEN" and self.start is not None and self.end is not None
                and self.start.year is None and self.end.year is None
                and compare_partial_dates(self.end, self.start) < 0):  # fmt: skip
            # "Between December and March": either side of the year's turn.
            start, end = self.start, self.end
            return QueryDefinition(
                lambda s: (
                    (s.start_date is not None and after_or_equals(start, s.start_date))
                    or (s.end_date is not None and before_or_equals(end, s.end_date))
                )
            )
        from_predicate, to_predicate = self._from(), self._to()
        if from_predicate is None:
            return QueryDefinition() if to_predicate is None else QueryDefinition(to_predicate)
        if to_predicate is None:
            return QueryDefinition(from_predicate)
        if self.query == "NOT_DURING":
            return QueryDefinition(lambda s: not (from_predicate(s) and to_predicate(s)))
        return QueryDefinition(lambda s: from_predicate(s) and to_predicate(s))


def parse_date(json: Any) -> DateValue:
    if not isinstance(json, dict):
        raise QueryJsonError(f"expected an object, got {json!r}")

    def date(text: str | None) -> PartialDate | None:
        if text is None:
            return None
        try:
            return parse_partial_date(text)
        except ValueError as error:
            raise QueryJsonError(str(error)) from error

    return DateValue("DATE", json.get("type") or "DURING", date(json.get("from")),
                     date(json.get("to")))  # fmt: skip

"""The list as the query engine sees it: every sighting loaded once into a light record,
with what Scythebill's predicates read (``Sighting`` and ``SightingInfo``), plus places and
trips. Built from the open list's database; rebuilt after any change.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import time
from typing import Any

from pipit.domain.partial_date import PartialDate, parse_partial_date
from pipit.domain.values import parse_time
from pipit.taxa.sighting_taxon import SightingTaxon

#: ``SightingInfo.SightingStatus`` IDs that are never countable (``CountabilityRules``).
NEVER_COUNTABLE = frozenset(
    {"notEstablished", "idUncertain", "unsatisfactoryViews", "dead", "notByMe", "signs",
     "domestic"}
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class QPlace:
    xml_id: str
    name: str
    type: str | None
    code: str | None  # Locations.getLocationCode ("US-" before bare US state codes)
    parent: str | None
    built_in: bool
    latitude: float | None
    longitude: float | None
    ebird_code: str | None = None  # as stored


@dataclass(frozen=True, slots=True)
class QTrip:
    xml_id: str
    start: PartialDate
    end: PartialDate
    location_xml_id: str | None
    name: str | None = None


@dataclass(slots=True)
class QSighting:
    row: int
    order: int
    taxonomy_id: str | None  # None: the base taxonomy
    taxon: SightingTaxon
    location_xml_id: str | None
    date: PartialDate | None  # as stored
    time: time | None
    trip: QTrip | None
    count: str | None
    heard_only: bool
    photographed: bool
    male: bool
    female: bool
    adult: bool
    immature: bool
    status: str  # "none" when not set
    breeding: str
    description: str
    users: frozenset[str] = frozenset()
    photos: int = 0
    favorite_photo: bool = False
    #: Sorts exactly as Scythebill's MoreRecentComparator (set by ``load_query_list``).
    recency: tuple[Any, ...] = ()

    # ------------------------------------------------------------ Scythebill's dates

    @property
    def start_date(self) -> PartialDate | None:
        """``getStartDateAsPartial``: its date, else its trip's start."""
        if self.date is not None:
            return self.date
        return None if self.trip is None else self.trip.start

    @property
    def end_date(self) -> PartialDate | None:
        """``getEndDateAsPartial``: its date, else its trip's end."""
        if self.date is not None:
            return self.date
        return None if self.trip is None else self.trip.end

    @property
    def single_date(self) -> PartialDate | None:
        """``getSingleDateAsPartial``: its date, else its trip's when the trip is one date."""
        if self.date is not None:
            return self.date
        if self.trip is not None and self.trip.start == self.trip.end:
            return self.trip.start
        return None


@dataclass
class QueryList:
    sightings: list[QSighting]
    trips: dict[str, QTrip]
    #: place -> every place inside it, itself included (its subtree)
    subtree: dict[str, frozenset[str]] = field(default_factory=dict)
    #: place -> its parent
    parent: dict[str, str | None] = field(default_factory=dict)
    #: (place, date, start time or "") -> visit comments; the visits with records
    visit_comments: dict[tuple[str, str, str], str] = field(default_factory=dict)
    #: place -> (latitude, longitude), for those with coordinates
    coordinates: dict[str, tuple[float, float]] = field(default_factory=dict)
    #: every place, in list order (for synthetic regions)
    places: dict[str, QPlace] = field(default_factory=dict)
    #: synthetic regions by ID, filled once by pipit.query.synthetic.regions_for
    regions: dict[str, frozenset[str]] | None = None

    def places_within(self, xml_id: str) -> frozenset[str]:
        return self.subtree.get(xml_id, frozenset())


def recency_key(sighting: QSighting) -> tuple[Any, ...]:
    """A sort key ordering sightings exactly as Scythebill's ``MoreRecentComparator``:
    undated first (time then ignored); then by start date as ``comparePartialDates``
    (field by field, a larger field such as a year after a smaller one, fewer fields
    first); then untimed first, then by time."""
    date = sighting.start_date
    if date is None:
        return (0,)
    date_key = tuple((-int(field), number) for field, number in date.fields)
    time_value = sighting.time
    return (1, date_key, (0,) if time_value is None else (1, time_value.hour, time_value.minute))


def _taxon(kind: str, ids: tuple[str, ...], subspecies: str | None) -> SightingTaxon:
    if kind == "ssp":
        return SightingTaxon.with_secondary_subspecies(ids[0], subspecies or "")
    if kind == "sp":
        return SightingTaxon.sp(ids)
    if kind == "hybrid":
        return SightingTaxon.hybrid(ids)
    return SightingTaxon.single(ids[0])


def load_query_list(connection: sqlite3.Connection) -> QueryList:
    trips = {
        xml_id: QTrip(xml_id, parse_partial_date(start), parse_partial_date(end), location, name)
        for xml_id, start, end, location, name in connection.execute(
            "SELECT xml_id, start_date, end_date, location_xml_id, name FROM trips"
        )
    }
    parts: dict[int, list[str]] = defaultdict(list)
    for sighting, taxon_id in connection.execute(
        "SELECT sighting_id, taxon_id FROM sighting_taxa ORDER BY sighting_id, ord"
    ):
        parts[sighting].append(taxon_id)
    users: dict[int, set[str]] = defaultdict(set)
    for sighting, user in connection.execute("SELECT sighting_id, user_xml_id FROM sighting_users"):
        users[sighting].add(user)
    photos: dict[int, tuple[int, int]] = {
        sighting: (count, favorites)
        for sighting, count, favorites in connection.execute(
            "SELECT sighting_id, count(*), sum(favorite) FROM photos "
            "WHERE sighting_id IS NOT NULL GROUP BY sighting_id"
        )
    }
    dates: dict[str, PartialDate] = {}
    sightings = []
    for (row, order, taxonomy_id, kind, taxon_id, subspecies, location, date, time_text, trip,
         count, male, female, immature, adult, heard_only, photographed, status, breeding,
         description) in connection.execute(
        "SELECT id, ord, taxonomy_id, kind, taxon_id, subspecies, location_xml_id, date, time, "
        "trip_xml_id, count, male, female, immature, adult, heard_only, photographed, status, "
        "breeding, description FROM sightings ORDER BY ord"
    ):  # fmt: skip
        ids = (taxon_id,) if taxon_id is not None else tuple(parts[row])
        parsed = None
        if date is not None:
            parsed = dates.get(date)
            if parsed is None:
                parsed = dates[date] = parse_partial_date(date)
        sightings.append(
            QSighting(
                row, order, taxonomy_id, _taxon(kind, ids, subspecies), location, parsed,
                parse_time(time_text) if time_text else None, trips.get(trip) if trip else None,
                count, bool(heard_only), bool(photographed), bool(male), bool(female),
                bool(adult), bool(immature), status, breeding, description or "",
                frozenset(users.get(row, ())), photos.get(row, (0, 0))[0],
                photos.get(row, (0, 0))[1] > 0,
            )
        )  # fmt: skip
    subtree: dict[str, set[str]] = defaultdict(set)
    for ancestor, descendant in connection.execute(
        "SELECT a.xml_id, d.xml_id FROM location_closure c "
        "JOIN locations a ON a.id = c.ancestor JOIN locations d ON d.id = c.descendant"
    ):
        subtree[ancestor].add(descendant)
    parent = dict(
        connection.execute(
            "SELECT l.xml_id, p.xml_id FROM locations l LEFT JOIN locations p ON p.id = l.parent_id"
        ).fetchall()
    )
    comments = {
        (location, date, start): text or ""
        for location, date, start, text in connection.execute(
            "SELECT location_xml_id, date, start_time, comments FROM visits"
        )
    }
    for sighting in sightings:
        sighting.recency = recency_key(sighting)
    coordinates = {
        xml_id: (float(latitude), float(longitude))
        for xml_id, latitude, longitude in connection.execute(
            "SELECT xml_id, latitude, longitude FROM locations WHERE latitude IS NOT NULL"
        )
    }
    rows = connection.execute(
        "SELECT l.xml_id, l.name, l.type, l.ebird_code, p.xml_id, l.latitude, l.longitude "
        "FROM locations l LEFT JOIN locations p ON p.id = l.parent_id ORDER BY l.id"
    ).fetchall()
    codes = {xml_id: code for xml_id, _n, _t, code, _p, _la, _lo in rows}
    places = {}
    for xml_id, name, kind, code, parent_id, latitude, longitude in rows:
        location_code = code
        if kind == "state" and code and "-" not in code and _under_us(parent_id, parent, codes):
            location_code = f"US-{code}"
        places[xml_id] = QPlace(
            xml_id, name, kind, location_code, parent_id, xml_id.startswith("_"),
            None if latitude is None else float(latitude),
            None if longitude is None else float(longitude), code,
        )  # fmt: skip
    return QueryList(
        sightings, trips, {key: frozenset(value) for key, value in subtree.items()}, parent,
        comments, coordinates, places,
    )  # fmt: skip


def _under_us(xml_id: str | None, parent: dict[str, str | None],
              codes: dict[str, str | None]) -> bool:  # fmt: skip
    """``Locations.isUsChild``: the place or one above it has the code "US"."""
    current = xml_id
    while current is not None:
        if codes.get(current) == "US":
            return True
        current = parent.get(current)
    return False

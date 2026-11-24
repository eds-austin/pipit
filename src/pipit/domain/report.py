"""A bird list in memory: what a ``.bsxm`` file holds, after Scythebill's parse-time
normalizations. The list database stores exactly this, so a list exports back to the
same ``.bsxm``.

Mirrors Scythebill ``ReportSet``, ``Sighting``/``SightingInfo``, ``Location``, ``Trip``,
``VisitInfo``/``VisitInfoKey``, ``User`` and ``Photo``/``Link``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum

from pipit.domain.partial_date import PartialDate
from pipit.domain.values import ApproximateNumber, LatLong
from pipit.taxa.model import Taxonomy
from pipit.taxa.sighting_taxon import SightingTaxon

#: ``SightingInfo.SightingStatus`` IDs in order ("none" is never written).
SIGHTING_STATUSES = (
    "none", "notAccepted", "bvd", "intro", "provisional", "notEstablished", "restrained",
    "domestic", "idUncertain", "unsatisfactoryViews", "notByMe", "dead", "signs",
)  # fmt: skip
#: ``SightingInfo.BreedingBirdCode`` IDs ("" is none, never written).
BREEDING_CODES = (
    "", "NY", "NE", "CS", "FY", "CF", "FL", "ON", "UN", "DD", "NB", "CN", "PE", "B", "A", "N",
    "C", "T", "P", "M", "S7", "S", "H", "F",
)  # fmt: skip
#: ``Checklist.Status`` texts for custom checklists (native has none).
CHECKLIST_STATUS_TEXTS = (
    "endemic", "extinct", "introduced", "provisional", "rarity", "rarity-from-introduced",
    "escaped",
)  # fmt: skip
#: Location element names; None (``<location>``) is an untyped location.
LOCATION_TYPES = ("region", "country", "state", "county", "city", "town", "park")


class VisitField(Enum):
    START_TIME = "start-time"
    DURATION = "duration"
    DISTANCE = "distance"
    AREA = "area"
    PARTY_SIZE = "party-size"
    COMPLETE_CHECKLIST = "complete"


_S = VisitField


class ObservationType(Enum):
    """eBird protocols, with the fields each requires and hides (``VisitInfo.kt``)."""

    INCIDENTAL = (
        "incidental",
        "Incidental",
        frozenset[VisitField](),
        frozenset({_S.DISTANCE, _S.DURATION, _S.AREA, _S.COMPLETE_CHECKLIST}),
    )
    TRAVELING = (
        "traveling",
        "Traveling",
        frozenset({_S.START_TIME, _S.DURATION, _S.DISTANCE, _S.PARTY_SIZE}),
        frozenset({_S.AREA}),
    )
    STATIONARY = (
        "stationary",
        "Stationary",
        frozenset({_S.START_TIME, _S.DURATION, _S.PARTY_SIZE}),
        frozenset({_S.DISTANCE, _S.AREA}),
    )
    HISTORICAL = ("historical", "Historical", frozenset[VisitField](), frozenset[VisitField]())
    AREA = (
        "area",
        "Area",
        frozenset({_S.START_TIME, _S.DURATION, _S.AREA, _S.PARTY_SIZE}),
        frozenset({_S.DISTANCE}),
    )
    BANDING = (
        "banding",
        "Banding",
        frozenset({_S.START_TIME, _S.DURATION, _S.PARTY_SIZE}),
        frozenset({_S.DISTANCE}),
    )
    PELAGIC = (
        "pelagic",
        "eBird Pelagic Protocol",
        frozenset({_S.START_TIME, _S.DURATION, _S.DISTANCE, _S.PARTY_SIZE}),
        frozenset({_S.AREA}),
    )
    NOCTURNAL = (
        "nocturnal",
        "Nocturnal Birding",
        frozenset({_S.START_TIME, _S.DURATION, _S.DISTANCE}),
        frozenset({_S.AREA}),
    )
    FLIGHT_CALL = (
        "flight_call",
        "Nocturnal Flight Call Count",
        frozenset({_S.START_TIME, _S.DURATION, _S.PARTY_SIZE}),
        frozenset({_S.AREA, _S.DISTANCE}),
    )
    RANDOM = ("random", "Random",
              frozenset({_S.START_TIME, _S.DURATION, _S.DISTANCE, _S.PARTY_SIZE}),
              frozenset({_S.AREA}))  # fmt: skip

    def __init__(
        self,
        type_id: str,
        label: str,
        required: frozenset[VisitField],
        hidden: frozenset[VisitField],
    ) -> None:
        self.type_id = type_id
        self.label = label
        self.required = required
        self.hidden = hidden

    @classmethod
    def from_id(cls, type_id: str) -> ObservationType | None:
        return next((member for member in cls if member.type_id == type_id), None)


@dataclass(slots=True)
class Link:
    uri: str
    name: str | None = None


@dataclass(slots=True)
class Photo:
    uri: str
    name: str | None = None
    favorite: bool = False


@dataclass(slots=True, eq=False)
class Location:
    """A node of the location tree. ``id`` is the file ID ("loc12", "_ct_US")."""

    id: str
    name: str
    type: str | None  # one of LOCATION_TYPES, or None for <location>
    parent: Location | None = None
    children: list[Location] = field(default_factory=list)
    ebird_code: str | None = None
    ebird_hotspot_id: str | None = None
    lat_long: LatLong | None = None
    private: bool = False
    description: str | None = None
    restored: bool = False  # created for a missing ID ("RESTORED LOCATION")

    def child_named(self, name: str) -> Location | None:
        return next((child for child in self.children if child.name == name), None)

    def __repr__(self) -> str:
        return f"Location({self.id!r}, {self.name!r})"


@dataclass(slots=True)
class User:
    id: str
    name: str | None = None
    abbreviation: str | None = None


@dataclass(slots=True)
class Trip:
    id: str
    start_date: PartialDate
    end_date: PartialDate
    location_id: str | None = None
    start_time: time | None = None
    name: str | None = None
    notes: str | None = None
    links: list[Link] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)


@dataclass(slots=True)
class Sighting:
    taxon: SightingTaxon
    taxonomy_id: str | None = None  # None: the base taxonomy; else an extended taxonomy
    location_id: str | None = None
    date: PartialDate | None = None
    time: time | None = None
    trip_id: str | None = None
    count: ApproximateNumber | None = None
    male: bool = False
    female: bool = False
    immature: bool = False
    adult: bool = False
    heard_only: bool = False
    photographed: bool = False
    status: str = "none"
    breeding: str = ""
    users: list[str] = field(default_factory=list)
    description: str | None = None
    photos: list[Photo] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VisitKey:
    location_id: str
    date: PartialDate
    start_time: time | None


@dataclass(slots=True)
class Visit:
    key: VisitKey
    observation_type: ObservationType
    area_hectares: float | None = None  # float32
    distance_km: float | None = None  # float32
    duration_minutes: int | None = None
    party_size: int | None = None
    comments: str | None = None
    complete: bool = False
    photos: list[Photo] = field(default_factory=list)


@dataclass(slots=True)
class ChecklistEntry:
    taxon: SightingTaxon
    status: str | None  # None = native


@dataclass(slots=True)
class CustomChecklist:
    location_id: str
    entries: list[ChecklistEntry] = field(default_factory=list)


@dataclass(slots=True)
class ReportSet:
    """A whole list. Orders matter: they are the file order Scythebill writes."""

    taxonomy_id: str
    loaded_version: str | None = None
    extended_taxonomies: list[Taxonomy] = field(default_factory=list)
    roots: list[Location] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    trips: list[Trip] = field(default_factory=list)
    sightings: list[Sighting] = field(default_factory=list)
    checklists: list[CustomChecklist] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)
    preferences_json: str | None = None
    one_time_upgrades: list[str] = field(default_factory=list)

    def iter_locations(self) -> list[Location]:
        """Every location, pre-order, roots in order."""
        found: list[Location] = []
        stack = list(reversed(self.roots))
        while stack:
            location = stack.pop()
            found.append(location)
            stack.extend(reversed(location.children))
        return found

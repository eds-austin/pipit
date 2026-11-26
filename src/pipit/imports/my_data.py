"""eBird's "My Data" download (MyEBirdData.csv): every checklist of an eBird account.

Ported from Scythebill ``ui/.../imports/EBirdMyDataImporter.java`` and the field mappers it
uses (``CountFieldMapper``, ``DescriptionFieldMapper``, ``TimeMapper``,
``BreedingBirdCodeFieldMapper``, ``MLCatalogNumbersFieldMapper``) and ``EBird.observationType``.

Scythebill quirks kept, so imports match it:
- the count is always read from the fifth column (where eBird puts it);
- the number of observers is read from the second reading of the columns on (a typo skips it
  the first time); Scythebill fails on a file without that column, which Pipit imports without
  party sizes;
- places are made for every row, even rows on dates left out; the import removes the new ones
  nothing uses, but built-in places stay marked as used.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from pipit.domain.partial_date import PartialDate
from pipit.domain.report import ObservationType, Photo, Sighting
from pipit.domain.values import ApproximateNumber
from pipit.imports.fields import (
    JodaDateParser,
    bool_at,
    breeding_code,
    float_at,
    int_at,
    parse_external_time,
    parse_first_match,
    read_rows,
    string_at,
)
from pipit.imports.places import ImportedLocation
from pipit.imports.taxa import WHITESPACE, after_binomial, just_binomial

DATE_PARSERS = [JodaDateParser("yy-MM-dd"), JodaDateParser("yy/MM/dd")]
MACAULAY_LIBRARY_URL = "https://macaulaylibrary.org/asset/{}"
#: eBird's (and other languages') protocol names; ``ObservationType.fromName``.
_PROTOCOL_NAMES: dict[ObservationType, tuple[str, ...]] = {
    ObservationType.INCIDENTAL: (
        "Casual", "eBird - Casual Observation", "Zufällig", "Ustekabekoa",
        "Observation informelle", "Casuale", "אקראית", "偶発的", "Tilfeldig",
        "Observação Casual", "Случайное наблюдение", "Tesadüfi", "Випадкове", "附帶紀錄",
        "偶然记录"),
    ObservationType.TRAVELING: (
        "Trasa", "Strecke", "Con Desplazamiento", "Mugitzen",
        "Relevé en mouvement ou transect", "Itinerante", "ניידת", "移動", "Turbasert",
        "Percurso", "Contagem de Percurso", "Наблюдение во время передвижения", "Seyyar",
        "Маршрутне", "行進計數", "行进中观鸟", "eBird - Traveling Count"),
    ObservationType.STATIONARY: (
        "eBird - Stationary Count", "Statické", "Stationär", "Estacionario", "Geldirik",
        "Relevé ponctuel ou stationnaire", "Stazionaria", "נייחת", "定点", "Stasjonær",
        "Estacionária", "Contagem Estacionária", "Наблюдение из одной точки", "Sabit",
        "Точкове", "定點計數", "定点观鸟"),
    ObservationType.HISTORICAL: (
        "Historické", "Historisch", "Historikoa", "Historique", "Storico", "היסטורי",
        "過去の", "Historisk", "Histórico", "История", "Sandıktan", "Історичне", "歷史資料",
        "历史记录"),
    ObservationType.AREA: ("eBird - Exhaustive Area Count",),
    ObservationType.BANDING: ("PriMig - Pri Mig Banding Protocol", "Pri Mig Banding Protocol",
                              "Banding Protocol"),
    ObservationType.PELAGIC: (),
    ObservationType.NOCTURNAL: ("Nocturnal Count",),
    ObservationType.FLIGHT_CALL: ("eBird--Nocturnal Flight Call Count",),
    ObservationType.RANDOM: ("eBird Random Location Count",),
}  # fmt: skip


def _normalize_protocol(name: str) -> str:
    normalized = "".join(c for c in name.lower() if c not in " -")
    return normalized[5:] if normalized.startswith("ebird") else normalized


def _protocols() -> dict[str, ObservationType]:
    found: dict[str, ObservationType] = {}
    for observation_type, names in _PROTOCOL_NAMES.items():
        found[_normalize_protocol(observation_type.label)] = observation_type
        for name in names:
            found[_normalize_protocol(name)] = observation_type
    return found


_PROTOCOLS = _protocols()


def observation_type(protocol: str | None) -> ObservationType:
    """``EBird.observationType``: unknown or missing protocols are historical."""
    if not protocol:
        return ObservationType.HISTORICAL
    return _PROTOCOLS.get(_normalize_protocol(protocol), ObservationType.HISTORICAL)


class MissingHeaderError(ValueError):
    """``IMPORT_REQUIRED_HEADER_MISSING_FORMAT``."""


@dataclass(frozen=True, slots=True)
class VisitFields:
    """What a row says about its checklist, before ``VisitInfo`` checks it."""

    observation_type: ObservationType
    duration_minutes: int | None
    distance_km: float | None
    area_hectares: float | None
    party_size: int | None
    complete: bool
    comments: str | None


class MyDataFile:
    """A My Data file's rows and columns (``computeMappings``)."""

    #: A mass export: everything the account has, so only new dates need importing.
    mass_export = True
    format_name = "eBird My Data"

    def __init__(self, path: Path) -> None:
        self.path = path
        rows = read_rows(path)
        if not rows:
            raise MissingHeaderError("The file is empty.")
        self.header = rows[0]
        self.rows = rows[1:]
        index = {name.lower(): i for i, name in enumerate(self.header)}
        self._time = index.get("time")
        self._breeding = index.get("breeding code")
        # "Species Comments" became "Observation Details" in October 2019
        self._details = index.get("species comments")
        if self._details is None:
            self._details = index.get("observation details")
        self._photos = index.get("ml catalog numbers")
        self._count = 4 if "count" in index else None
        self._date = _required(index, "Date")
        self._region = _required(index, "State/Province")
        self._county = _required(index, "County")
        self._location = _required(index, "Location")
        self._hotspot = index.get("location id")
        self._latitude = index.get("latitude")
        self._longitude = index.get("longitude")
        self._common = _required(index, "Common Name")
        self._scientific = _required(index, "Scientific Name")
        self._protocol = _required(index, "Protocol")
        self._duration_minutes = index.get("duration (min)")
        self._duration_hours = index.get("duration (hrs)")
        self._complete = index.get("all obs reported")
        self._distance = index.get("distance traveled (km)")
        self._area = index.get("area covered (ha)")
        self._comments = index.get("checklist comments")
        self._observers = index.get("number of observers")

    # -------------------------------------------------------------- keys

    def location_key(self, row: list[str]) -> str:
        return "|".join(string_at(row, i) or "" for i in (self._region, self._county,
                                                           self._location))  # fmt: skip

    def taxon_key(self, row: list[str]) -> str:
        return "|".join(string_at(row, i) or "" for i in (self._common, self._scientific))

    def date(self, row: list[str]) -> PartialDate | None:
        """``PartialDateParserLineExtractor``; raises DateParseError."""
        text = string_at(row, self._date)
        return parse_first_match(DATE_PARSERS, text) if text else None

    # -------------------------------------------------------------- places and names

    def imported_location(self, row: list[str]) -> ImportedLocation:
        region = string_at(row, self._region) or ""
        parts = region.split("-")
        if len(parts) != 2:
            raise ValueError(f"Doesn't look like an eBird file. Location contains {region}")
        return ImportedLocation(
            country_code=parts[0], state_code=parts[1],
            county=string_at(row, self._county) or None,
            location_names=[string_at(row, self._location) or None],
            ebird_hotspot_id=string_at(row, self._hotspot) or None,
            latitude=string_at(row, self._latitude) or None,
            longitude=string_at(row, self._longitude) or None,
        )  # fmt: skip

    def names(self, row: list[str]) -> tuple[str | None, str | None, str | None]:
        """Common name, binomial and what follows it (``FieldTaxonImporter`` with
        ``JustBinomial`` and ``AfterBinomial``)."""
        common = string_at(row, self._common)
        scientific = string_at(row, self._scientific)
        binomial = just_binomial(scientific) if scientific is not None else None
        rest = after_binomial(scientific) if scientific is not None else None
        return common or None, binomial or None, rest

    # -------------------------------------------------------------- sightings

    def map_fields(self, row: list[str], sighting: Sighting) -> None:
        """The mappers other than place and taxon, in order: date, count, details, time,
        breeding code, photos. Only the date can fail (DateParseError)."""
        date = self.date(row)
        if date is not None:
            sighting.date = date
        if self._count is not None:
            text = string_at(row, self._count)
            if text is not None:
                number = ApproximateNumber.parse(text)
                if number is not None:
                    sighting.count = number
        if self._details is not None:
            details = string_at(row, self._details)
            if details:
                sighting.description = details
        if self._time is not None:
            text = string_at(row, self._time)
            if text:
                with contextlib.suppress(ValueError):  # TimeMapper only logs it
                    sighting.time = parse_external_time(text)
        if self._breeding is not None:
            code = breeding_code(string_at(row, self._breeding))
            if code is not None:
                sighting.breeding = code
        if self._photos is not None:
            numbers = string_at(row, self._photos)
            if numbers:
                photos = [Photo(MACAULAY_LIBRARY_URL.format(number))
                          for number in _split_whitespace(numbers)]  # fmt: skip
                if photos:
                    sighting.photographed = True
                sighting.photos = photos

    def visit(self, row: list[str]) -> VisitFields:
        """``lookForVisitInfo``'s values."""
        if self._duration_hours is not None:
            hours = float_at(row, self._duration_hours)
            duration = None if hours is None else int(hours * 60)
        else:
            duration = int_at(row, self._duration_minutes)
        return VisitFields(
            observation_type(string_at(row, self._protocol)),
            duration if duration is not None and duration > 0 else None,
            _positive(float_at(row, self._distance)),
            _positive(float_at(row, self._area)),
            _positive_int(int_at(row, self._observers)),
            bool_at(row, self._complete) if self._complete is not None else False,
            string_at(row, self._comments) or None,
        )


def _required(index: dict[str, int], name: str) -> int:
    found = index.get(name.lower())
    if found is None:
        raise MissingHeaderError(f'The file has no "{name}" column.')
    return found


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0.0 else None


def _positive_int(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _split_whitespace(text: str) -> list[str]:
    """``Splitter.on(CharMatcher.whitespace())``: every whitespace character splits."""
    parts = [""]
    for character in text:
        if character in WHITESPACE:
            parts.append("")
        else:
            parts[-1] += character
    return parts

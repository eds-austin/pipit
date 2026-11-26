"""What an importer reads from a file, row by row (each format's part of Scythebill's
``CsvSightingsImporter`` subclasses)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pipit.domain.partial_date import PartialDate
from pipit.domain.report import ObservationType, Sighting
from pipit.imports.places import ImportedLocation, LocationShortcuts
from pipit.imports.taxa import TaxonResolver


@dataclass(frozen=True, slots=True)
class VisitFields:
    """What a row says about its checklist, before ``VisitInfo`` checks it. A duration of 0
    counts as given (Scythebill keeps it, but never writes it)."""

    observation_type: ObservationType
    duration_minutes: int | None
    distance_km: float | None
    area_hectares: float | None
    party_size: int | None
    complete: bool
    comments: str | None


class ImportSource(Protocol):
    path: Path
    #: The rows after the header (if any), as ``CsvImportLines`` reads them.
    rows: list[list[str]]
    header: list[str] | None
    #: The whole of an account's data, so Pipit asks about dates the list already has.
    mass_export: bool
    #: Whether "only the new dates" narrows the import (Scythebill ignores it for some).
    filters_dates: bool
    format_name: str
    #: ``TaxonResolver``'s maximum edit distance for names.
    name_distance: int
    #: The refusal when no row's date (or other fields) reads.
    unreadable_message: str

    def location_key(self, row: list[str]) -> str: ...

    def taxon_key(self, row: list[str]) -> str: ...

    def date(self, row: list[str]) -> PartialDate | None: ...

    def imported_location(
        self, row: list[str], shortcuts: LocationShortcuts
    ) -> ImportedLocation: ...

    def names(
        self, row: list[str], resolver: TaxonResolver
    ) -> tuple[str | None, str | None, str | None]: ...

    def map_fields(self, row: list[str], sighting: Sighting) -> None: ...

    def visit(self, row: list[str]) -> VisitFields | None:
        """The row's checklist details; None for formats without any."""
        ...

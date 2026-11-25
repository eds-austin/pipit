"""The Species screen's data: the display taxonomy as a list (families as headings, each
species with what was seen of it), and the sightings of one entry with their details.

Entries are the Locations screen's roll-up (``species_at`` over the whole list): a
subspecies or group counts as its species; a sp., hybrid or genus-level sighting is its
own entry, listed where it falls in taxonomic order; another taxonomy (mammals) follows
the birds.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from pipit.browse.dates import date_key, display_date
from pipit.browse.locations import SpeciesSeen
from pipit.domain.partial_date import PartialDate, parse_partial_date
from pipit.entry.taxa import EntryTaxa
from pipit.taxa.model import TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon

DATE_RANGE = " \u2013 "  # an en dash between two dates
_FLAG_TEXT = (("heard_only", "heard only"), ("male", "male"), ("female", "female"),
              ("adult", "adult"), ("immature", "immature"), ("photographed", "photo"))  # fmt: skip


@dataclass(frozen=True, slots=True)
class TaxonRow:
    key: str  # "" for a family heading
    heading: bool
    common: str
    scientific: str
    sightings: int
    first_text: str
    last_text: str
    is_species: bool


def taxonomy_rows(
    taxa: EntryTaxa,
    seen: Iterable[SpeciesSeen],
    *,
    only_seen: bool = True,
    query: str = "",
) -> list[TaxonRow]:
    """Families (as headings) and their species in taxonomic order. With ``only_seen``,
    only what has a sighting; ``query`` keeps entries whose common or scientific name
    contains it. Entries that are not one species (sp., hybrid, genus-level) and other
    taxonomies are listed where they fall."""
    by_key = {entry.key: entry for entry in seen}
    needle = query.strip().casefold()

    def wanted(common: str, scientific: str) -> bool:
        return not needle or needle in common.casefold() or needle in scientific.casefold()

    rows: list[TaxonRow] = []
    # Entries that aren't a species of the display taxonomy, by taxonomic position.
    extras = sorted(
        (entry for entry in by_key.values() if not _is_display_species(taxa, entry.key)),
        key=lambda entry: (entry.order, entry.key),
    )
    extra_index = 0
    family_name = ""
    family_scientific = ""
    family_shown = True

    def emit(row: TaxonRow) -> None:
        nonlocal family_shown
        if not family_shown and family_name:
            rows.append(TaxonRow("", True, family_name, family_scientific, 0, "", "", False))
            family_shown = True
        rows.append(row)

    def from_entry(entry: SpeciesSeen) -> TaxonRow:
        return TaxonRow(entry.key, False, entry.common, entry.scientific, entry.sightings,
                        entry.first_text, entry.last_text, entry.is_species)  # fmt: skip

    for taxon in taxa.display.walk():
        if taxon.disabled:
            continue
        if taxon.type is TaxonType.FAMILY:
            family_name = taxon.common_name or taxon.name
            family_scientific = taxon.name
            family_shown = False
            continue
        if taxon.type is not TaxonType.SPECIES:
            continue
        order = taxa.order(taxon.id)
        while extra_index < len(extras) and extras[extra_index].order < order:
            entry = extras[extra_index]
            extra_index += 1
            if wanted(entry.common, entry.scientific):
                emit(from_entry(entry))
        entry_seen = by_key.get(taxon.id)
        if entry_seen is not None:
            if wanted(entry_seen.common, entry_seen.scientific):
                emit(from_entry(entry_seen))
        elif not only_seen:
            common, scientific = taxa.names(taxon.id)
            if wanted(common, scientific):
                emit(TaxonRow(taxon.id, False, common, scientific, 0, "", "", True))
    for entry in extras[extra_index:]:  # other taxonomies, then anything unresolved
        heading = "Other taxonomies" if entry.key.startswith("ext:") else "Not in this taxonomy"
        if heading != family_name:
            family_name, family_scientific, family_shown = heading, "", False
        if wanted(entry.common, entry.scientific):
            emit(from_entry(entry))
    return rows


def _is_display_species(taxa: EntryTaxa, key: str) -> bool:
    taxon = taxa.display.get(key)
    return taxon is not None and taxon.type is TaxonType.SPECIES


@dataclass(frozen=True, slots=True)
class SightingRow:
    sighting_id: int
    date_text: str
    time_text: str
    place: str  # "Lake Merritt · Bay Area, California"
    location_xml_id: str | None
    date_raw: str | None
    as_recorded: str  # the taxon as recorded, when it is narrower than the entry ("" else)
    count: str  # "" when present with no count
    flags: str  # "heard only · photo"
    status: str
    breeding: str
    notes: str
    trip: str
    sort_key: tuple[tuple[int, int, int], str, int]


def sightings_of(
    connection: sqlite3.Connection, taxa: EntryTaxa, entry: SpeciesSeen
) -> list[SightingRow]:
    """The entry's sightings, newest first, with where, when and every detail."""
    if not entry.sighting_ids:
        return []
    places = place_labels(connection)
    trips = dict(connection.execute("SELECT xml_id, coalesce(name, xml_id) FROM trips"))
    trip_spans = {
        xml_id: (parse_partial_date(start), parse_partial_date(end))
        for xml_id, start, end in connection.execute(
            "SELECT xml_id, start_date, end_date FROM trips"
        )
    }
    marks = ",".join("?" * len(entry.sighting_ids))
    parts: dict[int, list[str]] = {}
    for sighting, taxon_id in connection.execute(
        f"SELECT sighting_id, taxon_id FROM sighting_taxa WHERE sighting_id IN ({marks}) "
        "ORDER BY sighting_id, ord",
        entry.sighting_ids,
    ):
        parts.setdefault(sighting, []).append(taxon_id)
    rows = []
    for (sighting, taxonomy_id, kind, taxon_id, subspecies, location, date, year, month,
         day, time, count, male, female, immature, adult, heard_only, photographed, status,
         breeding, description, trip) in connection.execute(
        "SELECT id, taxonomy_id, kind, taxon_id, subspecies, location_xml_id, date, date_y, "
        "date_m, date_d, time, count, male, female, immature, adult, heard_only, "
        f"photographed, status, breeding, description, trip_xml_id FROM sightings "
        f"WHERE id IN ({marks})",
        entry.sighting_ids,
    ):  # fmt: skip
        flags = {"heard_only": heard_only, "male": male, "female": female, "adult": adult,
                 "immature": immature, "photographed": photographed}  # fmt: skip
        rows.append(
            SightingRow(
                sighting, _date_text(year, month, day, trip_spans.get(trip)), time or "",
                places.get(location, "No place") if location else "No place", location, date,
                _as_recorded(taxa, entry, taxonomy_id=taxonomy_id, kind=kind,
                             taxon_id=taxon_id, subspecies=subspecies,
                             parts=parts.get(sighting, [])),
                count or "",
                " · ".join(text for flag, text in _FLAG_TEXT if flags[flag]),
                "" if status == "none" else status, breeding, description or "",
                trips.get(trip, "") if trip else "",
                (_sort_date(year, month, day, trip_spans.get(trip)), time or "", sighting),
            )
        )  # fmt: skip
    rows.sort(key=lambda row: row.sort_key, reverse=True)
    return rows


def _date_text(year: int | None, month: int | None, day: int | None,
               span: tuple[PartialDate, PartialDate] | None) -> str:  # fmt: skip
    """The sighting's date; an undated one on a trip shows the trip's first and last days."""
    if (year, month, day) == (None, None, None) and span is not None:
        start, end = span
        first = display_date(start.year, start.month, start.day)
        last = display_date(end.year, end.month, end.day)
        return first if first == last else f"{first}{DATE_RANGE}{last}"
    return display_date(year, month, day)


def _sort_date(year: int | None, month: int | None, day: int | None,
               span: tuple[PartialDate, PartialDate] | None) -> tuple[int, int, int]:  # fmt: skip
    if (year, month, day) == (None, None, None) and span is not None:
        return date_key(span[0].year, span[0].month, span[0].day)
    return date_key(year, month, day)


def _as_recorded(
    taxa: EntryTaxa,
    entry: SpeciesSeen,
    *,
    taxonomy_id: str | None,
    kind: str,
    taxon_id: str | None,
    subspecies: str | None,
    parts: list[str],
) -> str:
    """The recorded subspecies or group, when it is narrower than the entry."""
    if taxonomy_id is not None or kind in ("sp", "hybrid") or taxon_id is None:
        return ""
    stored = (
        SightingTaxon.with_secondary_subspecies(taxon_id, subspecies or "")
        if kind == "ssp"
        else SightingTaxon.single(taxon_id)
    )
    shown = taxa.row_id(stored)
    if shown is None or shown == entry.key:
        return ""
    common, scientific = taxa.names(shown)
    return scientific if common == scientific or not common else f"{common} ({scientific})"


def place_labels(connection: sqlite3.Connection) -> dict[str, str]:
    """Each place as "name · up to three places it is in" (regions left out)."""
    rows = {
        xml_id: (name, parent, kind)
        for xml_id, name, parent, kind in connection.execute(
            "SELECT l.xml_id, l.name, p.xml_id, l.type FROM locations l "
            "LEFT JOIN locations p ON p.id = l.parent_id"
        )
    }
    labels = {}
    for xml_id, (name, parent, _kind) in rows.items():
        ancestors: list[str] = []
        current = parent
        while current is not None and len(ancestors) < 3:
            parent_name, next_parent, parent_kind = rows[current]
            if parent_kind != "region":
                ancestors.append(parent_name)
            current = next_parent
        labels[xml_id] = name + (f" · {', '.join(ancestors)}" if ancestors else "")
    return labels

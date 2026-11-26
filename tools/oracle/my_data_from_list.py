"""Write a list's sightings as an eBird "My Data" file, for testing imports at scale: every
dated sighting of the base taxonomy at a place in a country, with eBird's names (sp. as
"A/B", hybrids as "A x B (hybrid)", groups and subspecies after the binomial), the state as
"CC-SS", the county, the place's own name, coordinates and hotspot, and its checklist's
protocol and details. Rows come in the list's order, so a checklist's rows may be apart, as
they can be in eBird's files.

    python -I tools/oracle/my_data_from_list.py pack.sqlite list.bsxm out.csv [limit]

For a private list, write the file somewhere private (it holds the list's contents).
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from pipit.bsxm.reader import read_bsxm
from pipit.bsxm.upgrades import apply_upgrades
from pipit.datapack.pack import DataPack
from pipit.domain.locations import location_code
from pipit.domain.partial_date import format_partial_date
from pipit.domain.report import Location, ObservationType, Sighting, Visit, VisitKey
from pipit.taxa.model import Taxon, Taxonomy, TaxonType, full_name
from pipit.taxa.sighting_taxon import SightingTaxonType

HEADER = [
    "Submission ID", "Common Name", "Scientific Name", "Taxonomic Order", "Count",
    "State/Province", "County", "Location ID", "Location", "Latitude", "Longitude", "Date",
    "Time", "Protocol", "Duration (Min)", "All Obs Reported", "Distance Traveled (km)",
    "Area Covered (ha)", "Number of Observers", "Breeding Code", "Observation Details",
    "Checklist Comments", "ML Catalog Numbers",
]  # fmt: skip
PROTOCOLS = {
    ObservationType.INCIDENTAL: "eBird - Casual Observation",
    ObservationType.TRAVELING: "eBird - Traveling Count",
    ObservationType.STATIONARY: "eBird - Stationary Count",
    ObservationType.HISTORICAL: "Historical",
    ObservationType.AREA: "eBird - Exhaustive Area Count",
    ObservationType.BANDING: "eBird--Banding Protocol",
    ObservationType.PELAGIC: "eBird Pelagic Protocol",
    ObservationType.NOCTURNAL: "eBird - Nocturnal Count",
    ObservationType.FLIGHT_CALL: "eBird - Nocturnal Flight Call Count",
    ObservationType.RANDOM: "eBird Random Location Count",
}  # fmt: skip


def _species(taxon: Taxon) -> Taxon:
    while taxon.type < TaxonType.SPECIES and taxon.parent is not None:
        taxon = taxon.parent
    return taxon


def names(taxonomy: Taxonomy, sighting: Sighting) -> tuple[str, str] | None:
    taxon_type = sighting.taxon.type
    taxa = [taxonomy[taxon_id] for taxon_id in sighting.taxon.ids]
    if taxon_type in (SightingTaxonType.SP, SightingTaxonType.HYBRID):
        species = [_species(taxon) for taxon in taxa]
        if len(set(species)) == 1:
            # Forms of one species: eBird names them after the binomial ("a/b")
            return (
                species[0].common_name or "",
                f"{full_name(species[0])} {'/'.join(taxon.name for taxon in taxa)}",
            )
        commons = [taxon.common_name or "" for taxon in species]
        scientific = [full_name(taxon) for taxon in species]
        if taxon_type is SightingTaxonType.SP:
            return "/".join(commons), "/".join(scientific)
        return " x ".join(commons) + " (hybrid)", " x ".join(scientific)
    taxon = taxa[0]
    if taxon.type > TaxonType.SPECIES:
        return None
    if taxon.type is TaxonType.SUBSPECIES:
        own_species = _species(taxon)
        return own_species.common_name or "", f"{full_name(own_species)} {taxon.name}"
    return taxon.common_name or "", full_name(taxon)


def place(location: Location) -> tuple[str, str, str] | None:
    """State/Province, county and place name."""
    country: Location | None = None
    state: Location | None = None
    county: Location | None = None
    current: Location | None = location
    while current is not None:
        code = location_code(current)
        if current.type == "county" and county is None and state is None:
            county = current
        if code is not None and "-" in code and state is None and country is None:
            state = current
        if current.type == "country" and code is not None and len(code) == 2:
            country = current
            break
        current = current.parent
    if country is None:
        return None
    country_code = location_code(country)
    state_code = location_code(state) if state is not None else None
    region = state_code if state_code is not None else f"{country_code}-"
    if region.count("-") != 1:
        return None
    leaf = "" if location in (country, state, county) else location.name
    return region, county.name if county is not None else "", leaf


def _time(sighting: Sighting) -> str:
    if sighting.time is None:
        return ""
    hour = sighting.time.hour % 12 or 12
    return f"{hour:02d}:{sighting.time.minute:02d} {'AM' if sighting.time.hour < 12 else 'PM'}"


def main() -> None:
    with DataPack(Path(sys.argv[1])) as pack:
        report = read_bsxm(Path(sys.argv[2]), pack.base_taxonomy_id, pack.base_taxon_ids()).report
        apply_upgrades(report)
        taxonomy = pack.load_taxonomy(pack.base_taxonomy_id)
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
    locations = {location.id: location for location in report.iter_locations()}
    visits: dict[VisitKey, Visit] = {visit.key: visit for visit in report.visits}
    submissions: dict[VisitKey, str] = {}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    written = 0
    for sighting in report.sightings:
        if limit is not None and written >= limit:
            break
        if sighting.taxonomy_id is not None or sighting.location_id is None:
            continue
        if sighting.date is None or not sighting.date.is_full_date:
            continue
        found_names = names(taxonomy, sighting)
        found_place = place(locations[sighting.location_id])
        if found_names is None or found_place is None:
            continue
        location = locations[sighting.location_id]
        key = VisitKey(sighting.location_id, sighting.date, sighting.time)
        visit = visits.get(key)
        submission = submissions.setdefault(key, f"S{len(submissions) + 1}")
        writer.writerow([
            submission, *found_names, "1",
            str(sighting.count) if sighting.count is not None else "X",
            *found_place[:2], location.ebird_hotspot_id or f"L{location.id}", found_place[2],
            location.lat_long.latitude if location.lat_long else "",
            location.lat_long.longitude if location.lat_long else "",
            format_partial_date(sighting.date), _time(sighting),
            PROTOCOLS[visit.observation_type] if visit else "eBird - Casual Observation",
            visit.duration_minutes or "" if visit else "",
            "1" if visit and visit.complete else "0",
            visit.distance_km or "" if visit else "",
            visit.area_hectares or "" if visit else "",
            visit.party_size or "" if visit else "",
            sighting.breeding, sighting.description or "",
            visit.comments or "" if visit else "", "",
        ])  # fmt: skip
        written += 1
    Path(sys.argv[3]).write_text(out.getvalue(), encoding="utf-8")
    print(f"{written} rows")


if __name__ == "__main__":
    main()

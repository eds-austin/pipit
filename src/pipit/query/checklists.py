"""The checklist Scythebill uses for a place (``Checklists.getChecklist``), in either taxonomy.

Ported from Scythebill's ``checklist`` package:
- ``Checklists.getChecklist``: a place always covered by a synthesized checklist (a world
  region, a synthetic region, the US outside North America, the Caribbean Netherlands, Great
  Britain or St Helena as the union of their parts); else the built-in checklist of its code;
  else the list's own checklist for the place, if it has one.
- ``ChecklistLocationCodes``: a place's checklist code, and the country codes under a region.
- ``TransposedChecklistSynthesizer``: a union of built-in checklists, status by status, with
  native species found nowhere else promoted to endemic.
- ``ClementsChecklist``: a list's own checklist, stored in Clements, seen in the display
  taxonomy at species level (a sp. counted for each of its species).

Statuses are Scythebill's ``Checklist.Status`` names: NATIVE, ENDEMIC, EXTINCT, INTRODUCED,
PROVISIONAL, RARITY, RARITY_FROM_INTRODUCED, ESCAPED.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from pipit.datapack.pack import DataPack
from pipit.domain.partial_date import after_or_equals, before_or_equals
from pipit.query.engine import Resolver
from pipit.query.model import QPlace, QSighting, QTrip, QueryList
from pipit.storage.checklist_ops import read_checklist
from pipit.taxa.model import Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

#: Stored status text (as in the pack and in lists) -> Scythebill's status name.
STATUS_NAMES = {None: "NATIVE", "": "NATIVE", "native": "NATIVE", "endemic": "ENDEMIC",
                "extinct": "EXTINCT", "introduced": "INTRODUCED", "provisional": "PROVISIONAL",
                "rarity": "RARITY", "rarity-from-introduced": "RARITY_FROM_INTRODUCED",
                "escaped": "ESCAPED"}  # fmt: skip
#: ``Checklist.Status`` in declaration order (EnumSet order).
STATUS_ORDER = ("NATIVE", "ENDEMIC", "EXTINCT", "INTRODUCED", "PROVISIONAL", "RARITY",
                "RARITY_FROM_INTRODUCED", "ESCAPED")  # fmt: skip

MULTI_REGION_COUNTRIES = frozenset({"RU", "ID", "XX"})
AGGREGATE_CHECKLIST_MEMBERS = {
    "GB": ("GB-ENG", "GB-NIR", "GB-SCT", "GB-WLS"),
    "SH": ("SH-AC", "SH-SH", "SH-TA"),
}
SYNTHETIC_US_CHECKLISTS = {
    "West Indies": ("PR", "VI"),
    "Pacific Ocean": ("US-HI", "GU", "MP", "AS"),
}
SUPPORTED_REGIONS_WITH_EXCLUSIONS = {
    "Europe": frozenset({"TR"}), "Asia": frozenset(), "Eurasia": frozenset(),
    "Africa": frozenset(), "Australasia": frozenset(), "South Polar Region": frozenset(),
    "Central America": frozenset(), "North America": frozenset(),
    "South America": frozenset(), "West Indies": frozenset(), "Indian Ocean": frozenset(),
    "Pacific Ocean": frozenset(), "Atlantic Ocean": frozenset(), "Arctic Ocean": frozenset(),
}  # fmt: skip
STATE_CHECKLIST_COUNTRIES = frozenset({"US", "CA", "MX", "AU", "ID", "MY", "GB", "SH", "AR",
                                       "BR", "CO", "EC", "PE"})  # fmt: skip
_OWN_PLACES = frozenset({"US-HI", "EC-W", "CO-SAP"})
_INDONESIA_AUSTRALASIA_STATES = frozenset({"ID-IJ", "ID-MA"})
_STATE_CODE = re.compile(r"[A-Z]{2}-[A-Z0-9]+")

# Synthetic regions' checklist unions (``SyntheticLocation.syntheticChecklistUnion``).
_FIXED_UNIONS: dict[str, tuple[str, ...]] = {
    "aba": ("US", "CA", "PM", "US-HI", "UM-71"),
    "abawh": ("US", "CA", "PM"),
    "us50": ("US", "US-HI", "UM-71"),
    "us48": ("US-AL", "US-AZ", "US-AR", "US-CA", "US-CO", "US-CT", "US-DE", "US-DC", "US-FL",
             "US-GA", "US-ID", "US-IL", "US-IN", "US-IA", "US-KS", "US-KY", "US-LA", "US-ME",
             "US-MD", "US-MA", "US-MI", "US-MN", "US-MS", "US-MO", "US-MT", "US-NE", "US-NV",
             "US-NH", "US-NJ", "US-NM", "US-NY", "US-NC", "US-ND", "US-OH", "US-OK", "US-OR",
             "US-PA", "US-RI", "US-SC", "US-SD", "US-TN", "US-TX", "US-UT", "US-VT", "US-VA",
             "US-WA", "US-WV", "US-WI", "US-WY"),
    "aou": ("US", "CA", "PM", "US-HI", "UM-71", "UM-67", "GL", "CU", "BQ", "BS", "MF", "CP",
            "MX", "BM", "BZ", "CR", "SV", "GT", "HN", "NI", "PA", "AI", "AG", "BB", "VG", "KY",
            "DM", "DO", "GD", "GP", "HT", "JM", "MQ", "MS", "BL", "KN", "LC", "VC", "CO-SAP",
            "TC", "PR", "VI"),
    "aossouth": ("AR", "AW", "BO", "BR", "BQ-BO", "CL", "CO", "CW", "EC", "GF", "GY", "PY",
                 "PE", "SR", "TT", "UY", "VE", "EC-W", "FK"),
    "sounafr": ("ZA", "ZW", "BW", "NA", "SZ", "LS", "MZ-L", "MZ-G", "MZ-I", "MZ-B", "MZ-S",
                "MZ-T"),
    "uswidepterr": ("US", "US-HI", "UM-71", "PR", "GU", "AS", "VI", "MP"),
    "austaba": (),
    "orireg": ("ID-Asia", "MV", "IN", "LA", "PK", "HK", "BD", "BT", "BN", "KH", "CN", "CX",
               "TL", "JP", "LA", "MO", "MY", "MN", "MM", "NP", "KP", "SG", "KR", "LK", "TW",
               "TH", "VN", "PH", "ID-MA", "RU-Asia"),
    "clwidepterr": ("CL", "CL-VS-Easter", "CL-VS-JuanFernandez"),
    "ushiwinowiis": ("US-HI", "UM-71"),
    "nlwidepterr": ("NL", "BQ", "AW", "CW", "BQ-BO"),
}  # fmt: skip
#: ``GenericSyntheticLocation.regionIfAvailable``: the codes present in the list.
_PRESENT_UNIONS: dict[str, tuple[str, ...]] = {
    "auwidepterr": ("AU", "AC", "CS", "CC", "CX", "NF", "HM", "AU-TAS-Macquarie"),
    "cowidepterr": ("CO", "CO-SAP"), "ecwidepterr": ("EC", "EC-W"),
    "ptwidepterr": ("PT", "PT-20", "PT-30"), "eswidepterr": ("ES", "ES-CEUMEL", "ES-CN"),
    "nzwidepterr": ("NZ", "TK"), "nowidepterr": ("NO", "BV", "SJ"),
    "gbwidepterr": ("GB", "AI", "BM", "IO", "VG", "KY", "FK", "GI", "MS", "PN", "SH", "TC",
                    "GS"),
    "cnwidepterr": ("CN", "HK", "MO"), "dkwidepterr": ("DK", "FO", "GL"),
    "zawidepterr": ("ZA", "ZA-WC-EdwardMarion"),
    "frwidepterr": ("FR", "BL", "MF", "PM", "WF", "PF", "NC", "CP", "TF", "RE", "GP", "GF",
                    "YT", "MQ"),
    "ireislof": ("IE", "GB-NIR"),
}  # fmt: skip
_WESTERN_PALEARCTIC_BUT_NOT_EUROPE = (
    "TR", "AZ", "AM", "GE", "CY", "IL", "PS", "JO", "LB", "KW", "SY", "IQ", "MA", "EH", "DZ",
    "TN", "LY", "EG", "ES-CN", "CV", "SJ", "FO", "ES-CEUMEL")  # fmt: skip
_PACIFIC_OCEAN_ABA_BUT_NOT_PACIFIC_OCEAN = ("AU-TAS-Macquarie", "NC", "NZ", "NF", "SB", "VU")


class Checklist:
    """Species (as sighting taxa of the display taxonomy) and their statuses."""

    def __init__(self, statuses: dict[SightingTaxon, str], built_in: bool) -> None:
        self.statuses = statuses
        self.built_in = built_in

    def status(self, taxon: SightingTaxon) -> str | None:
        """``getStatus``: a single taxon with a secondary subspecies counts as its species."""
        if taxon.type is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
            taxon = SightingTaxon.single(taxon.ids[0])
        return self.statuses.get(taxon)

    def includes(self, taxon_id: str, excluding: Iterable[str] = ()) -> bool:
        status = self.statuses.get(SightingTaxon.single(taxon_id))
        return status is not None and status not in excluding


@dataclass(frozen=True)
class _Place:
    xml_id: str
    name: str
    type: str | None
    code: str | None
    ebird_code: str | None
    parent: str | None
    built_in: bool


class Checklists:
    """``Checklists`` for one open list: built-in checklists from the data pack, synthesized
    ones cached, and the list's own."""

    def __init__(self, pack: DataPack, connection: sqlite3.Connection,
                 query_list: QueryList) -> None:  # fmt: skip
        self._pack = pack
        self._connection = connection
        self._places: dict[str, _Place] = {}
        self._children: dict[str, list[str]] = defaultdict(list)
        for place in query_list.places.values():
            self._places[place.xml_id] = _place(place)
            if place.parent is not None:
                self._children[place.parent].append(place.xml_id)
        self._codes: dict[str, set[str]] = {}
        self._built_in: dict[tuple[str, str], Checklist | None] = {}
        self._transposed: dict[str, dict[str, dict[str, list[str]]]] = {}
        self._synthesized: dict[tuple[str, frozenset[str]], Checklist] = {}
        self._custom: dict[tuple[str, str], Checklist | None] = {}
        self._present_codes: set[str] | None = None

    # ------------------------------------------------------------ getChecklist

    @property
    def pack(self) -> DataPack:
        return self._pack

    def checklist(self, taxonomy: Taxonomy, xml_id: str) -> Checklist | None:
        transposed = self._transposed_codes(xml_id)
        if transposed is not None:
            return self.synthesize(taxonomy, transposed)
        place = self._places.get(xml_id)
        if place is None:
            return None
        code = self.checklist_code(place)
        if code is None or code not in self._region_codes(taxonomy):
            return self._custom_checklist(taxonomy, xml_id)
        return self._built_in_checklist(taxonomy, code)

    def trip_checklist_codes(self, taxonomy: Taxonomy, trips: list[QTrip],
                             query_list: QueryList) -> list[str] | None:  # fmt: skip
        """``getTripChecklistCodes``: for one trip with a place, the nearest place with a
        built-in checklist; otherwise each trip's country's codes (for a trip with no place,
        the countries of the places its sightings are at). None if a country has none."""
        codes: dict[str, None] = {}
        undated: list[QTrip] = []
        for trip in trips:
            if trip.location_xml_id is not None and trip.location_xml_id in self._places:
                if len(trips) == 1:
                    nearest = self.nearest_built_in_code(taxonomy, trip.location_xml_id)
                    if nearest is not None:
                        return [nearest]
                country = self._ancestor_of_type(trip.location_xml_id, "country")
                if country is not None:
                    found = self.checklist_codes(self._places[country])
                    if not found:
                        return None
                    codes.update(dict.fromkeys(found))
                    continue
            undated.append(trip)
        if undated:
            matching: dict[str, None] = {}
            for sighting in query_list.sightings:
                # Scythebill fails on a sighting with no place here; Pipit skips it
                if sighting.location_xml_id is not None and any(
                    _in_trip(sighting, trip, query_list) for trip in undated
                ):
                    matching[sighting.location_xml_id] = None
            for location in matching:
                country = self._ancestor_of_type(location, "country")
                if country is not None:
                    found = self.checklist_codes(self._places[country])
                    if not found:
                        return None
                    codes.update(dict.fromkeys(found))
        return list(codes)

    def nearest_built_in_code(self, taxonomy: Taxonomy, xml_id: str) -> str | None:
        """``getLocationWithNearestBuiltInChecklist``."""
        regions = set(self._pack.checklist_regions(_pack_taxonomy_id(taxonomy)))
        place = self._places.get(xml_id)
        while place is not None:
            code = self.checklist_code(place)
            if code is not None and code in regions:
                return code
            place = self._places.get(place.parent) if place.parent else None
        return None

    def _ancestor_of_type(self, xml_id: str, place_type: str) -> str | None:
        place = self._places.get(xml_id)
        while place is not None and place.type != place_type:
            place = self._places.get(place.parent) if place.parent else None
        return None if place is None else place.xml_id

    def checklist_for_codes(self, taxonomy: Taxonomy, codes: list[str] | None) -> Checklist | None:
        """``getChecklist(reportSet, taxonomy, synthesizer, codes)``: one code's checklist,
        or several synthesized into one."""
        if not codes:
            return None
        if len(codes) == 1:
            code = codes[0]
            if code in AGGREGATE_CHECKLIST_MEMBERS:
                return self.synthesize(taxonomy, frozenset(AGGREGATE_CHECKLIST_MEMBERS[code]))
            if code not in self._region_codes(taxonomy):
                return None
            return self._built_in_checklist(taxonomy, code)
        return self.synthesize(taxonomy, frozenset(codes))

    def _transposed_codes(self, xml_id: str) -> frozenset[str] | None:
        """``getTransposedChecklistLocations``."""
        if xml_id.startswith("***") and xml_id.endswith("***"):
            return frozenset(self._synthetic_union(xml_id[3:-3]))
        place = self._places.get(xml_id)
        if place is None:
            return None
        if (
            place.built_in
            and place.type == "region"
            and (place.name in SUPPORTED_REGIONS_WITH_EXCLUSIONS)
        ):
            codes = self.gather_country_codes(xml_id)
            return frozenset(codes) - SUPPORTED_REGIONS_WITH_EXCLUSIONS[place.name]
        parent_name = self._parent_name(place)
        if place.ebird_code == "US" and parent_name in SYNTHETIC_US_CHECKLISTS:
            return frozenset(SYNTHETIC_US_CHECKLISTS[parent_name])
        if place.ebird_code == "BQ":
            if parent_name == "South America":
                return frozenset({"AW", "BQ-BO", "CW"})
            return frozenset({"BQ"})
        code = self.checklist_code(place)
        if code in AGGREGATE_CHECKLIST_MEMBERS:
            return frozenset(AGGREGATE_CHECKLIST_MEMBERS[code])
        return None

    def _parent_name(self, place: _Place) -> str | None:
        parent = self._places.get(place.parent) if place.parent else None
        return parent.name if parent else None

    def checklist_code(self, place: _Place) -> str | None:
        """``ChecklistLocationCodes.getChecklistLocationCode``."""
        code = place.code
        parent_name = self._parent_name(place)
        if code == "US" and parent_name != "North America":
            return None
        if code == "BQ" and parent_name != "West Indies":
            return None
        if code == "UM":
            return None
        if code in MULTI_REGION_COUNTRIES:
            parent = self._places.get(place.parent) if place.parent else None
            while parent is not None:
                if parent.built_in and parent.type == "region":
                    return f"{code}-{parent.name}"
                parent = self._places.get(parent.parent) if parent.parent else None
            return None
        return code

    def checklist_codes(self, place: _Place) -> list[str]:
        """``ChecklistLocationCodes.getChecklistLocationCodes``."""
        if place.ebird_code == "BQ":
            if self._parent_name(place) == "South America":
                return ["AW", "BQ-BO", "CW"]
            return ["BQ"]
        code = self.checklist_code(place)
        if code is None:
            if place.ebird_code == "US":
                found = SYNTHETIC_US_CHECKLISTS.get(self._parent_name(place) or "")
                if found is not None:
                    return list(found)
            if place.ebird_code == "UM":
                return ["UM-71"]
            return []
        return list(AGGREGATE_CHECKLIST_MEMBERS.get(code, (code,)))

    def gather_country_codes(self, xml_id: str) -> list[str]:
        """``ChecklistLocationCodes.gatherCountryChecklistCodes``."""
        codes: dict[str, None] = {}

        def gather(parent: str) -> None:
            for child_id in self._children.get(parent, []):
                child = self._places[child_id]
                if child.built_in and child.type != "region":
                    codes.update(dict.fromkeys(self.checklist_codes(child)))
                elif child.ebird_code is not None and child.ebird_code.startswith("XX-"):
                    codes[child.ebird_code] = None
                else:
                    gather(child_id)

        gather(xml_id)
        return list(codes)

    def _synthetic_union(self, key: str) -> Iterable[str]:
        if key in _FIXED_UNIONS:
            return _FIXED_UNIONS[key]
        if key in _PRESENT_UNIONS:
            present = self.present_codes()
            return [code for code in _PRESENT_UNIONS[key] if code in present]
        if key in ("wepale", "pacoceaba"):
            name = "Europe" if key == "wepale" else "Pacific Ocean"
            extra = (_WESTERN_PALEARCTIC_BUT_NOT_EUROPE if key == "wepale"
                     else _PACIFIC_OCEAN_ABA_BUT_NOT_PACIFIC_OCEAN)  # fmt: skip
            region = next((p.xml_id for p in self._places.values()
                           if p.built_in and p.name == name), None)  # fmt: skip
            if region is None:
                return ()
            return [*self.gather_country_codes(region), *extra]
        return ()

    def present_codes(self) -> set[str]:
        """Codes ``LocationSet.getLocationsByCode`` finds once Scythebill has added its
        predefined places: the list's, and the states and counties below its countries and
        US states."""
        if self._present_codes is None:
            codes = {p.code for p in self._places.values() if p.code}
            countries = [p.name for p in self._places.values()
                         if p.built_in and p.type == "country"]  # fmt: skip
            us_states = [p.code.removeprefix("US-") for p in self._places.values()
                         if p.built_in and p.type == "state" and p.code
                         and p.code.startswith("US-")]  # fmt: skip
            codes.update(self._pack.predefined_locations().codes(countries, us_states))
            self._present_codes = codes
        return self._present_codes

    # ------------------------------------------------------------ built-in checklists

    def _region_codes(self, taxonomy: Taxonomy) -> set[str]:
        key = _pack_taxonomy_id(taxonomy)
        if key not in self._codes:
            self._codes[key] = set(self._pack.checklist_regions(key)) | set(
                AGGREGATE_CHECKLIST_MEMBERS
            )
        return self._codes[key]

    def _built_in_checklist(self, taxonomy: Taxonomy, code: str) -> Checklist | None:
        key = (_pack_taxonomy_id(taxonomy), code)
        if key not in self._built_in:
            rows = self._pack.checklist(key[0], code)
            self._built_in[key] = Checklist(
                {SightingTaxon.single(row.taxon_id): STATUS_NAMES[row.status] for row in rows},
                built_in=True,
            )
        return self._built_in[key]

    # ------------------------------------------------------------ synthesis

    def _transpose(self, taxonomy: Taxonomy) -> dict[str, dict[str, list[str]]]:
        """``TransposedChecklists``: species -> status -> region codes."""
        key = _pack_taxonomy_id(taxonomy)
        if key not in self._transposed:
            transposed: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
            for taxon_id, status, region in self._pack.transposed_checklists(key):
                transposed[taxon_id][STATUS_NAMES[status]].append(region)
            self._transposed[key] = transposed
        return self._transposed[key]

    def synthesize(self, taxonomy: Taxonomy, codes: frozenset[str]) -> Checklist:
        """``TransposedChecklistSynthesizer.createChecklist``."""
        key = (_pack_taxonomy_id(taxonomy), codes)
        if key in self._synthesized:
            return self._synthesized[key]
        transposed = self._transpose(taxonomy)
        exclusions = {c for c in (_containing_code(code) for code in codes) if c is not None}
        statuses: dict[SightingTaxon, str] = {}
        for taxon in taxonomy.walk():
            if taxon.type is not TaxonType.SPECIES:
                continue
            by_status = transposed.get(taxon.id)
            if not by_status:
                continue
            single = SightingTaxon.single(taxon.id)
            for status in ("EXTINCT", "RARITY_FROM_INTRODUCED", "RARITY", "PROVISIONAL",
                           "INTRODUCED"):  # fmt: skip
                if any(code in codes for code in by_status.get(status, ())):
                    statuses[single] = status
            endemic = by_status.get("ENDEMIC", [])
            if endemic and all(code in codes for code in endemic):
                statuses[single] = "ENDEMIC"
                continue
            inside = outside = False
            for code in (*by_status.get("NATIVE", ()), *endemic):
                if code in codes:
                    statuses[single] = "NATIVE"
                    inside = True
                elif code not in exclusions and _containing_code(code) not in codes:
                    outside = True
                if inside and outside:
                    break
            if inside and not outside:
                statuses[single] = "ENDEMIC"
        checklist = self._synthesized[key] = Checklist(statuses, built_in=True)
        return checklist

    # ------------------------------------------------------------ the list's own

    def _custom_checklist(self, taxonomy: Taxonomy, xml_id: str) -> Checklist | None:
        key = (taxonomy.id, xml_id)
        if key not in self._custom:
            entries = read_checklist(self._connection, xml_id)
            if not entries:
                self._custom[key] = None
            else:
                resolver = Resolver(taxonomy)
                statuses: dict[SightingTaxon, str] = {}
                for entry in entries:
                    resolved = resolver(_entry_taxon(entry.kind, entry.taxon_ids,
                                                     entry.subspecies))  # fmt: skip
                    if resolved is None:
                        continue
                    species = resolved.parent_of_at_least_type(TaxonType.SPECIES)
                    status = STATUS_NAMES[entry.status]
                    if species.type is SightingTaxonType.SP:
                        for taxon_id in species.ids:
                            statuses[SightingTaxon.single(taxon_id)] = status
                    else:
                        statuses[species] = status
                self._custom[key] = Checklist(statuses, built_in=False)
        return self._custom[key]


def _in_trip(sighting: QSighting, trip: QTrip, query_list: QueryList) -> bool:
    """``TripUtils.tripPredicate``: within the trip's dates (and place)."""
    start, end = sighting.start_date, sighting.end_date
    if start is None or not after_or_equals(trip.start, start):
        return False
    if end is None or not before_or_equals(trip.end, end):
        return False
    if trip.location_xml_id is None:
        return True
    return sighting.location_xml_id in query_list.places_within(trip.location_xml_id)


def _entry_taxon(kind: str, ids: tuple[str, ...], subspecies: str | None) -> SightingTaxon:
    if kind == "ssp":
        return SightingTaxon.with_secondary_subspecies(ids[0], subspecies or "")
    if kind == "sp":
        return SightingTaxon.sp(ids)
    if kind == "hybrid":
        return SightingTaxon.hybrid(ids)
    return SightingTaxon.single(ids[0])


def _containing_code(code: str) -> str | None:
    """``TransposedChecklistSynthesizer.containingChecklistCode``."""
    if code in ("FI-01", "PG-NSA"):
        return code[:2]
    if code in _OWN_PLACES or not _STATE_CODE.fullmatch(code):
        return None
    country = code[:2]
    if country not in STATE_CHECKLIST_COUNTRIES:
        return None
    if country == "ID":
        return "ID-Australasia" if code in _INDONESIA_AUSTRALASIA_STATES else "ID-Asia"
    return country


def _pack_taxonomy_id(taxonomy: Taxonomy) -> str:
    return taxonomy.id


def _place(place: QPlace) -> _Place:
    return _Place(place.xml_id, place.name, place.type, place.code, place.ebird_code, place.parent,
                  place.built_in)  # fmt: skip

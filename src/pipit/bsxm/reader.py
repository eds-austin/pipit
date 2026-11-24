"""Read a Scythebill ``.bsxm`` file into a ``ReportSet``.

A port of Scythebill ``model/src/commonMain/kotlin/.../xml/XmlReportSetParsers.kt`` (with
the JVM checklist and extended-taxonomy hooks from ``XmlReportSetImport.kt``). Every
normalization Scythebill applies while loading is applied here too, because Pipit's export
must equal what Scythebill writes after loading the same file:

- missing location IDs become root "RESTORED LOCATION" entries; an empty location name
  is "(Unnamed)"; a duplicate sibling name gets " duplicate" (then " duplicate 1", ...);
- two-digit years become 19xx/20xx; invalid sighting times are dropped;
- sighting notes lose trailing whitespace; visit fields are trimmed, and non-positive or
  unparseable numbers are dropped;
- a visit whose protocol is unknown, or needs a start time it lacks, or misses a required
  field, becomes "historical"; fields hidden by the protocol are dropped;
- a trip's end time replaces its start time (a Scythebill bug kept for compatibility);
- unknown users referenced by sightings are created with their ID as abbreviation;
- sp. and hybrid IDs are de-duplicated and sorted; checklists for unknown locations
  and invalid links or photos are dropped; unknown elements are skipped.

Things Scythebill refuses (a missing taxon ID, any malformed date, duplicate IDs)
raise ``BsxmError``.
"""

from __future__ import annotations

from collections.abc import Callable, Container
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from pipit.domain.partial_date import PartialDate, parse_partial_date, parse_with_century_fix
from pipit.domain.report import (
    BREEDING_CODES,
    CHECKLIST_STATUS_TEXTS,
    LOCATION_TYPES,
    SIGHTING_STATUSES,
    ChecklistEntry,
    CustomChecklist,
    Link,
    Location,
    ObservationType,
    Photo,
    ReportSet,
    Sighting,
    Trip,
    User,
    Visit,
    VisitField,
    VisitKey,
)
from pipit.domain.values import (
    ApproximateNumber,
    LatLong,
    is_valid_uri,
    kotlin_int_or_none,
    normalize_file_localhost,
    parse_float32,
    parse_time,
)
from pipit.taxa.model import Taxonomy
from pipit.taxa.sighting_taxon import SightingTaxon
from pipit.taxa.xml_reader import TaxonomyFormatError, embedded_taxonomy, own_text

#: ``ReportSetVersions.VERSION_FORMAT_CURRENT``: the format Scythebill (and Pipit) write.
CURRENT_FORMAT_VERSION = "21.5.0"
DEFAULT_TAXONOMY_ID = "clements6_4"  # files from before the taxonomy attribute existed
_NOT_ELIGIBLE_ABBREVIATION = set(",/ \n")


class BsxmError(ValueError):
    """The file cannot be loaded (Scythebill would refuse it too)."""


class VersionTooNewError(BsxmError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def version_parts(version: str) -> list[int]:
    digits = "".join(c for c in version if c.isdigit() or c == ".")
    return [int(part) for part in digits.split(".") if part]


def compare_versions(left: str, right: str) -> int:
    """``compareVersions``: dotted numeric comparison; a longer prefix-equal version wins."""
    left_parts = version_parts(left)
    right_parts = version_parts(right)
    for a, b in zip(left_parts, right_parts, strict=False):
        if a != b:
            return a - b
    return len(left_parts) - len(right_parts)


@dataclass
class ReadResult:
    report: ReportSet
    warnings: list[str] = field(default_factory=list)


class _Reader:
    def __init__(
        self,
        base_taxonomy_id: str,
        base_taxon_ids: Container[str],
    ) -> None:
        self.base_taxonomy_id = base_taxonomy_id
        self.base_taxon_ids = base_taxon_ids
        self.warnings: list[str] = []
        self.locations: dict[str, Location] | None = None
        self.report = ReportSet(taxonomy_id=DEFAULT_TAXONOMY_ID)
        self.extended: dict[str, Taxonomy] = {}
        self.users: dict[str, User] = {}
        self.trips: dict[str, Trip] = {}
        self.visits: dict[VisitKey, Visit] = {}
        self.checklists: dict[str, CustomChecklist] = {}

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    # -------------------------------------------------------------- top level

    def read(self, root: Element) -> ReportSet:
        if _local(root.tag) != "report-set":
            raise BsxmError(f"not a Scythebill list: root element is <{_local(root.tag)}>")
        version = root.get("version")
        if version is not None and compare_versions(version, CURRENT_FORMAT_VERSION) > 0:
            raise VersionTooNewError(
                f"this file is version {version}; Pipit reads up to {CURRENT_FORMAT_VERSION}"
            )
        report = self.report
        report.loaded_version = version
        report.taxonomy_id = root.get("taxonomy") or DEFAULT_TAXONOMY_ID
        handlers: dict[str, Callable[[Element], None]] = {
            "taxonomy": self.read_extended_taxonomy,
            "locations": self.read_locations,
            "user": self.read_user,
            "trip": self.read_trip,
            "sighting": self.read_sighting,
            "checklist": self.read_checklist,
            "visit-info": self.read_visit,
            "prefs": self.read_prefs,
            "one-time-upgrade": self.read_one_time_upgrade,
        }
        for child in root:
            handler = handlers.get(_local(child.tag))
            if handler is None:
                self.warn(f"unknown element <{_local(child.tag)}> skipped")
            else:
                handler(child)
        if self.locations is None:
            raise BsxmError("no <locations> element")
        report.extended_taxonomies = list(self.extended.values())
        report.users = list(self.users.values())
        report.trips = list(self.trips.values())
        report.visits = list(self.visits.values())
        report.checklists = list(self.checklists.values())
        return report

    def read_prefs(self, element: Element) -> None:
        self.report.preferences_json = own_text(element)

    def read_one_time_upgrade(self, element: Element) -> None:
        name = own_text(element)
        if name not in self.report.one_time_upgrades:
            self.report.one_time_upgrades.append(name)

    def read_extended_taxonomy(self, element: Element) -> None:
        if element.get("id") is None:
            raise BsxmError("embedded <taxonomy> without an id")
        try:
            taxonomy = embedded_taxonomy(element, self.warnings)
        except (TaxonomyFormatError, KeyError) as error:
            raise BsxmError(f"embedded taxonomy {element.get('id')}: {error}") from error
        self.extended[taxonomy.id] = taxonomy

    # -------------------------------------------------------------- locations

    def read_locations(self, element: Element) -> None:
        if self.locations is not None:
            raise BsxmError("duplicate <locations> elements")
        self.locations = {}
        for child in element:
            self._read_location(child, None)

    def _read_location(self, element: Element, parent: Location | None) -> None:
        assert self.locations is not None
        tag = _local(element.tag)
        if tag == "description":
            if parent is not None:
                parent.description = own_text(element)
            return
        if tag != "location" and tag not in LOCATION_TYPES:
            self.warn(f"unknown location element <{tag}> skipped")
            return
        location_id = _required(element, "id")
        name = _required(element, "name") or "(Unnamed)"
        if parent is not None and parent.child_named(name) is not None:
            for i in range(10):
                base = name if name.endswith(" duplicate") else f"{name} duplicate"
                candidate = base if i == 0 else f"{base} {i}"
                if parent.child_named(candidate) is None:
                    name = candidate
                    break
        if location_id in self.locations:
            raise BsxmError(f"location ID {location_id} is used twice")
        location = Location(
            id=location_id,
            name=name,
            type=None if tag == "location" else tag,
            parent=parent,
            ebird_code=element.get("ebirdCode"),
            ebird_hotspot_id=element.get("ebirdLocId"),
            private=element.get("private") == "true",
        )
        latitude = element.get("lat")
        longitude = element.get("long")
        if latitude is not None and longitude is not None:
            try:
                location.lat_long = LatLong.parse(latitude, longitude)
            except ValueError:
                self.warn(f"invalid lat/long on location {location_id} ignored")
        self.locations[location_id] = location
        if parent is None:
            self.report.roots.append(location)
        else:
            parent.children.append(location)
        for child in element:
            self._read_location(child, location)

    def location_or_restored(self, location_id: str | None) -> Location | None:
        """``getOrRestoreLocation``: a missing ID becomes a placeholder root location."""
        if location_id is None:
            return None
        if self.locations is None:
            raise BsxmError("sightings or trips before <locations>")
        location = self.locations.get(location_id)
        if location is None:
            location = Location(
                id=location_id,
                name=f'RESTORED LOCATION "{location_id}"',
                type=None,
                restored=True,
            )
            self.locations[location_id] = location
            self.report.roots.append(location)
            self.warn(f"missing location {location_id} restored as a placeholder")
        return location

    # -------------------------------------------------------------- users, trips

    def read_user(self, element: Element) -> None:
        user = User(_required(element, "id"), element.get("name"), element.get("abbrev"))
        self._add_user(user)

    def _add_user(self, user: User) -> None:
        if user.abbreviation is not None and set(user.abbreviation) & _NOT_ELIGIBLE_ABBREVIATION:
            raise BsxmError(f"observer abbreviation {user.abbreviation!r} is not allowed")
        if user.name is None and user.abbreviation is None:
            raise BsxmError(f"observer {user.id} has neither a name nor an abbreviation")
        if user.id in self.users:
            raise BsxmError(f"observer ID {user.id} is used twice")
        self.users[user.id] = user

    def read_trip(self, element: Element) -> None:
        if self.locations is None:
            raise BsxmError("trips must come after locations")
        trip_id = _required(element, "id")
        if not trip_id or trip_id in self.trips:
            raise BsxmError(f"trip ID {trip_id!r} is missing or used twice")
        trip = Trip(
            id=trip_id,
            start_date=_date(_required(element, "startDate"), century_fix=False),
            end_date=_date(_required(element, "endDate"), century_fix=False),
        )
        location_id = element.get("loc")
        if location_id:
            self.location_or_restored(location_id)
            trip.location_id = location_id
        start_time = element.get("startTime")
        if start_time:
            trip.start_time = parse_time(start_time)
        end_time = element.get("endTime")
        if end_time:
            # Scythebill stores the end time as the *start* time (kept for compatibility).
            trip.start_time = parse_time(end_time)
        trip.name = element.get("name") or None
        for child in element:
            tag = _local(child.tag)
            if tag == "notes":
                trip.notes = own_text(child)
            elif tag == "link":
                link = self._link(child)
                if link is not None:
                    trip.links.append(link)
            elif tag == "photo":
                photo = self._photo(child)
                if photo is not None:
                    trip.photos.append(photo)
        self.trips[trip_id] = trip

    def _link(self, element: Element) -> Link | None:
        uri = own_text(element)
        if not is_valid_uri(uri):
            self.warn(f"invalid link {uri!r} dropped")
            return None
        return Link(normalize_file_localhost(uri), element.get("name"))

    def _photo(self, element: Element) -> Photo | None:
        uri = own_text(element)
        if not is_valid_uri(uri):
            self.warn(f"invalid photo {uri!r} dropped")
            return None
        return Photo(normalize_file_localhost(uri), element.get("name"),
                     element.get("favorite") == "true")  # fmt: skip

    # -------------------------------------------------------------- taxa

    def sighting_taxonomy(self, element: Element) -> str | None:
        taxonomy_id = element.get("taxonomy")
        if taxonomy_id is not None and taxonomy_id not in self.extended:
            raise BsxmError(f"invalid taxonomy {taxonomy_id}")
        return taxonomy_id

    def sighting_taxon(self, element: Element, taxonomy_id: str | None) -> SightingTaxon:
        taxon_id = element.get("taxon")
        if taxon_id is not None:
            if taxonomy_id is None:
                if taxon_id not in self.base_taxon_ids and taxon_id == "sspCarpo3davwal":
                    taxon_id = "sspCarpo3eoswal"  # Scythebill 10.2.0 renamed it without a rule
                if taxon_id not in self.base_taxon_ids:
                    raise BsxmError(f"unknown taxon {taxon_id}")
            elif self.extended[taxonomy_id].get(taxon_id) is None:
                raise BsxmError(f"unknown taxon {taxon_id} in {taxonomy_id}")
            return SightingTaxon.single(taxon_id)
        for attribute, factory in (("sp", SightingTaxon.sp), ("hybrid", SightingTaxon.hybrid)):
            value = element.get(attribute)
            if value is not None:
                try:
                    return factory(value.split(","))
                except ValueError as error:
                    raise BsxmError(f"invalid {attribute} {value!r}: {error}") from error
        with_ssp = element.get("taxonSsp")
        if with_ssp is None:
            raise BsxmError("none of the taxon, sp, hybrid or taxonSsp attributes")
        parts = with_ssp.split("|")
        if len(parts) != 2:
            raise BsxmError(f"invalid taxonSsp {with_ssp!r}")
        return SightingTaxon.with_secondary_subspecies(parts[0], parts[1])

    # -------------------------------------------------------------- sightings

    def read_sighting(self, element: Element) -> None:  # noqa: PLR0915
        if self.locations is None:
            raise BsxmError("<sighting> before <locations>")
        location = self.location_or_restored(element.get("loc"))
        taxonomy_id = self.sighting_taxonomy(element)
        sighting = Sighting(
            taxon=self.sighting_taxon(element, taxonomy_id),
            taxonomy_id=taxonomy_id,
            location_id=location.id if location else None,
        )
        date_text = element.get("date")
        if date_text is not None:
            sighting.date = _date(date_text, century_fix=True)  # Scythebill refuses bad dates
        time_text = element.get("time")
        if time_text is not None:
            sighting.time = parse_time(time_text)
        trip_id = element.get("trip")
        if trip_id is not None:
            if trip_id in self.trips:
                sighting.trip_id = trip_id
            else:
                self.warn(f"could not find trip {trip_id}")
        count = element.get("count")
        if count is not None:
            sighting.count = ApproximateNumber.parse(count)
        sighting.male = element.get("male") == "true"
        sighting.female = element.get("female") == "true"
        sighting.immature = element.get("immature") == "true"
        sighting.adult = element.get("adult") == "true"
        sighting.photographed = element.get("photo") == "true"
        sighting.heard_only = element.get("heardOnly") == "true"
        status = element.get("popStatus")
        if status is not None:
            if status in SIGHTING_STATUSES:
                sighting.status = status
            else:
                self.warn(f"invalid sighting status {status!r}")
        breeding = element.get("breeding")
        if breeding is not None:
            if breeding in BREEDING_CODES:
                sighting.breeding = breeding
            else:
                self.warn(f"invalid breeding code {breeding!r}")
        users = element.get("users")
        if users is not None:
            for user_id in users.split(","):
                if user_id not in self.users:
                    self._add_user(User(user_id, None, user_id))
                if user_id not in sighting.users:
                    sighting.users.append(user_id)
        text_parts = [element.text or ""]
        for child in element:
            text_parts.append(child.tail or "")
            if _local(child.tag) == "photo":
                photo = self._photo(child)
                if photo is not None:
                    sighting.photos.append(photo)
        if any(text_parts) or element.text is not None:
            sighting.description = "".join(text_parts).rstrip()
        self.report.sightings.append(sighting)

    # -------------------------------------------------------------- visits

    def read_visit(self, element: Element) -> None:
        location_id = _required(element, "loc")
        if self.locations is None or location_id not in self.locations:
            self.warn(f"visit at unknown location {location_id}")
        date = _date(_required(element, "date"), century_fix=True)
        time_text = element.get("time")
        start_time = parse_time(time_text) if time_text else None
        key = VisitKey(location_id, date, start_time)
        type_id = _required(element, "observationType")
        observation_type = ObservationType.from_id(type_id)
        if observation_type is None:
            self.warn(f"unknown observation type {type_id!r}; historical used")
            observation_type = ObservationType.HISTORICAL
        if start_time is None and VisitField.START_TIME in observation_type.required:
            observation_type = ObservationType.HISTORICAL
        visit = Visit(key, observation_type)
        for child in element:
            tag = _local(child.tag)
            if tag == "photo":
                photo = self._photo(child)
                if photo is not None:
                    visit.photos.append(photo)
                continue
            if tag == "complete":
                visit.complete = True
                continue
            text = own_text(child).strip()
            if tag == "area":
                area = parse_float32(text)
                if area is not None and area > 0:
                    visit.area_hectares = area
            elif tag == "distance":
                distance = parse_float32(text)
                if distance is not None and distance > 0:
                    visit.distance_km = distance
            elif tag == "duration":
                minutes = kotlin_int_or_none(text)
                if minutes is not None and minutes > 0:
                    visit.duration_minutes = minutes
            elif tag == "partySize":
                party = kotlin_int_or_none(text)
                if party is not None and party > 0:
                    visit.party_size = party
            elif tag == "comments" and text:
                visit.comments = text
        self.visits[key] = _apply_field_rules(visit)

    # -------------------------------------------------------------- checklists

    def read_checklist(self, element: Element) -> None:
        location_id = _required(element, "loc")
        known = self.locations is not None and location_id in self.locations
        if not known:
            self.warn(f"checklist for unknown location {location_id} dropped")
        entries: dict[SightingTaxon, str | None] = {}
        for child in element:
            if _local(child.tag) != "entry":
                continue
            taxon = self.sighting_taxon(child, self.sighting_taxonomy(child))
            status = child.get("status")
            entries[taxon] = status if status in CHECKLIST_STATUS_TEXTS else None
        if known:
            self.checklists[location_id] = CustomChecklist(
                location_id, [ChecklistEntry(taxon, status) for taxon, status in entries.items()]
            )


def _apply_field_rules(visit: Visit) -> Visit:
    """``VisitInfo`` construction: a missing required field fails the build, and the
    parser retries as "historical" with every value kept (historical requires and hides
    nothing); otherwise fields hidden by the protocol are dropped."""
    required = visit.observation_type.required
    missing = (
        (VisitField.AREA in required and visit.area_hectares is None)
        or (VisitField.DURATION in required and visit.duration_minutes is None)
        or (VisitField.DISTANCE in required and visit.distance_km is None)
        or (VisitField.PARTY_SIZE in required and visit.party_size is None)
    )
    if missing:
        visit.observation_type = ObservationType.HISTORICAL
        return visit
    hidden = visit.observation_type.hidden
    if VisitField.AREA in hidden:
        visit.area_hectares = None
    if VisitField.DURATION in hidden:
        visit.duration_minutes = None
    if VisitField.DISTANCE in hidden:
        visit.distance_km = None
    if VisitField.PARTY_SIZE in hidden:
        visit.party_size = None
    return visit


def _required(element: Element, name: str) -> str:
    value = element.get(name)
    if value is None:
        raise BsxmError(f"<{_local(element.tag)}> is missing its {name} attribute")
    return value


def _date(text: str, century_fix: bool) -> PartialDate:
    try:
        return parse_with_century_fix(text) if century_fix else parse_partial_date(text)
    except ValueError as error:
        raise BsxmError(str(error)) from error


def read_bsxm(
    source: Path | bytes,
    base_taxonomy_id: str,
    base_taxon_ids: Container[str],
) -> ReadResult:
    """Parse a ``.bsxm`` file (path or bytes)."""
    data = source.read_bytes() if isinstance(source, Path) else source
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise BsxmError(f"not well-formed XML: {error}") from error
    reader = _Reader(base_taxonomy_id, base_taxon_ids)
    report = reader.read(root)
    return ReadResult(report, reader.warnings)

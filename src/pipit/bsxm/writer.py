"""Write a ``ReportSet`` as a ``.bsxm`` file, byte for byte as Scythebill writes it.

Ports Scythebill ``model/src/jvmMain/.../io/XmlResponseWriter.java`` and
``IndentingResponseWriter.java`` (two-space indentation, every character from U+007F up
as a lowercase hex reference, invalid control characters dropped, empty elements
self-closed, no newline after the root), ``xml/XmlReportSetExport.java`` (element and
attribute order) and ``xml/XmlTaxonExport.kt`` with ``ExtendedTaxonomyParsing.java``
(embedded taxonomies and their checklist codes).

Lines end with "\\n" (Scythebill uses the platform separator; this matches Linux/macOS).
"""

from __future__ import annotations

from pipit.domain.partial_date import format_partial_date
from pipit.domain.report import Location, Photo, ReportSet, Sighting, Trip, Visit
from pipit.domain.values import format_time, java_float_to_string, round_three_digits
from pipit.taxa.model import Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType
from pipit.taxa.xml_reader import NAMESPACE

from .reader import CURRENT_FORMAT_VERSION

_MAX_INDENT = 50
_INVALID_LOW = {*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20)}


def _escape(text: str, quote: bool) -> str:
    out = []
    for character in text:
        code = ord(character)
        if code < 0x7F:
            if character == ">":
                out.append("&gt;")
            elif character == "<":
                out.append("&lt;")
            elif character == "&":
                out.append("&amp;")
            elif character == '"' and quote:
                out.append("&quot;")
            elif character == "\t":
                out.append("&#x9;")
            elif code not in _INVALID_LOW:
                out.append(character)
        else:
            out.append(f"&#x{code:x};")
    return "".join(out)


class XmlOut:
    """``IndentingResponseWriter`` over ``XmlResponseWriter``."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._close_start = False
        self._depth = 0
        self._just_ended = False

    def start_document(self) -> None:
        self._parts.append('<?xml version="1.0" encoding="UTF-8"?>\n')

    def _close(self) -> None:
        if self._close_start:
            self._parts.append(">")
            self._close_start = False

    def _indent(self, depth: int) -> None:
        self._close()
        self._parts.append("\n")
        spaces = min(depth * 2, _MAX_INDENT)
        if spaces:
            self._parts.append(" " * spaces)

    def _after_end(self) -> None:
        if self._just_ended:
            self._just_ended = False
            self._indent(self._depth)

    def start(self, name: str) -> None:
        depth = self._depth
        self._depth += 1
        if depth > 0:
            self._indent(depth)
        self._just_ended = False
        self._close()
        self._parts.append("<" + name)
        self._close_start = True

    def attribute(self, name: str, value: str | int | bool | None) -> None:
        if value is None:
            return
        if isinstance(value, bool):
            value = "true" if value else "false"
        self._parts.append(f' {name}="{_escape(str(value), quote=True)}"')

    def text(self, value: str | int | None) -> None:
        self._after_end()
        if value is None:
            return
        text = str(value)
        if text:
            self._close()
            self._parts.append(_escape(text, quote=False))

    def end(self, name: str) -> None:
        self._depth -= 1
        self._after_end()
        if self._close_start:
            self._parts.append("/>")
            self._close_start = False
        else:
            self._parts.append(f"</{name}>")
        self._just_ended = True

    def element(self, name: str, text: str | int | None) -> None:
        self.start(name)
        self.text(text)
        self.end(name)

    def getvalue(self) -> str:
        return "".join(self._parts)


# ------------------------------------------------------------------ report set


def write_bsxm(report: ReportSet) -> bytes:
    out = XmlOut()
    out.start_document()
    out.start("report-set")
    out.attribute("version", CURRENT_FORMAT_VERSION)
    out.attribute("taxonomy", report.taxonomy_id)
    for taxonomy in report.extended_taxonomies:
        write_taxonomy(out, taxonomy)
    out.start("locations")
    for root in report.roots:
        _write_location(out, root)
    out.end("locations")
    for user in report.users:
        out.start("user")
        out.attribute("id", user.id)
        out.attribute("name", user.name)
        out.attribute("abbrev", user.abbreviation)
        out.end("user")
    for trip in report.trips:
        _write_trip(out, trip)
    for sighting in report.sightings:
        _write_sighting(out, sighting)
    for checklist in report.checklists:
        out.start("checklist")
        out.attribute("loc", checklist.location_id)
        for entry in checklist.entries:
            out.start("entry")
            _write_sighting_taxon(out, entry.taxon)
            out.attribute("status", entry.status)
            out.end("entry")
        out.end("checklist")
    for visit in report.visits:
        _write_visit(out, visit)
    if report.preferences_json:
        out.element("prefs", report.preferences_json)
    for name in report.one_time_upgrades:
        out.element("one-time-upgrade", name)
    out.end("report-set")
    return out.getvalue().encode("utf-8")


def _write_location(out: XmlOut, location: Location) -> None:
    element = location.type or "location"
    out.start(element)
    out.attribute("id", location.id)
    out.attribute("name", location.name)
    if location.ebird_code:
        out.attribute("ebirdCode", location.ebird_code)
    if location.ebird_hotspot_id:
        out.attribute("ebirdLocId", location.ebird_hotspot_id)
    if location.lat_long is not None:
        out.attribute("lat", location.lat_long.latitude)
        out.attribute("long", location.lat_long.longitude)
    if location.private:
        out.attribute("private", True)
    if location.description is not None:
        out.element("description", location.description)
    for child in location.children:
        _write_location(out, child)
    out.end(element)


def _write_trip(out: XmlOut, trip: Trip) -> None:
    out.start("trip")
    out.attribute("id", trip.id)
    out.attribute("loc", trip.location_id)
    out.attribute("startDate", format_partial_date(trip.start_date))
    if trip.start_time is not None:
        out.attribute("startTime", format_time(trip.start_time))
    out.attribute("endDate", format_partial_date(trip.end_date))
    # The end time is never kept (see the reader), so it is never written.
    if trip.name:
        out.attribute("name", trip.name)
    if trip.notes:
        out.element("notes", trip.notes)
    for link in trip.links:
        out.start("link")
        out.attribute("name", link.name)
        out.text(link.uri)
        out.end("link")
    for photo in trip.photos:
        _write_photo(out, photo)
    out.end("trip")


def _write_photo(out: XmlOut, photo: Photo) -> None:
    out.start("photo")
    if photo.favorite:
        out.attribute("favorite", True)
    out.attribute("name", photo.name)
    out.text(photo.uri)
    out.end("photo")


def _write_sighting_taxon(out: XmlOut, taxon: SightingTaxon) -> None:
    if taxon.type is SightingTaxonType.SINGLE:
        out.attribute("taxon", taxon.id)
    elif taxon.type is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
        out.attribute("taxonSsp", f"{taxon.id}|{taxon.subspecies}")
    elif taxon.type is SightingTaxonType.SP:
        out.attribute("sp", ",".join(taxon.ids))
    else:
        out.attribute("hybrid", ",".join(taxon.ids))


def _write_sighting(out: XmlOut, sighting: Sighting) -> None:
    out.start("sighting")
    out.attribute("taxonomy", sighting.taxonomy_id)
    _write_sighting_taxon(out, sighting.taxon)
    out.attribute("loc", sighting.location_id)
    if sighting.date is not None:
        out.attribute("date", format_partial_date(sighting.date))
    if sighting.time is not None:
        out.attribute("time", format_time(sighting.time))
    out.attribute("trip", sighting.trip_id)
    if sighting.count is not None:
        out.attribute("count", str(sighting.count))
    flags = (
        ("male", sighting.male),
        ("female", sighting.female),
        ("immature", sighting.immature),
        ("adult", sighting.adult),
        ("heardOnly", sighting.heard_only),
        ("photo", sighting.photographed),
    )
    for name, flag in flags:
        if flag:
            out.attribute(name, True)
    if sighting.status != "none":
        out.attribute("popStatus", sighting.status)
    if sighting.breeding:
        out.attribute("breeding", sighting.breeding)
    if sighting.users:
        out.attribute("users", ",".join(sighting.users))
    out.text(sighting.description)
    for photo in sighting.photos:
        _write_photo(out, photo)
    out.end("sighting")


def _write_visit(out: XmlOut, visit: Visit) -> None:
    out.start("visit-info")
    out.attribute("loc", visit.key.location_id)
    out.attribute("date", format_partial_date(visit.key.date))
    if visit.key.start_time is not None:
        out.attribute("time", format_time(visit.key.start_time))
    out.attribute("observationType", visit.observation_type.type_id)
    if visit.area_hectares is not None:
        out.element("area", java_float_to_string(round_three_digits(visit.area_hectares)))
    if visit.distance_km is not None:
        out.element("distance", java_float_to_string(round_three_digits(visit.distance_km)))
    if visit.duration_minutes is not None and visit.duration_minutes > 0:
        out.element("duration", visit.duration_minutes)
    if visit.party_size is not None:
        out.element("partySize", visit.party_size)
    if visit.comments is not None:
        out.element("comments", visit.comments)
    if visit.complete:
        out.start("complete")
        out.end("complete")
    for photo in visit.photos:
        _write_photo(out, photo)
    out.end("visit-info")


# ------------------------------------------------------------------ taxonomies

_STATUS_SUFFIXES = {
    "I": "I", "P": "P", "ES": "ES", "EX": "EX", "R": "R", "V": "R", "RI": "RI", "E": "E",
}  # fmt: skip


def normalized_checklist_codes(taxon: Taxon) -> list[str]:
    """An extended taxon's ``<checklists>`` codes as Scythebill re-writes them: each
    code's status suffix parsed ("(V)" is a rarity, unknown is native), extinct species
    (IUCN EX/EW) forced to "(EX)", a lone native code made endemic "(E)", "ID" and "RU"
    split into their Asian and other parts, then sorted (``ExtendedTaxonomyChecklists``,
    ``ExtendedTaxonomyParsing``)."""
    if taxon.checklists is None:
        return []
    codes = taxon.checklists.split(",")
    extinct = taxon.status in ("EX", "EW")
    statuses: dict[str, str] = {}
    for code_with_status in codes:
        location, status = _location_and_status(code_with_status)
        if extinct:
            status = "EX"
        elif status == "" and len(codes) == 1:
            status = "E"
        expanded = {"ID": ["ID-Asia", "ID-Australasia"], "RU": ["RU-Europe", "RU-Asia"]}
        for code in expanded.get(location, [location]):
            statuses[code] = status
    return sorted(code + (f"({status})" if status else "") for code, status in statuses.items())


def _location_and_status(code_with_status: str) -> tuple[str, str]:
    """``locationAndStatus``: "XX(I)" -> ("XX", "I"); regex ``(.*)\\((.*)\\)``."""
    if code_with_status.endswith(")"):
        open_paren = code_with_status.rfind("(", 0, len(code_with_status) - 1)
        # Greedy (.*): the *last* "(" that leaves a closing ")" at the end.
        if open_paren >= 0:
            status = code_with_status[open_paren + 1 : -1]
            return code_with_status[:open_paren], _STATUS_SUFFIXES.get(status, "")
    return code_with_status, ""


def write_taxonomy(out: XmlOut, taxonomy: Taxonomy) -> None:
    out.start("taxonomy")
    out.attribute("xmlns", NAMESPACE)
    out.attribute("id", taxonomy.id)
    out.attribute("name", taxonomy.name)
    out.attribute("accountUrlFormat", taxonomy.account_url_format)
    out.attribute("accountLinkTitle", taxonomy.account_link_title)
    for credit in taxonomy.additional_credits:
        out.element("additional-credit", credit)
    if taxonomy.root is not None:
        _write_taxon(out, taxonomy.root)
    out.end("taxonomy")


def _write_taxon(out: XmlOut, taxon: Taxon) -> None:
    element = taxon.type.xml_name
    out.start(element)
    out.attribute("name", taxon.name)
    out.attribute("id", taxon.id)
    out.attribute("accountId", taxon.account_id)
    out.attribute("conceptId", taxon.concept_id)
    if taxon.common_name is not None:
        out.element("common-name", taxon.common_name)
    if taxon.type <= TaxonType.SPECIES:
        if _has_metadata(taxon):
            out.start("metadata")
            if taxon.status != "LC":
                out.element("status", taxon.status)
            if taxon.range:
                out.element("range", taxon.range)
            if taxon.taxonomic_info:
                out.element("taxonomy", taxon.taxonomic_info)
            for name in taxon.alternate_names:
                out.element("alternate-names", name)
            for name in taxon.alternate_common_names:
                out.element("alternate-common-names", name)
            if taxon.miscellaneous:
                out.element("miscellaneous", taxon.miscellaneous)
            out.end("metadata")
        codes = normalized_checklist_codes(taxon)
        if codes:
            out.element("checklists", ",".join(codes))
    for child in taxon.children:
        _write_taxon(out, child)
    out.end(element)


def _has_metadata(taxon: Taxon) -> bool:
    return (
        taxon.status != "LC"
        or taxon.range is not None
        or taxon.taxonomic_info is not None
        or bool(taxon.alternate_names)
        or bool(taxon.alternate_common_names)
        or taxon.miscellaneous is not None
    )

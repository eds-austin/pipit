"""Store a whole ``ReportSet`` in a list database, and read it back unchanged.

``load_report(save_report(x)) == x`` field for field and order for order; the importer
checks this on every import by exporting both and comparing bytes.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import time

from pipit.domain.partial_date import PartialDate, format_partial_date, parse_partial_date
from pipit.domain.report import (
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
    VisitKey,
)
from pipit.domain.values import ApproximateNumber, LatLong, format_time, parse_time
from pipit.taxa.model import Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon, SightingTaxonType

_KIND = {
    SightingTaxonType.SINGLE: "single",
    SightingTaxonType.SP: "sp",
    SightingTaxonType.HYBRID: "hybrid",
    SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES: "ssp",
}
_TYPE = {kind: taxon_type for taxon_type, kind in _KIND.items()}


def _date_text(date: PartialDate | None) -> tuple[str | None, int | None, int | None, int | None]:
    if date is None:
        return None, None, None, None
    return format_partial_date(date), date.year, date.month, date.day


def _time_text(value: time | None) -> str | None:
    return None if value is None else format_time(value)


def _time(text: str | None) -> time | None:
    if not text:
        return None
    parsed = parse_time(text)
    if parsed is None:
        raise ValueError(f"stored time {text!r} is invalid")
    return parsed


def _taxon(kind: str, ids: list[str], subspecies: str | None) -> SightingTaxon:
    taxon_type = _TYPE[kind]
    if taxon_type is SightingTaxonType.SINGLE:
        return SightingTaxon.single(ids[0])
    if taxon_type is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
        assert subspecies is not None
        return SightingTaxon.with_secondary_subspecies(ids[0], subspecies)
    return SightingTaxon(taxon_type, tuple(ids))


# ------------------------------------------------------------------ save


def save_report(connection: sqlite3.Connection, report: ReportSet) -> None:
    """Write ``report`` into an empty list database (inside the caller's transaction)."""
    if connection.execute("SELECT 1 FROM locations LIMIT 1").fetchone():
        raise ValueError("the list is not empty")
    connection.executemany(
        "INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [("taxonomy_id", report.taxonomy_id), ("loaded_version", report.loaded_version or "")],
    )
    for order, taxonomy in enumerate(report.extended_taxonomies):
        _save_taxonomy(connection, taxonomy, order)
    _save_locations(connection, report)
    connection.executemany(
        "INSERT INTO users(xml_id, name, abbreviation, ord) VALUES (?, ?, ?, ?)",
        [(u.id, u.name, u.abbreviation, i) for i, u in enumerate(report.users)],
    )
    for order, trip in enumerate(report.trips):
        cursor = connection.execute(
            "INSERT INTO trips(xml_id, location_xml_id, start_date, end_date, start_time, "
            "name, notes, ord) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (trip.id, trip.location_id, format_partial_date(trip.start_date),
             format_partial_date(trip.end_date), _time_text(trip.start_time), trip.name,
             trip.notes, order),
        )  # fmt: skip
        trip_row = cursor.lastrowid
        connection.executemany(
            "INSERT INTO links(trip_id, ord, uri, name) VALUES (?, ?, ?, ?)",
            [(trip_row, i, link.uri, link.name) for i, link in enumerate(trip.links)],
        )
        _save_photos(connection, "trip_id", trip_row, trip.photos)
    _save_sightings(connection, report.sightings)
    for order, visit in enumerate(report.visits):
        date, year, month, day = _date_text(visit.key.date)
        cursor = connection.execute(
            "INSERT INTO visits(ord, location_xml_id, date, date_y, date_m, date_d, start_time, "
            "observation_type, area_hectares, distance_km, duration_minutes, party_size, "
            "comments, complete) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order, visit.key.location_id, date, year, month, day,
             _time_text(visit.key.start_time) or "", visit.observation_type.type_id,
             _float_text(visit.area_hectares), _float_text(visit.distance_km),
             visit.duration_minutes, visit.party_size, visit.comments, int(visit.complete)),
        )  # fmt: skip
        _save_photos(connection, "visit_id", cursor.lastrowid, visit.photos)
    for order, checklist in enumerate(report.checklists):
        cursor = connection.execute(
            "INSERT INTO checklists(location_xml_id, ord) VALUES (?, ?)",
            (checklist.location_id, order),
        )
        connection.executemany(
            "INSERT INTO checklist_entries(checklist_id, ord, kind, taxon_ids, subspecies, "
            "status) VALUES (?, ?, ?, ?, ?, ?)",
            [(cursor.lastrowid, i, _KIND[entry.taxon.type], ",".join(entry.taxon.ids),
              entry.taxon.subspecies, entry.status)
             for i, entry in enumerate(checklist.entries)],
        )  # fmt: skip
    connection.execute("INSERT INTO report_prefs VALUES (1, ?)", (report.preferences_json,))
    connection.executemany(
        "INSERT INTO one_time_upgrades(ord, name) VALUES (?, ?)",
        list(enumerate(report.one_time_upgrades)),
    )


def _float_text(value: float | None) -> str | None:
    return None if value is None else repr(value)


def _save_taxonomy(connection: sqlite3.Connection, taxonomy: Taxonomy, order: int) -> None:
    connection.execute(
        "INSERT INTO ext_taxonomies(taxonomy_id, name, account_url_format, account_link_title, "
        "credits, ord) VALUES (?, ?, ?, ?, ?, ?)",
        (taxonomy.id, taxonomy.name, taxonomy.account_url_format, taxonomy.account_link_title,
         json.dumps(taxonomy.additional_credits, ensure_ascii=False), order),
    )  # fmt: skip
    rows = []
    for position, taxon in enumerate(taxonomy.walk()):
        rows.append(
            (taxonomy.id, taxon.id, taxon.parent.id if taxon.parent else None,
             taxon.type.xml_name, taxon.name, taxon.common_name, taxon.account_id,
             taxon.concept_id, taxon.status, taxon.range, taxon.taxonomic_info,
             taxon.miscellaneous, json.dumps(taxon.alternate_names, ensure_ascii=False),
             json.dumps(taxon.alternate_common_names, ensure_ascii=False), taxon.checklists,
             position)
        )  # fmt: skip
    connection.executemany(
        "INSERT INTO ext_taxa(taxonomy_id, taxon_id, parent_taxon_id, rank, name, common_name, "
        "account_id, concept_id, status, range, taxonomic_info, miscellaneous, alternate_names, "
        "alternate_common_names, checklists, ord) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _save_locations(connection: sqlite3.Connection, report: ReportSet) -> None:
    row_ids: dict[int, int] = {}

    def save(location: Location, order: int) -> None:
        parent_row = row_ids[id(location.parent)] if location.parent is not None else None
        lat_long = location.lat_long
        cursor = connection.execute(
            "INSERT INTO locations(xml_id, parent_id, ord, type, name, ebird_code, "
            "ebird_hotspot_id, latitude, longitude, private, description, restored) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (location.id, parent_row, order, location.type, location.name, location.ebird_code,
             location.ebird_hotspot_id, lat_long.latitude if lat_long else None,
             lat_long.longitude if lat_long else None, int(location.private),
             location.description, int(location.restored)),
        )  # fmt: skip
        assert cursor.lastrowid is not None
        row_ids[id(location)] = cursor.lastrowid
        for child_order, child in enumerate(location.children):
            save(child, child_order)

    for order, root in enumerate(report.roots):
        save(root, order)


def _save_photos(
    connection: sqlite3.Connection, owner: str, owner_row: int | None, photos: list[Photo]
) -> None:
    connection.executemany(
        f"INSERT INTO photos({owner}, ord, uri, name, favorite) VALUES (?, ?, ?, ?, ?)",
        [(owner_row, i, p.uri, p.name, int(p.favorite)) for i, p in enumerate(photos)],
    )


def _save_sightings(connection: sqlite3.Connection, sightings: list[Sighting]) -> None:
    rows = []
    for order, s in enumerate(sightings):
        date, year, month, day = _date_text(s.date)
        single = s.taxon.type in (
            SightingTaxonType.SINGLE, SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES
        )  # fmt: skip
        rows.append(
            (order, order, s.taxonomy_id, _KIND[s.taxon.type],
             s.taxon.ids[0] if single else None, s.taxon.subspecies, s.location_id, date, year,
             month, day, _time_text(s.time), s.trip_id,
             None if s.count is None else str(s.count), int(s.male), int(s.female),
             int(s.immature), int(s.adult), int(s.heard_only), int(s.photographed), s.status,
             s.breeding, s.description)
        )  # fmt: skip
    # Row IDs follow file order (ord + 1), so child rows can refer to them directly.
    base = _next_rowid(connection, "sightings")
    connection.executemany(
        "INSERT INTO sightings(id, ord, taxonomy_id, kind, taxon_id, subspecies, "
        "location_xml_id, date, date_y, date_m, date_d, time, trip_xml_id, count, male, female, "
        "immature, adult, heard_only, photographed, status, breeding, description) VALUES "
        "(? + ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(base, *row) for row in rows],
    )
    taxa: list[tuple[int, int, str]] = []
    users: list[tuple[int, int, str]] = []
    photos: list[tuple[int, int, str, str | None, int]] = []
    for order, s in enumerate(sightings):
        row = base + order
        if s.taxon.type in (SightingTaxonType.SP, SightingTaxonType.HYBRID):
            taxa.extend((row, i, taxon_id) for i, taxon_id in enumerate(s.taxon.ids))
        users.extend((row, i, user_id) for i, user_id in enumerate(s.users))
        photos.extend((row, i, p.uri, p.name, int(p.favorite)) for i, p in enumerate(s.photos))
    connection.executemany(
        "INSERT INTO sighting_taxa(sighting_id, ord, taxon_id) VALUES (?, ?, ?)", taxa
    )
    connection.executemany(
        "INSERT INTO sighting_users(sighting_id, ord, user_xml_id) VALUES (?, ?, ?)", users
    )
    connection.executemany(
        "INSERT INTO photos(sighting_id, ord, uri, name, favorite) VALUES (?, ?, ?, ?, ?)",
        photos,
    )


def _next_rowid(connection: sqlite3.Connection, table: str) -> int:
    highest = connection.execute(f"SELECT max(id) FROM {table}").fetchone()[0]
    return (highest or 0) + 1


# ------------------------------------------------------------------ load


def _meta(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def load_report(connection: sqlite3.Connection) -> ReportSet:
    taxonomy_id = _meta(connection, "taxonomy_id")
    if taxonomy_id is None:
        raise ValueError("the list has no taxonomy recorded")
    report = ReportSet(taxonomy_id, _meta(connection, "loaded_version") or None)
    report.extended_taxonomies = _load_taxonomies(connection)
    report.roots = _load_locations(connection)
    report.users = [
        User(xml_id, name, abbreviation)
        for xml_id, name, abbreviation in connection.execute(
            "SELECT xml_id, name, abbreviation FROM users ORDER BY ord"
        )
    ]
    photos = _load_photos(connection)
    links: dict[int, list[Link]] = defaultdict(list)
    for trip_row, uri, name in connection.execute(
        "SELECT trip_id, uri, name FROM links ORDER BY trip_id, ord"
    ):
        links[trip_row].append(Link(uri, name))
    for row, xml_id, location_id, start, end, start_time, name, notes in connection.execute(
        "SELECT id, xml_id, location_xml_id, start_date, end_date, start_time, name, notes "
        "FROM trips ORDER BY ord"
    ):
        report.trips.append(
            Trip(xml_id, parse_partial_date(start), parse_partial_date(end), location_id,
                 _time(start_time), name, notes, links[row], photos["trip_id"][row])
        )  # fmt: skip
    report.sightings = _load_sightings(connection, photos["sighting_id"])
    for (row, location_id, date, start_time, type_id, area, distance, duration, party,
         comments, complete) in connection.execute(
        "SELECT id, location_xml_id, date, start_time, observation_type, area_hectares, "
        "distance_km, duration_minutes, party_size, comments, complete FROM visits ORDER BY ord"
    ):  # fmt: skip
        observation_type = ObservationType.from_id(type_id)
        if observation_type is None:
            raise ValueError(f"stored observation type {type_id!r} is invalid")
        report.visits.append(
            Visit(VisitKey(location_id, parse_partial_date(date), _time(start_time)),
                  observation_type, None if area is None else float(area),
                  None if distance is None else float(distance), duration, party, comments,
                  bool(complete), photos["visit_id"][row])
        )  # fmt: skip
    entries: dict[int, list[ChecklistEntry]] = defaultdict(list)
    for checklist_row, kind, ids, subspecies, status in connection.execute(
        "SELECT checklist_id, kind, taxon_ids, subspecies, status FROM checklist_entries "
        "ORDER BY checklist_id, ord"
    ):
        entries[checklist_row].append(
            ChecklistEntry(_taxon(kind, ids.split(","), subspecies), status)
        )
    report.checklists = [
        CustomChecklist(location_id, entries[row])
        for row, location_id in connection.execute(
            "SELECT id, location_xml_id FROM checklists ORDER BY ord"
        )
    ]
    prefs = connection.execute("SELECT json FROM report_prefs WHERE id = 1").fetchone()
    report.preferences_json = prefs[0] if prefs else None
    report.one_time_upgrades = [
        name for (name,) in connection.execute("SELECT name FROM one_time_upgrades ORDER BY ord")
    ]
    return report


def _load_taxonomies(connection: sqlite3.Connection) -> list[Taxonomy]:
    taxonomies = []
    for taxonomy_id, name, url_format, link_title, credits in connection.execute(
        "SELECT taxonomy_id, name, account_url_format, account_link_title, credits "
        "FROM ext_taxonomies ORDER BY ord"
    ):
        taxonomy = Taxonomy(taxonomy_id, name, url_format, link_title)
        taxonomy.additional_credits = json.loads(credits)
        for (taxon_id, parent_id, rank, taxon_name, common, account, concept, status, range_text,
             info, misc, alternates, alternate_commons, checklists) in connection.execute(
            "SELECT taxon_id, parent_taxon_id, rank, name, common_name, account_id, concept_id, "
            "status, range, taxonomic_info, miscellaneous, alternate_names, "
            "alternate_common_names, checklists FROM ext_taxa WHERE taxonomy_id = ? ORDER BY ord",
            (taxonomy_id,),
        ):  # fmt: skip
            parent = taxonomy[parent_id] if parent_id is not None else None
            taxon: Taxon = taxonomy.add(taxon_id, TaxonType.from_xml_name(rank), taxon_name, parent)
            taxon.common_name = common
            taxon.account_id = account
            taxon.concept_id = concept
            taxon.status = status
            taxon.range = range_text
            taxon.taxonomic_info = info
            taxon.miscellaneous = misc
            taxon.alternate_names = json.loads(alternates)
            taxon.alternate_common_names = json.loads(alternate_commons)
            taxon.checklists = checklists
        taxonomies.append(taxonomy)
    return taxonomies


def _load_locations(connection: sqlite3.Connection) -> list[Location]:
    by_row: dict[int, Location] = {}
    roots: list[Location] = []
    pending: list[tuple[int | None, int, Location]] = []
    for (row, xml_id, parent_row, order, location_type, name, code, hotspot, latitude,
         longitude, private, description, restored) in connection.execute(
        "SELECT id, xml_id, parent_id, ord, type, name, ebird_code, ebird_hotspot_id, latitude, "
        "longitude, private, description, restored FROM locations"
    ):  # fmt: skip
        location = Location(
            id=xml_id, name=name, type=location_type, ebird_code=code,
            ebird_hotspot_id=hotspot,
            lat_long=LatLong(latitude, longitude) if latitude is not None else None,
            private=bool(private), description=description, restored=bool(restored),
        )  # fmt: skip
        by_row[row] = location
        pending.append((parent_row, order, location))
    for parent_row, _order, location in sorted(pending, key=lambda item: item[1]):
        if parent_row is None:
            roots.append(location)
        else:
            parent = by_row[parent_row]
            location.parent = parent
            parent.children.append(location)
    return roots


def _load_photos(connection: sqlite3.Connection) -> dict[str, dict[int, list[Photo]]]:
    photos: dict[str, dict[int, list[Photo]]] = {
        owner: defaultdict(list) for owner in ("sighting_id", "trip_id", "visit_id")
    }
    for sighting_row, trip_row, visit_row, uri, name, favorite in connection.execute(
        "SELECT sighting_id, trip_id, visit_id, uri, name, favorite FROM photos ORDER BY ord"
    ):
        photo = Photo(uri, name, bool(favorite))
        if sighting_row is not None:
            photos["sighting_id"][sighting_row].append(photo)
        elif trip_row is not None:
            photos["trip_id"][trip_row].append(photo)
        else:
            photos["visit_id"][visit_row].append(photo)
    return photos


def _load_sightings(
    connection: sqlite3.Connection, photos: dict[int, list[Photo]]
) -> list[Sighting]:
    taxa: dict[int, list[str]] = defaultdict(list)
    for sighting_row, taxon_id in connection.execute(
        "SELECT sighting_id, taxon_id FROM sighting_taxa ORDER BY sighting_id, ord"
    ):
        taxa[sighting_row].append(taxon_id)
    users: dict[int, list[str]] = defaultdict(list)
    for sighting_row, user_id in connection.execute(
        "SELECT sighting_id, user_xml_id FROM sighting_users ORDER BY sighting_id, ord"
    ):
        users[sighting_row].append(user_id)
    sightings = []
    for (row, taxonomy_id, kind, taxon_id, subspecies, location_id, date, time_text, trip_id,
         count, male, female, immature, adult, heard_only, photographed, status, breeding,
         description) in connection.execute(
        "SELECT id, taxonomy_id, kind, taxon_id, subspecies, location_xml_id, date, time, "
        "trip_xml_id, count, male, female, immature, adult, heard_only, photographed, status, "
        "breeding, description FROM sightings ORDER BY ord"
    ):  # fmt: skip
        ids = [taxon_id] if taxon_id is not None else taxa[row]
        sightings.append(
            Sighting(
                taxon=_taxon(kind, ids, subspecies), taxonomy_id=taxonomy_id,
                location_id=location_id,
                date=None if date is None else parse_partial_date(date), time=_time(time_text),
                trip_id=trip_id,
                count=None if count is None else ApproximateNumber.parse(count),
                male=bool(male), female=bool(female), immature=bool(immature),
                adult=bool(adult), heard_only=bool(heard_only),
                photographed=bool(photographed), status=status, breeding=breeding,
                users=users[row], description=description, photos=photos[row],
            )
        )  # fmt: skip
    return sightings

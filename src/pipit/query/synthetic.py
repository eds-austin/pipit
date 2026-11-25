"""Scythebill's synthetic regions ("***aba***" and so on: ``SyntheticLocations``), as the set
of the list's places each one includes.

Scythebill adds every built-in place when a list opens, so a region's required places always
exist; only places actually in the list can have sightings, so a region is the union of the
subtrees of the list's places it names (by eBird code, ``LocationSet.getLocationsByCode``,
or by name), minus any it removes. Ported per region, including their quirks (the Kingdom of
the Netherlands leaves out the Netherlands itself; the Western Palearctic adds places by
coordinates in a few Saharan, Arabian and ocean regions).
"""

from __future__ import annotations

from collections.abc import Iterable

from pipit.query.model import QPlace, QueryList


class _Index:
    def __init__(self, places: dict[str, QPlace], query_list: QueryList) -> None:
        self.places = places
        self.query_list = query_list
        self.by_code: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}
        for place in places.values():  # in list order: the last wins getLocationByCode
            if place.code is not None:
                self.by_code.setdefault(place.code, []).append(place.xml_id)
            self.by_name.setdefault(place.name, []).append(place.xml_id)

    def codes(self, code: str) -> list[str]:
        return self.by_code.get(code, [])

    def code(self, code: str) -> str | None:
        found = self.by_code.get(code)
        return found[-1] if found else None

    def within(self, xml_ids: Iterable[str | None]) -> set[str]:
        found: set[str] = set()
        for xml_id in xml_ids:
            if xml_id is not None:
                found |= self.query_list.places_within(xml_id)
        return found

    def is_inside(self, ancestor: str, xml_id: str) -> bool:
        return xml_id in self.query_list.places_within(ancestor)

    def built_in_named(self, name: str) -> str | None:
        return next((x for x in self.by_name.get(name, []) if self.places[x].built_in), None)

    def ancestor_of_type(self, xml_id: str, place_type: str) -> QPlace | None:
        current: str | None = xml_id
        while current is not None:
            place = self.places[current]
            if place.type == place_type:
                return place
            current = place.parent
        return None


def _north_american_usa(index: _Index) -> str | None:
    """``SyntheticLocations.getNorthAmericanUsa``."""
    north_america = index.built_in_named("North America")
    if north_america is None:
        return None
    west_indies = index.built_in_named("West Indies")
    for candidate in index.by_name.get("United States", []):
        if west_indies is not None and index.is_inside(west_indies, candidate):
            continue
        if index.is_inside(north_america, candidate):
            return candidate
    return None


def _generic(
    index: _Index,
    codes: Iterable[str],
    *,
    required: Iterable[str] = (),
    optional: Iterable[str] = (),
    removed: Iterable[str] = (),
) -> set[str] | None:
    """``GenericSyntheticLocation``: None if a required place is missing (never, as
    Scythebill populates every built-in place) or nothing is found."""
    found: list[str] = []
    for code in [*required, *codes, *optional]:
        if code == "ID-Asia":
            for indonesia in index.codes("ID"):
                if _built_in_ancestor_name(index, index.places[indonesia].parent) == "Asia":
                    found.append(indonesia)
        else:
            found.extend(index.codes(code))
    if not found:
        return None
    places = index.within(found)
    taken_out = index.within(x for code in removed for x in index.codes(code))
    return places - taken_out


def _built_in_ancestor_name(index: _Index, xml_id: str | None) -> str | None:
    current = xml_id
    while current is not None:
        place = index.places[current]
        if place.built_in:
            return place.name
        current = place.parent
    return None


_WESTERN_PALEARCTIC_NOT_EUROPE = ("TR", "AZ", "AM", "GE", "CY", "IL", "PS", "JO", "LB", "KW",
                                  "SY", "IQ", "MA", "EH", "DZ", "TN", "LY", "EG", "ES-CN", "CV",
                                  "SJ", "FO", "ES-CEUMEL")  # fmt: skip


def _western_palearctic(index: _Index) -> set[str] | None:
    europe = index.built_in_named("Europe")
    if europe is None:
        return None
    by_code = index.within([europe, *(x for c in _WESTERN_PALEARCTIC_NOT_EUROPE
                                      for x in index.codes(c))])  # fmt: skip
    by_coordinates_only = index.within(index.code(c) for c in ("DZ-01", "DZ-11"))
    found = set()
    for xml_id in index.places:
        if xml_id in by_coordinates_only:
            if _palearctic_by_coordinates(index, xml_id):
                found.add(xml_id)
        elif xml_id in by_code or _palearctic_by_coordinates(index, xml_id):
            found.add(xml_id)
    return found


def _palearctic_by_coordinates(index: _Index, xml_id: str) -> bool:
    """``WesternPalearcticRegion.matchesExplicitLatLong``."""
    place = index.places[xml_id]
    if place.latitude is None or place.longitude is None:
        return False
    latitude, longitude = place.latitude, place.longitude
    country = index.ancestor_of_type(xml_id, "country")
    code = None if country is None else country.code
    if code is None:
        return False
    if code == "XX":
        region = index.ancestor_of_type(xml_id, "region")
        name = None if region is None else region.name
        if name == "Atlantic Ocean":
            if -30 <= longitude <= -20 and 14 <= latitude <= 67:
                return True
            return -20 <= longitude <= -10 and 19 <= latitude <= 67
        if name == "Arctic Ocean":
            return -10 <= longitude <= 70 and latitude < 82
        return False
    if code in ("MR", "ML", "NE", "DZ"):
        return latitude >= 20
    if code == "TD":
        return latitude >= 20 or (latitude >= 18 and 16 <= longitude <= 20)
    if code == "SA":
        return latitude >= 27
    if code == "KZ":
        return longitude <= 51
    return False


def regions_for(query_list: QueryList) -> dict[str, frozenset[str]]:
    """The list's synthetic regions, computed once per loaded list."""
    if query_list.regions is None:
        query_list.regions = synthetic_regions(query_list)
    return query_list.regions


def synthetic_regions(query_list: QueryList) -> dict[str, frozenset[str]]:
    """Every synthetic region Scythebill offers, by its ID ("***aba***")."""
    index = _Index(query_list.places, query_list)
    regions: dict[str, set[str] | None] = {}
    usa = _north_american_usa(index)
    if usa is not None:
        canada, miquelon = index.code("CA"), index.code("PM")
        regions["aba"] = index.within([usa, canada, miquelon, index.code("US-HI"),
                                       index.code("UM-71")])  # fmt: skip
        regions["abawh"] = index.within([usa, canada, miquelon])
        regions["us50"] = index.within([usa, index.code("US-HI")])
        regions["us48"] = index.within([usa]) - index.within([index.code("US-AK")])
    north_america = index.by_name.get("North America", [])
    if len(north_america) == 1:
        extra = [index.code(c) for c in ("US-HI", "UM-67", "UM-71", "CP")]
        regions["aou"] = index.within([north_america[0], *extra])
    south_america = index.by_name.get("South America", [])
    if len(south_america) == 1:
        regions["aossouth"] = index.within([south_america[0], index.code("EC-W"),
                                            index.code("FK")])  # fmt: skip
    regions["wepale"] = _western_palearctic(index)
    regions["sounafr"] = index.within(
        index.code(c)
        for c in (
            "ZA",
            "ZW",
            "BW",
            "NA",
            "SZ",
            "LS",
            "MZ-L",
            "MZ-G",
            "MZ-I",
            "MZ-B",
            "MZ-S",
            "MZ-T",
        )
    )
    united_states = [x for x in index.by_name.get("United States", [])
                     if index.places[x].code == "US"]  # fmt: skip
    territories = [index.code(c) for c in ("UM", "PR", "GU", "AS", "VI", "MP")]
    regions["uswidepterr"] = index.within([*united_states, *territories])
    regions["auwidepterr"] = _generic(index, ("AU", "AC", "CS", "CC", "CX", "NF", "HM",
                                              "AU-TAS-Macquarie"))  # fmt: skip
    regions["austaba"] = _generic(index, (), required=("AU", "PG"), optional=("AC", "CS"),
                                  removed=("PG-NSA",))  # fmt: skip
    pacific = index.built_in_named("Pacific Ocean")
    if pacific is not None:
        regions["pacoceaba"] = index.within(
            [
                pacific,
                *(
                    index.code(c)
                    for c in ("AU-TAS-Macquarie", "NC", "NZ", "NF", "SB", "VU", "PG-NSA")
                ),
            ]
        )
    regions["orireg"] = _generic(index, ("ID-Asia", "MV", "IN", "LA", "PK", "HK", "BD", "BT",
                                         "BN", "KH", "CN", "CX", "TL", "JP", "LA", "MO", "MY",
                                         "MN", "MM", "NP", "KP", "SG", "KR", "LK", "TW", "TH",
                                         "VN", "PH"),
                                 optional=("ID-MA", "RU-KYA", "RU-TY", "RU-IRK", "RU-BU",
                                           "RU-CHI", "RU-AGB", "RU-ORB", "RU-KAM", "RU-AMU",
                                           "RU-YEV", "RU-PRI", "RU-SAK", "RU-KHA", "RU-MAG",
                                           "RU-SA", "RU-CHU"))  # fmt: skip
    regions["clwidepterr"] = _generic(index, (), required=("CL",),
                                      optional=("CL-VS-Easter", "CL-VS-JuanFernandez"))  # fmt: skip
    for key, codes in (
        ("cowidepterr", ("CO", "CO-SAP")), ("ecwidepterr", ("EC", "EC-W")),
        ("ptwidepterr", ("PT", "PT-20", "PT-30")), ("eswidepterr", ("ES", "ES-CEUMEL", "ES-CN")),
        ("nzwidepterr", ("NZ", "TK")), ("nowidepterr", ("NO", "BV", "SJ")),
        ("gbwidepterr", ("GB", "AI", "BM", "IO", "VG", "KY", "FK", "GI", "MS", "PN", "SH", "TC",
                         "GS")),
        ("cnwidepterr", ("CN", "HK", "MO")), ("dkwidepterr", ("DK", "FO", "GL")),
        ("zawidepterr", ("ZA", "ZA-WC-EdwardMarion")),
        ("frwidepterr", ("FR", "BL", "MF", "PM", "WF", "PF", "NC", "CP", "TF", "RE", "GP", "GF",
                         "YT", "MQ")),
        ("ireislof", ("IE", "GB-NIR")),
    ):  # fmt: skip
        regions[key] = _generic(index, codes)
    regions["ushiwinowiis"] = _generic(index, (), required=("US-HI",), optional=("UM-71",))
    if index.code("NL") is not None:  # the Netherlands itself is not included (Scythebill)
        regions["nlwidepterr"] = index.within([*index.codes("BQ"), index.code("AW")])
    # Scythebill adds every built-in place when a list opens, so every region exists there
    # even when this list has none of its places (it then matches nothing).
    for key in REGION_KEYS:
        regions.setdefault(key, None)
    return {f"***{key}***": frozenset(found or ()) for key, found in regions.items()}


#: Every region's key, in Scythebill's order (``SyntheticLocations``).
REGION_KEYS = ("aba", "abawh", "us50", "us48", "aou", "aossouth", "wepale", "sounafr",
               "uswidepterr", "auwidepterr", "austaba", "pacoceaba", "orireg", "clwidepterr",
               "cowidepterr", "ecwidepterr", "ptwidepterr", "eswidepterr", "nzwidepterr",
               "nowidepterr", "gbwidepterr", "cnwidepterr", "dkwidepterr", "zawidepterr",
               "frwidepterr", "ireislof", "ushiwinowiis", "nlwidepterr")  # fmt: skip

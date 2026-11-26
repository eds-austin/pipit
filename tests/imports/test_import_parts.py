"""The pieces of an import that can be checked on their own: dates read as Joda-Time reads
them, times, counts, protocols, breeding codes, the BK-tree's search order, and names."""

from __future__ import annotations

from datetime import time
from typing import Any

import pytest

from pipit.domain.partial_date import parse_partial_date
from pipit.domain.report import ObservationType
from pipit.imports.bktree import BKTree
from pipit.imports.fields import (
    DateParseError,
    JodaDateParser,
    breeding_code,
    float_at,
    int_at,
    parse_external_time,
    parse_first_match,
)
from pipit.imports.my_data import DATE_PARSERS, observation_type
from pipit.imports.places import normalize_alias
from pipit.imports.taxa import (
    TaxonResolver,
    TbdTaxon,
    after_binomial,
    just_binomial,
    normalize_common_name,
)
from pipit.taxa.sighting_taxon import SightingTaxon


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2024-04-13", "2024-04-13"), ("24-04-13", "2024-04-13"), ("98-06-15", "1998-06-15"),
     ("49-01-01", "2049-01-01"), ("50-01-01", "1950-01-01"), ("2024-4-3", "2024-04-03"),
     ("2024/04/13", "2024-04-13"), ("1500-02-29", "1500-02-29"), ("2000-02-29", "2000-02-29"),
     ("123-05-06", "0123-05-06")],
)  # fmt: skip
def test_my_data_dates(text: str, expected: str) -> None:
    assert parse_first_match(DATE_PARSERS, text) == parse_partial_date(expected)


@pytest.mark.parametrize(
    "text", ["2024-02-30", "1900-02-29", "2024-13-01", "2024-04-13 ", "2024-04", "13/04/2024",
             "2024-04-131", "1582-10-10", ""])  # fmt: skip
def test_bad_dates(text: str) -> None:
    with pytest.raises(DateParseError):
        parse_first_match(DATE_PARSERS, text)


def test_other_patterns() -> None:
    assert JodaDateParser("dd/MM/yyyy").parse("13/4/2024") == parse_partial_date("2024-04-13")
    assert JodaDateParser("MM-yyyy").parse("04-2024") == parse_partial_date("2024-04")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("07:15 AM", time(7, 15)), ("7:15AM", time(7, 15)), ("12:00 AM", time(0, 0)),
     ("12:30 PM", time(12, 30)), ("04:30 PM", time(16, 30)), ("16:30", time(16, 30)),
     ("7:05", time(7, 5)), ("07:15:59", time(7, 15)), ("7:15:30.5", time(7, 15)),
     ("08:00 AM", time(8, 0))],
)  # fmt: skip
def test_times(text: str, expected: time) -> None:
    assert parse_external_time(text) == expected


@pytest.mark.parametrize("text", ["13:00 PM", "0:30 AM", "24:00", "7:5", "7", "7:15 am", ""])
def test_bad_times(text: str) -> None:
    with pytest.raises(ValueError, match="time"):
        parse_external_time(text)


def test_numbers() -> None:
    assert int_at(["20+"], 0) == 20
    assert int_at(["~50"], 0) == 50
    assert int_at(["X"], 0) is None
    assert int_at([""], 0) is None
    assert int_at([], 0) is None
    assert float_at(["2.5 km"], 0) == 2.5
    assert float_at(["1.2.3"], 0) is None


@pytest.mark.parametrize(
    ("protocol", "expected"),
    [("eBird - Traveling Count", ObservationType.TRAVELING),
     ("eBird - Stationary Count", ObservationType.STATIONARY),
     ("eBird - Casual Observation", ObservationType.INCIDENTAL),
     ("Incidental", ObservationType.INCIDENTAL), ("Historical", ObservationType.HISTORICAL),
     ("eBird - Exhaustive Area Count", ObservationType.AREA),
     ("eBird--Banding Protocol", ObservationType.BANDING),
     ("eBird Pelagic Protocol", ObservationType.PELAGIC),
     ("eBird - Nocturnal Flight Call Count", ObservationType.FLIGHT_CALL),
     ("Stationär", ObservationType.STATIONARY), ("Oiled Birds", ObservationType.HISTORICAL),
     ("", ObservationType.HISTORICAL)],
)  # fmt: skip
def test_protocols(protocol: str, expected: ObservationType) -> None:
    assert observation_type(protocol) is expected


def test_breeding_codes() -> None:
    assert breeding_code("NY Nest with Young (NY)") == "NY"
    assert breeding_code("F") == "F"
    assert breeding_code("ZZ Unknown") is None
    assert breeding_code("") is None


def test_bk_tree_finds_in_order() -> None:
    tree: BKTree[str] = BKTree()
    for name in ("mallard", "mallards", "ballard", "mallord", "dunlin"):
        tree.add(name, name)
    assert tree.search("mallard", 1) == ["mallard", "mallards", "ballard", "mallord"]
    assert tree.search("mallard", 0) == ["mallard"]


def test_names() -> None:
    assert just_binomial("Junco hyemalis [oreganus Group]") == "Junco hyemalis"
    assert after_binomial("Junco hyemalis [oreganus Group]") == "[oreganus Group]"
    assert just_binomial("Anas platyrhynchos x rubripes") == "Anas platyrhynchos x rubripes"
    assert after_binomial("Anas platyrhynchos") is None
    assert normalize_common_name("Grey-headed Woodpecker") == "gray headed woodpecker"
    assert normalize_alias("St. John’s & Lincs.") == "st johns and lincs"
    assert TbdTaxon("duck sp.", "Anatidae sp.").should_ignore()
    assert not TbdTaxon("Pinkish Warbler", "Setophaga rosea").should_ignore()


@pytest.mark.scythebill
def test_repeated_names_are_one_taxon(pack: Any) -> None:
    """Scythebill's import fails on a hybrid of a bird with itself; Pipit imports the bird."""
    clements, _avilist = pack.load_base_and_avilist()
    resolver = TaxonResolver(clements, maximum_name_distance=1)
    found = resolver.map("Mallard x Mallard", None, None)
    assert found is not None
    assert found.primary == SightingTaxon.single("spAnaspla")
    near = resolver.map("Malard", "Anas platyrhynchos", None)
    assert near is not None
    assert near.primary == SightingTaxon.single("spAnaspla")


def test_checklist_fields() -> None:
    from pipit.imports.ebird_checklist import area_hectares, distance_km, duration_minutes

    assert duration_minutes("1 hour(s), 35 minute(s)") == 95
    assert duration_minutes("2 Stunde(n)") == 120
    assert duration_minutes("45 minute(s)") == 45
    assert duration_minutes("an afternoon") is None
    assert distance_km("3.0 Kilometer") == 3.0
    assert distance_km("1.3 mile(s)") == pytest.approx(2.092142, abs=1e-6)
    assert distance_km("12 furlongs") is None
    assert area_hectares("2.5 ha") == 2.5
    assert area_hectares("1 ac") == pytest.approx(0.404686, abs=1e-6)


def test_ebird_api_asks_for_the_checklist_then_its_location() -> None:
    from pipit.ebird.api import EBirdApi, EBirdApiError

    asked: list[str] = []
    answers = {
        "checklist/view/S1": b'{"subnational1Code": "US-CA", "locId": "L1"}',
        "hotspot/info/L1": b'{"subnational1Code": "US-OR", "subnational2Name": "Lane"}',
        "checklist/view/S2": b'{"subnational1Code": "GB-ENG", "locId": "L2"}',
        "hotspot/info/L2": b"",  # a personal location
        "checklist/view/S3": b'{"subnational1Code": "CR-P", "locId": "L3"}',
    }

    def transport(url: str, headers: dict[str, str]) -> bytes:
        assert headers == {"X-eBirdApiToken": "key"}
        asked.append(url)
        key = url.split("/v2/")[1].split("/", 1)[1]
        if key not in answers:
            raise EBirdApiError("404")
        return answers[key]

    api = EBirdApi("key", transport)
    place = api.checklist_place("S1")
    assert (place.country_code, place.state_code, place.county, place.hotspot_id) == (
        "US", "OR", "Lane", "L1")  # fmt: skip
    assert asked == ["https://api.ebird.org/v2/product/checklist/view/S1",
                     "https://api.ebird.org/v2/ref/hotspot/info/L1"]  # fmt: skip
    personal = api.checklist_place("S2")
    assert (personal.country_code, personal.state_code, personal.county) == ("GB", "ENG", None)
    no_hotspot = api.checklist_place("S3")  # the hotspot request fails: the state is enough
    assert (no_hotspot.country_code, no_hotspot.state_code) == ("CR", "P")
    with pytest.raises(EBirdApiError):
        api.checklist_place("S4")


def test_ebird_api_only_over_https() -> None:
    from pipit.ebird.api import EBirdApiError, http_transport

    with pytest.raises(EBirdApiError, match="non-https"):
        http_transport("http://api.ebird.org/v2/x", {})

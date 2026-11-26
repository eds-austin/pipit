"""Write the trip report cases for tools/oracle/PrintOracle.java's trip mode, on
tests/fixtures/bsxm/trip_report.bsxm: reports over the Costa Rica trip (with Costa Rica's
checklist), a park, a county, a California visit and the whole list, then every option,
names order, depth and taxonomy on the Costa Rica one.

    python -I tools/oracle/make_trip_report_cases.py cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: ``TripReportPreferences``' defaults.
DEFAULTS = {"includeScientific": True, "includeItinerary": True, "includeSpeciesTable": True,
            "includeSpeciesList": True, "showStatus": True, "lifersInBold": True}  # fmt: skip


def _in(place: str) -> dict[str, object]:
    return {"fields": [{"type": "LOCATION", "value": {"type": "IN", "id": place},
                        "bool": "ALL"}]}  # fmt: skip


COSTA_RICA = _in("_ct_cosric")
QUERIES: list[tuple[str, dict[str, object]]] = [
    ("costa_rica", COSTA_RICA),
    ("everything", {"fields": []}),
    ("carara", _in("carara")),
    ("valle", _in("valle")),
    ("california", _in("_usst_califo")),
    ("selva", _in("laselva")),
    ("february", {"fields": [{"type": "DATE", "value": {"type": "BETWEEN",
                  "from": "2025-02-07", "to": "2025-02-10"}, "bool": "ALL"}]}),
]  # fmt: skip
VARIATIONS: list[tuple[str, dict[str, object], str, str, str, bool]] = [
    # label, options, names order, display, depth, miles
    ("scientific_first", {}, "SCIENTIFIC_FIRST", "clements", "species", False),
    ("scientific_only", {}, "SCIENTIFIC_ONLY", "clements", "species", False),
    ("common_only", {"includeScientific": False}, "COMMON_FIRST", "clements", "species",
     False),
    ("no_itinerary", {"includeItinerary": False}, "COMMON_FIRST", "clements", "species",
     False),
    ("no_table", {"includeSpeciesTable": False}, "COMMON_FIRST", "clements", "species",
     False),
    ("no_list", {"includeSpeciesList": False}, "COMMON_FIRST", "clements", "species", False),
    ("no_list_scientific", {"includeSpeciesList": False}, "SCIENTIFIC_FIRST", "clements",
     "species", False),
    ("itinerary_only", {"includeSpeciesTable": False, "includeSpeciesList": False},
     "COMMON_FIRST", "clements", "species", False),
    ("no_status", {"showStatus": False}, "COMMON_FIRST", "clements", "species", False),
    ("no_lifers", {"lifersInBold": False}, "COMMON_FIRST", "clements", "species", False),
    ("miles", {}, "COMMON_FIRST", "clements", "species", True),
    ("subspecies", {}, "COMMON_FIRST", "clements", "subspecies", False),
    ("subspecies_scientific", {}, "SCIENTIFIC_FIRST", "clements", "subspecies", False),
    ("group_common_only", {"includeScientific": False}, "COMMON_FIRST", "clements", "group",
     False),
    ("avilist", {}, "COMMON_FIRST", "avilist", "species", False),
    ("avilist_subspecies", {}, "COMMON_FIRST", "avilist", "subspecies", False),
]  # fmt: skip


def case(name: str, query: object, *, options: dict[str, object] | None = None,
         names: str = "COMMON_FIRST", display: str = "clements", depth: str = "species",
         miles: bool = False, trips: list[str] | None = None) -> str:  # fmt: skip
    found: dict[str, object] = {"name": name, "query": query, "display": display,
                                "depth": depth, "namesOrder": names, "useMiles": miles,
                                "options": {**DEFAULTS, **(options or {})}}  # fmt: skip
    if trips is not None:
        found["trips"] = trips
    return json.dumps(found, ensure_ascii=False)


def main() -> None:
    lines = [case(name, query) for name, query in QUERIES]
    for label, options, names, display, depth, miles in VARIATIONS:
        lines.append(case(f"costa_rica_{label}", COSTA_RICA, options=options, names=names,
                          display=display, depth=depth, miles=miles))  # fmt: skip
    lines.append(case("everything_subspecies", {"fields": []}, depth="subspecies"))
    lines.append(case("selva_scientific_only", _in("laselva"), names="SCIENTIFIC_ONLY"))
    # As from the Trips screen: the trips given, not matched
    lines.append(case("trip_part_two", COSTA_RICA, trips=["cr2"]))
    lines.append(case("trips_both", {"fields": []}, trips=["cr2", "cr1"]))
    # From the Trips screen: the selected trips' sightings, their place and checklist
    trips_cases = [
        ("trips_screen_cr1", ["cr1"], "species"),
        ("trips_screen_cr2", ["cr2"], "species"),
        ("trips_screen_both", ["cr1", "cr2"], "subspecies"),
        ("trips_screen_california", ["ca24"], "species"),
        ("trips_screen_all", ["ca24", "cr1", "cr2"], "species"),
        ("trips_screen_two_countries", ["ca24", "cr1"], "species"),
    ]
    for name, trips, depth in trips_cases:
        found = json.loads(case(name, {"fields": []}, depth=depth, trips=trips))
        found["fromTrips"] = True
        lines.append(json.dumps(found, ensure_ascii=False))
    Path(sys.argv[1]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

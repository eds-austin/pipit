"""Write the family report cases for tools/oracle/PrintOracle.java's family mode, on
tests/fixtures/bsxm/trip_report.bsxm: the whole list (the world), a country, a state, a park
(its country's checklist), a country and a state together (their checklists merged), family,
order and IUCN rows (with "never"), and dates, in both taxonomies.

    python -I tools/oracle/make_family_cases.py cases.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _field(field_type: str, value: dict[str, object], bool_op: str = "ALL") -> dict[str, object]:
    return {"type": field_type, "value": value, "bool": bool_op}


def _in(place: str) -> dict[str, object]:
    return _field("LOCATION", {"type": "IN", "id": place})


QUERIES: list[tuple[str, list[dict[str, object]]]] = [
    ("everything", []),
    ("costa_rica", [_in("_ct_cosric")]),
    ("california", [_in("_usst_califo")]),
    ("carara", [_in("carara")]),
    ("two_countries", [_in("_ct_cosric"), _field("LOCATION", {"type": "IN",
                                                             "id": "_usst_califo"}, "ANY")]),
    ("hummingbirds", [_in("_ct_cosric"), _field("FAMILY", {"type": "IS_IN", "id": "famTro"})]),
    ("not_passerines", [_in("_ct_cosric"),
                        _field("FAMILY", {"type": "IS_NOT_IN", "id": "ordPas"})]),
    ("never_pigeons", [_in("_ct_cosric"), _field("FAMILY", {"type": "IS_IN", "id": "famCol"},
                                                  "NEVER")]),
    ("pigeons_or_ducks", [_field("FAMILY", {"type": "IS_IN", "id": "famCol"}),
                          _field("FAMILY", {"type": "IS_IN", "id": "famAna"}, "ANY")]),
    ("near_threatened", [_in("_ct_cosric"),
                         _field("SPECIES_STATUS", {"type": "IS_OR_WORSE", "statusId": "NT"})]),
    ("february", [_in("_ct_cosric"), _field("DATE", {"type": "BETWEEN", "from": "2025-02-07",
                                                       "to": "2025-02-10"})]),
]  # fmt: skip


def main() -> None:
    lines = []
    for display in ("clements", "avilist"):
        for name, fields in QUERIES:
            lines.append(json.dumps({"name": f"{name}_{display}", "query": {"fields": fields},
                                     "display": display, "depth": "species"}))  # fmt: skip
    Path(sys.argv[1]).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

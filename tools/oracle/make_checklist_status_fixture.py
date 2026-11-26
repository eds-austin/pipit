"""Write tests/fixtures/bsxm/checklist_status.bsxm: the Costa Rica trip
(tests/fixtures/bsxm/trip_report.bsxm) with more to find for the checklist status report
(tools/oracle/PrintOracle.java's status mode):

- custom checklists for Carara (a park; its sightings are on trails inside it) with the
  species seen there in every status, some left off, and for La Selva with one species;
- species far from Costa Rica's checklist, one plainly, one recorded as introduced, and
  others only with the statuses the report skips (uncertain, domestic, not accepted,
  introduced but not established);
- a subspecies and a sp. of two subspecies of a species not on the checklist (both count as
  the species), a sp. of two such species (left out), and an extinct species;
- a Costa Rica species in California.

    python -I tools/oracle/make_checklist_status_fixture.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BSXM = Path(__file__).parents[2] / "tests" / "fixtures" / "bsxm"
STATUSES = (None, "endemic", "extinct", "escaped", "provisional", "rarity",
            "rarity-from-introduced", "introduced")  # fmt: skip

EXTRA_SIGHTINGS = [
    '  <sighting taxon="spAptenfor" loc="tarc1" date="2025-02-03" count="1"/>',
    '  <sighting taxon="spStrutcam" loc="tarc2" date="2025-02-03" count="2" popStatus="intro"/>',
    '  <sighting taxon="spBubosca" loc="muer70" date="2025-02-04" popStatus="idUncertain"/>',
    '  <sighting taxon="spPicapic" loc="muer70" date="2025-02-04" popStatus="domestic"/>',
    '  <sighting taxon="spCorvucor" loc="muer80" date="2025-02-04" popStatus="notAccepted"/>',
    '  <sighting taxon="spApteraus" loc="muer80" date="2025-02-04" popStatus="notEstablished"/>',
    '  <sighting taxon="sspFratearcnau" loc="pelag" date="2025-02-05" count="3"/>',
    '  <sighting sp="sspStrutcamcam,sspStrutcamsyr" loc="pelag" date="2025-02-05"/>',
    '  <sighting sp="spBubosca,spPicapic" loc="pelag" date="2025-02-05"/>',
    '  <sighting taxon="spEctopmig" loc="canneg" date="2025-02-06" count="1"/>',
    '  <sighting taxon="spMicro3cup" loc="_usst_califo" date="2024-05-01" count="1"/>',
]


def _species_at(text: str, places: tuple[str, ...]) -> list[str]:
    found: dict[str, None] = {}
    for match in re.finditer(r'<sighting taxon="(sp[^"]+)" loc="([^"]+)"', text):
        if match.group(2) in places:
            found[match.group(1)] = None
    return list(found)


def _checklist(place: str, species: list[str], every_status: bool) -> list[str]:
    lines = [f'  <checklist loc="{place}">']
    for i, taxon in enumerate(species):
        if every_status and i % 9 == 8:
            continue  # left off: not found
        status = STATUSES[i % len(STATUSES)] if every_status else None
        lines.append(f'    <entry taxon="{taxon}"'
                     + (f' status="{status}"' if status else "") + "/>")  # fmt: skip
    lines.append("  </checklist>")
    return lines


def main() -> int:
    text = (BSXM / "trip_report.bsxm").read_text(encoding="utf-8")
    carara = _species_at(text, ("carara", "caralag", "caruni"))
    selva = _species_at(text, ("laselva", "selvaori", "selvarib"))
    lines = text.split("\n")
    last = max(i for i, line in enumerate(lines) if line.startswith("  <sighting "))
    added = (EXTRA_SIGHTINGS + _checklist("carara", carara, every_status=True)
             + _checklist("laselva", selva[:1], every_status=False))  # fmt: skip
    lines[last + 1 : last + 1] = added
    out = BSXM / "checklist_status.bsxm"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}: {len(carara)} species at Carara, {len(selva)} at La Selva")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Write tests/fixtures/bsxm/trip_report.bsxm: a made-up birding trip to Costa Rica, for
checking trip reports against Scythebill (tools/oracle/TripReportOracle.java).

It is built to reach every part of a trip report:

- stops: a national park with trails inside it, a place of the user's own with parts, eBird
  hotspots named "Place--Part", locations named for their coordinates, back-to-back visits
  to places whose names start alike, long names that need shortening (two of them alike),
  and two places with the same name;
- visits with and without times, durations, distances, unusual protocols (banding, pelagic,
  nocturnal), comments (one with eBird's "Submitted from" tail), several visits on a day, a
  stay of several days at one lodge, and back-to-back visits to one stop;
- three trips (one with notes over two lines, one in California) and sightings recorded on
  a trip, undated;
- endemic, introduced and rarity species (Costa Rica's checklist), threatened ones, groups,
  subspecies, sp. and hybrids, a species at more than eight stops, and one never countable;
- counts (exact and approximate), heard only, sex and age, statuses, breeding codes, notes,
  three observers, and photos (online favorites and others, files, and photographed with no
  photo);
- a visit to California in 2024, so some species aren't lifers and not every date is in one
  year.

    python -I tools/oracle/make_trip_report_fixture.py <out.bsxm>
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

BSXM = Path(__file__).parents[2] / "tests" / "fixtures" / "bsxm"

#: Places inside Costa Rica: (id, element, name, children).
PLACES: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    ("carara", "park", "Parque Nacional Carara",
     [("caralag", "location", "Sendero Laguna Meándrica"),
      ("caruni", "location", "Sendero Universal")]),
    ("laselva", "location", "La Selva Biological Station",
     [("selvaori", "location", "Sendero Oriente"), ("selvarib", "location", "River Bridge")]),
    ("montbos", "location", "Monteverde Reserve--Sendero Bosque Nuboso", []),
    ("montcam", "location", "Monteverde Reserve--Sendero El Camino", []),
    ("tarc1", "location", "Tárcoles River Bridge (9.78, -84.61)", []),
    ("tarc2", "location", "Tárcoles River Bridge (9.7851, -84.6123)", []),
    ("muer70", "location", "Cerro de la Muerte Km 70", []),
    ("muer80", "location", "Cerro de la Muerte Km 80 Paraíso Quetzal", []),
    ("canneg", "location", "Refugio Nacional de Vida Silvestre Caño Negro", []),
    ("ranchgar", "location", "Rancho Naturalista Lodge Gardens", []),
    ("ranchfee", "location", "Rancho Naturalista Lodge Feeders (upper deck)", []),
    ("savegre", "location", "Savegre Mountain Lodge", []),
    ("pelag", "location", "Pelagic off Quepos", []),
    ("valle", "county", "Valle Central", [("hotel1", "location", "Hotel Garden")]),
    ("zonasur", "county", "Zona Sur", [("hotel2", "location", "Hotel Garden")]),
    ("airport", "location", "SJO Airport", []),
]  # fmt: skip

USERS = [("ew", "Eric W", "EW"), ("ab", "Ann Bell", "AB"), ("cy", "Cy", None)]

TRIPS = [
    ("cr1", "_ct_cosric", "2025-02-01", "2025-02-06", "Costa Rica 2025 Part 1",
     "Rain most afternoons.\nGuide: Ernesto."),
    ("cr2", None, "2025-02-07", "2025-02-10", "Costa Rica 2025 Part 2", None),
    ("ca24", "lakmer", "2024-05-01", "2024-05-01", "California day", None),
]  # fmt: skip

#: Visits: (location, date, time or None, protocol, minutes, km, comments, trip).
VISITS: list[tuple[str, str, str | None, str, int | None, str | None, str | None, str]] = [
    ("airport", "2025-02-01", "14:30", "incidental", None, None, None, "cr1"),
    ("hotel1", "2025-02-01", None, "stationary", 45, None, "Arrival", "cr1"),
    ("caralag", "2025-02-02", "06:15", "traveling", 150, "3.2", "Hot and humid", "cr1"),
    ("caruni", "2025-02-02", "09:00", "traveling", 60, "1.15", None, "cr1"),
    ("tarc1", "2025-02-02", "11:30", "stationary", 30, None,
     "Crocodiles<br />Submitted from eBird for iOS, version 3.2", "cr1"),
    ("tarc2", "2025-02-02", "12:10", "stationary", 20, None, None, "cr1"),
    ("pelag", "2025-02-03", "05:30", "pelagic", 300, "42.5", None, "cr1"),
    ("muer70", "2025-02-04", "06:00", "traveling", 40, "0.8", None, "cr1"),
    ("muer80", "2025-02-04", "07:00", "traveling", 90, "2", None, "cr1"),
    ("savegre", "2025-02-04", None, "incidental", None, None, None, "cr1"),
    ("savegre", "2025-02-05", None, "incidental", None, None, None, "cr1"),
    ("savegre", "2025-02-06", "19:30", "nocturnal", 45, None, None, "cr1"),
    ("montbos", "2025-02-07", "07:00", "traveling", 120, "2.5", "Quetzal at the start", "cr2"),
    ("montcam", "2025-02-07", "09:30", "banding", 90, None, None, "cr2"),
    ("selvaori", "2025-02-08", "05:45", "traveling", 180, "4", None, "cr2"),
    ("selvarib", "2025-02-08", "10:00", "stationary", 30, None, "Sungrebe below", "cr2"),
    ("selvaori", "2025-02-08", "15:00", "traveling", 60, "1.3", None, "cr2"),
    ("canneg", "2025-02-09", "06:00", "traveling", 200, "8.75", None, "cr2"),
    ("ranchgar", "2025-02-09", "15:00", "stationary", 60, None, None, "cr2"),
    ("ranchfee", "2025-02-10", "06:00", "stationary", 75, None, None, "cr2"),
    ("hotel2", "2025-02-10", "18:00", "stationary", 10, None, None, "cr2"),
    ("lakmer", "2024-05-01", "08:00", "stationary", 30, None, None, "ca24"),
]  # fmt: skip

#: Common species spread over many families (Costa Rica natives).
COMMON = ["spNotho1bon", "spDendr1leu", "spChordacu", "spCypsecry", "spHelio4ful",
          "spHiman1mex", "spJacanspi", "spCreagfur", "spPhaet2aet", "spArdenpac", "spSulasul",
          "spEudocalb", "spSarcopap", "spTytofur", "spHylommom", "spGalburuf", "spAulacpra",
          "spBolbo1lin", "spGrallgua", "spScler1mex", "spTityrinq", "spPiprigri",
          "spRiparrip", "spCincl3mex", "spBombyced", "spRhodiros", "spIctervir",
          "spPiranfla"]  # fmt: skip


def sighting(attributes: dict[str, str], body: str = "") -> str:
    text = "  <sighting" + "".join(f" {k}={quoteattr(v)}" for k, v in attributes.items())
    return text + (f">{body}</sighting>" if body else "/>")


def at(visit: int, taxon: str, **extra: str) -> str:
    """A sighting on a visit (by its index in VISITS); ``taxon`` may be "sp:a,b" or
    "hybrid:a,b"; ``note`` and ``photos`` go in the body."""
    location, date, time, *_rest, trip = VISITS[visit]
    attributes: dict[str, str] = {}
    if taxon.startswith(("sp:", "hybrid:")):
        kind, ids = taxon.split(":")
        attributes[kind] = ids
    else:
        attributes["taxon"] = taxon
    attributes["loc"] = location
    attributes["date"] = date
    if time:
        attributes["time"] = time
    if trip:
        attributes["trip"] = trip
    body = escape(extra.pop("note", ""))
    body += extra.pop("photos", "")
    attributes.update(extra)
    return sighting(attributes, body)


def sightings() -> list[str]:
    lines = []
    # A common species at every stop (more than eight), and the rest spread around
    for visit in range(21):
        lines.append(at(visit, "spColum1pas", count=str(visit % 4 + 1)))
    for i, taxon in enumerate(COMMON):
        lines.append(at(i % 21, taxon, count=["2", "~10", "1"][i % 3]))
        if i % 4 == 0:
            lines.append(at((i + 7) % 21, taxon, heardOnly="true"))
    # California first, in 2024: these aren't lifers in Costa Rica
    for taxon in ("spAnaspla", "spBombyced", "spColumliv"):
        lines.append(at(21, taxon, count="3"))
    lines += [
        # Endemics, introduced species, a rarity, threatened ones
        at(
            7,
            "spMicro3cup",
            count="2",
            male="true",
            female="true",
            photos='<photo favorite="true" name="Emerald">https://example.org/eme.jpg</photo>'
            "<photo>https://example.org/eme2.jpg</photo>",
        ),
        at(13, "spMicro3cup", count="1", immature="true", users="ew"),
        at(8, "spMelozcab", heardOnly="true", users="ab"),
        at(
            4,
            "spChrys3bou",
            count="1",
            adult="true",
            breeding="CF",
            note="Feeding at mangrove flowers",
        ),
        at(0, "grColumliv(Fe", count="~30", popStatus="intro"),
        at(20, "spPassedom", count="5", breeding="NB"),
        at(19, "spPassedom", count="2", breeding="S"),
        at(
            17,
            "spAnser1alb",
            count="1",
            popStatus="idUncertain",
            note="Distant; may have been a domestic bird",
            users="ew,ab",
        ),
        at(2, "spCraxrub", count="2", male="true", photo="true"),
        at(14, "spCryptbou", heardOnly="true"),
        at(9, "spPenel1pur", count="4"),
        # Groups and subspecies of one species, then of another
        at(12, "grPatagfas[al", count="6"),
        at(10, "sspPatagfas[alcri", count="2"),
        at(11, "spPatagfas", count="1"),
        at(15, "sspTinam1majbru", heardOnly="true", users="cy"),
        at(1, "grColumliv(Wi", count="1"),
        # Mallard in Costa Rica too (not a lifer), domestic type
        at(5, "grAnaspla(Do", count="3", popStatus="domestic"),
        # A sp. and a hybrid
        at(6, "sp:spArdenpac,spSulasul", count="~40"),
        at(
            16,
            "hybrid:spPiranfla,spRhodiros",
            count="1",
            photos='<photo favorite="true">file:/home/x/hybrid.jpg</photo>',
        ),
        # Statuses, breeding, observers, photos
        at(3, "spGalburuf", count="2", popStatus="dead", users="ew,ab,cy"),
        at(
            18,
            "spGalburuf",
            count="1",
            popStatus="bvd",
            breeding="ON",
            users="ab,cy",
            photos='<photo name="Jacamar">http://example.org/jac.jpg</photo>',
        ),
        at(19, "spHylommom", count="1", note="Calling from the gully"),
        at(20, "spHylommom", count="2", note="Two at the feeders"),
        # Never countable: only ever recorded as "not by me"
        at(12, "spSarkisyl", count="1", popStatus="notByMe"),
    ]
    # Recorded on a trip, with no date: the trips' own columns
    lines.append(
        sighting(
            {"taxon": "spTytofur", "loc": "savegre", "trip": "cr1", "count": "1"},
            "Heard every night",
        )
    )
    lines.append(sighting({"taxon": "spAulacpra", "trip": "cr2", "count": "3"}))
    return lines


def visit_infos() -> list[str]:
    lines = []
    for location, date, time, protocol, minutes, km, comments, _trip in VISITS:
        attributes = f" loc={quoteattr(location)} date={quoteattr(date)}"
        if time:
            attributes += f" time={quoteattr(time)}"
        attributes += f" observationType={quoteattr(protocol)}"
        body = ""
        if minutes:
            body += f"<duration>{minutes}</duration>"
        if km:
            body += f"<distance>{km}</distance>"
        elif protocol == "nocturnal":
            body += "<distance>0.6</distance>"
        if protocol != "incidental":
            body += "<partySize>3</partySize>"
        if comments:
            body += f"<comments>{escape(comments)}</comments>"
        if location == "montbos":
            body += '<photo favorite="true">https://example.org/quetzal.jpg</photo>'
        lines.append(f"  <visit-info{attributes}>{body}</visit-info>")
    return lines


def places_xml() -> str:
    lines = ['        <country id="_ct_cosric" name="Costa Rica" ebirdCode="CR">']
    for place_id, element, name, children in PLACES:
        head = f"          <{element} id={quoteattr(place_id)} name={quoteattr(name)}"
        if not children:
            lines.append(head + "/>")
            continue
        lines.append(head + ">")
        for child_id, child_element, child_name in children:
            lines.append(f"            <{child_element} id={quoteattr(child_id)} "
                         f"name={quoteattr(child_name)}/>")  # fmt: skip
        lines.append(f"          </{element}>")
    lines.append("        </country>")
    return "\n".join(lines)


def main() -> int:
    source = (BSXM / "visits.bsxm").read_text(encoding="utf-8")
    head = source[: source.index("</locations>") + len("</locations>")]
    country = '        <country id="_ct_cosric" name="Costa Rica" ebirdCode="CR"/>'
    assert country in head
    head = head.replace(country, places_xml())
    upgrades = source[source.index("  <one-time-upgrade>") :]
    users = [f"  <user id={quoteattr(i)}" + (f" name={quoteattr(n)}" if n else "")
             + (f" abbrev={quoteattr(a)}" if a else "") + "/>" for i, n, a in USERS]  # fmt: skip
    trips = []
    for trip_id, location, start, end, name, notes in TRIPS:
        attributes = f" id={quoteattr(trip_id)}"
        if location:
            attributes += f" loc={quoteattr(location)}"
        attributes += f" startDate={quoteattr(start)} endDate={quoteattr(end)}"
        attributes += f" name={quoteattr(name)}"
        if notes:
            trips.append(f"  <trip{attributes}><notes>{escape(notes)}</notes></trip>")
        else:
            trips.append(f"  <trip{attributes}/>")
    body = [head, *users, *trips, *sightings(), *visit_infos()]
    Path(sys.argv[1]).write_text("\n".join(body) + "\n" + upgrades, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

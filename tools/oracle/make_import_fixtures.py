"""Write the made-up eBird "My Data" exports that tools/oracle/ImportOracle.java and Pipit's
import tests read, and their cases:

- ``my_data.csv``: checklists in California, Costa Rica and England, with every protocol,
  groups, forms and subspecies, "sp.", slash and hybrid names, repeated rows, a name eBird
  doesn't use, places Scythebill builds in (grouped names, built-in counties, a county the
  list already has under another name), photos, breeding codes and comments that need quoting.
  Its Costa Rica checklist repeats one of tests/fixtures/bsxm/trip_report.bsxm's visits, so
  importing it there (as ``trip_report.no_observers.bsxm``, written here without the list's
  observers) finds duplicates and dates the list already has.
- ``my_data_hours.csv``: an older export, with durations in hours and "Species Comments".
- ``my_data_bad_date.csv``: a date eBird would never write, which stops the import.

    python -I tools/oracle/make_import_fixtures.py tests/fixtures/imports
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

NEW = "../bsxm/new_list.scythebill.bsxm"
TRIPS = "../bsxm/trip_report.no_observers.bsxm"
HEADER = [
    "Submission ID", "Common Name", "Scientific Name", "Taxonomic Order", "Count",
    "State/Province", "County", "Location ID", "Location", "Latitude", "Longitude", "Date",
    "Time", "Protocol", "Duration (Min)", "All Obs Reported", "Distance Traveled (km)",
    "Area Covered (ha)", "Number of Observers", "Breeding Code", "Observation Details",
    "Checklist Comments", "ML Catalog Numbers",
]  # fmt: skip

TRAVELING = "eBird - Traveling Count"
STATIONARY = "eBird - Stationary Count"
CASUAL = "eBird - Casual Observation"
AREA = "eBird - Exhaustive Area Count"
PELAGIC = "eBird Pelagic Protocol"
HISTORICAL = "Historical"
BANDING = "eBird--Banding Protocol"
NOCTURNAL = "eBird - Nocturnal Flight Call Count"


class Checklist:
    """One eBird checklist's columns; ``species`` adds its rows."""

    def __init__(self, submission: str, region: str, county: str, location_id: str,  # noqa: PLR0917
                 location: str, latitude: str, longitude: str, date: str, time: str,
                 protocol: str, duration: str = "", complete: str = "1",
                 distance: str = "", area: str = "", observers: str = "1",
                 comments: str = "") -> None:  # fmt: skip
        self.columns = {
            "Submission ID": submission, "State/Province": region, "County": county,
            "Location ID": location_id, "Location": location, "Latitude": latitude,
            "Longitude": longitude, "Date": date, "Time": time, "Protocol": protocol,
            "Duration (Min)": duration, "All Obs Reported": complete,
            "Distance Traveled (km)": distance, "Area Covered (ha)": area,
            "Number of Observers": observers, "Checklist Comments": comments,
        }  # fmt: skip
        self.rows: list[dict[str, str]] = []

    def species(self, common: str, scientific: str, count: str, *, order: str = "1",
                breeding: str = "", details: str = "", photos: str = "") -> Checklist:  # fmt: skip
        self.rows.append(
            {
                **self.columns,
                "Common Name": common,
                "Scientific Name": scientific,
                "Taxonomic Order": order,
                "Count": count,
                "Breeding Code": breeding,
                "Observation Details": details,
                "ML Catalog Numbers": photos,
            }
        )
        return self


def my_data() -> list[Checklist]:
    madrona = ("US-CA", "Los Angeles", "L1001", "Madrona Marsh Preserve", "33.8250",
               "-118.3410")  # fmt: skip
    morning = Checklist("S1001", *madrona, "2024-04-13", "07:15 AM", TRAVELING, "95", "1",
                        "2.1", "", "2", "Windy, \"cool\" morning")  # fmt: skip
    morning.species("Mallard", "Anas platyrhynchos", "4")
    morning.species("Anna's Hummingbird", "Calypte anna", "2", breeding="NY Nest with Young (NY)",
                    photos="612345 612346")  # fmt: skip
    morning.species("Song Sparrow (California Coast)", "Melospiza melodia [heermanni Group]",
                    "3")  # fmt: skip
    morning.species("California Scrub-Jay", "Aphelocoma californica", "X")
    morning.species("Black Phoebe", "Sayornis nigricans", "1",
                    details="Flycatching over the pond, then \"chip\" calls")  # fmt: skip
    morning.species("duck sp.", "Anatidae sp.", "2")
    morning.species("Greater/Lesser Yellowlegs", "Tringa melanoleuca/flavipes", "1")
    morning.species("Mallard x American Black Duck (hybrid)", "Anas platyrhynchos x rubripes",
                    "1")  # fmt: skip
    morning.species("Mallard", "Anas platyrhynchos", "2", details="A second flock")
    afternoon = Checklist("S1002", *madrona, "2024-04-13", "04:30 PM", STATIONARY, "30", "1",
                          "", "", "1")  # fmt: skip
    afternoon.species("House Finch", "Haemorhous mexicanus", "5")
    afternoon.species("Rock Pigeon (Feral Pigeon)", "Columba livia (Feral Pigeon)", "12")
    afternoon.species("Mallard (Domestic type)", "Anas platyrhynchos (Domestic type)", "3")
    ballona = Checklist("S1003", "US-CA", "Los Angeles", "L1002",
                        "Ballona Wetlands--Freshwater Marsh", "33.9688", "-118.4290",
                        "2024-04-14", "", TRAVELING, "60", "1", "1.5")  # fmt: skip
    ballona.species("Snowy Egret", "Egretta thula", "2")
    ballona.species("Western Gull", "Larus occidentalis", "10")
    ballona.species("Pinkish Warbler", "Setophaga rosea", "1", details="Not a real bird")
    backyard = Checklist("S1004", "US-CA", "Orange", "L1003", "Backyard", "33.6600",
                         "-117.9000", "2024-04-15", "08:00 AM", CASUAL, "", "0")  # fmt: skip
    backyard.species("Dark-eyed Junco (Oregon)", "Junco hyemalis [oreganus Group]", "1")
    backyard.species("Red-tailed Hawk", "Buteo jamaicensis", "1", breeding="F Flyover (F)")
    marin = Checklist("S1005", "US-CA", "Marin", "L1004", "Muir Woods", "37.8970",
                      "-122.5810", "2024-04-20", "10:00 AM", AREA, "45", "1", "", "2.5",
                      "3")  # fmt: skip
    marin.species("Steller's Jay", "Cyanocitta stelleri", "2")
    marin.species("Yellow-rumped Warbler (Audubon's)", "Setophaga coronata auduboni", "4")
    pelagic = Checklist("S1006", "US-CA", "", "L1005", "Pelagic--Monterey Bay", "36.8000",
                        "-122.0000", "2024-04-21", "07:00 AM", PELAGIC, "240", "1",
                        "35.4", "", "20")  # fmt: skip
    pelagic.species("Western Gull", "Larus occidentalis wymani", "30")
    banding = Checklist("S1007", *madrona, "2024-05-01", "06:30 AM", BANDING, "180", "1",
                        "", "", "4")  # fmt: skip
    banding.species("Song Sparrow", "Melospiza melodia", "6")
    history = Checklist("S1008", "US-CA", "Los Angeles", "L1001", "Madrona Marsh Preserve",
                        "33.8250", "-118.3410", "1998-06-15", "", HISTORICAL, "", "0")  # fmt: skip
    history.species("Bald Eagle", "Haliaeetus leucocephalus", "1")
    flight = Checklist("S1009", "US-CA", "Los Angeles", "L1006", "Home (33.85, -118.35)",
                       "33.85", "-118.35", "2024-05-02", "09:15 PM", NOCTURNAL, "60", "1",
                       "", "", "1")  # fmt: skip
    flight.species("Swainson's Thrush", "Catharus ustulatus", "14")
    carara = Checklist("S2001", "CR-P", "", "L2001",
                       "Parque Nacional Carara--Sendero Laguna Meándrica", "9.7800", "-84.6000",
                       "2025-02-02", "06:15 AM", TRAVELING, "120", "1", "2.0", "", "2")  # fmt: skip
    carara.species("Common Ground Dove", "Columbina passerina", "3")
    carara.species("Lesser Nighthawk", "Chordeiles acutipennis", "1")
    carara.species("Scarlet Macaw", "Ara macao", "6", details="Pair at nest cavity",
                   breeding="ON Occupied Nest (ON)")  # fmt: skip
    poas = Checklist("S2002", "CR-A", "", "L2002", "Volcán Poás", "10.1900", "-84.2300",
                     "2025-02-20", "07:00 AM", STATIONARY, "", "1", "", "", "2")  # fmt: skip
    poas.species("Resplendent Quetzal (Costa Rican)", "Pharomachrus mocinno costaricensis", "1")
    poas.species("Clay-colored Thrush", "Turdus grayi", "3")
    dungeness = Checklist("S3001", "GB-ENG", "Kent", "L3001", "Dungeness RSPB", "50.9260",
                          "0.9640", "2023-09-10", "10:00 AM", TRAVELING, "120", "1", "3.0",
                          "", "4", "Lovely day; the café was open")  # fmt: skip
    dungeness.species("Eurasian Blackbird", "Turdus merula", "3")
    dungeness.species("European Robin", "Erithacus rubecula", "2")
    dungeness.species("Gray Heron", "Ardea cinerea", "1")
    dungeness.species("Great Tit", "Parus major", "4")
    dungeness.species("gull sp.", "Larinae sp.", "40")
    return [morning, afternoon, ballona, backyard, marin, pelagic, banding, history, flight,
            carara, poas, dungeness]  # fmt: skip


def write(path: Path, header: list[str], checklists: list[Checklist]) -> None:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for checklist in checklists:
        for row in checklist.rows:
            writer.writerow([row.get(column, "") for column in header])
    path.write_text(out.getvalue(), encoding="utf-8")


def hours_header() -> list[str]:
    renamed = {"Duration (Min)": "Duration (Hrs)", "Observation Details": "Species Comments"}
    return [renamed.get(column, column) for column in HEADER]


#: eBird Record Format rows (no header): common, genus, species, count, comments, location,
#: latitude, longitude, date, time, state, country, protocol, observers, duration (min),
#: complete, distance (miles), area (acres), checklist comments.
RECORD_ROWS = [
    ["Mallard", "Anas", "platyrhynchos", "4", "", "Madrona Marsh Preserve", "33.825",
     "-118.341", "04/13/2024", "07:15", "CA", "US", "traveling", "2", "95", "Y", "1.3", "",
     "Windy"],
    ["Mallard", "Anas", "platyrhynchos", "2", "Second flock", "Madrona Marsh Preserve",
     "33.825", "-118.341", "04/13/2024", "07:15", "CA", "US", "traveling", "2", "95", "Y",
     "1.3", "", "Windy"],
    ["Mallard (Domestic type)", "Anas", "platyrhynchos", "3", "", "Madrona Marsh Preserve",
     "33.825", "-118.341", "04/13/2024", "07:15", "CA", "US", "traveling", "2", "95", "Y",
     "1.3", "", "Windy"],
    ["Dark-eyed Junco", "Junco", "hyemalis oreganus", "X", "", "Madrona Marsh Preserve",
     "33.825", "-118.341", "04/13/2024", "07:15", "CA", "US", "traveling", "2", "95", "Y",
     "1.3", "", "Windy"],
    ["Greater/Lesser Yellowlegs", "Tringa", "melanoleuca/flavipes", "1", "",
     "Madrona Marsh Preserve", "33.825", "-118.341", "04/13/2024", "07:15", "CA", "US",
     "traveling", "2", "95", "Y", "1.3", "", "Windy"],
    ["Mallard x American Black Duck (hybrid)", "Anas", "platyrhynchos x rubripes", "1", "",
     "Madrona Marsh Preserve", "33.825", "-118.341", "04/13/2024", "07:15", "CA", "US",
     "traveling", "2", "95", "Y", "1.3", "", "Windy"],
    ["Mallerd", "Anas", "platyrhyncos", "5", "", "Ballona Wetlands", "", "", "04-14-24",
     "4:30 PM", "CA", "US", "stationary", "1", "0", "N", "", "", ""],
    ["Western Gull", "Larus", "occidentalis wymani", "10", "", "Ballona Wetlands", "", "",
     "04-14-24", "4:30 PM", "CA", "US", "stationary", "1", "0", "N", "", "", ""],
    ["Snowy Egret", "Egretta", "thula", "2", "", "Ballona Wetlands", "", "", "04/14/2024",
     "", "CA", "US", "area", "3", "45", "Y", "", "2.5", "Marsh walk"],
    ["Red-tailed Hawk", "Buteo", "jamaicensis", "1", "", "Backyard", "", "", "04/15/2024",
     "08:00", "CA", "US", "casual", "", "", "", "", "", ""],
    ["Anna's Hummingbird", "Calypte", "anna", "2", "", "Backyard", "", "", "04/16/2024",
     "08:00", "CA", "US", "incidental", "", "", "", "", "", ""],
    ["Scarlet Macaw", "Ara", "macao", "6", "", "Costa Rica", "", "", "02/02/2025", "06:15",
     "", "", "traveling", "2", "120", "Y", "1.2", "", ""],
    ["Steller's Jay", "Cyanocitta", "stelleri", "2", "", "Oregon", "", "", "05/01/2024",
     "09:00", "", "", "", "", "", "", "", "", ""],
    ["Gray Jay", "Perisoreus", "canadensis", "1", "", "Ontario", "", "", "06/01/2024",
     "", "", "", "historical", "", "", "", "", "", ""],
    ["Willow Ptarmigan", "Lagopus", "lagopus", "3", "Flushed [Denali Highway]", "Alaska",
     "", "", "06/20/2023", "", "", "", "", "", "", "", "", "", ""],
    ["Eurasian Blackbird", "Turdus", "merula", "3", "", "Dungeness RSPB", "50.926", "0.964",
     "09/10/2023", "10:00", "ENG", "GB", "traveling", "4", "120", "Y", "1.9", "",
     "Lovely day"],
    ["Common Ground Dove", "Columbina", "passerina", "3", "", "Carara", "", "",
     "02/02/2025", "06:15", "P", "CR", "traveling", "2", "120", "Y", "1.2", "", ""],
    ["Pinkish Warbler", "Setophaga", "rosea", "1", "", "Carara", "", "", "02/02/2025",
     "06:15", "P", "CR", "traveling", "2", "120", "Y", "1.2", "", ""],
    ["duck sp.", "Anatidae", "sp.", "4", "", "Carara", "", "", "02/02/2025", "06:15", "P",
     "CR", "traveling", "2", "120", "Y", "1.2", "", ""],
]  # fmt: skip
LIFE_2023 = [
    ["Row #", "Taxon Order", "Category", "Common Name", "Scientific Name", "Count", "Location",
     "S/P", "Date", "LocID", "SubID", "Exotic", "Countable"],
    ["1", "320", "species", "Mallard", "Anas platyrhynchos", "4", "Madrona Marsh Preserve",
     "US-CA", "13 Apr 2024", "L1001", "S1001", "", "1"],
    ["2", "2010", "species", "Rock Pigeon", "Columba livia", "X", "Home (33.85, -118.35)",
     "US-CA", "02 May 2024", "", "S1009", "N", "1"],
    ["3", "640", "species", "Ring-necked Pheasant", "Phasianus colchicus", "1", "Backyard",
     "US-CA", "15 Apr 2024", "L1003", "S1004", "Y", "1"],
    ["4", "30001", "species", "Dark-eyed Junco", "Junco hyemalis oreganus", "1", "Backyard",
     "US-CA", "15-Apr-24", "L1003", "S1004", "", "1"],
    ["5", "8000", "species", "Scarlet Macaw", "Ara macao", "6", "Carara", "CR-P",
     "02 Feb 2025", "L2001", "S2001", "", "1"],
    ["6", "29000", "species", "Eurasian Blackbird", "Turdus merula", "3", "Dungeness RSPB",
     "GB-ENG", "10 Sept 2023", "L3001", "S3001", "", "1"],
    ["7", "31000", "species", "Pinkish Warbler", "Setophaga rosea", "1", "Backyard", "US-CA",
     "16 Apr 2024", "L1003", "S1005", "", "1"],
    ["8", "28000", "species", "Swainson's Thrush", "Catharus ustulatus", "14",
     "Pond - 33.85x-118.35", "US-CA", "02-May-24", "", "S1010", "", "1"],
    ["9", "7000", "species", "Common Ground Dove", "Columbina passerina", "3",
     "Lake 9.78, -84.60", "CR-P", "01 Feb 2025", "", "S2002", "", "1"],
    ["10", "7100", "species", "Lesser Nighthawk", "Chordeiles acutipennis", "1", "",
     "CR-", "2 Feb 2025", "", "S2003", "", "1"],
]  # fmt: skip
LIFE_OLD = [
    ["Row #", "Species", "Count", "Location", "S/P", "Date"],
    ["1", "Mallard - Anas platyrhynchos", "4", "Madrona Marsh Preserve", "US-CA",
     "13 Apr 2024"],
    ["2", "Rock Pigeon (Feral Pigeon) (Columba livia (Domestic type))", "12",
     "Home (33.85, -118.35)", "US-CA", "02 May 2024"],
    ["3", "Anna's Hummingbird (Calypte anna)", "2", "Backyard", "US-CA", "15-Apr-24"],
    ["4", "Haliaeetus leucocephalus", "1", "Madrona Marsh Preserve", "US-CA", "15 Jun 1998"],
    ["5", "Scarlet Macaw", "6", "Carara", "CR-P", "02 Feb 2025"],
    ["6", "Common Ground Dove", "3", "Carara", "CR-P", "1 Feb 2025"],
    ["7", "Turdus merula", "3", "Dungeness RSPB", "GB-ENG", "10 Sep 2023"],
]  # fmt: skip
UNKNOWN_PLACE_ROWS = [
    ["Mallard", "Anas", "platyrhynchos", "1", "", "Somewhere Pond", "", "", "04/13/2024",
     "", "", "", "", "", "", "", "", "", ""],
]  # fmt: skip


def write_record(path: Path, rows: list[list[str]]) -> None:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8")


def without_observers(source: Path, target: Path) -> None:
    """The list with its observers left out: Pipit imports only into lists without them."""
    text = source.read_text(encoding="utf-8")
    text = re.sub(r"  <user [^>]*/>\n", "", text)
    text = re.sub(r' users="[^"]*"', "", text)
    target.write_text(text, encoding="utf-8")


def main() -> None:
    target = Path(sys.argv[1])
    bsxm = target.parent / "bsxm"
    without_observers(bsxm / "trip_report.bsxm", bsxm / "trip_report.no_observers.bsxm")
    target.mkdir(parents=True, exist_ok=True)
    checklists = my_data()
    write(target / "my_data.csv", HEADER, checklists)
    old = Checklist("S4001", "US-CA", "Los Angeles", "L1001", "Madrona Marsh Preserve",
                    "33.8250", "-118.3410", "2022-10-02", "08:45 AM", TRAVELING, "1.5", "1",
                    "0.8", "", "2")  # fmt: skip
    old.species("White-crowned Sparrow", "Zonotrichia leucophrys", "8", details="Back for winter")
    old.species("Black Phoebe", "Sayornis nigricans", "1")
    write(target / "my_data_hours.csv", hours_header(), [old])
    bad = Checklist("S5001", "US-CA", "Los Angeles", "L1001", "Madrona Marsh Preserve",
                    "33.8250", "-118.3410", "2024-02-30", "08:00 AM", CASUAL)  # fmt: skip
    bad.species("Mallard", "Anas platyrhynchos", "1")
    write(target / "my_data_bad_date.csv", HEADER, [bad])
    write_record(target / "ebird_record.csv", RECORD_ROWS)
    write_record(target / "ebird_record_unknown_place.csv", UNKNOWN_PLACE_ROWS)
    write_record(target / "life_list.csv", LIFE_2023)
    write_record(target / "life_list_old.csv", LIFE_OLD)
    cases = [
        {"name": "new_list", "list": NEW, "file": "my_data.csv"},
        {"name": "new_list_avilist", "list": NEW, "file": "my_data.csv",
         "display": "avilist"},
        {"name": "new_list_resolved", "list": NEW, "file": "my_data.csv",
         "taxa": {"Pinkish Warbler|Setophaga rosea": "spCardever"}},
        {"name": "hours", "list": NEW, "file": "my_data_hours.csv"},
        {"name": "bad_date", "list": NEW, "file": "my_data_bad_date.csv"},
        {"name": "trips_only_new", "list": TRIPS, "file": "my_data.csv"},
        {"name": "trips_all_dates", "list": TRIPS, "file": "my_data.csv",
         "onlyNewDates": False},
        {"name": "trips_drop", "list": TRIPS, "file": "my_data.csv", "onlyNewDates": False,
         "duplicates": "drop"},
        {"name": "trips_overwrite", "list": TRIPS, "file": "my_data.csv",
         "onlyNewDates": False, "duplicates": "overwrite"},
        {"name": "trips_avilist", "list": TRIPS, "file": "my_data.csv", "onlyNewDates": False,
         "display": "avilist", "duplicates": "drop"},
    ]  # fmt: skip
    record = [
        {"name": "record_new", "list": NEW, "file": "ebird_record.csv"},
        {"name": "record_new_avilist", "list": NEW, "file": "ebird_record.csv",
         "display": "avilist"},
        {"name": "record_resolved", "list": NEW, "file": "ebird_record.csv",
         "taxa": {"Pinkish Warbler|Setophaga|rosea": "spCardever"}},
        {"name": "record_trips", "list": TRIPS, "file": "ebird_record.csv",
         "duplicates": "drop"},
        {"name": "record_unknown_place", "list": NEW, "file": "ebird_record_unknown_place.csv"},
        # Pipit's own Save for eBird of trip_report.bsxm (checked against Scythebill's in
        # tests/ebird), imported back
        {"name": "record_export_new", "list": NEW, "file": "trip_report.ebird.csv"},
        {"name": "record_export_avilist", "list": NEW, "file": "trip_report.ebird.csv",
         "display": "avilist"},
        {"name": "record_export_back", "list": TRIPS, "file": "trip_report.ebird.csv",
         "duplicates": "drop"},
        {"name": "record_export_overwrite", "list": TRIPS, "file": "trip_report.ebird.csv",
         "duplicates": "overwrite"},
        {"name": "record_export_back_avilist", "list": TRIPS, "file": "trip_report.ebird.csv",
         "display": "avilist", "duplicates": "drop"},
    ]  # fmt: skip
    cases += [{**case, "format": "ebirdRecord"} for case in record]
    life = [
        {"name": "life_new", "list": NEW, "file": "life_list.csv", "format": "lifeList2023"},
        {"name": "life_avilist", "list": NEW, "file": "life_list.csv", "display": "avilist",
         "format": "lifeList2023"},
        {"name": "life_trips", "list": TRIPS, "file": "life_list.csv", "duplicates": "drop",
         "format": "lifeList2023", "taxa": {"Pinkish Warbler|Setophaga rosea": "spCardever"}},
        {"name": "life_old_new", "list": NEW, "file": "life_list_old.csv", "format": "lifeList"},
        {"name": "life_old_trips", "list": TRIPS, "file": "life_list_old.csv",
         "duplicates": "overwrite", "format": "lifeList"},
    ]  # fmt: skip
    cases += life
    lines = [json.dumps({"format": "myData", **case}, ensure_ascii=False) for case in cases]
    (target / "cases.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

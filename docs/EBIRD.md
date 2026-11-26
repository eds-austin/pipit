# eBird and CSV (M6)

## Save for eBird (Ctrl+Shift+E on the Reports screen)

`pipit/ebird/record_format.py` is a port of Scythebill's `EBirdCsvExport` and
`EbirdExportAction`: the Reports screen's query, run in Clements (eBird's taxonomy) at group
depth (subspecies become their group or species), written as eBird Record Format CSV, the
19 columns eBird imports, no header. Scythebill's file name is suggested
("eBird-export-Washington.csv", else "eBird-export.csv").

- **Which sightings.** Left out: no place; a place that is a built-in region or private; a
  record not accepted or of uncertain ID. A sighting without a full date is written as a
  "list-building" record: 1/1/1900, Incidental, "life-list building checklist".
- **Order.** Oldest first, then in Clements order. Ties keep the order of Scythebill's
  `getAllSightings()` (`QueryResults.all_sightings()`, Java `HashMap` order).
- **Columns.** Common name (" (hybrid)" added for hybrids), genus and species (a group's
  name after the species'), count ("X" when none), notes (quotes and line breaks replaced,
  a trailing "LL: lat,long" from BirdLasser imports trimmed), the place as eBird groups it
  ("Park--Trail"), coordinates to seven decimals, M/d/yyyy and HH:mm, state and country
  from the nearest places with eBird codes (with the United Kingdom's hyphenated codes
  split), then the visit's protocol (those eBird can't import swapped: pelagic to
  traveling, banding and nocturnal to historical, flight calls to stationary; one needing
  a start time with none to historical), observers, minutes, complete, distance in miles
  and area in acres (float32, Java's `Float.toString`), checklist comments.
- **Files.** Past 900K the rest go to "name-1.csv" and so on. Scythebill checks the bytes
  that have reached the file, which lag behind its writers' buffers;
  `JavaWriterBytes` models them (a 10,240-character `BufferedWriter`, then a UTF-8
  encoder writing 8K at a time; checked against the JDK on 3,000 lines), so files split
  at the same lines.
- **One difference.** Scythebill's export fails on a sighting with an impossible date
  (February 30, from an old import); Pipit leaves it out and says so.

**Checked against Scythebill.** PrintOracle's ebird mode runs `EbirdExportAction` on the 30
reference queries and everything in queries.bsxm, trip_report.bsxm and edge_cases.bsxm
(without its February 30 sighting): every file is byte-identical. On Eric's list (private,
`PIPIT_PRIVATE_EBIRD`), 269 exports (everything, which splits into four files, his saved
reports and every country) are identical, 281 files in all. Scythebill's own
`EBirdCsvExportTest` cases are ported (`tests/ebird`); its British-names case doesn't
apply, as Pipit writes eBird's English names.

## Save as Scythebill CSV (Ctrl+Shift+C on the Reports screen)

`pipit/csvio/scythebill_csv.py` is a port of Scythebill's `FullReportExport` and
`ScythebillCsvExportAction`: every detail of the query's sightings (in the display taxonomy,
at the screen's depth), one line each after a header, sorted by `MoreRecentComparator`
(ties in `getAllSightings()` order). Scythebill's file name is suggested
("export-<list>-<report>.csv", or today's date for a report without a name).

- **Columns.** Names (a group's or subspecies' common name is its group's, then the
  species' scientific name and its own), the taxonomic index (a sp. or hybrid ".5" after its
  last taxon), date and time as stored, count as written, sex and age, status (as
  Scythebill exports it), breeding code, photos ("[* name](uri)" lines), notes, the
  place's coordinates as stored, its description, then region, country, state, county and
  city (display names) and the rest of its places as "Location 1"... Then the visit's
  details once per visit, observers (abbreviations, then names), and the trip (notes once
  per trip; never an end time: Scythebill's parser keeps none).
- **"Location N" columns.** As many as the deepest place in the list needs, counted after
  Scythebill adds its predefined places when a file opens (`populated_tree` replays
  `PredefinedLocationPopulator`), so lists with nested built-in places get the same columns.
- **Excel-compatible** (Scythebill's import preference; `csv_excel_compatible`, off):
  spaces for line breaks.

`QueryResults.all_sightings()` orders keys as Guava's `ArrayListMultimap` does: it makes
its `HashMap` with `HashMap.newHashMap(12)`, a table of 16 (found when two sp.s on Eric's
list came out swapped; checked against the JDK).

**Checked against Scythebill.** PrintOracle's csv mode: 45 exports on three lists (the 30
reference queries; everything in both taxonomies, at every depth, Excel-compatible) are
byte-identical, and 74 on Eric's list (private, `PIPIT_PRIVATE_CSV`).

## Importing sightings (Ctrl+K, "Import sightings")

The file eBird's "Download My Data" sends (the .zip, or the `MyEBirdData.csv` in it), read
as Scythebill's `EBirdMyDataImporter` reads it and imported as `ImportController` does
(`src/pipit/imports/`). The dialog asks Scythebill's questions in turn, then shows what will
change before anything is stored:

1. **Only the new dates?** My Data holds the whole account, so when some of its dates already
   have sightings in the list, Pipit offers just the others (Enter); if every date has, it
   asks whether to import anyway.
2. **Names Pipit didn't recognize**, one at a time: type a species and Enter picks it (its
   subspecies too, if the file names one there), or Leave out (Ctrl+L). eBird's "sp." rows
   ("duck sp.") are left out without asking, as in Scythebill.
3. **Sightings already in the list** (same date, time and species): leave them out, replace
   them, or import them too.
4. **Review**: sightings to add and replace, new places (listed), checklists, and notes (rows
   not imported, which can be saved next to the file as `<name>-failed.csv`; places of yours
   given coordinates or a hotspot; sp. rows left out). Import makes a backup snapshot, then
   stores everything as one undo step (Ctrl+Z takes it all back).

How names and places are matched is Scythebill's: `TaxonResolver` (exact names, near common
names within one letter, the genus, alternate names, "A/B" and "A x B"; a doubtful match is
kept only if some checklist where it was seen has it), `LocationShortcuts`, `LocationAliases`
and `ImportedLocation` (state and county codes, built-in counties, "Park--Trail" grouped
names), with every predefined place present as `PredefinedLocationPopulator` leaves them.
Scythebill's tables of place aliases and translated country names are in the data pack.

Scythebill's ways, kept so the list comes out the same:
- The count is read from the fifth column, wherever "Count" is.
- The number of observers is read from the importer's second reading of the columns on (a
  typo skips it once); since it always reads them more than once, party sizes are imported.
- A protocol that needs a start time, on a checklist without one, becomes historical; one
  missing a required field (a stationary count without a duration) too.
- Places are made for every row, even rows on dates left out; the new ones nothing uses are
  removed again, but built-in places stay marked as used (saved, empty).
- A place of yours that gets coordinates or a hotspot moves to the end of its parent's places
  (Scythebill replaces it with a copy).
- Checklist details are added in Java `HashMap` order of their keys.

Where Pipit differs: Scythebill counts duplicates with a Bloom filter (Pipit exactly; only
which question is asked could differ); a file without a "Number of Observers" column makes
Scythebill's import fail (Pipit imports it without party sizes); a name like "Mallard x
Mallard" makes Scythebill's import fail (Pipit imports a Mallard). Lists with observers are
refused for now (Scythebill asks which observers saw the sightings).

### Other eBird files

The same command reads the file type from its first row, as Scythebill's
`EBird.chooseImporter` does: a "Checklist Comments" column is My Data; "Row #" with "S/P"
and "LocID" is a life list (with "Countable", the 2023 form); anything else is the Record
Format. (eBird's checklist download, which starts "Species", comes with the checklist
download in 6d.)

- **Record Format** (`EBirdImportImporter`; what eBird imports and Save for eBird writes: 19
  columns, no header). Distances are miles and areas acres (converted as Scythebill does, in
  float32); a duration of 0 counts as given (kept in memory, never written); names are matched
  within two letters, a subspecies taken from the common name's last brackets or the species
  column's last word. With no country code, the place may name a country or a US or Canadian
  state, and old Birder's Diary files put a place in brackets in the comments. Scythebill
  treats it as a mass export but never narrows it to new dates, so Pipit only asks the "every
  date is in your list already" question. A place with no country Scythebill asks the user to
  locate (and may look up online); Pipit refuses the file for now.
- **Life lists** (`EBird2023LifeListImporter`, `EBirdLifeListImporter`): each species' first
  sighting, dated "05 Mar 2024" (English month names, "Sept" too), with coordinates written
  into place names ("Pond (12.34, -56.78)", "Pond - 12.34x-56.78", "Pond 12.34, -56.78").
  "Exotic" rows are introduced but not established. The older form has one name column, which
  may be the common name, the scientific name, or both ("Mallard - Anas platyrhynchos",
  "Mallard (Anas platyrhynchos)"). No date questions, no checklist details.

- **Scythebill CSV** (`ScythebillImporter`; Save as Scythebill CSV, or a spreadsheet with
  its headers, found ignoring case and spaces). A checklist's details are gathered from all
  its rows, in file order, "Complete list" true when there's no such column, a duration from
  start and end times when there's none; a place given more than one set of coordinates gets
  them in each sighting's description ("LL:lat,long"); rows without a name are skipped; no
  introduced or domestic status is added; a place that can't be made, or a row with no place,
  leaves its rows not imported. Trips come from the trip columns (`TripImporter`): the existing
  trip holding the row's dates at its place or one above (taking its name if it has none,
  its dates if it's the only one within them, and the row's notes, links and photos), else a
  new one (Scythebill's trip IDs); only an undated sighting goes on its trip, as in Scythebill.
  A trip's end time isn't kept. Dates not in Scythebill's own form are read in forms guessed
  from the file (`LocalDateFormatterChooser`, `pipit/imports/date_formats.py`: dates grouped by
  separators, patterns narrowed on each group, ties by month-before-day order); as in
  Scythebill, the header's own "Date" takes part (so a month name alone reads as a month), and
  "05-Mar-2024" reads as March 2024, its "05" taken for a month. Not yet: observers, and
  places given only as location text (Scythebill's `FreeformLocationResolver`); such files are
  refused with a message.

Found on the way: Scythebill dates an undated sighting on a trip by the trip's start, for
duplicates too; and when the import's clean-up removes a new place nothing ended up using,
its checklist details move to the place above (`ReportSet.deleteLocation`). Pipit does both.
And one more Scythebill bug: a new trip without a name never imports (it names it after its
place, but has walked that place up to nothing first), so those rows aren't imported; Pipit
leaves them out too.

**Checked against Scythebill.** `tools/oracle/ImportOracle.java` runs Scythebill's importer
with the choices made in advance and saves the list. 37 cases on made-up files
(`tools/oracle/make_import_fixtures.py`): My Data (every protocol, groups, forms, subspecies,
sp., slash and hybrid names, repeated rows, an unknown name, built-in counties, a county the
list has under another name, a bad date), the Record Format (a file of edge cases, one with a
place without a country, and `trip_report.bsxm`'s own Save for eBird imported back), both
life lists and Scythebill CSV (files of edge cases and of dates in other forms, and five fixture lists' own Save as
Scythebill CSV via `tools/oracle/export_scythebill_csv.py`, trips included), into a new list and into `trip_report.bsxm` (only new dates, all dates, drop,
replace, AviList), come out byte-identical, with the same counts; each is also stored,
exported and undone. 21 more on files made from Eric's list (private,
`PIPIT_PRIVATE_IMPORT`): My Data (`tools/oracle/my_data_from_list.py`, 8,397 rows), his whole
list through Save for eBird (23,632 rows) and Save as Scythebill CSV, and his life list
(`... life`, 3,546 species), into a
new list, into his own (drop, replace, import all) and into the trip list.

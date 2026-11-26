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

## Import from eBird (My Data) (Ctrl+K, "Import from eBird")

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

**Checked against Scythebill.** `tools/oracle/ImportOracle.java` runs Scythebill's importer
with the choices made in advance and saves the list. Ten cases on made-up exports
(`tools/oracle/make_import_fixtures.py`: every protocol, groups, forms, subspecies, sp.,
slash and hybrid names, repeated rows, an unknown name, built-in counties, a county the list
has under another name, a bad date), into a new list and into `trip_report.bsxm` (only new
dates, all dates, drop, replace, AviList) come out byte-identical, with the same counts; each
is also stored, exported and undone. Seven more on a My Data file made from Eric's list
(`tools/oracle/my_data_from_list.py`, 8,397 rows; private, `PIPIT_PRIVATE_IMPORT`), into a new
list, into his own (drop, replace 8,418, import all) and into the trip list.

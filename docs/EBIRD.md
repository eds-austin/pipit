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

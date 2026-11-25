# Queries

M5's first slice: Scythebill's query engine, ported so that a stored query gives exactly
Scythebill's totals and taxa. The Reports screen, Home figures and outputs build on it.

## What a query is

A stored query is Scythebill's JSON, kept in the list's preferences and read unchanged:
`{"fields": [{"type", "value", "bool"}]}` (older files have one top-level "type" in place
of each field's "bool"). Fields combine as in Scythebill's `CompositeQueryDefinition`:
every ALL field must match; at least one ANY field must match; a NEVER field excludes
every taxon it ever matches; the NEVER_ALL fields together exclude the taxa they all match
at once.

Every field type is supported, read exactly as Scythebill's Gson reads it:

| Type | What it tests |
|---|---|
| LOCATION | in, not in, is, is not, nearer than (km or miles, haversine), not set; also Scythebill's 28 synthetic regions (`***aba***` and so on) |
| DATE | during, between (including "December to February" across the year), after, before, this year, today, not during, not set; a trip sighting without a date uses its trip's dates |
| ALLOW_HEARD_ONLY | heard only or not |
| PHOTOGRAPHED | has a photo, or a favorite photo, or not |
| SIGHTING_STATUS | is or is not a status |
| SPECIES_STATUS | IUCN status is, is not, or is at least as threatened (introduced, domestic and undescribed never match) |
| SIGHTING_NOTES, VISIT_COMMENTS | contains, doesn't contain, is exactly, starts with a word; case-sensitive or not |
| BREEDING_CODE | is, is not, is at least (Scythebill's level order) |
| SP_OR_HYBRID | is or is not a sp., hybrid, or neither (at the query's depth) |
| SEX_AGE | male, female, adult, immature |
| SUBSPECIES_ALLOCATED | allocated to a subspecies, or not |
| FIRST_SIGHTINGS | lifers (first sightings) highlighted or only them, optionally within a nested query (such as a place) |
| TIMES_SIGHTED | exactly, at most, at least, fewer or more than N countable sightings |
| FAMILY | in or not in a family or order |
| USER | includes, doesn't include, is only an observer, or has none |

A query Scythebill refuses (an unknown place, observer, status or field) is refused.

## Counting

Which sightings count is Scythebill's `QueryPreferences`, with its defaults: introduced,
provisional and heard-only birds count; restrained birds and undescribed forms don't;
escapes, uncertain IDs, unsatisfactory views, dead birds, signs only, domestic birds and
birds not seen by you never count. A query with its own status field drops the status
rule; one with its own heard-only field sets the heard-only rule.

The totals are those of Scythebill's Reports screen (`QueryResults`): species, species
plus sp. entries that add a species, groups, subspecies, spuhs, families and sightings, at
the query's depth (species, group or subspecies) and in the display taxonomy (AviList or
Clements). The taxa come in Scythebill's order, with a family heading before each family
and a sp. right after the last of its taxa.

## Checked against Scythebill

`tools/oracle/QueryOracle.java` runs a stored query through Scythebill's own headless path
(`StoredQueries.restore`, `CompositeQueryDefinition.forValues`, the countable predicate,
`QueryProcessor` as the Reports screen calls it) and prints every total and the ordered
taxa with their countability. Pipit must match each one exactly:

- 30 reference queries (`tests/fixtures/oracle/queries.txt`, covering every field type and
  operation) on a seeded 6,000-sighting list (`tools/oracle/make_queries_fixture.py`), in
  Clements and AviList, at species, group and subspecies depth: 120 results, all equal;
- every synthetic region (`regions.txt`) on a list with real built-in places;
- Eric's list (private, never stored): his three stored queries, one of them ABA, and the
  20 reference queries that don't depend on the test list, in Clements and AviList: all
  equal.

Scythebill itself fails on a sighting AviList can't map (its `QueryProcessor` dereferences
a null), so the test list leaves those out; Pipit skips them.

## Speed

On Eric's list (23,813 sightings): loading the list for queries takes 0.17 s; after the
first query (which fills the caches, up to 0.15 s), each query takes 20 to 96 ms, about
25 ms on average. Sightings are resolved into the display taxonomy once and cached per
depth; the taxa list is ordered by sorting on precomputed taxonomy positions.

## The Reports screen (Ctrl+6)

Three panes: the query, the species it finds, and the sightings of the chosen one.

- **Query.** One card per condition: And, Or, Never or Never All; the field (in
  Scythebill's menu order); its comparison; and what it needs: a place (with the synthetic
  regions) or family or observer picked by typing, dates as partial dates ("2024",
  "2024-05", "M12"), a status, a text, a count, or a distance. A new list starts with one
  Location condition; "Add condition" (Ctrl+Shift+A) adds the first field not used yet,
  as Scythebill does. "Show" chooses species, groups or subspecies.
- **Results.** The query reruns 150 ms after any change. The heading is Scythebill's own
  totals line ("Total species: 3,495 (8 "sp.")", with groups and ssps at those depths),
  then families and sightings. Families head their species; taxa with no countable
  sighting are gray and marked; lifers are marked when the query highlights them. Ctrl+R
  goes into the results; Up and Down skip the headings.
- **Sightings** of the chosen taxon, newest first, with place, count, flags, status and
  notes.

The query is kept as the very JSON Scythebill stores: each field's type, value and bool
in that order, each value's keys in its Scythebill class's order, numbers as Gson writes
them, so a saved query reads back in Scythebill unchanged. A query Scythebill would
refuse (an unknown place, say) shows why instead of a total.

## Saved reports

Scythebill's stored queries, shared both ways: a report saved in either app shows in the
other, with the same name, place in the list, and JSON.

- **Where they live.** The list's preferences (`<prefs>` in the .bsxm), under
  `StoredReportSetQueriesPreferences.storedQueries`: a JSON array of `{name, json, type}`
  kept as a string. Pipit reads it as `StoredQueries.restoreFromPreferences` does (a
  missing type is a report unless the JSON starts `COUNTRY/`, `STATE/` or `COUNTY/`; each
  query canonicalized, legacy top-level "type" pushed down to each field's "bool"). Saving
  rewrites only that key, as `ReportPreferencesManager.save` does: Gson's pretty printing,
  its HTML-safe escapes (`=` as `=` and so on), and every other preference written
  back as Gson writes what it read.
- **On the Reports screen.** "Saved reports" heads the query pane. Enter (or the play
  button) loads one into the query; the loaded one is marked, and "Edited" once the query
  differs. Ctrl+S saves the query under a name (a taken name replaces that report in
  place, as in Scythebill); F2 renames; Delete deletes after asking; Alt+Up/Down moves.
  Each is one undo. Total-ticks reports are listed and kept, but run only in Scythebill.
- **Checked against Scythebill.** `tools/oracle/StoredQueriesOracle.java` runs Scythebill's
  own `StoredQueries` (restore, add, replace, total ticks, remove, rename, move) on a list
  with stored queries in every form (`make_stored_queries_fixture.py`): Pipit restores the
  same queries and, after the same edits, writes the same file byte for byte (nine cases).
  On Eric's list (private), his stored queries restore identically, an added one gives
  Scythebill's exact file, and each loads into the query builder and writes back
  unchanged.

Scythebill's own restore writes the queries back without their type (but doesn't mark the
list changed), which is why older lists have none; Pipit writes the type, as Scythebill's
saving does.

## Home (Ctrl+1)

- **Figures.** The life list, this year, then every saved report in its saved order (up to
  twelve): each a real query with the Reports screen's counting (species and families, in
  the display taxonomy). Arrows choose one; Enter or a click opens it in Reports (a saved
  report loads as itself). A report Pipit can't run shows a dash and says so; total-ticks
  reports aren't figures. Choosing which reports appear (pinning) can come later; for now
  the saved order decides.
- **Recent visits.** The eight newest place, date and time groups of sightings; Ctrl+R goes
  in, Enter edits the visit in Enter Sightings.
- **Backups.** When the newest backup was made, and how they are kept.

Figures are counted on a worker thread with its own read-only connection and query
context, so Home never holds up the window: on Eric's list the window waits about 15 ms
and the figures follow about half a second later. Home only counts while it is showing;
changes made elsewhere are counted when it next shows.

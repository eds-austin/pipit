# Special reports (Ctrl+7)

The Special screen holds Scythebill's analytical reports. The report list on the left shows
which ones exist so far (Alt+1 to Alt+4 switch between them); the others are marked
"Soon".

## Family report

How many of each order's, family's or genus's species you've seen, out of the species
possible. This is Scythebill's family report (`FamilyReportPanel`), ported in
`pipit.special.family`.

- **The query is the Reports screen's.** In Scythebill the family report has its own query
  panel. Pipit counts the query you've built on the Reports screen ("Edit query" or
  Ctrl+Shift+Q goes there). It counts again when the query or the list changes, but only
  while the Special screen is shown.
- **What's possible.** The checklist comes from the query's places:
  - One place uses its own checklist.
  - Several places use their checklists merged (synthesized from the built-in checklists'
    codes, as `ChecklistSynthesizer` does).
  - A place without a checklist (a park, say) uses the nearest built-in checklist above it,
    and the report names that place.
  - With no place, every species in the world counts.

  A species counts as possible if you've seen it (countably, by the query). Otherwise it has
  to meet three conditions:
  - It's on the checklist, with a status the counting preferences don't leave out (only
    escaped species are left out by default).
  - It isn't undescribed (extinct species are shown).
  - The query's family and IUCN-status rows accept it, as `QueryPanel.getTaxonEligibilityPredicate`
    combines them: rows of one kind join with "or", and "never" rows exclude.
- **Grouping and sorting.** Group by order, family or genus (Ctrl+G cycles). Sort by
  taxonomic order, species seen, fraction seen, species unseen or total species, highest or
  lowest first. Ties fall back to the other count, then to taxonomic order, as in
  `FamilyReportTotals.sorted`.
- **A group's species.** Choosing a group (Ctrl+R, then Up/Down) lists its possible species
  in taxonomic order, with the seen ones checked. Scythebill opens a species browser with
  their sightings here; Pipit only lists the species for now.

Defaults are Scythebill's: introduced species count, undescribed species don't, and extinct
species are shown. Pipit has no settings for these yet.

### Checked against Scythebill

PrintOracle's family mode (`tools/oracle/PrintOracle.java`, run from `tools/oracle/run.sh`)
runs Scythebill's own computation: `resolveScope`, `seenSpeciesIds`, `speciesFilter`, and
`FamilyReportTotals.compute` at all three levels. It runs on
`tests/fixtures/bsxm/trip_report.bsxm`, for 11 queries in Clements and AviList
(`make_family_cases.py`):
- the world
- a country, a state, and a park
- a country and a state together
- family "is in", "is not in", and "never"
- two families joined with "or"
- an IUCN status "or worse"
- a date range

For all 22 cases, Pipit's places, checklist, and each group's seen and total species are
identical (`tests/special/test_family_against_scythebill.py`). On Eric's list (private), 18
cases are identical:
- the world, the US, California, Costa Rica, and North America
- the hummingbirds and Near Threatened-or-worse species
- the US without passerines
- the US or Costa Rica

Each case runs in under 0.4 s.

## Checklist status

The species you've seen at places with a checklist, whose status on that checklist is the
one you choose: not on the checklist, rarity, endemic, escaped, extinct, introduced or
provisional. This is Scythebill's `ChecklistStatusReportPanel`, ported in
`pipit.special.checklist_status`.

- **Which places.** Every place with its own checklist counts: a built-in one, or one you
  made. A sighting counts at its place and at each place above it that has a checklist.
  Checklists merged from others (the US outside North America, a region, a synthetic
  region) are left out, as in Scythebill.
- **Which sightings.** Sightings recorded as uncertain, domestic, not accepted, or
  introduced but not established are left out. A subspecies or group counts as its
  species. A sp. or hybrid of several species is left out.
- **The list.** Places are listed in the list's own order, depth first. Your own checklists
  are marked "Your checklist". Under each place come its species in taxonomic order, with
  their expected range. Enter, or a double-click, shows the place on the Locations screen.
- **Not on the checklist** adds Scythebill's warning that these may be mistakes in your
  data.

Pipit's wording differs from Scythebill's. It leaves out the request to mail
support@scythebill.com.

### Checked against Scythebill

PrintOracle's status mode runs `showReport`'s steps for every status in both taxonomies.
It runs on `tests/fixtures/bsxm/checklist_status.bsxm` (`make_checklist_status_fixture.py`),
which is the Costa Rica trip plus:
- your own checklists at Carara (every status, some species left off) and La Selva
- species far from Costa Rica, plain, introduced, and with each skipped status
- a subspecies, and a sp. of two subspecies, of a species not on the checklist
- a sp. of two species, and an extinct species
- a Costa Rica species in California

The report finds every status somewhere in the fixture. All 14 runs are identical: the
places, their order, built-in or yours, and the species and their order
(`tests/special/test_checklist_status_against_scythebill.py`). On Eric's list (private),
all 14 are identical, covering up to 29 places.

The first run loads the checklists, which takes about 1.2 s on Eric's list. After that, each
run takes 0.05 s, because the screen keeps the loaded checklists until the list changes.

Scythebill's report fails on a list whose custom checklist names a taxon the taxonomy
doesn't have (`ClementsChecklist.createTaxaMap`). `tests/fixtures/bsxm/checklists.bsxm` has
one such entry. Pipit leaves such entries out.

## Splits and lumps

How the species your query finds would count in another taxonomy version: species gained
by splits, species lost by lumps, and those that might be either. This is Scythebill's
`SplitsAndLumpsProcessor` and the version list of `SplitsAndLumpsPanel`, ported in
`pipit.special.splits_lumps`. Like the family report, it uses the Reports screen's query.

- **Versions.** A Clements list compares against AviList 2026 and every older Clements
  version back to 6.5 (December 2010). An AviList list compares against Clements 2026 and
  AviList 2025.
- **Tables.** Each version's table is Scythebill's `report-<version>.csv`. Each row is one
  "bundle" of old names and current species. The data pack keeps the tables (built from
  Scythebill's app resources). A pack built before they were added says so, and asks for a
  rebuild with `pipit-build-pack`.
- **Counting.** Each countable sighting at species depth is placed in its bundle:
  - A sighting that maps to one old name makes that name known.
  - A sighting that could be several old names makes them possible.

  Comparing the bundle's current species with its known and possible old names gives
  splits, lumps, possible splits, possible lumps, and "unknown" bundles that could be a
  lump, a split, or neither. A sp. whose species all lie in one bundle adds to the range of
  species unresolved sp.'s may stand for. If it's all you have of that bundle, it's listed
  as a split you have only a sp. of.
- **Wording.** The totals line and the sentences are Scythebill's: "Gained", "Lost",
  "is now", "Some or all of ... are now". The totals' parts are separated with " · ".

### Checked against Scythebill

PrintOracle's splits mode runs `SplitsAndLumpsProcessor.process` for every version each
taxonomy offers. It runs on `tests/fixtures/bsxm/queries.bsxm` (6,000 sightings), for the
whole list, one state, and the list without another state, in both taxonomies
(`make_splits_cases.py`). That makes 54 runs (16 Clements versions and 2 AviList versions
per query). Pipit's splits, lumps, possible ones, current species, old names, order and
counts are identical in every run (`tests/special/test_splits_against_scythebill.py`),
with up to 120 splits in one version.

On Eric's list (private), all 36 runs are identical, with up to 106 entries in one version.
All 16 Clements versions take 1.7 s together, about 0.1 s each.

The fixtures have no bundle that may be either a lump or a split.
`tests/special/test_splits_parts.py` checks that case, the fewest species unresolved sp.'s
stand for, and the sentences.

## Year comparison

Each species the query finds, year by year. This is Scythebill's `YearComparisonProcessor`,
with the year range and sorts of `YearComparisonPanel`, ported in
`pipit.special.year_comparison`. Like the family report, it uses the Reports screen's query.

- **Years.** The years run from the first sighting with a year to the last, at most a
  century. A sighting counts in a year when both its dates fall in that year. A trip
  sighting without a date of its own takes the trip's dates.
- **From and to.** The fields limit the sightings to a range of years, as Scythebill's
  panel does. A species' first year ever still comes from the whole query, so a species
  seen before the range isn't "new" in its first year within it.
- **Species per year.** The strip above the grid has a bar per year, counting single
  species only (sp.'s and hybrids are rows in the grid, but don't count). Click a year, or
  use Left and Right, to choose it. Esc clears it.
- **The grid.** Each species' cells are shaded by Scythebill's buckets: 1 sighting, 2–4,
  5–19, and 20 or more. Pointing at a cell shows that year's sightings and their earliest
  and latest dates.
- **Filters.** With a year chosen, you can show only species new that year (first seen
  ever), or only those missing that year (sp.'s and hybrids are left out of "missing").
- **Sorts.** Most sightings (the default), most years, newest, longest unseen, or
  taxonomic order. Ties keep taxonomic order.

Half years (H1 and H2) and the days each sighting is drawn on are computed and checked,
but not shown yet.

Not ported yet:
- the strip's "year lists" mode (each year's first-seen days)
- the species detail pane
- saving as a spreadsheet
- the suggested places to compare

### Checked against Scythebill

PrintOracle's years mode runs `YearComparisonProcessor.process` with the panel's year range
(`SightingPredicates.afterOrEquals` and `beforeOrEquals`). It runs on
`tests/fixtures/bsxm/queries.bsxm`: forty years of sightings, some dated only by month or
year. There are 12 cases (`make_years_cases.py`):
- the whole list and one state
- a range of years, a start year only, and an end year only
- a state within a range

Each case runs in both taxonomies. For every species, Pipit's years match exactly:
- sightings, earliest and latest dates per whole year and half year
- totals and first year ever
- drawn days

The species counted per year and the first-seen days match too
(`tests/special/test_years_against_scythebill.py`; the recorded results are gzipped).

On Eric's list (private), all 4 cases are identical:
- the whole list, in both taxonomies
- 2015–2024 in AviList
- up to 2010 in Clements

They cover up to 3,509 species rows, and each runs in 0.2–0.7 s.

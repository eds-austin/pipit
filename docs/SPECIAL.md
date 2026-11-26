# Special reports (Ctrl+7)

The Special screen holds Scythebill's analytical reports. The report list on the left shows
which ones exist so far (Alt+1 and Alt+2 switch between them); the others are marked
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

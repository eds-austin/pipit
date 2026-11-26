# Special reports (Ctrl+7)

The Special screen holds Scythebill's analytical reports. The report list on the left shows
which ones exist so far; the others are marked "Soon".

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

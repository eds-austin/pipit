# Browsing: species, locations and trips

Species and Locations came with M4; Trips and custom checklists with M4.1.

## Species (Ctrl+3)

Three panes: the display taxonomy as a list, the chosen species' sightings, and the chosen sighting.

- **List.** Families are headings. Each species shows its number of sightings, bold when seen and italic when not, as in Scythebill. "Seen only" (Ctrl+Shift+A) switches between what you've seen and the whole taxonomy. Filter with Ctrl+F or `/`, or just start typing; it matches common and scientific names. Entries come from the same roll-up as the Locations screen: subspecies and groups count as their species, and a sp., hybrid or genus-level record is its own entry where it falls in taxonomic order. Another taxonomy (mammals) follows the birds.
- **Sightings.** Newest first, with place, time and count. A caption line shows the record when it is narrower than the entry (a subspecies, or in AviList an AviList subspecies sp.), plus flags, status, trip and notes. In AviList, Scythebill's Andean Duck is listed under Ruddy Duck, because AviList treats it as a sp. of two Ruddy Duck subspecies.
- **The sighting.** Count (empty or "x" for present), status, breeding code, notes and the six flags, with Scythebill's labels. Enter or Ctrl+S saves as one undo step and returns to the list. Esc puts the fields back. "Edit its visit" (Ctrl+E) opens the visit in Enter sightings, which is where place, date and species change, as in Scythebill. Ctrl+Delete deletes the sighting (its observers and photos go with it, and Ctrl+Z brings it all back).

Speed on Eric's list (3,495 species seen; 11,650 in AviList): the whole-list roll-up takes 0.15 s after each change, and a filter change 0.13 s. Moving through all 11,650 rows, including a full redraw, stays within 20 ms for each step: End, Home, PageDown, Down.

## Locations (Ctrl+4)

Three panes: the place tree, what was seen in the chosen place, and the place itself.

- **Tree.** Every place in list order, with the number of sightings in it and in every place inside it. Continents start open. Filter with Ctrl+F or `/`, or just start typing: matches stay visible with the places they are in.
- **Seen in.** One row per species in the display taxonomy (AviList or Clements, from Settings), in taxonomic order, with its number of sightings and the first and latest dates. Subspecies and groups count as their species. A sp. or hybrid row stays its own row and doesn't add to the species total. Species of an embedded taxonomy (mammals) are listed after the birds and counted separately ("+ 32 in other taxonomies"). The pane refreshes 120 ms after the selection settles, so holding an arrow key stays smooth.
- **The place.** Kind, built-in status, eBird code, coordinates, hotspot, notes, the actions with their keys, and its own visits (eBird checklists) with protocol, effort and the number of sightings on that date. Ctrl+E goes into the visits, and Enter (or a click) opens one in Enter sightings for editing (see ENTERING.md).

Keys: Up/Down choose; Right opens a place (again: the first place inside); Left closes it (again: goes up); Enter or Tab into the species list, Esc or Shift+Tab back; Insert new place inside; F2 edit; Delete; Ctrl+M move; Ctrl+Shift+M merge. All are in F1.

### Changes follow Scythebill's rules

Each change is one undoable action (one Ctrl+Z), using `pipit.storage.location_ops`. Each one was checked against Scythebill's own result on the locations fixture (`tools/oracle/LocationOps.java`, see docs/TESTING.md):

- **Delete** only a place with nothing inside it. Built-in places with an eBird code can't be deleted, apart from Scythebill's short allowlist. Its sightings move to the place it is in and go to the end of the list, as Scythebill re-adds them. Its visits move too, unless the parent already has a visit at that date and time, in which case they are dropped (as in Scythebill). Its trips move as well, and its own checklist is removed.
- **Merge** moves everything (sightings, visits, trips, places inside it) into the chosen place. A place inside that has the same name as one already there is merged into it too.
- **Move** into another place. If a place with the same name is already there, the two are merged.
- **Edit** coordinates (both or neither), notes, private flag and eBird hotspot. Only your own places can be renamed. A new name must not clash with a sibling.
- Built-in places can't be moved or merged away from the screen. They mirror eBird's regions.

### A place's own checklist (Ctrl+L)

"Edit its checklist" (or "Start a checklist") opens Scythebill's checklist editor: the species in taxonomic order with their status. Up and Down choose a species. Digits 0–7 set its status, in Scythebill's order and words (Regular, Introduced, Provisional, Not established, Rarity, Rarity from introduced pop., Endemic, Extinct). Delete takes it off. Typing (or Ctrl+J) adds a species, and Enter adds the match. Nothing is stored until Ctrl+S, which saves as one undo step. Esc closes, asking twice if there are unsaved changes. "Delete checklist" removes it, and the place then uses the checklist of the place it is in.

Saved as Scythebill saves them (`EditChecklistPanel`): it rebuilds the checklist as a Java `HashMap` and writes it in that map's order, not the order shown. Pipit reproduces that order (`pipit.domain.java_hash`: Java string and list hashes, Guava's `newHashMapWithExpectedSize`, `HashMap` buckets). Five cases match Scythebill byte for byte (`tools/oracle/ChecklistOps.java`). On Eric's list, re-saving all 18 checklists (7,952 entries, in AviList) unchanged gives exactly Scythebill's file. A new checklist goes after the others.

Not yet: making a checklist from your sightings (it needs M5's query engine), from pasted text, or from eBird.



`location_closure` (schema 3) holds every (ancestor, descendant, depth) pair, so "everything in this place" is one join. Triggers keep it current on insert, delete and re-parenting, including while undo and redo replay their statements. It isn't journaled itself. The integrity check on open compares it with a fresh walk of the tree. The location-operations fuzz test checks it after every random add, move, merge, delete and rename, and after every undo and redo.

### Speed (Eric's list: 674 places, 23,813 sightings)

The tree builds in 8 ms. The largest "seen in" (North America, about 1,100 rows) takes under 0.1 s.

## Trips (Ctrl+5)

Three panes: trips, the species seen on the chosen trip, and the trip itself.

- **Trips** newest first, in Scythebill's order (`comparePartialDates` reversed). Filter by name or notes with Ctrl+F or `/`, or just start typing.
- **Species seen on the trip**: its own sightings, plus any sighting inside its place (anywhere, if it has none) within its dates (Scythebill's `isPartOfTrip`, with `afterOrEquals` / `beforeOrEquals` ported). An undated sighting on a trip takes the trip's dates. Elsewhere it shows as "1 Jul 2026 – 8 Jul 2026", as Scythebill's detailed rows do.
- **The trip**: F2 edits name, dates (partial dates such as "2025-05" work) and notes, and Ctrl+P chooses its place. Enter or Ctrl+S saves as one undo step. Ctrl+Delete deletes it.

Changes follow Scythebill (`tools/oracle/TripOps.java`, seven cases byte-identical):

- **Edit** (`TripInfoBrowsePanel.save`): the end may not come before the start. Empty notes are removed. A new place moves the trip's sightings at its old place to the new one, at the end of the list. Sightings inside the old place, or elsewhere, stay.
- **Delete** (`ReportSet.deleteTrips`): no sighting is deleted. Each loses the trip and goes to the end of the list. An undated one gets the date the trip's start and end share (`getCommonPartialDate`: 1–8 July 2026 gives "2026-07"), or else the start year. Links and photos go with the trip.

Your list has no trips. Trips come from lists made in Scythebill; creating them in Pipit (in Enter sightings, or automatically from visits as Scythebill can) comes later, and so does combining trips.

## Next

Trip reports (HTML and Word) come with M5's reports, where Scythebill has them too.

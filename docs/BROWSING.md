# Browsing: species, locations and trips

M4 in progress. This page covers what is built so far.

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

### The place index

`location_closure` (schema 3) holds every (ancestor, descendant, depth) pair, so "everything in this place" is one join. Triggers keep it current on insert, delete and re-parenting, including while undo and redo replay their statements. It isn't journaled itself. The integrity check on open compares it with a fresh walk of the tree. The location-operations fuzz test checks it after every random add, move, merge, delete and rename, and after every undo and redo.

### Speed (Eric's list: 674 places, 23,813 sightings)

The tree builds in 8 ms. The largest "seen in" (North America, about 1,100 rows) takes under 0.1 s.

## Still to come in M4

Species browse, trips, and custom checklists from the Locations screen.

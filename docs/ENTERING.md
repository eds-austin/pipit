# Entering sightings

Ctrl+2 (or Ctrl+N) opens Enter sightings. A day is a date, up to four locations (A–D), and the birds, each with a count per location. Every key below works without the mouse, and F1 shows them in the app.

## A day, step by step

1. **Date.** Type `t` (today), `y` (yesterday), `+` or `−` (a day later or earlier), or a date such as `2026-11-20`. A partial date (`2026-11`, `2026`) is allowed for one location without start times.
2. **Location A.** Tab into the place field and type part of a name. The suggestions are your own places first (most used first), then built-in states, provinces and US counties not yet in your list. Enter picks one.
3. **A new place.** Type its name, then press Ctrl+Enter. Type the place it is inside, then Enter. It gets an ID exactly as Scythebill would give it.
4. **Protocol and effort.** Press one letter for the protocol:

   | Key | Protocol |
   |---|---|
   | T | Traveling |
   | S | Stationary |
   | I | Incidental |
   | H | Historical |
   | A | Area |
   | P | Pelagic |
   | N | Nocturnal |
   | B | Banding |
   | F | Flight calls |
   | R | Random |

   Then Tab through start time (`0730`), duration (`90`, `1h30`), distance in km, party size, Complete (Space) and comments. Fields the protocol hides are skipped, and fields it requires are marked `*`.
5. **More locations.** Alt+2, Alt+3 and Alt+4 add locations B, C and D and put you in their place field. Each has its own protocol, times and effort. Alt+Shift+2…4 removes one; later locations move up a letter, birds included.
6. **Birds.** Ctrl+J goes to the species field:
   - `mall`, then Enter: Mallard, ticked at the active location.
   - `mall 12`: with a count. `~20` and `>100` work too, and `x` means present without a count.
   - `amro a3 b1`: 3 at A and 1 at B.
   - `western grebe/clark's grebe`: a sp.
   - `mall+amblduck`: a hybrid.

   Typing an existing bird again updates its row. A bird is never added twice.
7. **Adjusting.** Down moves into the grid:
   - Left and Right choose the location column.
   - Type a count, or Enter to edit the current one.
   - Delete unticks the cell, and Ctrl+Delete removes the row.
   - Alt+H heard only, Alt+P photographed, Alt+M male, Alt+F female, Alt+U adult, Alt+J immature.
   - Any letter goes back to the species field.
8. **Walking a checklist.** Ctrl+Shift+L moves to the checklist of the active location's region, built in for every country, state and province. Up and Down move through it. Type a count and press Enter to tick a bird; it moves to the next. `/` filters the list, Tab switches location, and Esc goes back.
9. **Save.** Ctrl+Enter saves the day. "Before saving" lists anything missing, such as a place or a required start time. Ctrl+Z undoes the whole day in one step.

Suggestions are ranked for the place you are at:

1. Exact names and eBird codes first.
2. Then queries matching the start of consecutive words ("amro" for American Robin).
3. Then birds on the location's checklist, expected birds before rarities.
4. Then birds already on your life list, and species before subspecies.

Badges mark lifers, rarities, endemics and birds not on the checklist.

The session is saved as a draft half a second after every change. If Pipit closes or crashes, the day is still there when you open the list again.

## How a day is saved

Each location becomes its own Scythebill visit (`SingleLocationEdit.apply`):

- **Sightings.** Each bird ticked at a location becomes one sighting with that location, the date and the location's start time. New sightings are added in taxonomic order.
- **Visit record.** The protocol and effort become the visit record, keyed by place, date and start time. Fields the protocol hides are dropped. A historical visit with no details is not stored, as in Scythebill.
- **New places.** Built-in places are created on first use, with the ID `_scyco_<eBird code>`. Your own new places get a short ID made from their name.
- **Taxonomy.** Birds are chosen in AviList by default, and stored as Scythebill stores them: the Clements mapping of the AviList bird. An AviList lump becomes a Clements sp.

Everything is one transaction. Scythebill's own load and save leaves an exported list unchanged after entry. That was checked for built-in counties, new places with coordinates, sp. and hybrid sightings, flags, statuses, breeding codes and every visit field (see TESTING.md).

### One deliberate difference

Scythebill's entry screen loads a visit's existing sightings and then replaces them all when you save. Pipit doesn't show existing sightings yet, so it never deletes on save. A bird already recorded at the same place, date and start time is updated in place, and everything else is added. Saving can therefore never lose a record. Editing existing visits comes with the browse screens (M4).

## Not yet in this milestone

- Trips (entering a multi-day trip instead of a visit).
- Observers.
- Subspecies picking (Ctrl+Shift+S) and the per-sighting details drawer (Ctrl+D).
- OpenBirding month-aware lists. The built-in checklists are used.
- Ranking by personal history at a place beyond "seen at all".
- Scythebill's `ReassignNewBuiltInLocations` upgrade. It is now possible with the predefined-location port, and will be added with the location screens.

# Lists: storage, import, export, undo and backups

A Pipit list is one SQLite file (`<name>.pipit`) holding exactly what a Scythebill `.bsxm` holds. A list exports back to the same `.bsxm` Scythebill itself would write, byte for byte. The data pack (taxonomies, checklists) is separate and read-only; see [DATA_PACK.md](DATA_PACK.md).

## Command line

```bash
.venv/bin/pipit-list import List.bsxm ~/.local/share/pipit/lists/List.pipit
.venv/bin/pipit-list export List.pipit Copy.bsxm     # opens in Scythebill
.venv/bin/pipit-list check List.pipit                # every integrity check
.venv/bin/pipit-list backup List.pipit               # a snapshot now
.venv/bin/pipit-list undo List.pipit                 # and redo
.venv/bin/pipit-list restore List.pipit BACKUP.zip   # the current list is snapshotted first
```

`--pack` chooses a data pack; by default the newest in `~/.local/share/pipit/packs` or `./datapacks` is used. `--backups` changes the backup folder (default `~/.local/share/pipit/backups`).

## Exactly like Scythebill

The reader (`bsxm/reader.py`) and writer (`bsxm/writer.py`) are ports of Scythebill's parser and writer, including every normalization Scythebill applies when it opens a file:

- **Restored and renamed locations.** Missing locations become "RESTORED LOCATION" placeholders. Empty names become "(Unnamed)", and duplicate sibling names get " duplicate".
- **Dates.** Two-digit years are fixed.
- **Visits.** A visit missing a required field becomes "historical", and fields hidden by its protocol are dropped.
- **Trips.** A trip's end time replaces its start time; this is a Scythebill bug, kept for compatibility.
- **Numbers.** Areas and distances are 32-bit floats rounded to three decimals and printed with Java's `Float.toString`.

These are checked against Scythebill itself, using `tools/oracle/RoundTrip.java`, which runs Scythebill's own load, upgrades and save:

| File | Result |
|---|---|
| Your list (23,813 sightings) | identical to Scythebill's re-save, and a fixed point |
| Scythebill's `large_sample.bsxm` (30,000 sightings) | identical |
| `tests/fixtures/bsxm/edge_cases.bsxm` | identical, including Scythebill's second pass |
| Java float formatting and parsing | identical on 2,607 values |

The edge-case file covers trips, links and photos, observers, every protocol and fallback, odd numbers and coordinates, partial dates, restored and duplicate locations, sp., hybrid and subspecies forms, checklists, an embedded taxonomy with every checklist-code form, unknown elements, and Unicode.

Scythebill's own output is not always a fixed point. A latitude of `-0.0000000` reads back as `0.0000000`, and an area written as `0.0` is dropped on the next load. Pipit matches both passes.

## What import accepts

Pipit imports lists saved by current Scythebill (format 18.1.0 or later) in the data pack's taxonomy (clements2026). It applies the one upgrade such files can still need, `moveImageTripLinksToPhotos`, and records it as Scythebill does.

It refuses, with a message to open and save the file in Scythebill first:

- a file in an older taxonomy (taxonomy upgrades are milestone M8);
- a file that still needs any other Scythebill upgrade;
- a file that uses a taxon this data pack doesn't have.

Everything Scythebill itself refuses is refused too: unknown taxa, malformed dates, duplicate IDs.

Import also runs Scythebill's on-load `ReassignNewBuiltInLocations` (after the stored list has been checked against the file): a place of yours that matches a newer built-in place under the same parent is replaced by the built-in one, so the list matches what Scythebill shows after opening the same file. The places replaced are listed as warnings.

## Data integrity

- **All or nothing.** An import is read, checked, written in one transaction, then exported again from the database and compared byte for byte with the expected output. Any difference deletes the new list.
- **Always saved.** Every change is one SQLite transaction (WAL, `synchronous=FULL`, foreign keys on), so there is no Save command and a crash loses nothing that was committed.
- **Undo and redo.** Generated triggers record the inverse of every change to every table (except derived ones such as `location_closure`, which its own triggers keep current, during undo and redo too). Undo replays them in one transaction, so the database returns to exactly its earlier state. The last 200 actions are kept, and an action that changes nothing isn't recorded.
- **Checks on open.** Every open runs SQLite's quick check and foreign-key check, then Pipit's own checks: the sp. and hybrid structure, extended taxa, the location tree (no cycles, and the `location_closure` index of every ancestor matches a fresh walk of the tree), migration checksums, and taxa against the data pack. If any fails, the list opens read-only ("repair mode"), so nothing is written on top of damage.
- **Backups.** One zip per day, holding the database and the same list as `.bsxm`, so Scythebill can open every backup. Pipit keeps the latest 7 daily, 5 weekly and 12 monthly backups. Snapshots (`pre-<operation>-<time>.zip`) are taken before risky operations and are never rotated away.
- **Schema changes.** Numbered SQL migrations, each recorded with its checksum. A list made by a newer Pipit is refused rather than misread.

## Speed

Measured on this machine:

| List | Import | Open and back up | Export |
|---|---|---|---|
| Your list (23,813 sightings) | 2.9 s | 1.3 s | 1.1 s |
| `large_sample` (30,000 sightings) | under 5 s (tested) | | under 3 s (tested) |

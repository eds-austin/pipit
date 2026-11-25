# Testing

Run every quality gate with:

```bash
scripts/ci.sh
```

It runs ruff, the ruff format check, strict mypy and pytest. UI tests run offscreen (`QT_QPA_PLATFORM=offscreen`), so no display is needed.

## Set up

Pipit uses Fedora's `python3-pyside6`, so the virtualenv must see system packages:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e . pytest ruff mypy
```

## What the tests cover

- **Qt-free logic** (`tests/test_navigation.py`, `test_settings.py`, `test_paths.py`, `test_desktop.py`): palette matching, back history, settings validation and atomic saves, XDG paths, the per-user launcher.
- **Layering** (`tests/test_smoke.py`): core modules must not import Qt. Add new core packages to `CORE_MODULES`.
- **Rendering** (`tests/test_smoke.py`): every screen and overlay is rendered offscreen to a screenshot. Any QML warning fails the test, because a broken binding still "loads".
- **Keyboard** (`tests/ui/test_shell.py`): the real main window is driven by key events. Ctrl+1…8, Ctrl+, and Ctrl+N switch screens, Alt+Left goes back, the palette runs commands from typed text and arrow keys, and Ctrl+B collapses the sidebar and saves the setting.

- **Taxonomy** (`tests/taxa/`): the mapping rules on a small hand-made taxonomy (exact, lumped, duplicate, from children, more than three subspecies, families, base species plus AviList subspecies, disabling).
- **Search** (`tests/search/`): Scythebill's normalization and splitting rules, the fast engine against a literal port on random data, and Scythebill's own indexer test cases.
- **Data pack** (`tests/packbuild/`): readers, building, validation, determinism, loading, and the CLI.
- **Against Scythebill** (`tests/search/test_against_scythebill.py`): exact agreement with answers recorded from Scythebill itself, and the 10 ms search budget. See [DATA_PACK.md](DATA_PACK.md).

- **Values** (`tests/domain/`): partial dates, counts, times, coordinates, and Java's float formatting and parsing (ground truth recorded from Java in `tests/fixtures/java/floats.tsv`).
- **.bsxm** (`tests/bsxm/`): reading and writing compared byte for byte with Scythebill's own re-saves of an edge-case file and its 30,000-sighting sample, plus everything Scythebill refuses.
- **Lists** (`tests/storage/`): lossless import and export through the database, the speed budgets, all-or-nothing imports, undo and redo back to the exact earlier state, repair mode for damaged lists, backups, rotation and restore, and the `pipit-list` command. See [LISTS.md](LISTS.md).

- **Entering** (`tests/entry/`, `tests/ui/test_enter_screen.py`): input parsing, problems, drafts, ranking for a place, saving (built-in counties, new places, update in place, one-step undo), and the real window driven only by the keyboard through a two-location day of 41 species with an sp. and a new place. Entry tests start from `tests/fixtures/bsxm/new_list.scythebill.bsxm`, an empty list exactly as Scythebill creates one (`tools/oracle/NewList.java`).
- **Locations** (`tests/storage/test_location_ops.py`, `tests/browse/`, `tests/ui/test_locations_screen.py`): delete, merge (including a recursive merge), move and `ReassignNewBuiltInLocations` give byte-identical files to Scythebill's own result on `tests/fixtures/bsxm/locations.bsxm` (made by `tools/oracle/make_locations_fixture.py`; Scythebill's results by `tools/oracle/LocationOps.java`, both run from `tools/oracle/run.sh`). Refused changes change nothing. A seeded fuzz test applies random adds, moves, merges, deletes and renames, then checks after each step, and after every undo and redo, that the tree, the `location_closure` index and every sighting are intact. The browse queries are checked for subtree totals and roll-up to species, and the real window is driven by keyboard through filtering, adding, deleting, merging and one-step undo.
- **Editing visits** (`tests/entry/test_edit_visit.py`, `tests/ui/test_edit_visit_screen.py`): `tests/fixtures/bsxm/visits.bsxm` (from `tools/oracle/make_visits_fixture.py`) has a visit with notes and flags, a subspecies, a sp., a duplicate taxon, taxa that AviList maps to a subspecies and to a sp., and a visit record, plus an untimed visit. `tools/oracle/EditVisit.java` edits it through Scythebill's `SingleLocationEdit`, and Pipit's load, edit and save must give the same bytes in all six cases. Also checked: one undo restores the file, observers stay with re-saved sightings, drafts keep what was loaded, and the real window opens a visit from Locations, adds a bird, saves and undoes.
- **Species** (`tests/browse/test_browse_species.py`, `tests/ui/test_species_screen.py`): the taxonomy list (families with species under them, sp. in order, seen-only and all, name filter), a species' sightings (newest first, with the narrower records), single-sighting edits and refusals, and delete with observers restored by undo. The real window is driven by keyboard through filtering, editing a count, undo, showing every species, delete and undo, and opening the sighting's visit.
- **Trips** (`tests/storage/test_trip_ops.py`, `tests/browse/test_browse_trips.py`, `tests/ui/test_trips_screen.py`): `tests/fixtures/bsxm/trips.bsxm` (from `tools/oracle/make_trips_fixture.py`) has trips with dated and undated sightings, inside and outside their place, and trips with partial and year-spanning dates. `tools/oracle/TripOps.java` deletes them and edits them (name, dates, notes, place, clearing notes) through Scythebill's own code. Pipit gives the same bytes in all seven cases, each undone in one step, and refuses bad edits without changing anything. Also: which sightings belong to a trip, the dates of undated trip sightings, the ported partial-date rules, and the real window driven by keyboard through choosing, editing, moving, deleting and undoing.

## Your own list

```bash
PIPIT_PRIVATE_BSXM=~/Projects/scythebill-birdlist/List-Eric.bsxm .venv/bin/python -m pytest -m private
```

This imports, exports, re-imports and re-exports the file in a temporary folder, and requires a fixed point. Set `PIPIT_PRIVATE_EXPECTED` to Scythebill's re-save of the same file (see the end of `tools/oracle/run.sh`) to also require Scythebill's exact output. The file is only read; nothing derived from it is kept.

## Markers

| Marker | Meaning |
|---|---|
| `ui` | Launches the Qt/QML interface offscreen. |
| `private` | Needs Eric's real `.bsxm` through `PIPIT_PRIVATE_BSXM`. Never runs in CI, never copies the file. |
| `scythebill` | Needs a Scythebill checkout: `PIPIT_SCYTHEBILL`, or `~/Projects/scythebill-birdlist`. Builds a data pack once per session (about 10 s). Skipped when there is no checkout. |

## Screenshots

Hidden flags render the window without a display, for checking against the design system:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pipit --size 1920x1080 --screen enter --screenshot enter.png
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pipit --size 1920x1080 --overlay palette --palette-query ensi --screenshot palette.png
```

Tests and screenshots never read or write the user's `settings.toml`.

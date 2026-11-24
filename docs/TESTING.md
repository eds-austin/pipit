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

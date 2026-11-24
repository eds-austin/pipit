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

## Markers

| Marker | Meaning |
|---|---|
| `ui` | Launches the Qt/QML interface offscreen. |
| `private` | Needs Eric's real `.bsxm` through `PIPIT_PRIVATE_BSXM`. Never runs in CI, never copies the file. |

## Screenshots

Hidden flags render the window without a display, for checking against the design system:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pipit --size 1920x1080 --screen enter --screenshot enter.png
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pipit --size 1920x1080 --overlay palette --palette-query ensi --screenshot palette.png
```

Tests and screenshots never read or write the user's `settings.toml`.

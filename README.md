# Pipit

*Bird Listing.*

A modern, keyboard-first bird list app for Linux desktops, compatible with eBird and Scythebill:
it imports your eBird data and saves sightings ready to upload to eBird (see
[docs/EBIRD.md](docs/EBIRD.md)), and opens and saves Scythebill .bsxm files exactly as Scythebill
writes them.

See [docs/PLAN.md](docs/PLAN.md) and [docs/BUILD_PROMPT.md](docs/BUILD_PROMPT.md).

## Run it

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e . pytest ruff mypy
.venv/bin/pipit-build-pack         # build the taxonomy data pack from a Scythebill checkout
.venv/bin/pipit-list import List.bsxm List.pipit   # a Scythebill list into Pipit
.venv/bin/pipit-list export List.pipit Copy.bsxm   # and back, exactly as Scythebill writes it
.venv/bin/pipit --list List.pipit  # opens maximized; Ctrl+2 enters sightings, F1 shows every key
.venv/bin/pipit --install-desktop  # add Pipit to the Plasma menu for this user
scripts/ci.sh                      # lint, types and tests
```

Status: milestones M0 (app shell), M1 (data pack and search), M2 (lists: .bsxm import and export, storage, undo, backups) and M3 (entering sightings, including multi-location days) are done. See [docs/ENTERING.md](docs/ENTERING.md), [docs/LISTS.md](docs/LISTS.md), [docs/DATA_PACK.md](docs/DATA_PACK.md), [docs/TESTING.md](docs/TESTING.md) and [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).

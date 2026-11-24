# Pipit

A modern, keyboard-first bird list app for Linux desktops, compatible with Scythebill .bsxm files.

See [docs/PLAN.md](docs/PLAN.md) and [docs/BUILD_PROMPT.md](docs/BUILD_PROMPT.md).

## Run it

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e . pytest ruff mypy
.venv/bin/pipit-build-pack         # build the taxonomy data pack from a Scythebill checkout
.venv/bin/pipit                    # opens maximized
.venv/bin/pipit --install-desktop  # add Pipit to the Plasma menu for this user
scripts/ci.sh                      # lint, types and tests
```

Status: milestones M0 (app shell) and M1 (data pack and search) are done. See [docs/DATA_PACK.md](docs/DATA_PACK.md), [docs/TESTING.md](docs/TESTING.md) and [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).

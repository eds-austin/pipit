# Pipit build prompt

You are building **Pipit**, a Linux-first (Fedora KDE Plasma) desktop bird-listing app in `~/Projects/pipit`. It re-implements the core of Scythebill (`~/Projects/scythebill-birdlist`, Apache 2.0) with a modern, dense, keyboard-first UI. Read `docs/PLAN.md` fully before starting; it is the source of truth for scope, schema, fidelity rules, keyboard map and milestones.

**Stack and style.** Python ≥3.12, PySide6 QML, hatchling `src/` layout. Copy the structure, tooling (`scripts/ci.sh`: ruff, ruff format, strict mypy, pytest + pytest-qt with `QT_QPA_PLATFORM=offscreen`), `Theme.qml` and `Pac` components from `~/Projects/perfect-audio-copy`, renamed to a `Pipit` QML module. Follow `~/Projects/perfect-audio-copy/docs/DESIGN_SYSTEM.md` and Eric's global house style: tokens are the only source of colour, size and spacing; soft dark surfaces; Inter for UI, JetBrains Mono with tabular figures for numbers; Lucide icons; status never shown by colour alone. Add a font `scale` token (default body 15 px) and 28 px dense rows. Windows are used maximized; avoid wasted space.

**Non-negotiables.**
1. Data integrity: SQLite with WAL, foreign keys, `synchronous=FULL`, STRICT tables; one transaction per user action; trigger-based undo/redo; entry drafts survive crashes; rotated backups that include a `.bsxm`; snapshots before risky operations; integrity checks on open.
2. `.bsxm` round-trip fidelity: import then export must be byte-identical to a Scythebill-normalized re-save. Port the reader/writer from the Scythebill files listed in the plan; do not guess the format.
3. Keyboard-only entry, including the multi-location day (slots A–D, one count per ticked slot, own visit details per slot, each saved as a separate visit). Every action reachable without a mouse; Ctrl+K palette; F1 key overlay.
4. eBird compatibility: Record Format export with Scythebill's rules, and the eBird imports listed in the plan.
5. Taxonomy: sightings stored with eBird/Clements base IDs; AviList is the default display and counting view; annual updates install a new data pack and upgrade IDs with a pre-upgrade snapshot and an sp.-resolution UI.

**Privacy.** Eric's real file `~/Projects/scythebill-birdlist/List-Eric.bsxm` is private. Read it only locally, only through `PIPIT_PRIVATE_BSXM` in tests marked `private`. Never copy it into the repo, never commit it or derived data, never send it over the network. No telemetry. All network services are off until enabled; the eBird key lives in the system keyring. Never use `api.scythebill.com`.

**Conventions.** US English. No abbreviated variable names. Strong types over primitives (`datetime`, `timedelta`, enums, dataclasses). `domain/` is pure and imports nothing from Pipit; Qt only in `ui/` and `app.py`. Port Scythebill logic faithfully and cite the source file in a module docstring. Add an Apache-2.0 LICENSE and a NOTICE crediting Scythebill and data sources.

**Process.** Work milestone by milestone (M0 → M9). For each: write tests first for domain/storage logic, implement, run `scripts/ci.sh`, take screenshots of new UI and compare with the house style, then commit with a clear message. Use Scythebill as the oracle: where numbers or output must match, build a small JVM harness in a scratch location (not committed to Scythebill) and record expected results as fixtures. Stop and ask Eric when a choice changes what he sees or what is stored, or when a Scythebill behavior looks like a bug worth not copying.

Start with M0, then M1 and M2 before any UI beyond the shell: the data pack and a proven round-trip come first.

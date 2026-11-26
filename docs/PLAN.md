# Pipit: a modern Scythebill-compatible bird list app (plan + build prompt)

## Context

Scythebill (Java Swing, Apache 2.0, `~/Projects/scythebill-birdlist`) is the best stand-alone bird-listing app, but its UI is dated: tiny text, wasted space. Eric wants a new desktop app with the same core features, a sleek soft-dark UI matching his other apps, keyboard-only rapid entry, strong data integrity, eBird compatibility, annual taxonomy updates (AviList primary from 2027), and one new feature: **multi-location days** (up to 4 locations A–D per date, saved as separate checklists).

Deliverable of this planning task: this plan plus a self-contained build prompt. After approval, both are written into a new repo `~/Projects/pipit` (`docs/PLAN.md`, `docs/BUILD_PROMPT.md`), `git init`, no code yet.

## Decisions made with Eric

| Topic | Decision |
|---|---|
| Name | **Pipit**, repo `~/Projects/pipit`, package `pipit` |
| Stack | Python ≥3.12 + PySide6 **QML**, cloned from perfect-audio-copy (PAC) structure, tokens and `Pac` components |
| Storage | **SQLite** native store; full-fidelity **.bsxm import and export** (round-trip back to Scythebill) |
| Taxonomy source | Phase 1: convert Scythebill's release data into a read-only SQLite **data pack**. Own pipeline from raw Clements/AviList later |
| Taxonomy view | Store eBird/Clements base IDs (+ Avibase concept IDs). **Default display and counting = AviList**, one-click switch to Clements |
| Multi-location | Up to 4 slots A–D; **one count per ticked slot**; **own visit details per slot** (time, duration, distance, protocol, complete) |
| Entry style | Fast word-prefix typing **and** walking a regional checklist |
| In scope | Entry, browse species/locations/trips, trip reports, query builder + reports, special reports and maps, eBird import/export, Scythebill CSV, backups, geocoding, regional checklists, **mammals** (extended taxonomy) |
| Deferred | Photos, itinerary planner, send-to-phone, multi-observer UI (users still preserved on round-trip), non-eBird importers, OpenBirding month-aware lists |
| Online | User's own free **eBird API key** (stored in KWallet via `keyring`) for hotspot search and checklist download. Optional Nominatim geocoding. All network off until enabled. No telemetry. Scythebill's proxy is not used |
| Licence | Apache-2.0 with NOTICE crediting Scythebill (Adam Winer). PAC components relicensed by Eric as owner |

Dev data: `~/Projects/scythebill-birdlist/List-Eric.bsxm` (private, untracked; 23,813 sightings, 233 locations, 99 visits, 18 custom checklists, embedded Mammal Watching taxonomy, version 20.0.0 / clements2026). Never copied into the Pipit repo, never committed, never sent anywhere; tests reach it only via `PIPIT_PRIVATE_BSXM`. Shareable fixture: `mobile/app/src/androidDeviceTest/assets/large_sample.bsxm`.

## Architecture

```
src/pipit/
  app.py, __main__.py        QQmlApplicationEngine bootstrap (as PAC)
  config/                    XDG paths (~/.local/share/pipit/{lists,backups,packs}), TOML settings
  domain/                    pure types: PartialDate, ApproximateNumber, SightingTaxon(single|ssp|sp|hybrid),
                             Sighting, Location, Visit (ObservationType required/hidden fields), Trip, User, enums
  datapack/                  read-only pack access: taxonomy tree, AviList mapped view, names, checklists, predefined locations
  packbuild/                 offline converter CLI `pipit-build-pack` (never imported by the app)
  storage/                   db.py (WAL, FK, synchronous=FULL, STRICT), migrations/, uow.py, journal.py (undo/redo),
                             backup.py, integrity.py, repos/*
  bsxm/                      streaming reader, Scythebill-identical writer, btxm, LocationsToSave, upgraders/, canonical diff
  search/                    Indexer port (bitset engine), ranking, taxon + location indexes
  entry/                     EntrySession with LocationSlots A–D, drafts, inline count parsing, validate, commit
  query/                     AST (All/Any/Never/NeverAll), fields, SQL compiler, stored-query codec
  reports/                   HTML print, xlsx, trip docx, special/*
  ebird/  csvio/  geo/  upgrade/
  ui/backend/ (Python models/controllers)   ui/qml/Pipit/ (Theme + components)   ui/qml/screens/
```

Rules: `domain` imports nothing; Qt only under `ui/` and `app.py`; nothing imports `ui`; enforced by an import-walk test.

### User database (`<list>.pipit`, SQLite)
Tables: `meta`, `schema_migrations`, `users`, `locations` (verbatim `xml_id`, type, parent, eBird code/hotspot, lat/long **as text**, private, description, `ord`) + `location_closure`, `trips` (+ raw `end_time_raw` quirk), `visits` (UNIQUE `loc_id,date,start_time`), `sightings` (taxonomy_id, kind, taxon_id, ssp_name, partial date y/m/d, time, `count_raw` verbatim, flags, status, breeding, notes, `file_ord`), `sighting_taxa` (sp/hybrid parts in order), `sighting_users`, `passthrough` (verbatim `<photo>`/link XML), `custom_checklists` + entries, `ext_taxonomies` (verbatim `btxm_raw`) + derived `ext_taxa`/`ext_names`/`ext_checklists`, `prefs_raw` (verbatim JSON), `one_time_upgrades`, `stored_queries`, `app_prefs`, `entry_drafts`, `undo_actions`/`undo_log`.

### Data pack (`pipit-pack-2026.1.sqlite`, read-only, attached)
`pack_meta` (sources + sha256 + attributions), `taxonomies`, `taxa` (nested-set order, eBird code, concept ID, IUCN, range), `alt_names`, `avilist_map`, precomputed `resolve` (base ID → counting species per taxonomy), `names` (locales), `search_words`, `checklists` (520 regions × 2 taxonomies), `checklist_regions`, `upgrade_map` (+ ssp), `predefined_locations`, `synthetic_locations`, `geo_features` (simplified Natural Earth polygons from `.mapbin`).

### .bsxm fidelity (key guarantees)
Exact base/extended taxon IDs; partial dates via a port of `PartialDateIO.kt` (incl. `M05-12` forms); counts verbatim; location IDs/order verbatim, new IDs with Scythebill's scheme; prefs JSON verbatim (only `storedQueries` rewritten when changed); embedded taxonomy re-emitted byte-for-byte unless edited; photos/links passthrough; writer reproduces `XmlResponseWriter`/`IndentingResponseWriter` (2-space indent, attribute order, every char >0x7E as `&#x..;`); output order per `XmlReportSetExport.java`; always writes version 21.5.0; on import runs ported versioned upgraders (incl. always-on `ReassignNewBuiltInLocations`) and missing one-time upgraders.

## Data integrity
1. **One transaction per user action** (`UnitOfWork`, `BEGIN IMMEDIATE`, validate before commit, rollback on error).
2. **Undo/redo** from trigger-generated inverse SQL, grouped per action; multi-location Finish or an import is one undo step.
3. **No Save button**: SQLite commit is the save; entry drafts persisted every 500 ms so a crash loses nothing.
4. **Backups**: online backup API → zip containing the `.pipit` **and** an exported `.bsxm` (openable in Scythebill). Rotation 7 daily / 5 weekly / 12 monthly; mandatory snapshots before import, taxonomy upgrade, merge, bulk delete, migration.
5. **On open**: `quick_check`, `foreign_key_check`, app invariants (taxa resolve, visit keys unique, closure consistent, sp. ≥2 parts). Failure → read-only repair mode offering restore.
6. **Golden round-trip**: Scythebill JVM harness re-saves a file to `expected.bsxm`; Pipit import→export must be byte-identical; export→import→export is a fixed point; canonical diff names the first differing path on failure.

## Search (type-ahead)
Exact port of Scythebill `Indexer.kt`/`Trie.kt`/`WordSeparator.kt` semantics (any combination of word prefixes, positional, ≤5 words, single-token splits capped at 15 chars; "wiwa", "he gu"), plus eBird species codes. Engine: sorted word arrays + Python-int bitsets per word position, LRU prefix cache; target **p95 < 10 ms per keystroke**. Ranking: exact/code match → on checklist of the active slot's location (native before rarity) → personal history → species before ssp. → taxonomic order. Same engine powers location autocomplete and the Ctrl+K command palette.

## UI
House soft-dark style (tokens only; Inter + JetBrains Mono tnum; Lucide). Added `scale` token (default body 15 px) and dense 28 px table rows. Maximized shell: 200 px collapsible sidebar (Home, Enter, Species, Locations, Trips, Reports, Special, Taxonomies, Settings; Ctrl+1…8), 40 px title strip, status bar with undo toasts, resizable SplitViews, Ctrl+K command palette, F1 key overlay.

- **Home**: KPI cards for pinned stored queries (life, year, country…), recent visits, pending items (sp. to resolve, backup status).
- **Species / Locations / Trips**: three-pane browse; windowed SQL table models for 24k+ rows; location CRUD/move/merge/custom checklists; trip reports (HTML, docx).
- **Reports**: query builder strip with all Scythebill filters and All/Any/Never/Never-All; sorts; stored queries (round-trip with Scythebill's prefs); print HTML, xlsx, eBird CSV, Scythebill CSV.
- **Special**: timeline, ticks map, year comparison, splits & lumps, lifers map, checklist status, family report.

### Enter Sightings (incl. multi-location)
```
┌ Date [2026-11-24] · Trip · Checklist mode ⇄ · Taxonomy: AviList ─────────────────────────┐
│ A Rock Pond    Traveling 07:30 90m 3.2km party 2 ☑complete  comments…                     │
│ B Home Garden  Stationary 10:15 45m ☐complete       C + add (Alt+3)   D + add (Alt+4)    │
├ Entry grid ─────────────────────────────────────────┬ Context: Checklist │ Species │ Day ─┤
│ Mallard            A 12   B ~4          H   notes   │ regional checklist for focused     │
│ Wilson's Warbler   A 1            C x   ♂           │ slot; LIFER/YEAR/ENDEMIC/RARE      │
│ ▸ [type species…]                                    │ badges; seen-here counts           │
├ A 34 spp · B 12 spp · total 41 · lifers 1 · draft saved · Ctrl+Enter Finish ──────────────┤
```
Keyboard flow:
1. Ctrl+N → Date (`t` today, `y` yesterday, `+`/`-` days, partial dates allowed; partial date disables slots B–D and visit fields).
2. Tab → slot A location autocomplete; Ctrl+Enter creates a new location inline (parent, type, lat/long, Ctrl+G eBird hotspot search).
3. Visit fields per slot: protocol by letter (T/S/I/H/A/P/N/B), time `0730`, duration `1h30`, distance, party, complete (Space), comments; hidden fields skipped, required ones flagged.
4. Alt+2/3/4 add slot B/C/D (Alt+Shift removes). Date shared; everything else per slot.
5. Ctrl+J → species field. Type `wiwa`, Enter. `/` builds an sp., `+` a hybrid. Duplicate species jumps to the existing row.
6. Focus lands on the active slot's count cell: `3`, `~20`, `x` (present). Tab between ticked slots, Alt+1…4 jump to a slot's cell, Space ticks present, Backspace on empty unticks. Inline syntax `wiwa a3 c~12`.
7. Row details: Alt+H heard, Alt+P photographed, Alt+M/F sex, Alt+U/J adult/immature, Alt+S status, Alt+B breeding code, Alt+N notes, Ctrl+D full per-slot drawer, Ctrl+Shift+S subspecies/group. Apply to focused slot, or all ticked slots when on the species cell.
8. Checklist mode (Ctrl+Shift+L): walk the regional checklist for the focused slot; j/k or arrows, digits enter counts, Tab switches slot, `/` filters.
9. Finish (Ctrl+Enter / Ctrl+S): validation list with jump links (missing required fields, duplicate loc+date+time, etc.), then one transaction writes up to 4 visits and all sightings; toast "Saved 2 checklists · 46 sightings — Undo". Esc keeps the draft; reopening a date+location edits the existing visits as a diff.

## Roadmap (each milestone ends with `scripts/ci.sh` green)

| M | Scope | Acceptance |
|---|---|---|
| M0 | Scaffold from PAC; Theme + components renamed; shell, sidebar, palette skeleton, desktop file | Launches maximized; Ctrl+1…8 navigate; ruff, strict mypy, pytest offscreen pass |
| M1 | `pipit-build-pack` from the Scythebill checkout + validator | Deterministic pack; counts match XML; all maps/checklist IDs resolve; search p95 < 10 ms; 500-name corpus matches Scythebill's indexer |
| M2 | bsxm reader/writer, upgraders, schema v1, UoW, undo, backups, integrity | Byte-identical vs Scythebill-normalized `large_sample.bsxm` and the private file; fixed point; corrupt copy → repair mode; 24k import < 5 s, export < 3 s |
| M3 | Enter Sightings incl. multi-location, drafts | Scripted keyboard-only pytest-qt test enters a 2-slot day (40 species, one sp., one new location) → 2 visits + correct sightings; one Ctrl+Z reverts; kill + reopen restores draft; export opens in Scythebill |
| M4 | Browse species / locations; edit recorded visits | 24k-row scroll smooth; merge atomic and undoable; closure fuzz holds |
| M4.1 | Browse trips; custom checklists from Locations | Trip edits equal Scythebill's output; every trip change one undo |
| M5 | Query engine, stored queries, Home KPIs, HTML print, xlsx, trip reports (HTML, Word) | 30 reference queries equal Scythebill totals; < 100 ms each; Scythebill stored queries round-trip |
| M6 | eBird Record Format export; Record Format, My Data, life list import; checklist download via user API key; Scythebill CSV | Ported `EBirdCsvExportTest` cases pass; review screen before commit; My Data import re-exports field-for-field |
| M7 | Special reports + choropleth maps | Numbers match Scythebill on the sample; map render < 200 ms |
| M8 | Annual taxonomy upgrade (pack N→N+1, snapshot, sp.-resolution UI) + mammal taxonomy browse, btxm import/export | Simulated 2025→2026 upgrade equals Scythebill `UpgradeTrackerImpl` output; mammal sightings untouched |
| M9 | RPM (noarch, system `python3-pyside6`), pack as subpackage or first-run build; Flatpak | `dnf install`, launch from Plasma menu, import a .bsxm |
| Later | Own taxonomy pipeline, OpenBirding lists, Windows/macOS, photos, multi-observer UI | — |

## Scythebill sources to port (MC = `model/src/commonMain/kotlin/com/scythebill/birdlist/model`, MJ = `model/src/jvmMain/java/com/scythebill/birdlist/model`, U = `ui/src/main/java/com/scythebill/birdlist/ui`)
- **bsxm**: `MC/xml/XmlReportSetParsers.kt`, `XmlReportSetConstants.kt`, `XmlTaxonParsers.kt`; `MJ/xml/XmlReportSetExport.java`, `XmlTaxonExport.kt`; `MJ/io/XmlResponseWriter.java`, `IndentingResponseWriter.java`; `MJ/sighting/LocationsToSave.java`; `MJ/sighting/upgrades/*`
- **domain**: `MC/date/PartialDate*.kt`, `MC/sighting/ApproximateNumber.kt`, `SightingInfo.kt`, `VisitInfo.kt`, `SightingTaxon.kt`, `Location*.kt`, `Trip.kt`; `MC/io/TimeIO.kt`
- **taxonomy/pack**: `MC/taxa/MappedTaxonomy.kt`; `MJ/taxa/*Mapping*.kt`, `UpgradeTrackerImpl.kt`; `MJ/checklist/*`; `MJ/mapdata/MapLayerFile.java`; runbook `taxonomy/CLEMENTS_UPGRADE.md`
- **search**: `MC/util/Indexer.kt`, `Trie.kt`, `WordSeparator.kt`; `MJ/util/TaxonomyIndexer.java`; `U/util/LocationTaxonScorer.java`
- **entry**: `U/panels/SingleLocation*Panel.java`, `U/components/VisitInfoPanel.java`, `SightingInfoPanel.java`; docs `ui/docs/panels/wizard-infrastructure.md`
- **query/reports**: `MJ/query/*`, `MC/query/*`, `U/panels/reports/*`; docs `ui/docs/panels/query-system.md`, `analytical-panels.md`
- **eBird**: `MJ/export/EBirdCsvExport.java`; `U/imports/EBird*.java`, `TaxonResolver.java`
- **design**: `~/Projects/perfect-audio-copy/src/perfect_audio_copy/ui/qml/Pac/*`, `docs/DESIGN_SYSTEM.md`, `scripts/ci.sh`, `packaging/*.spec`

## Risks
- QML tables at 24k rows → windowed models, delegate reuse, preformatted strings.
- Clements/eBird data redistribution terms → pack built locally from Eric's checkout; confirm before any public package.
- Hidden Scythebill semantics (countability, Never queries, sp. counting) → Scythebill as oracle via a JVM harness; port predicates line by line.
- Stored-query string format must be reverse-engineered; keep the raw form until supported.
- Scythebill format drift → golden tests pinned to 21.5.0 flag changes.

## Verification (end to end)
1. `scripts/ci.sh` (ruff, ruff format, strict mypy, pytest offscreen) green at every milestone.
2. `pipit-build-pack --scythebill ~/Projects/scythebill-birdlist` then `pipit-build-pack --validate`.
3. `PIPIT_PRIVATE_BSXM=~/Projects/scythebill-birdlist/List-Eric.bsxm pytest -m private`: byte-identical round-trip and life-list totals equal Scythebill's.
4. Launch `python -m pipit`, import the real file, enter a 3-location day by keyboard only, export eBird CSV and .bsxm, open the .bsxm in Scythebill and confirm visits and counts.
5. Screenshots of each screen checked against the house style.

The build prompt is in [BUILD_PROMPT.md](BUILD_PROMPT.md).

## Progress

| Milestone | State | Notes |
|---|---|---|
| M0 | Done | App shell, tokens, palette, keyboard navigation. |
| M1 | Done | Data pack (110.6 MB, deterministic); search and AviList mapping identical to Scythebill on every oracle case. |
| M2 | Done | `.bsxm` import/export byte-identical to Scythebill (your list, its 30,000-sighting sample, an edge-case file); SQLite storage, undo/redo, integrity checks with repair mode, rotating backups, `pipit-list`. See docs/LISTS.md. |
| M3 | Done | Enter sightings with up to four locations per day, keyboard only (acceptance test drives the real window); built-in places and Scythebill IDs (`PredefinedLocations.kt` port); ranked species search with checklist badges; checklist walking; sp./hybrid entry; drafts; one-undo save; Scythebill's own re-save of entered data is identical. See docs/ENTERING.md. |
| M4 | Done | Location operations identical to Scythebill (delete, merge, move, `ReassignNewBuiltInLocations` on import); `location_closure` index, fuzz-checked through undo and redo; Locations screen (tree, species seen with roll-up, place details and visits; every change one Ctrl+Z); editing recorded visits with Scythebill's load and replace, byte-identical on six oracle cases; Species screen (taxonomy list, sightings, edit and delete one sighting). Acceptance: the longest list (all 11,650 species; no M4 view lists 24k rows) moves by key in about 20 ms a step with a full redraw, kept by a test; merge is atomic and one undo; the closure fuzz holds. See docs/BROWSING.md and docs/ENTERING.md. |
| M4.1 | Done | Split from M4 when M4 closed. Trips screen (trips newest first, species seen on a trip by Scythebill's `isPartOfTrip`, edit and delete byte-identical to Scythebill on seven oracle cases, one undo each); custom checklists from the Locations screen (edit, start, delete; saved in Scythebill's Java HashMap order, byte-identical on five oracle cases and on re-saving all 18 of Eric's). Trip reports moved to M5 with the other report outputs (in Scythebill they are a "save as" of the reports system). Later: creating and combining trips; checklists from sightings (needs M5), pasted text or eBird. See docs/BROWSING.md. |
| M5 | Done | Slice 1 done: the query engine (`pipit.query`): stored-query JSON, all 15 field types, ALL/ANY/NEVER/NEVER_ALL, Scythebill's countability and totals, 28 synthetic regions. Checked against Scythebill's own headless query path (`tools/oracle/QueryOracle.java`) on 30 reference queries in four taxonomy and depth combinations (120 equal), every region, and Eric's list (23 equal); under 100 ms each once warm. Slice 2 done: the Reports screen (query builder over every field, results with Scythebill's totals line, sightings; the query kept as Scythebill's exact JSON). See docs/QUERIES.md. Slice 3 done: saved reports (Scythebill's stored queries) read and written byte-identical to Scythebill (StoredQueriesOracle, nine cases and Eric's list), with save, load, rename, delete and move on the Reports screen. Slice 4 done: Home (life, this year and saved-report figures counted off the UI thread; recent visits; backups). Pinning which reports appear is deferred. Slice 5a done: Print, byte-identical to Scythebill (PrintOracle: 122 pages and 220 checklists, plus Eric's list), with Scythebill's checklist lookup and Guava's greatestOf ported. Slice 5b done: Save as spreadsheet (Ctrl+E), the same content as Scythebill's ReportXlsOutput (cells, styles, merges, widths) on 154 oracle cases and 545 on Eric's list, written with openpyxl. Slice 5c in progress: trip report content, HTML and plain text byte-identical to Scythebill (27 oracle cases and 534 on Eric's list); built-in places now use Scythebill's display names everywhere. The Word document is byte-identical too (document.xml, as POI writes it). Trip reports on the Reports screen (Ctrl+T): copied to the clipboard, opened in the browser, Save as Word; and from the Trips screen (Ctrl+T), as Scythebill's Trips browser makes them. Deferred: pinning which saved reports Home shows; photos and other taxonomies' sections in trip reports (with photos and custom taxonomies). |
| M6 | Done | Slice 6a done: Save for eBird (Record Format CSV), byte-identical to Scythebill on 33 oracle exports and 269 on Eric's list, split into files at the same lines. Scythebill's export fails on impossible dates; Pipit leaves them out. Slice 6b done: Save as Scythebill CSV, byte-identical on 45 oracle exports and 74 on Eric's list. Slice 6c (part) done: Import sightings — eBird My Data, Record Format and life lists (both forms), and Scythebill CSV with trips — with Scythebill's questions and a review before storing (one undo step, after a backup); lists come out byte-identical to Scythebill's on 37 oracle imports and 21 from Eric's list (up to 23,632 rows). Slice 6d done: checklists downloaded from eBird, placed by asking eBird's API with the user's own key (system keyring; off until turned on in Settings), tested on 6 oracle cases against recorded answers. See docs/EBIRD.md. Acceptance: the ported `EBirdCsvExportTest` cases pass; a review screen comes before storing; a My Data import re-exports field for field (identical to Scythebill's). Deferred: Scythebill CSV files with observers (with the multi-observer UI) and with places given only as free text (Scythebill's `FreeformLocationResolver`), and asking where an import's unplaced places are (Scythebill's resolve-locations screen; needs coordinates-to-country lookup, with M7's maps). |
| M7 | In progress | Slice 7a done: the family report on the Special screen (the Reports query counted by order, family or genus against the checklist of its places), identical to Scythebill on 22 oracle cases and 18 on Eric's list. Slice 7b done: the checklist status report (species seen where their place's checklist gives them a status), identical on 14 oracle cases and 14 on Eric's list. Slice 7c done: splits and lumps against every Clements version back to 6.5 and between Clements and AviList (the tables in the data pack), identical on 54 oracle runs and 36 on Eric's list. See docs/SPECIAL.md. Next: timeline, year comparison, then the maps. |

Deferred from M2, by design: files in an older taxonomy or needing an unported Scythebill upgrade are refused with a message to open and save them in Scythebill first (taxonomy upgrades are M8); `ReassignNewBuiltInLocations` (done in M4); app UI for opening and importing lists comes with M3.

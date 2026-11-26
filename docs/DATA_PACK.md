# Data packs

A data pack is one read-only SQLite file holding everything Pipit needs about the world's birds for one taxonomy release: the eBird/Clements base taxonomy, the AviList view over it, regional checklists, localized names, mappings that upgrade older sightings, predefined locations and map outlines. Your own sightings never go in a pack.

The pack format is defined in `src/pipit/datapack/schema.py`. `PACK_FORMAT` is bumped whenever a table changes, and the app refuses packs of another format.

## Building a pack

Phase 1 converts the data Scythebill already prepares each year:

```bash
.venv/bin/pipit-build-pack --scythebill ~/Projects/scythebill-birdlist --out datapacks
```

This takes about 10 seconds and writes `datapacks/pipit-pack-2026.1.sqlite`, about 110 MB. The `datapacks/` folder is git-ignored. Packs are built locally and are not redistributed; see "Licensing" below.

- **Safe to interrupt.** The pack is written to a `.building` file in one transaction, vacuumed, checked with SQLite's integrity check, and only then renamed into place.
- **Deterministic.** The same sources give a byte-identical file. The pack records a hash of every source file, plus the Scythebill commit, instead of a build time.
- **Validated on every build.** The build prints a report. To validate an existing pack:

```bash
.venv/bin/pipit-build-pack --validate datapacks/pipit-pack-2026.1.sqlite   # against the sources
.venv/bin/pipit-build-pack --validate datapacks/pipit-pack-2026.1.sqlite --no-sources
```

## What the validator checks

- SQLite integrity and foreign keys.
- Each taxonomy's tree order (every taxon sits inside its parent's range).
- Every AviList mapping points at an existing Clements taxon.
- The stored Clements→AviList resolutions equal a fresh recomputation.
- Every checklist entry is a known species of its taxonomy.
- Every upgrade mapping points at an existing current taxon.
- Every map outline is a MultiPolygon.
- Against the sources: taxon counts per rank equal the element counts in the XML.
- Against the sources: the 520 per-region checklists agree exactly with Scythebill's `.transpose` files, in both taxonomies.

Two warnings are expected for the 2026 data:

- **12 Clements species have no AviList counterpart.** They are extinct forms AviList does not list. Scythebill gives the same answer.
- **One checklist status was read as native.** `MY-PEN.csv` spells a native status out as "native". Scythebill reads any status text it doesn't know as native, so Pipit stores it the same way and records it in the pack metadata.

## What is in a pack

| Table | Contents |
|---|---|
| `taxonomies`, `taxa`, `alternate_names`, `taxonomy_credits` | The Clements and AviList trees, with every field from the XML. |
| `mappings` | AviList's `<map>`, `<spmap>` and `<sspmap>` definitions, in Clements IDs. |
| `resolutions` | Precomputed AviList counterpart of every Clements taxon. |
| `names` | 71 localized name sets keyed by Clements ID. AviList names are derived from them at runtime (`taxa/avilist_names.py`). |
| `checklists` | 520 regions for each taxonomy. An empty status means native. |
| `upgrade_mappings`, `upgrade_warnings`, `upgrade_subspecies_mappings` | Old→current IDs for every older Clements release Scythebill supports, from 6.5 to 2025. |
| `location_rows`, `display_names` | Scythebill's predefined-location CSVs and display names, as on disk, and its importers' tables (`location-aliases.csv`, `imported-countries-{de,fr,nl}.csv`, `ebird-checklist-headers.csv`), and the splits-and-lumps tables (`report-<version>.csv`, from Scythebill's app resources). Interpreting them is part of M2 (`.bsxm` import), M6 (imports) and M7 (splits and lumps). |
| `map_features` | Natural Earth countries, states and US counties as WKB. Drawing them is part of M7. |

Sightings are always stored with Clements IDs. AviList is a view: `taxa/mapped.py` maps between the two, and so does the `resolutions` table.

## Matching Scythebill exactly

The search rules (`search/`), the AviList mapping (`taxa/mapped.py`) and the AviList names (`taxa/avilist_names.py`) are ports of Scythebill's code. They are checked against Scythebill itself:

- `tools/oracle/run.sh` builds Scythebill's model module from a scratch copy of the checkout. Neither the checkout nor `~/.m2` is touched, and the copy leaves out `.git` and any `.bsxm`.
- It then runs `tools/oracle/Oracle.java` over a corpus of 671 queries and every taxon, and stores the answers in `tests/fixtures/oracle` as counts and hashes of taxon IDs. No names are stored.
- `tests/search/test_against_scythebill.py` requires an exact match. On the 2026 data that covers:

| Check | Compared |
|---|---|
| Search results | 5,368 |
| Clements→AviList resolutions | 35,733 |
| AviList→Clements mappings and disabled flags | 33,769 |
| Derived AviList names (de, fr, en_GB, ja) | 34,090 |

None differ.

Search speed is tested too. A keystroke searches all four indexes (common, alternate common, scientific, alternate scientific), and the 95th percentile must stay under 10 ms. It is well under 1 ms for typical queries and about 3 ms for a single letter.

## The yearly update

1. Update the Scythebill checkout to the release with the new taxonomy.
2. Build and validate a pack. If the year is unchanged, use `--revision 2` or higher.
3. Run `tools/oracle/run.sh` to regenerate the oracle fixtures, then run `scripts/ci.sh`.
4. The pack carries the new upgrade mappings. Applying them to your list is milestone M8.

An independent pipeline from the raw Clements and AviList releases is planned for later; this pack format is what it will produce.

## Licensing

- Clements/eBird data comes from the Cornell Lab of Ornithology. Its terms require attribution and limit redistribution.
- AviList is CC BY 4.0.
- Natural Earth is public domain.
- The regional checklists, mappings and names were prepared by Scythebill (Apache 2.0).

Each pack lists these in `pack_meta.attributions`. Check the terms before publishing a pack or bundling one in a package.

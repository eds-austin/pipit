"""The read-only data pack: one SQLite file per taxonomy release.

Bump ``PACK_FORMAT`` whenever a table changes; the app refuses packs of another format.
"""

from __future__ import annotations

PACK_FORMAT = 1
APPLICATION_ID = 0x50495050  # "PIPP": Pipit pack

SCHEMA = """
CREATE TABLE pack_meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

-- The base taxonomy (eBird/Clements) and mapped views over it (AviList).
CREATE TABLE taxonomies(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('base', 'mapped')),
    base_id TEXT REFERENCES taxonomies(id),
    account_url_format TEXT,
    account_link_title TEXT,
    ord INTEGER NOT NULL UNIQUE
) STRICT;

CREATE TABLE taxonomy_credits(
    taxonomy_id TEXT NOT NULL REFERENCES taxonomies(id),
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (taxonomy_id, ord)
) STRICT;

-- Every taxon. taxo_ord is the pre-order position; a taxon's descendants have
-- taxo_ord in (taxo_ord, subtree_end].
CREATE TABLE taxa(
    taxonomy_id TEXT NOT NULL REFERENCES taxonomies(id),
    id TEXT NOT NULL,
    parent_id TEXT,
    rank TEXT NOT NULL CHECK (rank IN
        ('subspecies', 'group', 'species', 'genus', 'family', 'order', 'class', 'phylum')),
    name TEXT NOT NULL,
    common_name TEXT,
    account_id TEXT,
    concept_id TEXT,
    status TEXT NOT NULL DEFAULT 'LC',
    range TEXT,
    taxonomic_info TEXT,
    miscellaneous TEXT,
    disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
    taxo_ord INTEGER NOT NULL,
    subtree_end INTEGER NOT NULL,
    PRIMARY KEY (taxonomy_id, id),
    UNIQUE (taxonomy_id, taxo_ord)
) STRICT, WITHOUT ROWID;
CREATE INDEX taxa_account ON taxa(account_id) WHERE account_id IS NOT NULL;

CREATE TABLE alternate_names(
    taxonomy_id TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('common', 'scientific')),
    ord INTEGER NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (taxonomy_id, taxon_id, kind, ord),
    FOREIGN KEY (taxonomy_id, taxon_id) REFERENCES taxa(taxonomy_id, id)
) STRICT, WITHOUT ROWID;

-- A mapped taxon's definition in base IDs: <map>, <spmap> or <map>+<sspmap>.
CREATE TABLE mappings(
    taxonomy_id TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('single', 'sp', 'ssp')),
    base_ids TEXT NOT NULL,  -- comma-separated, sorted for 'sp'
    subspecies TEXT,         -- for 'ssp'
    PRIMARY KEY (taxonomy_id, taxon_id),
    FOREIGN KEY (taxonomy_id, taxon_id) REFERENCES taxa(taxonomy_id, id)
) STRICT, WITHOUT ROWID;

-- Precomputed MappedTaxonomy.resolveInto for every base taxon below the root.
-- No row: the base taxon has no counterpart in that taxonomy.
CREATE TABLE resolutions(
    taxonomy_id TEXT NOT NULL REFERENCES taxonomies(id),
    base_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('single', 'sp', 'hybrid')),
    ids TEXT NOT NULL,  -- comma-separated mapped IDs (sorted for sp)
    PRIMARY KEY (taxonomy_id, base_id)
) STRICT, WITHOUT ROWID;

-- Localized common names, keyed by base taxon ID (AviList names are derived at runtime).
CREATE TABLE names(
    locale TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (locale, taxon_id)
) STRICT, WITHOUT ROWID;

-- Built-in regional checklists. status '' = native.
CREATE TABLE checklists(
    taxonomy_id TEXT NOT NULL REFERENCES taxonomies(id),
    region TEXT NOT NULL,
    ord INTEGER NOT NULL,
    taxon_id TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (taxonomy_id, region, taxon_id)
) STRICT, WITHOUT ROWID;

-- Upgrading sightings recorded against an older base taxonomy (TaxonomyMappingLoader.kt).
-- Only what the upgrade reads is kept: the row kind (MULT = to_id is a comma-separated
-- sp.; WARN = warn about to_id), from_id, and to_id (NULL = the same ID). The human-readable
-- names in the source CSVs are left out.
CREATE TABLE upgrade_mappings(
    from_taxonomy TEXT NOT NULL,
    from_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    to_id TEXT,
    PRIMARY KEY (from_taxonomy, from_id)
) STRICT, WITHOUT ROWID;
-- WARN rows (rare) whose to_id needs a warning even without a from_id.
CREATE TABLE upgrade_warnings(
    from_taxonomy TEXT NOT NULL,
    to_id TEXT NOT NULL,
    PRIMARY KEY (from_taxonomy, to_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE upgrade_subspecies_mappings(
    from_taxonomy TEXT NOT NULL,
    ord INTEGER NOT NULL,
    species_id TEXT NOT NULL,
    subspecies TEXT NOT NULL,
    to_id TEXT NOT NULL,
    PRIMARY KEY (from_taxonomy, ord)
) STRICT, WITHOUT ROWID;

-- Predefined locations: rows of Scythebill's location CSVs, as on disk.
CREATE TABLE location_rows(
    source TEXT NOT NULL,  -- file name, e.g. countries.csv
    ord INTEGER NOT NULL,  -- 0 = header row
    fields TEXT NOT NULL,  -- JSON array of strings
    PRIMARY KEY (source, ord)
) STRICT, WITHOUT ROWID;

-- Display names: 'location' (locations*.properties) and 'synthetic' (synthetic locations).
CREATE TABLE display_names(
    kind TEXT NOT NULL CHECK (kind IN ('location', 'synthetic')),
    locale TEXT NOT NULL,  -- '' = default
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (kind, locale, key)
) STRICT, WITHOUT ROWID;

-- Natural Earth map layers, geometry as WKB.
CREATE TABLE map_features(
    layer TEXT NOT NULL,
    ord INTEGER NOT NULL,
    attributes TEXT NOT NULL,  -- JSON object
    geometry BLOB NOT NULL,
    water BLOB,
    PRIMARY KEY (layer, ord)
) STRICT, WITHOUT ROWID;
"""

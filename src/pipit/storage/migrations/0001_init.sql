-- Pipit list database, schema 1.
-- Holds exactly what a Scythebill .bsxm holds (see pipit/domain/report.py), so a list
-- exports back to the same file. "ord" columns keep the file order Scythebill writes.
-- Every user table has an integer rowid so the undo journal can address rows.

CREATE TABLE meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE ext_taxonomies(
    id INTEGER PRIMARY KEY,
    taxonomy_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    account_url_format TEXT,
    account_link_title TEXT,
    credits TEXT NOT NULL DEFAULT '[]',  -- JSON array
    ord INTEGER NOT NULL
) STRICT;

CREATE TABLE ext_taxa(
    id INTEGER PRIMARY KEY,
    taxonomy_id TEXT NOT NULL REFERENCES ext_taxonomies(taxonomy_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    taxon_id TEXT NOT NULL,
    parent_taxon_id TEXT,
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
    alternate_names TEXT NOT NULL DEFAULT '[]',         -- JSON array
    alternate_common_names TEXT NOT NULL DEFAULT '[]',  -- JSON array
    checklists TEXT,                                    -- raw "<checklists>" text
    ord INTEGER NOT NULL,                               -- pre-order position
    UNIQUE (taxonomy_id, taxon_id)
) STRICT;

CREATE TABLE locations(
    id INTEGER PRIMARY KEY,
    xml_id TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
    ord INTEGER NOT NULL,  -- among siblings (roots: among roots)
    type TEXT CHECK (type IN ('region', 'country', 'state', 'county', 'city', 'town', 'park')),
    name TEXT NOT NULL,
    ebird_code TEXT,
    ebird_hotspot_id TEXT,
    latitude TEXT,   -- seven-decimal strings, as Scythebill stores them
    longitude TEXT,
    private INTEGER NOT NULL DEFAULT 0 CHECK (private IN (0, 1)),
    description TEXT,
    restored INTEGER NOT NULL DEFAULT 0 CHECK (restored IN (0, 1)),
    CHECK ((latitude IS NULL) = (longitude IS NULL)),
    UNIQUE (parent_id, name)  -- roots (NULL parent) may share names
) STRICT;

CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    xml_id TEXT NOT NULL UNIQUE,
    name TEXT,
    abbreviation TEXT,
    ord INTEGER NOT NULL,
    CHECK (name IS NOT NULL OR abbreviation IS NOT NULL)
) STRICT;

CREATE TABLE trips(
    id INTEGER PRIMARY KEY,
    xml_id TEXT NOT NULL UNIQUE CHECK (xml_id != ''),
    location_xml_id TEXT REFERENCES locations(xml_id) ON UPDATE CASCADE,
    start_date TEXT NOT NULL,  -- partial date, as written in the file
    end_date TEXT NOT NULL,
    start_time TEXT,           -- "HH:mm"
    name TEXT,
    notes TEXT,
    ord INTEGER NOT NULL
) STRICT;

CREATE TABLE links(
    id INTEGER PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    uri TEXT NOT NULL,
    name TEXT
) STRICT;

CREATE TABLE sightings(
    id INTEGER PRIMARY KEY,
    ord INTEGER NOT NULL,
    taxonomy_id TEXT REFERENCES ext_taxonomies(taxonomy_id) ON UPDATE CASCADE,  -- NULL: base
    kind TEXT NOT NULL CHECK (kind IN ('single', 'sp', 'hybrid', 'ssp')),
    taxon_id TEXT,     -- single, or the base taxon of 'ssp'; sp/hybrid parts in sighting_taxa
    subspecies TEXT,   -- 'ssp' only
    location_xml_id TEXT REFERENCES locations(xml_id) ON UPDATE CASCADE,
    date TEXT,         -- partial date, as written in the file
    date_y INTEGER,
    date_m INTEGER,
    date_d INTEGER,
    time TEXT,         -- "HH:mm"
    trip_xml_id TEXT REFERENCES trips(xml_id) ON UPDATE CASCADE,
    count TEXT,        -- "12", "~20"
    male INTEGER NOT NULL DEFAULT 0 CHECK (male IN (0, 1)),
    female INTEGER NOT NULL DEFAULT 0 CHECK (female IN (0, 1)),
    immature INTEGER NOT NULL DEFAULT 0 CHECK (immature IN (0, 1)),
    adult INTEGER NOT NULL DEFAULT 0 CHECK (adult IN (0, 1)),
    heard_only INTEGER NOT NULL DEFAULT 0 CHECK (heard_only IN (0, 1)),
    photographed INTEGER NOT NULL DEFAULT 0 CHECK (photographed IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'none',
    breeding TEXT NOT NULL DEFAULT '',
    description TEXT,
    CHECK ((kind IN ('single', 'ssp')) = (taxon_id IS NOT NULL)),
    CHECK ((kind = 'ssp') = (subspecies IS NOT NULL))
) STRICT;
CREATE INDEX sightings_taxon ON sightings(taxon_id);
CREATE INDEX sightings_location_date ON sightings(location_xml_id, date_y, date_m, date_d);
CREATE INDEX sightings_trip ON sightings(trip_xml_id);

CREATE TABLE sighting_taxa(
    id INTEGER PRIMARY KEY,
    sighting_id INTEGER NOT NULL REFERENCES sightings(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    taxon_id TEXT NOT NULL,
    UNIQUE (sighting_id, ord),
    UNIQUE (sighting_id, taxon_id)
) STRICT;
CREATE INDEX sighting_taxa_taxon ON sighting_taxa(taxon_id);

CREATE TABLE sighting_users(
    id INTEGER PRIMARY KEY,
    sighting_id INTEGER NOT NULL REFERENCES sightings(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    user_xml_id TEXT NOT NULL REFERENCES users(xml_id) ON UPDATE CASCADE,
    UNIQUE (sighting_id, user_xml_id)
) STRICT;

-- Visits are keyed like Scythebill's VisitInfoKey; the location may be unknown (Scythebill
-- keeps such visits), so it is not a foreign key.
CREATE TABLE visits(
    id INTEGER PRIMARY KEY,
    ord INTEGER NOT NULL,
    location_xml_id TEXT NOT NULL,
    date TEXT NOT NULL,
    date_y INTEGER,
    date_m INTEGER,
    date_d INTEGER,
    start_time TEXT NOT NULL DEFAULT '',  -- '' = no start time
    observation_type TEXT NOT NULL,
    area_hectares TEXT,   -- the float32 value, as exact text
    distance_km TEXT,     -- the float32 value, as exact text
    duration_minutes INTEGER CHECK (duration_minutes > 0),
    party_size INTEGER CHECK (party_size > 0),
    comments TEXT,
    complete INTEGER NOT NULL DEFAULT 0 CHECK (complete IN (0, 1)),
    UNIQUE (location_xml_id, date, start_time)
) STRICT;

CREATE TABLE photos(
    id INTEGER PRIMARY KEY,
    sighting_id INTEGER REFERENCES sightings(id) ON DELETE CASCADE,
    trip_id INTEGER REFERENCES trips(id) ON DELETE CASCADE,
    visit_id INTEGER REFERENCES visits(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    uri TEXT NOT NULL,
    name TEXT,
    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    CHECK ((sighting_id IS NOT NULL) + (trip_id IS NOT NULL) + (visit_id IS NOT NULL) = 1)
) STRICT;
CREATE INDEX photos_sighting ON photos(sighting_id) WHERE sighting_id IS NOT NULL;
CREATE INDEX photos_trip ON photos(trip_id) WHERE trip_id IS NOT NULL;
CREATE INDEX photos_visit ON photos(visit_id) WHERE visit_id IS NOT NULL;

CREATE TABLE checklists(
    id INTEGER PRIMARY KEY,
    location_xml_id TEXT NOT NULL UNIQUE REFERENCES locations(xml_id) ON UPDATE CASCADE,
    ord INTEGER NOT NULL
) STRICT;

CREATE TABLE checklist_entries(
    id INTEGER PRIMARY KEY,
    checklist_id INTEGER NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('single', 'sp', 'hybrid', 'ssp')),
    taxon_ids TEXT NOT NULL,  -- comma-separated, sorted for sp/hybrid
    subspecies TEXT,
    status TEXT               -- NULL = native
) STRICT;

CREATE TABLE report_prefs(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT
) STRICT;

CREATE TABLE one_time_upgrades(
    id INTEGER PRIMARY KEY,
    ord INTEGER NOT NULL,
    name TEXT NOT NULL UNIQUE
) STRICT;

-- Undo/redo journal: triggers (generated by migrate.py) append the inverse SQL of every
-- change made while undo_state.recording_action is set.
CREATE TABLE undo_actions(
    id INTEGER PRIMARY KEY,
    stack TEXT NOT NULL CHECK (stack IN ('undo', 'redo')),
    label TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
CREATE TABLE undo_log(
    id INTEGER PRIMARY KEY,
    action_id INTEGER NOT NULL REFERENCES undo_actions(id) ON DELETE CASCADE,
    statement TEXT NOT NULL
) STRICT;
CREATE INDEX undo_log_action ON undo_log(action_id);
CREATE TABLE undo_state(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    recording_action INTEGER
) STRICT;
INSERT INTO undo_state VALUES (1, NULL);

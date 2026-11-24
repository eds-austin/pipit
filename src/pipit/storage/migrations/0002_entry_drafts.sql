-- Schema 2: the unsaved Enter Sightings session, kept so a crash or a closed window
-- loses nothing. Not journaled for undo (drafts change on every keystroke).
CREATE TABLE entry_drafts(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    saved_at TEXT NOT NULL,
    session TEXT NOT NULL  -- EntrySession.to_json()
) STRICT;

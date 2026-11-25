-- Schema 3: every (ancestor, descendant) pair of the location tree, so "everything in
-- this place" is one join. Derived from locations.parent_id and kept current by the
-- triggers below, including while undo and redo replay their statements; it is not
-- journaled itself. The integrity check compares it with a fresh walk of the tree.
CREATE TABLE location_closure(
    ancestor INTEGER NOT NULL,
    descendant INTEGER NOT NULL,
    depth INTEGER NOT NULL CHECK (depth >= 0),  -- 0: the location itself
    PRIMARY KEY (ancestor, descendant)
) STRICT, WITHOUT ROWID;

CREATE INDEX location_closure_descendant ON location_closure(descendant, ancestor);

WITH RECURSIVE pairs(ancestor, descendant, depth) AS (
    SELECT id, id, 0 FROM locations
    UNION ALL
    SELECT pairs.ancestor, locations.id, pairs.depth + 1
    FROM pairs JOIN locations ON locations.parent_id = pairs.descendant
)
INSERT INTO location_closure SELECT ancestor, descendant, depth FROM pairs;

CREATE TRIGGER closure_locations_insert AFTER INSERT ON locations BEGIN
    INSERT INTO location_closure(ancestor, descendant, depth)
    SELECT NEW.id, NEW.id, 0
    UNION ALL
    SELECT ancestor, NEW.id, depth + 1 FROM location_closure WHERE descendant = NEW.parent_id;
END;

CREATE TRIGGER closure_locations_delete AFTER DELETE ON locations BEGIN
    DELETE FROM location_closure WHERE descendant = OLD.id OR ancestor = OLD.id;
END;

-- Moving a subtree: drop the links from its old ancestors, then link every new ancestor
-- to every node of the subtree.
CREATE TRIGGER closure_locations_reparent AFTER UPDATE OF parent_id ON locations
WHEN OLD.parent_id IS NOT NEW.parent_id BEGIN
    DELETE FROM location_closure
    WHERE descendant IN (SELECT descendant FROM location_closure WHERE ancestor = NEW.id)
      AND ancestor NOT IN (SELECT descendant FROM location_closure WHERE ancestor = NEW.id);
    INSERT INTO location_closure(ancestor, descendant, depth)
    SELECT above.ancestor, below.descendant, above.depth + below.depth + 1
    FROM location_closure AS above, location_closure AS below
    WHERE above.descendant = NEW.parent_id AND below.ancestor = NEW.id;
END;

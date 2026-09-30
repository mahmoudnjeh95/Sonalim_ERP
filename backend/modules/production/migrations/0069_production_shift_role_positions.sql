-- Which HR positions may be named in each of the fiche de shift's four person fields.
--
-- The header's Conducteur ligne, Agent de fabrication, Machiniste and Aide machiniste
-- were free text, so the same person arrived spelled three ways and nothing could be
-- counted by who ran the line. They become lists of the plant's own people, and this
-- table is what says who belongs in each one: a role maps to one or more HR positions,
-- configured in Production settings rather than guessed from a job title's spelling.
--
-- The position is referenced by id, not by name, so renaming a position in HR never
-- empties a list. Nothing here is referenced by a report: a shift keeps the name it was
-- filed under, the way it keeps its team's name.
CREATE TABLE IF NOT EXISTS production.shift_role_positions (
    tenant_id TEXT NOT NULL,
    -- One of the header's four person fields, named as the report's own column is.
    role TEXT NOT NULL CHECK (role IN ('conducteur', 'agent_fabrication', 'machiniste', 'aide_machiniste')),
    -- An hr.positions id. Not a foreign key: production must not depend on hr's tables,
    -- so a mapping to a position hr has since deleted is simply skipped when listing.
    position_id TEXT NOT NULL,
    PRIMARY KEY (tenant_id, role, position_id)
);

CREATE INDEX IF NOT EXISTS shift_role_positions_role_idx
    ON production.shift_role_positions (tenant_id, role);

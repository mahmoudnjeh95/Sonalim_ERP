-- What the production dashboard needs to know that nothing recorded before.
-- All three start empty: nothing is pre-filled with a suggested value, so a
-- tenant that has not configured them sees "not set" instead of a guess.
--
-- Shift and team are the labels reports are filed under (core.report_options),
-- stored as text for the same reason reports store them: renaming a shift must
-- not rewrite history. location_id is an opaque reference into warehouse, like
-- production_reports.equipment_id points into maintenance -- production does not
-- join into those schemas.
--
-- Machines are deliberately not here: which machines a line has, and which stage
-- each works at, live in maintenance's equipment registry and are read from it.

-- Clock times of each shift, so "the shift running now" can be worked out.
-- end_time earlier than start_time means the shift runs through midnight.
CREATE TABLE IF NOT EXISTS production.shift_windows (
    tenant_id TEXT NOT NULL,
    shift TEXT NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    PRIMARY KEY (tenant_id, shift),
    CHECK (start_time <> end_time)
);

-- Which team works which shift on which line.
CREATE TABLE IF NOT EXISTS production.line_team_roster (
    tenant_id TEXT NOT NULL,
    work_center_id TEXT NOT NULL,
    shift TEXT NOT NULL,
    team TEXT NOT NULL,
    PRIMARY KEY (tenant_id, work_center_id, shift)
);

-- Which stores hold finished product waiting to be released (line) and which
-- receive it (final).
CREATE TABLE IF NOT EXISTS production.store_roles (
    tenant_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('line', 'final')),
    PRIMARY KEY (tenant_id, location_id)
);

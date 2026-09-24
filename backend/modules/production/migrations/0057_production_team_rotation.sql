-- Replaces line_team_roster: that table could only ever hold one team per
-- shift (one row per work_center_id + shift), which cannot express a 4-team
-- rotation with a resting team. This table anchors the whole plant's rotation
-- instead: on `anchor_date`, each team sits at `anchor_stop` in the cycle
-- [shift_0, shift_1, ..., shift_(n-1), rest] (n = the plant's configured shift
-- count, sorted by start time; `anchor_stop = n` means resting). A team's stop
-- on any other date is (anchor_stop + (date - anchor_date).days) mod (n + 1) --
-- see modules/production/domain/dashboard.py:team_rotation_schedule. All rows
-- for a tenant share the same anchor_date (enforced in the service, not here,
-- same as every other replace-the-whole-list setting on this dashboard).
CREATE TABLE production.team_rotation (
    tenant_id TEXT NOT NULL,
    team TEXT NOT NULL,
    anchor_date DATE NOT NULL,
    anchor_stop INTEGER NOT NULL CHECK (anchor_stop >= 0),
    PRIMARY KEY (tenant_id, team)
);

DROP TABLE production.line_team_roster;

-- A work center like Line_1_PL can carry more than one machine running at
-- once (maintenance.equipment already supports this -- the plant just hadn't
-- added the second/third one yet). Two additions make that fact usable:
-- who supervises an OF, and which machine within the line a given report was
-- run on, so productivity can be checked per machine, not just per line.

-- Optional, unlike work_center_id: the plant wants a name on file when one is
-- known, but existing OFs have none and creation must not be blocked on it.
-- No FK: core.users is not one of the shared-kernel tables a module may
-- reference directly (see created_by/closed_by above, which have none either).
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS supervisor_id TEXT;

-- Which physical machine within the report's work center ran this shift.
-- Opaque reference into maintenance.equipment -- same reasoning as
-- maintenance.equipment.work_center_id pointing back into production: modules
-- do not hold live FKs into another module's schema. Set once at creation,
-- same as work_center_id/team/shift, and required before a report can move
-- from draft to submitted (see ProductionReportService.submit_report).
ALTER TABLE production.production_reports ADD COLUMN IF NOT EXISTS equipment_id TEXT;

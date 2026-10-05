-- Deleting a shift report that was never fully submitted (spec
-- 2026-09-22-shift-report-lifecycle-design.md): a team member removes a report opened by
-- mistake, or one returned for correction that should not be redone at all. Anything
-- submitted or validated is refused by the service -- validating is what posts to stock.
--
-- Not an admin_* code: this is an everyday action for the team that files the report, so
-- it belongs in the module's default "Production" role like the other shift rights
-- (see 0070 for why the admin_ prefix is what excludes a code from that role).
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, 'production.shift.delete'
FROM core.roles r
WHERE r.name = 'Production'
ON CONFLICT DO NOTHING;

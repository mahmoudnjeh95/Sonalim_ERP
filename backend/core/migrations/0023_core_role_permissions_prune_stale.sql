-- Prune stale permission rows that no module.json declares any more.
--
-- production.view_machines / manage_machines and production.manage_reports /
-- validate_reports were removed from production/module.json in earlier
-- commits (nothing gates on them any more), but the default "Production"
-- role (and any user with a direct grant) still carries the old rows from
-- before that cleanup. The role-edit screen loads a role's current
-- permissions into the checkbox list, so they came back pre-checked, and
-- saving re-submitted the full set — which core.roles._validate_known_permissions
-- now rejects since these codes are absent from the catalog.
DELETE FROM core.role_permissions
WHERE permission IN (
    'production.view_machines',
    'production.manage_machines',
    'production.manage_reports',
    'production.validate_reports'
);

DELETE FROM core.user_permissions
WHERE permission IN (
    'production.view_machines',
    'production.manage_machines',
    'production.manage_reports',
    'production.validate_reports'
);

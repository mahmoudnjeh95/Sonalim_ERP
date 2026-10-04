-- Realign the default role bundles with what permissions_registry.py actually defines.
--
-- Two separate problems, both from the same cause.
--
-- 1. production.admin_machines is declared by no module.json any more. It sits in the
--    Administrateur role, so that role is currently unsaveable: the role-edit screen
--    loads a role's permissions into the checkbox list pre-checked, saving re-submits
--    the full set, and core.roles._validate_known_permissions rejects the unknown code
--    with a 422. Same failure 0023 fixed for its batch.
--
-- 2. The default roles drifted from their definitions. ensure_default_roles() only ever
--    INSERTs (ON CONFLICT DO NOTHING), so a permission that LEAVES a role's definition
--    is never removed from the row set -- it just accumulates. On the dev tenant the
--    "Finance" and "Ressources humaines" roles had picked up the whole payroll module,
--    admin_* codes included, and every module role still carried its own admin_* codes.
--    That silently defeats the admin_* split those roles are built on.
--
-- This deletes only rows the registry does not put there, and only from the default
-- roles it owns (by code). Custom roles an admin created are left alone, as are direct
-- per-user grants in core.user_permissions -- a deliberate one-off grant is exactly what
-- the admin_* codes are for, and it is not this migration's business to revoke them.
-- After this runs, ensure_default_roles() re-inserts whatever is currently defined, so
-- the two together converge on the definition instead of drifting from it.

-- 1. The undeclared code, wherever it sits.
DELETE FROM core.role_permissions WHERE permission = 'production.admin_machines';
DELETE FROM core.user_permissions WHERE permission = 'production.admin_machines';

-- 2. Strip admin_* codes back out of the everyday per-module roles. The role code is the
--    module name (see MODULE_LABELS), so a default role should never hold an admin_* code
--    -- of its own module or, as the drift showed, of another one.
DELETE FROM core.role_permissions rp
USING core.roles r
WHERE rp.role_id = r.id
  AND r.code <> 'administrateur'
  AND r.code IN (
      'crm','finance','hr','maintenance','payroll','procurement',
      'production','qc','scan','sales','warehouse'
  )
  AND split_part(rp.permission, '.', 2) LIKE 'admin\_%';

-- 3. Same roles: drop permissions belonging to a DIFFERENT module than the role itself.
--    The registry only ever bundles a module's own codes, so anything else is drift
--    (the payroll.* rows that had leaked into Finance and HR).
DELETE FROM core.role_permissions rp
USING core.roles r
WHERE rp.role_id = r.id
  AND r.code IN (
      'crm','finance','hr','maintenance','payroll','procurement',
      'production','qc','scan','sales','warehouse'
  )
  AND split_part(rp.permission, '.', 1) <> r.code;

-- 4. The codes held back from every everyday role on purpose
--    (DELIBERATE_GRANT_PERMISSIONS): personal data, and running payroll.
DELETE FROM core.role_permissions rp
USING core.roles r
WHERE rp.role_id = r.id
  AND r.code <> 'administrateur'
  AND rp.permission IN ('hr.view_sensitive', 'hr.view_payroll', 'hr.manage_payroll');

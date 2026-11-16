-- The receivables screens' codes for the Administrateur role of tenants that already have their default roles
-- (ensure_default_roles() only runs from the seed scripts; see treasury/0008). Administrateur only: the
-- everyday finance role is handed out through the role screen. finance.admin_receivables is included so
-- someone can set the dunning ladder and the credit rules, as treasury/0008 does with treasury.admin_config.
-- finance.admin_credit_override is left out on purpose: confirming an order past the credit rules is granted
-- one user at a time (ADMINISTRATOR_HELD_BACK_PERMISSIONS). Inserts only.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, granted.permission
FROM core.roles r
CROSS JOIN unnest(ARRAY[
    'finance.view_receivables',
    'finance.manage_receivables',
    'finance.admin_receivables',
    'finance.manage_dunning'
]) AS granted(permission)
WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;

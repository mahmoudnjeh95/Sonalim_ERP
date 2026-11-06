-- The company details every dunning letter prints, set in Recouvrement > Paramètres; an empty one is omitted.
ALTER TABLE finance.receivables_settings ADD COLUMN IF NOT EXISTS company_email TEXT;
ALTER TABLE finance.receivables_settings ADD COLUMN IF NOT EXISTS company_tax_id TEXT;
ALTER TABLE finance.receivables_settings ADD COLUMN IF NOT EXISTS company_rccm TEXT;
ALTER TABLE finance.receivables_settings ADD COLUMN IF NOT EXISTS signatory_title TEXT;

-- By decision the Administrateur role holds the credit override (confirming an order past the credit rules),
-- on tenants that already have their default roles. Inserts only.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, 'finance.admin_credit_override'
FROM core.roles r
WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;

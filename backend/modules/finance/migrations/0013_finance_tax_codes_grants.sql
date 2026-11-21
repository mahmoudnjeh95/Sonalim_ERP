-- finance.manage_tax_codes (the tax-code catalogue screen) for the Administrateur role of tenants that
-- already have their default roles, as 0010 does for receivables. Inserts only.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, 'finance.manage_tax_codes' FROM core.roles r WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;

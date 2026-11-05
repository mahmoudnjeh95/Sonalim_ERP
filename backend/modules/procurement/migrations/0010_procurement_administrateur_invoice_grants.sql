-- The complete purchase invoice declared two codes that tenants with existing default roles never
-- receive (ensure_default_roles() only runs from the seed scripts; see treasury/0008). By decision,
-- the Administrateur always holds both: the invoice settings (default VAT rate) and validating an
-- invoice beyond what the goods receipts carried. No other role gets them. Inserts only.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, granted.permission
FROM core.roles r
CROSS JOIN unnest(ARRAY[
    'procurement.admin_purchase_invoices',
    'procurement.admin_invoice_beyond_receipts'
]) AS granted(permission)
WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;

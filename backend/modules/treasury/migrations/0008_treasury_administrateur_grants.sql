-- ensure_default_roles() only runs from the seed scripts, so a tenant that already has the default
-- roles never picks up the codes treasury and the stock and purchase-invoice work declared, and
-- nobody could open those screens after a deploy. This carries them to the Administrateur role of
-- those tenants, the same way scan/0003 does; a brand new database has no role yet and gets nothing here.
--
-- Administrateur only, by decision: no treasury role is created and the everyday procurement and
-- warehouse roles get nothing. An admin hands those out through the role screen.
--
-- Left out on purpose: treasury.admin_ledger_posting and treasury.admin_add_prior_year_invoice
-- are granted deliberately, one user at a time (see ADMINISTRATOR_HELD_BACK_PERMISSIONS in
-- core/permissions_registry.py). Inserts only: nothing an admin already changed is revoked.
--
-- The view codes are what those screens need to load: locations, stock and vouchers read through
-- view_moves, the product, partner and currency pickers through the core codes. Cycle counts are
-- here because a started count freezes stock, so somebody must be able to finish or cancel it.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, granted.permission
FROM core.roles r
CROSS JOIN unnest(ARRAY[
    'treasury.view',
    'treasury.manage_accounts',
    'treasury.manage_receipts',
    'treasury.manage_disbursements',
    'treasury.collect_instruments',
    'treasury.import_statements',
    'treasury.admin_config',
    'warehouse.view_moves',
    'warehouse.manage_vouchers',
    'warehouse.post_vouchers',
    'warehouse.view_fulfillment',
    'warehouse.view_valuation',
    'warehouse.view_cycle_counts',
    'warehouse.manage_cycle_counts',
    'procurement.view_purchase_invoices',
    'procurement.manage_purchase_invoices',
    'core.view_partners',
    'core.view_products',
    'core.view_exchange_rates'
]) AS granted(permission)
WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;

-- Rename treasury.add_prior_year_invoice -> treasury.admin_add_prior_year_invoice.
--
-- Paying an invoice of a previous year is an override, so it becomes an admin_* code, which
-- core/permissions_registry.py leaves out of the everyday roles. Existing grants are carried over rather
-- than dropped: whoever could do this yesterday still can, until an admin or the next
-- ensure_default_roles() run takes it away. Running this twice changes nothing: the old code is gone
-- after the first run.
UPDATE core.role_permissions
SET permission = 'treasury.admin_add_prior_year_invoice'
WHERE permission = 'treasury.add_prior_year_invoice'
  AND NOT EXISTS (
      SELECT 1 FROM core.role_permissions existing
      WHERE existing.role_id = core.role_permissions.role_id
        AND existing.permission = 'treasury.admin_add_prior_year_invoice'
  );

UPDATE core.user_permissions
SET permission = 'treasury.admin_add_prior_year_invoice'
WHERE permission = 'treasury.add_prior_year_invoice'
  AND NOT EXISTS (
      SELECT 1 FROM core.user_permissions existing
      WHERE existing.user_id = core.user_permissions.user_id
        AND existing.permission = 'treasury.admin_add_prior_year_invoice'
  );

-- Any row the guard above skipped was a duplicate: the holder already had the new code.
DELETE FROM core.role_permissions WHERE permission = 'treasury.add_prior_year_invoice';
DELETE FROM core.user_permissions WHERE permission = 'treasury.add_prior_year_invoice';

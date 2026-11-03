-- Rename production.shift.unlock_validated -> production.admin_unlock_validated.
--
-- Reopening a validated shift rewrites figures that are already posted to stock
-- (validating a shift is what posts it), so this right belongs with the module's
-- other admin_* codes rather than in the everyday "Production" role.
--
-- The rename is what moves it: core/permissions_registry.py builds each module's
-- default role by excluding codes whose name starts with admin_, and it splits the
-- permission on the FIRST dot only -- so "production.shift.admin_unlock_validated"
-- would still have been bundled (its tail is "shift.admin_unlock_validated"). The
-- shift. segment has to go for the rule to fire.
--
-- Existing grants are carried over rather than dropped: whoever could unlock a shift
-- yesterday still can. ensure_default_roles() then re-derives the role bundles, which
-- removes the old code from the Production role and leaves the new one in
-- Administrateur. ON CONFLICT covers the user/role that already holds both.
UPDATE core.role_permissions
SET permission = 'production.admin_unlock_validated'
WHERE permission = 'production.shift.unlock_validated'
  AND NOT EXISTS (
      SELECT 1 FROM core.role_permissions existing
      WHERE existing.role_id = core.role_permissions.role_id
        AND existing.permission = 'production.admin_unlock_validated'
  );

UPDATE core.user_permissions
SET permission = 'production.admin_unlock_validated'
WHERE permission = 'production.shift.unlock_validated'
  AND NOT EXISTS (
      SELECT 1 FROM core.user_permissions existing
      WHERE existing.user_id = core.user_permissions.user_id
        AND existing.permission = 'production.admin_unlock_validated'
  );

-- Any row the guard above skipped was a duplicate: the holder already had the new code.
DELETE FROM core.role_permissions WHERE permission = 'production.shift.unlock_validated';
DELETE FROM core.user_permissions WHERE permission = 'production.shift.unlock_validated';

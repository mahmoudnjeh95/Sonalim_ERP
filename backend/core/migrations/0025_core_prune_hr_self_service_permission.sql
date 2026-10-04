-- Prune hr.self_service, removed from hr/module.json.
--
-- The code was declared and bundled into the default "Ressources humaines" role,
-- but nothing ever gated on it: it appeared in no require_permission() and no
-- user_has_permission() call anywhere in the backend. It was dead, and looked live.
--
-- Same reason 0023 pruned its batch: the role-edit screen loads a role's current
-- permissions into the checkbox list, so an undeclared leftover comes back
-- pre-checked and saving re-submits it -- which core.roles._validate_known_permissions
-- rejects, since the code is no longer in the catalog. That would make the HR role
-- unsaveable until the row was gone.
DELETE FROM core.role_permissions WHERE permission = 'hr.self_service';
DELETE FROM core.user_permissions WHERE permission = 'hr.self_service';

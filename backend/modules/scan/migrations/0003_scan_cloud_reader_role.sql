-- scan.use_cloud_reader: reading fiches with Claude sends the photos (workers' names on
-- them) to the Anthropic API, so it is granted deliberately, never with the everyday
-- "scan" role. It reaches users through the full-access Administrateur role and through a
-- role of its own, "scan_cloud", that holds only this permission.
-- ensure_default_roles() (core/permissions_registry.py) does the same for new tenants;
-- this carries it to the tenants that already have the default roles.

INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, 'scan.use_cloud_reader'
FROM core.roles r
WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;

INSERT INTO core.roles (id, tenant_id, code, name, description)
SELECT gen_random_uuid()::text, r.tenant_id, 'scan_cloud', 'Numérisation cloud (Claude)',
       'Lire les fiches papier avec Claude : les photos sont envoyées à l''API Anthropic.'
FROM core.roles r
WHERE r.code = 'administrateur'
ON CONFLICT (tenant_id, code) DO NOTHING;

INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, 'scan.use_cloud_reader'
FROM core.roles r
WHERE r.code = 'scan_cloud'
ON CONFLICT (role_id, permission) DO NOTHING;

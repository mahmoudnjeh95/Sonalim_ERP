INSERT INTO core.partners (id, tenant_id, name, kind, industry, website, phone, email, status)
SELECT a.id, a.tenant_id,
       CASE WHEN p.id IS NULL THEN a.name ELSE a.name || ' (CRM)' END,
       'customer', a.industry, a.website, a.phone, NULL, a.status
FROM crm.accounts a
LEFT JOIN core.partners p ON p.tenant_id = a.tenant_id AND p.name = a.name
ON CONFLICT (id) DO NOTHING;

ALTER TABLE crm.opportunities DROP CONSTRAINT IF EXISTS opportunities_account_id_fkey;
ALTER TABLE crm.opportunities RENAME COLUMN account_id TO partner_id;

ALTER TABLE crm.leads DROP CONSTRAINT IF EXISTS leads_converted_account_id_fkey;
ALTER TABLE crm.leads RENAME COLUMN converted_account_id TO converted_partner_id;

DROP TABLE crm.accounts;

-- Dunning and the credit hold only count installments that fall due on or after this date. A tenant that
-- already has open invoices starts chasing from the day this ships: its older invoices may have been paid
-- before treasury recorded payments, and would otherwise put every customer on hold at once. Finance moves
-- the date back (Recouvrement > Paramètres) once those payments are recorded.
ALTER TABLE finance.receivables_settings ADD COLUMN IF NOT EXISTS chase_from DATE;

INSERT INTO finance.receivables_settings (tenant_id, chase_from, updated_by)
SELECT DISTINCT tenant_id, CURRENT_DATE, 'system:migration'
FROM finance.invoices
WHERE status IN ('issued', 'partially_paid')
ON CONFLICT (tenant_id) DO UPDATE SET chase_from = COALESCE(finance.receivables_settings.chase_from, EXCLUDED.chase_from);

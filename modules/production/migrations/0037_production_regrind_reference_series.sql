-- Every regrind batch (RegrindService.create_regrind_batch, manual or the
-- automatic one decision 11 opens from a daily report) is created through
-- WorkOrderService.create_work_order exactly like a production order, and
-- until now both drew their reference from the same "production.work_orders"
-- / "OF-" sequence. A rebroyat run and the OF whose scrap fed it therefore
-- came out interleaved in one number space and indistinguishable by
-- reference alone -- both read "OF-000045". Regrind now gets its own
-- "production.regrind_orders" / "OFR-" series (see service.py's
-- reference_sequence/reference_prefix and regrind_service.py's call site).

-- Renumber every existing regrind order in creation order, the same
-- technique migration 0012 used to backfill "OF-" the first time.
WITH numbered AS (
    SELECT wo.id, wo.tenant_id, ROW_NUMBER() OVER (PARTITION BY wo.tenant_id ORDER BY wo.created_at) AS rn
    FROM production.work_orders wo
    JOIN production.regrind_batches rb ON rb.work_order_id = wo.id
)
UPDATE production.work_orders wo
SET reference = 'OFR-' || LPAD(numbered.rn::text, 6, '0')
FROM numbered
WHERE wo.id = numbered.id;

-- Seed the new sequence so the next regrind batch -- manual or automatic --
-- continues this count instead of restarting at OFR-000001 and colliding
-- with a just-renumbered row.
INSERT INTO core.sequences (tenant_id, name, prefix, next_value)
SELECT wo.tenant_id, 'production.regrind_orders', 'OFR-', COUNT(*)
FROM production.work_orders wo
JOIN production.regrind_batches rb ON rb.work_order_id = wo.id
GROUP BY wo.tenant_id
ON CONFLICT (tenant_id, name) DO UPDATE SET next_value = GREATEST(core.sequences.next_value, EXCLUDED.next_value);

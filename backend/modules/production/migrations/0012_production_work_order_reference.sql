-- Work orders get a human-readable auto-generated reference (e.g. "OF-000001"),
-- shown in the UI instead of the raw internal id.
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS reference TEXT;

-- Backfill existing rows in creation order, per tenant, using the same "OF-"
-- prefix new work orders get going forward (core.sequences, seeded lazily by
-- WorkOrderService.create_work_order via core.domain.sequences.next_sequence_value).
WITH numbered AS (
    SELECT id, tenant_id, ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at) AS rn
    FROM production.work_orders
    WHERE reference IS NULL
)
UPDATE production.work_orders wo
SET reference = 'OF-' || LPAD(numbered.rn::text, 6, '0')
FROM numbered
WHERE wo.id = numbered.id;

-- Keep core.sequences in sync so the next work order created continues the
-- count instead of restarting at OF-000001 and colliding with a backfilled row.
INSERT INTO core.sequences (tenant_id, name, prefix, next_value)
SELECT tenant_id, 'production.work_orders', 'OF-', COUNT(*)
FROM production.work_orders
GROUP BY tenant_id
ON CONFLICT (tenant_id, name) DO UPDATE SET next_value = GREATEST(core.sequences.next_value, EXCLUDED.next_value);

ALTER TABLE production.work_orders ALTER COLUMN reference SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS work_orders_tenant_reference_idx ON production.work_orders (tenant_id, reference);

-- Migration 0037 gave every regrind order an "OFR-" reference, but it only
-- renumbers the rows that exist at the moment it runs. A regrind batch created
-- afterwards by a backend still running the pre-0037 code drew its reference
-- from the production "OF-" sequence instead, and was left reading "OF-0000NN"
-- -- indistinguishable from a production OF, and burning a production number.
--
-- Give each such straggler the next "OFR-" reference. Idempotent: it only
-- touches regrind orders whose reference is not already an "OFR-" one, so a
-- database with none is left exactly as it is. The abandoned "OF-" numbers
-- stay unused, like any other gap in that sequence.

-- A tenant whose OFR counter was never seeded starts it at 0.
INSERT INTO core.sequences (tenant_id, name, prefix, next_value)
SELECT DISTINCT wo.tenant_id, 'production.regrind_orders', 'OFR-', 0
FROM production.work_orders wo
JOIN production.regrind_batches rb ON rb.work_order_id = wo.id
WHERE LEFT(wo.reference, 4) <> 'OFR-'
ON CONFLICT (tenant_id, name) DO NOTHING;

-- Advance the counter and renumber in one statement so the two cannot drift:
-- `bumped` returns the counter's value from before the bump, and each
-- straggler takes the next numbers after it in creation order.
WITH stray AS (
    SELECT wo.id, wo.tenant_id, ROW_NUMBER() OVER (PARTITION BY wo.tenant_id ORDER BY wo.created_at) AS rn
    FROM production.work_orders wo
    JOIN production.regrind_batches rb ON rb.work_order_id = wo.id
    WHERE LEFT(wo.reference, 4) <> 'OFR-'
), bumped AS (
    UPDATE core.sequences seq
    SET next_value = seq.next_value + counts.n
    FROM (SELECT tenant_id, COUNT(*) AS n FROM stray GROUP BY tenant_id) counts
    WHERE seq.tenant_id = counts.tenant_id AND seq.name = 'production.regrind_orders'
    RETURNING seq.tenant_id, seq.next_value - counts.n AS base
)
UPDATE production.work_orders wo
SET reference = 'OFR-' || LPAD((bumped.base + stray.rn)::text, 6, '0')
FROM stray
JOIN bumped ON bumped.tenant_id = stray.tenant_id
WHERE wo.id = stray.id;

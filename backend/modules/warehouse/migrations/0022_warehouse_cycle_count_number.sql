-- A count needs a reference people can quote: a refused stock move names the count that froze it.
ALTER TABLE warehouse.cycle_counts ADD COLUMN IF NOT EXISTS number TEXT;

WITH numbered AS (
    SELECT id,
           EXTRACT(YEAR FROM created_at)::INT AS year,
           ROW_NUMBER() OVER (PARTITION BY tenant_id, EXTRACT(YEAR FROM created_at) ORDER BY created_at, id) AS n
    FROM warehouse.cycle_counts
    WHERE number IS NULL
)
UPDATE warehouse.cycle_counts c
SET number = 'INV-' || numbered.year || '-' || LPAD(numbered.n::TEXT, 6, '0')
FROM numbered
WHERE numbered.id = c.id;

INSERT INTO warehouse.voucher_counters (tenant_id, voucher_type, year, last_number)
SELECT tenant_id, 'cycle_count', EXTRACT(YEAR FROM created_at)::INT, COUNT(*)
FROM warehouse.cycle_counts
GROUP BY tenant_id, EXTRACT(YEAR FROM created_at)
ON CONFLICT (tenant_id, voucher_type, year)
DO UPDATE SET last_number = GREATEST(warehouse.voucher_counters.last_number, EXCLUDED.last_number);

CREATE UNIQUE INDEX IF NOT EXISTS cycle_counts_number_uq ON warehouse.cycle_counts (tenant_id, number) WHERE number IS NOT NULL;

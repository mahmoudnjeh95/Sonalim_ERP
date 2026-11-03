-- An employee has at most one signed (non-draft) contract on any day. The domain checks it
-- first with a readable refusal; this constraint is the guard against a race.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Nothing checked overlaps before. Close each signed contract the day before the same
-- employee's next one starts...
WITH ordered AS (
    SELECT id, start_date,
           LEAD(start_date) OVER (PARTITION BY tenant_id, employee_id ORDER BY start_date, created_at, id) AS next_start
    FROM hr.contracts
    WHERE status <> 'draft'
)
UPDATE hr.contracts c
SET end_date = o.next_start - 1,
    end_reason = COALESCE(c.end_reason, 'other')
FROM ordered o
WHERE c.id = o.id
  AND o.next_start > c.start_date
  AND (c.end_date IS NULL OR c.end_date >= o.next_start);

-- ...and when two start the same day, the older one goes back to draft (it cannot be shortened
-- to nothing).
WITH ordered AS (
    SELECT id, start_date,
           LEAD(start_date) OVER (PARTITION BY tenant_id, employee_id ORDER BY start_date, created_at, id) AS next_start
    FROM hr.contracts
    WHERE status <> 'draft'
)
UPDATE hr.contracts c
SET status = 'draft'
FROM ordered o
WHERE c.id = o.id
  AND o.next_start = c.start_date;

ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_no_overlap
    EXCLUDE USING gist (tenant_id WITH =, employee_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
    WHERE (status <> 'draft');

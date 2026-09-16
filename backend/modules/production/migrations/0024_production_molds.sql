-- Moules: the physical tool mounted on the packaging line for one pack format,
-- PC or PL. Each mold names the work center it is mounted on — decision 15
-- says the OF's work center stays required, so creating an OF against a mold
-- resolves its machine from here rather than asking for it again.
CREATE TABLE IF NOT EXISTS production.molds (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('PC', 'PL')),
    work_center_id TEXT NOT NULL REFERENCES production.work_centers (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE INDEX IF NOT EXISTS molds_work_center_id_idx ON production.molds (work_center_id);

ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS mold_id TEXT REFERENCES production.molds (id);

-- Creation is now lightweight: product, PC/PL, mold and a start date. The
-- work center is resolved from the mold; the quantity is assigned later, once
-- known, via the edit form — planning no longer blocks on it.
ALTER TABLE production.work_orders ALTER COLUMN planned_quantity DROP NOT NULL;

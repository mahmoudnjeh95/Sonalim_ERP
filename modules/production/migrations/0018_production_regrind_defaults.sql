-- Phase 5 prerequisite. Automatic rebroyat creation has to know which product the
-- regrind of a given input yields, and nothing recorded that until now — so a
-- daily report validating with rebroyat above zero would either fail or silently
-- skip the OF it is supposed to open.
--
-- Same shape as qc.follow_up_policies: a tenant-wide default with an optional
-- per-input-product override. input_product_id NULL is the tenant default row.
CREATE TABLE IF NOT EXISTS production.regrind_defaults (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    input_product_id TEXT,
    output_product_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS regrind_defaults_one_per_input
    ON production.regrind_defaults (tenant_id, input_product_id)
    NULLS NOT DISTINCT;

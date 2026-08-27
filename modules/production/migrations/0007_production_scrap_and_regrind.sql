CREATE TABLE IF NOT EXISTS production.scrap_records (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL REFERENCES production.work_orders (id),
    operation_step_id TEXT,
    scrap_type TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    is_reground BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS scrap_records_work_order_idx ON production.scrap_records (tenant_id, work_order_id);

CREATE TABLE IF NOT EXISTS production.regrind_batches (
    work_order_id TEXT PRIMARY KEY REFERENCES production.work_orders (id),
    tenant_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS production.regrind_batch_inputs (
    id TEXT PRIMARY KEY,
    regrind_batch_work_order_id TEXT NOT NULL REFERENCES production.regrind_batches (work_order_id),
    scrap_record_id TEXT NOT NULL REFERENCES production.scrap_records (id)
);

CREATE INDEX IF NOT EXISTS regrind_batch_inputs_batch_idx ON production.regrind_batch_inputs (regrind_batch_work_order_id);

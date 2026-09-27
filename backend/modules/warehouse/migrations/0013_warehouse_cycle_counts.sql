-- Phase 2: a real cycle-count workflow. Today "counting" is only an ad hoc
-- single-delta adjust_stock or a privileged full overwrite -- this adds a
-- structured count -> variance -> approval flow scoped to a site (optionally
-- to one subtree of it), reconciling warehouse.stock_items the way a
-- physical inventory actually happens.

CREATE TABLE warehouse.cycle_counts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    -- NULL means every bin in the site; otherwise every bin at or under this
    -- location (a zone/aisle/rack, or a single bin counted on its own).
    scope_location_id TEXT REFERENCES warehouse.locations (id),
    count_type TEXT NOT NULL DEFAULT 'scheduled' CHECK (count_type IN ('scheduled', 'blind')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_progress', 'completed', 'cancelled')),
    scheduled_for DATE,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX cycle_counts_site_idx ON warehouse.cycle_counts (tenant_id, site_id);
CREATE INDEX cycle_counts_status_idx ON warehouse.cycle_counts (tenant_id, status);

CREATE TABLE warehouse.cycle_count_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    cycle_count_id TEXT NOT NULL REFERENCES warehouse.cycle_counts (id),
    location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    product_id TEXT NOT NULL REFERENCES core.products (id),
    -- Snapshotted from stock_items when the count is created -- what the
    -- books said at that moment, not a live figure.
    expected_quantity NUMERIC NOT NULL,
    counted_quantity NUMERIC,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'counted')),
    -- "matched" is set automatically when counted = expected; a real
    -- variance stays NULL (awaiting a decision) until approved or rejected.
    resolution TEXT CHECK (resolution IN ('matched', 'approved', 'rejected')),
    counted_by TEXT,
    counted_at TIMESTAMPTZ,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    UNIQUE (tenant_id, cycle_count_id, location_id, product_id)
);

CREATE INDEX cycle_count_lines_count_idx ON warehouse.cycle_count_lines (tenant_id, cycle_count_id);

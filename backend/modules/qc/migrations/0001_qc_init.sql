-- Phase 4: the qc module. Quality control and non-conformity are their own bounded
-- context, not a corner of production.
--
-- The specification files all three report types under one production_report
-- header, but a module may not read another's tables — so qc keeps its own header,
-- mirroring production's shape rather than borrowing its table. `of_id` appears
-- throughout as a plain TEXT column with NO foreign key: it points across a module
-- boundary, and qc resolves it through production's service layer when it needs
-- more than the id.
CREATE SCHEMA IF NOT EXISTS qc;

-- Same status vocabulary and validation trail as a production report, so the
-- Validation Center can present both kinds of pending work side by side.
CREATE TABLE IF NOT EXISTS qc.quality_reports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    of_id TEXT NOT NULL,
    report_date DATE NOT NULL,
    team TEXT,
    shift TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'validated', 'rejected')),
    revision INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    submitted_at TIMESTAMPTZ,
    validated_by TEXT,
    validated_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS quality_reports_of_idx ON qc.quality_reports (tenant_id, of_id);
CREATE INDEX IF NOT EXISTS quality_reports_status_idx ON qc.quality_reports (tenant_id, status);

-- One quality report per OF, date and shift — the same "a shift reports once" rule
-- production enforces, including the NULLS NOT DISTINCT treatment of an optional shift.
CREATE UNIQUE INDEX IF NOT EXISTS quality_reports_one_per_shift
    ON qc.quality_reports (tenant_id, of_id, report_date, shift)
    NULLS NOT DISTINCT;

-- The measured indices along the line, plus the conformity verdict the 40-day
-- follow-up hangs off.
CREATE TABLE IF NOT EXISTS qc.quality_report_details (
    report_id TEXT PRIMARY KEY REFERENCES qc.quality_reports (id),
    tenant_id TEXT NOT NULL,
    pre_dryer_index NUMERIC,
    humidity_percentage NUMERIC,
    cooling_index NUMERIC,
    pf_index NUMERIC,
    sumo_index NUMERIC,
    conforming_cartons NUMERIC NOT NULL DEFAULT 0,
    non_conforming_cartons NUMERIC NOT NULL DEFAULT 0,
    defect_details TEXT,
    comments TEXT,
    corrective_action TEXT
);

-- How long the follow-up window runs. A tenant-wide default with an optional
-- per-product override: shelf-life behaviour genuinely differs between pasta
-- shapes, so 40 days is a default rather than a constant. product_id NULL is the
-- tenant default row.
CREATE TABLE IF NOT EXISTS qc.follow_up_policies (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT,
    window_days INTEGER NOT NULL CHECK (window_days > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One default row per tenant, one override row per product.
CREATE UNIQUE INDEX IF NOT EXISTS follow_up_policies_one_per_product
    ON qc.follow_up_policies (tenant_id, product_id)
    NULLS NOT DISTINCT;

-- One row per observation inside the window. Survives OF closure — quality
-- follow-up outlives production, which is exactly why it cannot live in a table
-- keyed to an open work order.
CREATE TABLE IF NOT EXISTS qc.quality_follow_ups (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    quality_report_id TEXT NOT NULL REFERENCES qc.quality_reports (id),
    of_id TEXT NOT NULL,
    window_ends_on DATE NOT NULL,
    observed_on DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'completed')),
    result TEXT,
    observation TEXT,
    actor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS quality_follow_ups_report_idx ON qc.quality_follow_ups (tenant_id, quality_report_id);
CREATE INDEX IF NOT EXISTS quality_follow_ups_open_idx ON qc.quality_follow_ups (tenant_id, status) WHERE status <> 'completed';

-- The ticket. Raised against an OF whether or not it is still open: a closed OF
-- must still accept a non-conformity, since follow-up outlives production.
CREATE TABLE IF NOT EXISTS qc.non_conformities (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    reference TEXT NOT NULL,
    of_id TEXT NOT NULL,
    quality_report_id TEXT REFERENCES qc.quality_reports (id),
    product_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    -- Where the product was pulled from, and the blocked location it is held in
    -- until someone decides its fate. Both are warehouse location ids, carried as
    -- plain columns for the same cross-module reason as of_id.
    source_location_id TEXT NOT NULL,
    quarantine_location_id TEXT,
    defect_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'minor' CHECK (severity IN ('minor', 'major', 'critical')),
    status TEXT NOT NULL DEFAULT 'raised' CHECK (status IN ('raised', 'quarantined', 'dispositioned', 'closed')),
    description TEXT,
    corrective_action TEXT,
    raised_by TEXT,
    raised_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_by TEXT,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS non_conformities_of_idx ON qc.non_conformities (tenant_id, of_id);
CREATE INDEX IF NOT EXISTS non_conformities_status_idx ON qc.non_conformities (tenant_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS non_conformities_tenant_reference_idx ON qc.non_conformities (tenant_id, reference);

-- One line per component of what was pulled. This is what decides the stock and
-- scrap effects in Phase 5: the pasta goes to rebroyat, the film / carton / ruban
-- are recorded as déchet WITHOUT a second deduction — their stock already left
-- when the conditionnement report was validated.
CREATE TABLE IF NOT EXISTS qc.nc_dispositions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    non_conformity_id TEXT NOT NULL REFERENCES qc.non_conformities (id),
    component TEXT NOT NULL CHECK (component IN ('product', 'film', 'carton', 'tape')),
    disposition TEXT NOT NULL CHECK (disposition IN ('regrind', 'dechet', 'rework', 'return_to_stock')),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    uom TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS nc_dispositions_nc_idx ON qc.nc_dispositions (tenant_id, non_conformity_id);

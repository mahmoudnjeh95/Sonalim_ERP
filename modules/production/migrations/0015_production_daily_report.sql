-- The daily report's own figures. One row per production_reports row of type
-- 'daily'; the header carries the OF, team, date, shift and validation trail.
CREATE TABLE IF NOT EXISTS production.daily_reports (
    report_id TEXT PRIMARY KEY REFERENCES production.production_reports (id),
    tenant_id TEXT NOT NULL,

    -- What went in and what came off the line.
    semolina_quantity NUMERIC NOT NULL DEFAULT 0,
    dough_quantity NUMERIC NOT NULL DEFAULT 0,
    -- Recorded for yield and OF consolidation only. This figure posts NO stock:
    -- the finished product enters stock once, when the conditionnement report is
    -- validated, so counting it here too would double the same tonnage.
    finished_product_quantity NUMERIC NOT NULL DEFAULT 0,

    -- Waste by category. regrind_quantity is the rebroyat: on validation it
    -- writes a scrap record so the existing regrind workflow has an input, and
    -- from Phase 5 it also opens the regrind OF automatically.
    raw_material_waste_quantity NUMERIC NOT NULL DEFAULT 0,
    press_waste_quantity NUMERIC NOT NULL DEFAULT 0,
    regrind_quantity NUMERIC NOT NULL DEFAULT 0,

    -- Metered utilities, replacing the per-date production.daily_consumption rows
    -- dropped below: consumption is a fact about a shift's production, so it
    -- belongs on that shift's report rather than in a parallel ledger.
    water_quantity NUMERIC NOT NULL DEFAULT 0,
    fuel_quantity NUMERIC NOT NULL DEFAULT 0,
    electricity_quantity NUMERIC NOT NULL DEFAULT 0,

    start_time TIME,
    end_time TIME,
    production_minutes INTEGER NOT NULL DEFAULT 0,
    downtime_minutes INTEGER NOT NULL DEFAULT 0,
    downtime_reason TEXT
);

-- Superseded by the consumption columns above and by the conditionnement report's
-- own columns in Phase 3. production.resource_types is deliberately NOT dropped:
-- whether the Phase 8 dashboard still needs it is an open question, and keeping an
-- empty lookup table is reversible in a way that dropping it is not.
DROP TABLE IF EXISTS production.work_order_consumption;
DROP TABLE IF EXISTS production.daily_consumption;

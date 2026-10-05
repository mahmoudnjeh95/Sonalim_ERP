-- Phase 6C: reorder-point replenishment. core.products.stock_alert_threshold
-- only colours a row red; nothing turns it into an order. A reorder rule is
-- min/max: when what is available (on hand - reserved, quarantine excluded)
-- falls to the reorder point, propose ordering back up to order_up_to.
--
-- A proposal is not a purchase order -- procurement owns those. Approving one
-- publishes warehouse.replenishment.approved and procurement drafts the PO.
-- While a rule has an open or approved proposal, no second one is raised:
-- that is the "already on order" guard, kept entirely inside warehouse.

CREATE TABLE warehouse.reorder_rules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    -- NULL: availability summed across every site.
    site_id TEXT REFERENCES warehouse.sites (id),
    reorder_point NUMERIC NOT NULL CHECK (reorder_point >= 0),
    order_up_to NUMERIC NOT NULL,
    min_order_quantity NUMERIC NOT NULL DEFAULT 0 CHECK (min_order_quantity >= 0),
    preferred_supplier_id TEXT REFERENCES core.partners (id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (order_up_to > reorder_point)
);

CREATE UNIQUE INDEX reorder_rules_scope_uniq ON warehouse.reorder_rules (tenant_id, product_id, COALESCE(site_id, ''));

CREATE TABLE warehouse.replenishment_proposals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_id TEXT NOT NULL REFERENCES warehouse.reorder_rules (id),
    product_id TEXT NOT NULL REFERENCES core.products (id),
    site_id TEXT,
    available_at_proposal NUMERIC NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    supplier_id TEXT REFERENCES core.partners (id),
    -- open -> approved (sent to procurement) -> fulfilled (availability back
    -- above the reorder point); open -> dismissed.
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'approved', 'dismissed', 'fulfilled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX replenishment_proposals_one_pending_per_rule
    ON warehouse.replenishment_proposals (rule_id) WHERE status IN ('open', 'approved');
CREATE INDEX replenishment_proposals_status_idx ON warehouse.replenishment_proposals (tenant_id, status);

-- Phase 6A: reservation TTL / auto-release. Until now a reservation was only
-- a number (stock_items.quantity_reserved) -- nothing recorded *which*
-- reservation it was, so nothing could ever expire one. This ledger keeps one
-- row per reserve_stock call; quantity_reserved on stock_items stays the
-- authoritative counter every availability check already reads, and the
-- ledger explains it.
--
-- expires_at is opt-in: a confirmed sales order's reservation has none (the
-- pick list holds it until shipped or cancelled); a speculative hold made
-- through the generic reserve endpoint can be given one, and the worker
-- releases it when it lapses.

CREATE TABLE warehouse.stock_reservations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    reference TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    -- What is still held; drops as the reference releases, 0 once closed.
    quantity_open NUMERIC NOT NULL CHECK (quantity_open >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released', 'expired')),
    expires_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE INDEX stock_reservations_lookup_idx
    ON warehouse.stock_reservations (tenant_id, product_id, location_id, reference) WHERE status = 'active';
CREATE INDEX stock_reservations_expiry_idx
    ON warehouse.stock_reservations (expires_at) WHERE status = 'active' AND expires_at IS NOT NULL;

-- Backfill what is reserved today from the move log: per (location, product,
-- reference), reservations minus releases. No expiry -- nobody asked for one
-- when these were made. Best effort: an admin_set_stock that overwrote the
-- counter directly isn't in the move log, so the ledger can under- or
-- over-explain such a row; the counter itself is untouched either way.
INSERT INTO warehouse.stock_reservations
    (id, tenant_id, product_id, location_id, reference, quantity, quantity_open, created_at)
SELECT
    'backfill-' || md5(net.tenant_id || '|' || net.location_id || '|' || net.product_id || '|' || net.reference),
    net.tenant_id, net.product_id, net.location_id, net.reference,
    net.open_quantity, net.open_quantity, net.first_at
FROM (
    SELECT tenant_id, location_id, product_id, reference,
        SUM(CASE WHEN move_type = 'reservation' THEN quantity ELSE -quantity END) AS open_quantity,
        MIN(created_at) AS first_at
    FROM warehouse.stock_moves
    WHERE move_type IN ('reservation', 'reservation_released') AND location_id IS NOT NULL
    GROUP BY tenant_id, location_id, product_id, reference
) net
WHERE net.open_quantity > 0
    AND EXISTS (SELECT 1 FROM core.products p WHERE p.id = net.product_id)
    AND EXISTS (SELECT 1 FROM warehouse.locations l WHERE l.id = net.location_id);

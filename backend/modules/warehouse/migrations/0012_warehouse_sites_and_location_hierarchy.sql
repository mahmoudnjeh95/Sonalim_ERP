-- Multi-site foundation. warehouse.locations.id is an opaque string five
-- other modules already hold onto (sales.orders.location_id, qc's
-- quarantine columns, production's per-line location columns, crm's
-- won_location_id) -- none of them care about hierarchy, so the hierarchy is
-- layered on as additive columns rather than a new table that would force
-- every one of those call sites to change. Every existing location becomes a
-- "bin" directly under its tenant's synthetic default site; location_id
-- values themselves never change.

CREATE TABLE IF NOT EXISTS warehouse.sites (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    address TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

-- Backfill only matters for a DB with pre-existing locations; a fresh dev DB
-- has none yet, so seed_dev.py creates the demo tenant's site explicitly,
-- same as 0002_warehouse_locations.sql did for the default location.
INSERT INTO warehouse.sites (id, tenant_id, code, name)
SELECT DISTINCT 'default-site-' || tenant_id, tenant_id, 'main', 'Site principal'
FROM warehouse.locations
ON CONFLICT (tenant_id, code) DO NOTHING;

ALTER TABLE warehouse.locations ADD COLUMN IF NOT EXISTS site_id TEXT;
UPDATE warehouse.locations SET site_id = 'default-site-' || tenant_id WHERE site_id IS NULL;

-- A large number of call sites across other modules' tests (and any future
-- code) insert a location without ever mentioning a site -- they were
-- written when locations were flat and have no reason to know sites exist
-- now. Rather than touch every one of them, an insert that omits site_id
-- gets the same synthetic default the backfill above gave every
-- pre-existing row, computed the same way. No FK ties it to a real
-- warehouse.sites row: this is a safety net for code that doesn't care
-- about sites, not the path warehouse's own SiteService-aware code takes.
CREATE OR REPLACE FUNCTION warehouse.locations_default_site_id() RETURNS trigger AS $$
BEGIN
    IF NEW.site_id IS NULL THEN
        NEW.site_id := 'default-site-' || NEW.tenant_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS locations_default_site_id_trigger ON warehouse.locations;
CREATE TRIGGER locations_default_site_id_trigger
    BEFORE INSERT ON warehouse.locations
    FOR EACH ROW
    EXECUTE FUNCTION warehouse.locations_default_site_id();

ALTER TABLE warehouse.locations ALTER COLUMN site_id SET NOT NULL;

-- "bin" is the leaf level stock actually lives at, so every pre-existing
-- location -- which by definition already holds stock_items rows -- is
-- correctly classified as a bin by this default, not a zone/aisle/rack.
ALTER TABLE warehouse.locations
    ADD COLUMN IF NOT EXISTS location_type TEXT NOT NULL DEFAULT 'bin'
        CHECK (location_type IN ('zone', 'aisle', 'rack', 'bin'));

-- Self-referential place in the tree. Cycle prevention lives in domain code
-- (domain/site.py's validate_reparent), not a DB constraint -- Postgres has
-- no built-in "no cycles" check for a self-referencing foreign key.
ALTER TABLE warehouse.locations ADD COLUMN IF NOT EXISTS parent_location_id TEXT;
ALTER TABLE warehouse.locations ADD COLUMN IF NOT EXISTS sequence INT;

CREATE INDEX IF NOT EXISTS locations_site_idx ON warehouse.locations (tenant_id, site_id);
CREATE INDEX IF NOT EXISTS locations_parent_idx ON warehouse.locations (tenant_id, parent_location_id);

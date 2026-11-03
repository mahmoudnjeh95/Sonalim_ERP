-- Phase 5A: barcodes. Until now a scan could only match a product's SKU or a
-- location's code, typed exactly. Real pasta packaging carries GS1 codes --
-- an EAN-13 on the unit packet and an ITF-14 / GS1-128 on the carton -- so a
-- product needs several barcodes, each saying how many units one scan means.
--
-- Warehouse-owned rather than a column on core.products: which codes are
-- printed on which packaging level is a warehouse/logistics concern, and one
-- column couldn't hold both the packet and the carton code anyway.
--
-- GTINs are stored normalised to 14 digits (left-padded), so a packet's
-- EAN-13 and the same GTIN read back out of a GS1-128 carton label (always
-- 14 digits) resolve to the same row.

CREATE TABLE warehouse.product_barcodes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    barcode TEXT NOT NULL,
    barcode_type TEXT NOT NULL CHECK (barcode_type IN ('gtin', 'internal')),
    -- How many of the product's own unit one scan of this code stands for:
    -- 1 for the packet, e.g. 20 for a carton of 20 packets.
    units_per_scan NUMERIC NOT NULL DEFAULT 1 CHECK (units_per_scan > 0),
    label TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, barcode)
);

CREATE INDEX product_barcodes_product_idx ON warehouse.product_barcodes (tenant_id, product_id);

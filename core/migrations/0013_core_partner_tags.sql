-- Links partners (vendors) into the same tag space products already use
-- (core.product_tags), so a vendor's specialties and a product's category
-- are the same taxonomy, not two lists that happen to share label text.
CREATE TABLE IF NOT EXISTS core.partner_tag_links (
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    tag_id TEXT NOT NULL REFERENCES core.product_tags (id),
    is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
    lead_time_days INTEGER,
    min_order_qty NUMERIC,
    PRIMARY KEY (partner_id, tag_id)
);

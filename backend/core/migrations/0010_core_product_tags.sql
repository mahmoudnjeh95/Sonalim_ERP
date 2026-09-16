CREATE TABLE IF NOT EXISTS core.product_tags (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS core.product_tag_links (
    product_id TEXT NOT NULL REFERENCES core.products (id),
    tag_id TEXT NOT NULL REFERENCES core.product_tags (id),
    PRIMARY KEY (product_id, tag_id)
);

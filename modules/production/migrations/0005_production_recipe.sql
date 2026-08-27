CREATE TABLE IF NOT EXISTS production.recipes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    target_product_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    target_moisture_percentage NUMERIC,
    origin TEXT NOT NULL DEFAULT 'manual',
    ai_confidence NUMERIC,
    previous_recipe_id TEXT REFERENCES production.recipes (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS production.recipe_lines (
    id TEXT PRIMARY KEY,
    recipe_id TEXT NOT NULL REFERENCES production.recipes (id),
    tenant_id TEXT NOT NULL,
    component_product_id TEXT NOT NULL,
    default_percentage NUMERIC NOT NULL,
    min_percentage NUMERIC NOT NULL,
    max_percentage NUMERIC NOT NULL,
    is_hard_limit BOOLEAN NOT NULL DEFAULT FALSE
);

-- Defense in depth for "only one active recipe per target product", same reasoning as
-- packaging_boms_one_active_per_target: RecipeService already serializes activation via
-- a family-scoped row lock, this guarantees the invariant at the database level too.
CREATE UNIQUE INDEX IF NOT EXISTS recipes_one_active_per_target
    ON production.recipes (tenant_id, target_product_id)
    WHERE status = 'active';

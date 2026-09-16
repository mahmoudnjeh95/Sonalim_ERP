-- Opaque reference to the draft sales.orders row created when this opportunity
-- is won. No FK: per the architecture's hard rule, modules never reference
-- another module's tables directly.
ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS sales_order_id TEXT;

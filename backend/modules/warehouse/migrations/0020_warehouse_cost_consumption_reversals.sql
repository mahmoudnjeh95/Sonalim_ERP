-- A reversed production movement puts its quantity back into the very cost
-- layers it drew from, recorded as a negative consumption under the same
-- reference, so a reference's cost nets to what is still really consumed.
ALTER TABLE warehouse.cost_layer_consumptions DROP CONSTRAINT IF EXISTS cost_layer_consumptions_quantity_check;
ALTER TABLE warehouse.cost_layer_consumptions ADD CONSTRAINT cost_layer_consumptions_quantity_check CHECK (quantity <> 0);

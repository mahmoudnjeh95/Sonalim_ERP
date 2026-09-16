-- Phase 9, decision 20. The second half of the packaging parameter pair.
--
-- `net_weight_grams` (migration 0007) already says what one packet or sac weighs.
-- This says how many of them go in a carton, so a tonnage can be turned into an
-- expected packet and carton count and checked against what the line actually
-- tallied.
--
-- Nullable on purpose, and not merely because old rows have no value: some
-- finished goods have no carton at all. `doman-pc-4540g-sac` is a 4.54 kg sac
-- that is itself the selling unit, and forcing a number onto it would invent a
-- carton nobody packs. A NULL here means "no carton line", not "not filled in
-- yet", and the estimate omits cartons rather than guessing.
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS packets_per_carton NUMERIC;

ALTER TABLE core.products DROP CONSTRAINT IF EXISTS products_packets_per_carton_positive;
ALTER TABLE core.products ADD CONSTRAINT products_packets_per_carton_positive
    CHECK (packets_per_carton IS NULL OR packets_per_carton > 0);

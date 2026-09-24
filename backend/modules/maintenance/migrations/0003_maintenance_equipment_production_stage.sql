-- Which stage of a production line a machine works at. It is declared here, with
-- the machine, so the production dashboard draws each line from the registry
-- instead of keeping a second list that someone has to fill in.
--
-- Empty for a machine that works at none of the stages, and for every machine
-- registered before this column existed: nothing is pre-filled with a guess.
ALTER TABLE maintenance.equipment
    ADD COLUMN IF NOT EXISTS production_stage TEXT
    CONSTRAINT maintenance_equipment_production_stage_check
    CHECK (production_stage IN ('versement', 'extrusion', 'conditionnement'));

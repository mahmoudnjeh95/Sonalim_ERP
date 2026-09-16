-- One-time cutover cleanup, not a pattern to repeat: 0001 already copied every
-- row into maintenance.equipment, so production.machines is now dead weight.
-- This migration reaches into production's schema deliberately -- it must run
-- from here rather than from modules/production/migrations, because the
-- module migration runner applies a module's whole migration set before
-- moving to the next module (see core/migrations/runner.py MODULE_ORDER).
-- production runs before maintenance, so filing the drop under production
-- would execute it before 0001's copy ever ran. No runtime module code
-- reaches across schemas like this -- only this one-shot rollout step does.
DROP TABLE IF EXISTS production.machines;

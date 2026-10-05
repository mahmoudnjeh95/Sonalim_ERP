-- How far a preventive program has generated jobs. The sweep only creates
-- occurrences after this date, so the program -- not its jobs -- remembers what
-- it already raised. Without it, wiping jobs (the go-live reset keeps programs
-- and empties jobs) made the next sweep re-create every past occurrence since
-- the program was created, as a pile of overdue jobs.
--
-- NULL means nothing generated yet: the sweep then starts from the program's
-- start date / creation date, as before.
ALTER TABLE maintenance.programs
    ADD COLUMN IF NOT EXISTS last_generated_date DATE;

-- Backfill from the jobs each program has already generated.
UPDATE maintenance.programs p
SET last_generated_date = (
    SELECT MAX(j.occurrence_date) FROM maintenance.jobs j WHERE j.program_id = p.id
)
WHERE p.last_generated_date IS NULL;

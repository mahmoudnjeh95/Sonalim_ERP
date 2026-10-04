-- A parts request shows its lines in the order the chef typed them. Ids are
-- random ULIDs (not ordered within one millisecond), so the position is kept
-- explicitly: 1..n per request, 0 for any line written before this column.
ALTER TABLE maintenance.part_request_lines
    ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;

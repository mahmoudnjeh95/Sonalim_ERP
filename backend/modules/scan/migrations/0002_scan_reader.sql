-- Which engine reads a scan's photos: the local OCR container (the photos never leave the
-- server) or Claude (the photos are sent to the Anthropic API). Chosen per scan in the UI
-- and switchable while the scan is open. read_by records which engine produced each
-- page's stored reading, since a switch can leave pages read by either.
ALTER TABLE scan.scan_sessions
    ADD COLUMN IF NOT EXISTS reader TEXT NOT NULL DEFAULT 'ocr' CHECK (reader IN ('ocr', 'claude'));

ALTER TABLE scan.scan_pages
    ADD COLUMN IF NOT EXISTS read_by TEXT CHECK (read_by IN ('ocr', 'claude'));

-- Every reading stored so far came from the OCR container.
UPDATE scan.scan_pages SET read_by = 'ocr' WHERE ocr_result IS NOT NULL AND read_by IS NULL;

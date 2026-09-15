ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS probability SMALLINT NOT NULL DEFAULT 10;
ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS owner_id TEXT;
ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS lost_reason TEXT;

UPDATE crm.opportunities SET probability = 100 WHERE stage = 'won' AND probability = 10;
UPDATE crm.opportunities SET probability = 0 WHERE stage = 'lost' AND probability = 10;

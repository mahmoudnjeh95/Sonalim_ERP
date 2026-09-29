-- How a daily-paid worker's worked rest day is paid: only its rest/holiday overtime (like a
-- monthly worker), or its day rate as well. Effective-dated with the rule set it belongs to.
ALTER TABLE payroll.rule_sets
    ADD COLUMN IF NOT EXISTS daily_rest_day_pay TEXT NOT NULL DEFAULT 'overtime_only'
    CHECK (daily_rest_day_pay IN ('overtime_only', 'day_rate_and_overtime'));

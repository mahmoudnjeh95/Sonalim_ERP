-- SYSCOHADA ledger, entries: journal entries and their lines, the automatic postings that were
-- refused (and why), and the triggers that keep the books honest: a posted entry never changes
-- except posted -> reversed, its lines never change, and at commit every posted entry balances.

CREATE TABLE IF NOT EXISTS finance.journal_entries (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    journal_code TEXT NOT NULL,
    number TEXT,
    entry_date DATE NOT NULL,
    period DATE NOT NULL,
    label TEXT NOT NULL CHECK (btrim(label) <> ''),
    reference TEXT,
    source_module TEXT,
    source_id TEXT,
    source_kind TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'reversed')),
    reversal_of TEXT REFERENCES finance.journal_entries (id),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_by TEXT,
    posted_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, journal_code) REFERENCES finance.journals (tenant_id, code),
    FOREIGN KEY (tenant_id, period) REFERENCES finance.periods (tenant_id, period),
    CHECK (period = date_trunc('month', entry_date)::date),
    CHECK ((source_module IS NULL) = (source_id IS NULL) AND (source_id IS NULL) = (source_kind IS NULL)),
    CHECK (status = 'draft' OR (number IS NOT NULL AND posted_at IS NOT NULL))
);

-- One entry per (source, kind): the second delivery of an event finds the first entry.
CREATE UNIQUE INDEX IF NOT EXISTS journal_entries_source_uq
    ON finance.journal_entries (tenant_id, source_module, source_id, source_kind)
    WHERE source_module IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS journal_entries_number_uq
    ON finance.journal_entries (tenant_id, number) WHERE number IS NOT NULL;
CREATE INDEX IF NOT EXISTS journal_entries_date_idx ON finance.journal_entries (tenant_id, entry_date);
CREATE INDEX IF NOT EXISTS journal_entries_source_idx ON finance.journal_entries (tenant_id, source_module, source_id);

CREATE TABLE IF NOT EXISTS finance.journal_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entry_id TEXT NOT NULL REFERENCES finance.journal_entries (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    account_code TEXT NOT NULL,
    debit NUMERIC(18,0) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit NUMERIC(18,0) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    label TEXT,
    partner_id TEXT REFERENCES core.partners (id),
    employee_ref TEXT,
    UNIQUE (entry_id, line_no),
    CHECK ((debit = 0) <> (credit = 0)),
    FOREIGN KEY (tenant_id, account_code) REFERENCES finance.accounts (tenant_id, code)
);
CREATE INDEX IF NOT EXISTS journal_lines_account_idx ON finance.journal_lines (tenant_id, account_code);

-- An automatic posting that was refused: the event it came from and why. The run page reads
-- it; POST /finance/posting-failures/{id}/retry replays the envelope once the cause is fixed.
CREATE TABLE IF NOT EXISTS finance.posting_failures (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_module TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    envelope JSONB NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_message_fr TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'cancelled')),
    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (tenant_id, source_module, source_id, source_kind)
);

CREATE OR REPLACE FUNCTION finance.guard_posted_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'ENTRY_POSTED: journal entry % is % and cannot be deleted', OLD.id, OLD.status;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'posted' AND NEW.status = 'reversed'
       AND (NEW.id, NEW.tenant_id, NEW.journal_code, NEW.number, NEW.entry_date, NEW.period, NEW.label,
            NEW.reference, NEW.source_module, NEW.source_id, NEW.source_kind, NEW.reversal_of,
            NEW.created_by, NEW.posted_by, NEW.posted_at)
           IS NOT DISTINCT FROM
           (OLD.id, OLD.tenant_id, OLD.journal_code, OLD.number, OLD.entry_date, OLD.period, OLD.label,
            OLD.reference, OLD.source_module, OLD.source_id, OLD.source_kind, OLD.reversal_of,
            OLD.created_by, OLD.posted_by, OLD.posted_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'ENTRY_POSTED: journal entry % is % and cannot be changed', OLD.id, OLD.status;
END;
$$;

DROP TRIGGER IF EXISTS journal_entries_guard ON finance.journal_entries;
CREATE TRIGGER journal_entries_guard
    BEFORE UPDATE OR DELETE ON finance.journal_entries
    FOR EACH ROW EXECUTE FUNCTION finance.guard_posted_entry();

CREATE OR REPLACE FUNCTION finance.guard_posted_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target TEXT;
    parent_status TEXT;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.entry_id IS DISTINCT FROM OLD.entry_id THEN
        RAISE EXCEPTION 'ENTRY_POSTED: a line cannot move to another journal entry';
    END IF;
    IF TG_OP = 'DELETE' THEN
        target := OLD.entry_id;
    ELSE
        target := NEW.entry_id;
    END IF;
    -- NULL when the entry itself is being deleted, which only a draft can be.
    SELECT status INTO parent_status FROM finance.journal_entries WHERE id = target;
    IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
        RAISE EXCEPTION 'ENTRY_POSTED: the lines of journal entry % are frozen once it is %', target, parent_status;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS journal_lines_guard ON finance.journal_lines;
CREATE TRIGGER journal_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON finance.journal_lines
    FOR EACH ROW EXECUTE FUNCTION finance.guard_posted_lines();

-- Re-checked at commit, whatever wrote the rows: a posted entry has two or more lines and equal sides.
CREATE OR REPLACE FUNCTION finance.check_entry_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target TEXT;
    entry_status TEXT;
    total_debit NUMERIC;
    total_credit NUMERIC;
    line_count INTEGER;
BEGIN
    IF TG_TABLE_NAME = 'journal_entries' THEN
        target := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        target := OLD.entry_id;
    ELSE
        target := NEW.entry_id;
    END IF;
    SELECT status INTO entry_status FROM finance.journal_entries WHERE id = target;
    IF entry_status IS NULL OR entry_status = 'draft' THEN
        RETURN NULL;
    END IF;
    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0), COUNT(*)
      INTO total_debit, total_credit, line_count
      FROM finance.journal_lines WHERE entry_id = target;
    IF line_count < 2 OR total_debit = 0 OR total_debit <> total_credit THEN
        RAISE EXCEPTION 'ENTRY_UNBALANCED: journal entry % has debit % and credit % over % line(s)',
            target, total_debit, total_credit, line_count;
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS journal_entries_balanced ON finance.journal_entries;
CREATE CONSTRAINT TRIGGER journal_entries_balanced
    AFTER INSERT OR UPDATE ON finance.journal_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION finance.check_entry_balance();

DROP TRIGGER IF EXISTS journal_lines_balanced ON finance.journal_lines;
CREATE CONSTRAINT TRIGGER journal_lines_balanced
    AFTER INSERT OR UPDATE OR DELETE ON finance.journal_lines
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION finance.check_entry_balance();

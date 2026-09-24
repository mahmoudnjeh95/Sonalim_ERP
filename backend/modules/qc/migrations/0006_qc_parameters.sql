-- The Contrôle des paramètres paper sheet: nine instrument groups, each a
-- small table of rows the QC team fills after the shift. Every group is a
-- rows-list (a free "heure" or machine number as entry_label, plus that
-- group's own fixed fields) rather than a fixed 2-3-slot snapshot, because
-- the paper sheet's row counts and times vary shift to shift.
--
-- fields is JSONB rather than one table per group: nine groups of 4-10
-- columns each is a lot of schema for data only the QC screen reads, and the
-- domain layer (modules/qc/domain/parameters.py) validates each group's
-- fixed field list and ranges just as strictly as fixed columns would.
CREATE TABLE qc.quality_parameters (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES qc.quality_reports (id),
    group_key TEXT NOT NULL CHECK (group_key IN (
        'presse', 'pompe_vide', 'sechage', 'chaudiere', 'compresseurs',
        'traitement_eau', 'chiller', 'additif', 'proprete_locaux'
    )),
    -- Free time ("07h38") for most groups; a machine/press number for
    -- presse and compresseurs; PL/PC for additif.
    entry_label TEXT,
    fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX quality_parameters_report_idx
    ON qc.quality_parameters (tenant_id, report_id);

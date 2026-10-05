"""The SELECT every entry read shares, so the posting, query and manual-entry services return the
same dict for an entry. Callers append their own WHERE / ORDER BY."""
from __future__ import annotations

ENTRY_KEYS = (
    "id", "number", "journal_code", "entry_date", "period", "label", "reference", "status",
    "source_module", "source_id", "source_kind", "reversal_of", "created_by", "created_at",
    "posted_by", "posted_at", "total_debit", "total_credit",
)

ENTRY_SELECT = """
    SELECT e.id, e.number, e.journal_code, e.entry_date, e.period, e.label, e.reference, e.status,
           e.source_module, e.source_id, e.source_kind, e.reversal_of, e.created_by, e.created_at,
           e.posted_by, e.posted_at,
           COALESCE(t.total_debit, 0), COALESCE(t.total_credit, 0)
    FROM finance.journal_entries e
    LEFT JOIN LATERAL (
        SELECT SUM(l.debit) AS total_debit, SUM(l.credit) AS total_credit
        FROM finance.journal_lines l
        WHERE l.entry_id = e.id
    ) t ON TRUE
"""

STATUS_FR = {"draft": "brouillon", "posted": "comptabilisée", "reversed": "extournée"}


def entry_dict(row) -> dict:
    return dict(zip(ENTRY_KEYS, row))

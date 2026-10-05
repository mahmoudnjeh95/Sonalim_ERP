"""The ledger's read side: entries of one source (what the payroll run page shows), entries by
filters (the Entries screen, which is also the journal listing), one entry with its lines."""
from __future__ import annotations

import datetime

import psycopg

from modules.finance.api.ledger_sql import ENTRY_SELECT, entry_dict

LINE_KEYS = (
    "line_no", "account_code", "account_name", "debit", "credit", "label",
    "partner_id", "partner_name", "employee_ref",
)


class LedgerQueryService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def entries_for_source(self, *, tenant_id: str, source_module: str, source_id: str) -> list[dict]:
        """Every entry written for one source (a payroll run, an invoice), reversals included."""
        rows = self._connection.execute(
            f"""{ENTRY_SELECT}
            WHERE e.tenant_id = %s AND e.source_module = %s AND e.source_id = %s
            ORDER BY e.created_at, e.id""",
            (tenant_id, source_module, source_id),
        ).fetchall()
        return [entry_dict(row) for row in rows]

    def list_entries(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        journal_code: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        clauses = ["e.tenant_id = %s", "e.entry_date BETWEEN %s AND %s"]
        params: list[object] = [tenant_id, date_from, date_to]
        if journal_code:
            clauses.append("e.journal_code = %s")
            params.append(journal_code)
        if status:
            clauses.append("e.status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"""{ENTRY_SELECT}
            WHERE {' AND '.join(clauses)}
            ORDER BY e.entry_date DESC, e.number DESC NULLS FIRST, e.created_at DESC""",
            params,
        ).fetchall()
        return [entry_dict(row) for row in rows]

    def get_entry(self, *, tenant_id: str, entry_id: str) -> dict | None:
        row = self._connection.execute(
            f"{ENTRY_SELECT} WHERE e.tenant_id = %s AND e.id = %s", (tenant_id, entry_id)
        ).fetchone()
        if row is None:
            return None
        entry = entry_dict(row)
        lines = self._connection.execute(
            """
            SELECT l.line_no, l.account_code, a.name, l.debit, l.credit, l.label, l.partner_id, p.name, l.employee_ref
            FROM finance.journal_lines l
            JOIN finance.accounts a ON a.tenant_id = l.tenant_id AND a.code = l.account_code
            LEFT JOIN core.partners p ON p.id = l.partner_id
            WHERE l.entry_id = %s
            ORDER BY l.line_no
            """,
            (entry_id,),
        ).fetchall()
        entry["lines"] = [dict(zip(LINE_KEYS, line)) for line in lines]
        return entry

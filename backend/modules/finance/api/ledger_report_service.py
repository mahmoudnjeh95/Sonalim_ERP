"""Reports over booked entries: trial balance, general ledger of one account, and the balances of
a group of accounts (42x staff, 43x social bodies, 44x the State: what the company owes them).

Booked = posted or reversed. A reversal is itself a posted entry, so a reversed pair nets to zero
while both stay visible; drafts never count."""
from __future__ import annotations

import datetime

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.account_service import ACCOUNT_KEYS
from modules.finance.domain.ledger import ZERO, split_balance

BOOKED = ["posted", "reversed"]
TRIAL_BALANCE_AMOUNTS = (
    "opening_debit", "opening_credit", "period_debit", "period_credit", "closing_debit", "closing_credit",
)


class LedgerReportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def trial_balance(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict:
        rows = self._connection.execute(
            """
            SELECT a.code, a.name, a.class_no,
                   COALESCE(SUM(l.debit) FILTER (WHERE e.entry_date < %(date_from)s), 0),
                   COALESCE(SUM(l.credit) FILTER (WHERE e.entry_date < %(date_from)s), 0),
                   COALESCE(SUM(l.debit) FILTER (WHERE e.entry_date >= %(date_from)s), 0),
                   COALESCE(SUM(l.credit) FILTER (WHERE e.entry_date >= %(date_from)s), 0)
            FROM finance.journal_lines l
            JOIN finance.journal_entries e ON e.id = l.entry_id
            JOIN finance.accounts a ON a.tenant_id = l.tenant_id AND a.code = l.account_code
            WHERE l.tenant_id = %(tenant_id)s AND e.status = ANY(%(booked)s) AND e.entry_date <= %(date_to)s
            GROUP BY a.code, a.name, a.class_no
            ORDER BY a.code
            """,
            {"tenant_id": tenant_id, "date_from": date_from, "date_to": date_to, "booked": BOOKED},
        ).fetchall()
        report_rows: list[dict] = []
        totals = {key: ZERO for key in TRIAL_BALANCE_AMOUNTS}
        for code, name, class_no, before_debit, before_credit, period_debit, period_credit in rows:
            opening = before_debit - before_credit
            opening_debit, opening_credit = split_balance(opening)
            closing_debit, closing_credit = split_balance(opening + period_debit - period_credit)
            row = {
                "account_code": code,
                "account_name": name,
                "class_no": class_no,
                "opening_debit": opening_debit,
                "opening_credit": opening_credit,
                "period_debit": period_debit,
                "period_credit": period_credit,
                "closing_debit": closing_debit,
                "closing_credit": closing_credit,
            }
            for key in TRIAL_BALANCE_AMOUNTS:
                totals[key] += row[key]
            report_rows.append(row)
        return {"rows": report_rows, "totals": totals}

    def general_ledger(
        self, *, tenant_id: str, account_code: str, date_from: datetime.date, date_to: datetime.date
    ) -> Result[dict]:
        account = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts WHERE tenant_id = %s AND code = %s
            """,
            (tenant_id, account_code),
        ).fetchone()
        if account is None:
            return Err("NOT_FOUND", f"account {account_code} not found", f"compte {account_code} introuvable")
        opening = self._connection.execute(
            """
            SELECT COALESCE(SUM(l.debit - l.credit), 0)
            FROM finance.journal_lines l
            JOIN finance.journal_entries e ON e.id = l.entry_id
            WHERE l.tenant_id = %s AND l.account_code = %s AND e.status = ANY(%s) AND e.entry_date < %s
            """,
            (tenant_id, account_code, BOOKED, date_from),
        ).fetchone()[0]
        rows = self._connection.execute(
            """
            SELECT e.id, e.number, e.journal_code, e.entry_date, COALESCE(l.label, e.label), e.reference, l.debit, l.credit
            FROM finance.journal_lines l
            JOIN finance.journal_entries e ON e.id = l.entry_id
            WHERE l.tenant_id = %s AND l.account_code = %s AND e.status = ANY(%s)
              AND e.entry_date BETWEEN %s AND %s
            ORDER BY e.entry_date, e.number, l.line_no
            """,
            (tenant_id, account_code, BOOKED, date_from, date_to),
        ).fetchall()
        balance = opening
        total_debit = total_credit = ZERO
        lines: list[dict] = []
        for entry_id, number, journal_code, entry_date, label, reference, debit, credit in rows:
            balance += debit - credit
            total_debit += debit
            total_credit += credit
            lines.append(
                {
                    "entry_id": entry_id,
                    "number": number,
                    "journal_code": journal_code,
                    "entry_date": entry_date,
                    "label": label,
                    "reference": reference,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                }
            )
        return Ok(
            {
                "account": dict(zip(ACCOUNT_KEYS, account)),
                "opening_balance": opening,
                "lines": lines,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "closing_balance": balance,
            }
        )

    def account_balances(self, *, tenant_id: str, prefixes: list[str], as_of: datetime.date) -> list[dict]:
        """Postable accounts whose number starts with one of `prefixes`, as booked on `as_of`.
        `owed` is credit minus debit: what the company owes on a liability account."""
        patterns = [f"{prefix}%" for prefix in prefixes if prefix.isdigit()]
        if not patterns:
            return []
        rows = self._connection.execute(
            """
            SELECT a.code, a.name, COALESCE(SUM(m.debit), 0), COALESCE(SUM(m.credit), 0)
            FROM finance.accounts a
            LEFT JOIN (
                SELECT l.account_code, l.debit, l.credit
                FROM finance.journal_lines l
                JOIN finance.journal_entries e ON e.id = l.entry_id
                WHERE l.tenant_id = %s AND e.status = ANY(%s) AND e.entry_date <= %s
            ) m ON m.account_code = a.code
            WHERE a.tenant_id = %s AND a.is_postable AND a.code LIKE ANY(%s)
            GROUP BY a.code, a.name
            ORDER BY a.code
            """,
            (tenant_id, BOOKED, as_of, tenant_id, patterns),
        ).fetchall()
        return [
            {"account_code": code, "account_name": name, "debit": debit, "credit": credit, "owed": credit - debit}
            for code, name, debit, credit in rows
        ]

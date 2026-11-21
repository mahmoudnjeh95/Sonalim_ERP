"""VAT report: what was collected on sales by rate, and what the ledger says is collected, deductible and payable.

Sales by rate comes from finance's own invoice and credit-note lines. The purchase side comes from the ledger
(the deductible-VAT account of the `purchase_invoice / vat` posting rule), because finance may not read
procurement's tables; the ledger is also what the VAT return is filed from."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg

from modules.finance.api.ledger_report_service import BOOKED

ZERO = Decimal("0")
COUNTED_STATUSES = ["issued", "partially_paid", "paid"]


class VatReportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _rule_account(self, tenant_id: str, source: str, side: str) -> str | None:
        row = self._connection.execute(
            f"SELECT {side}_account_code FROM finance.posting_rules WHERE tenant_id = %s AND source = %s AND source_kind = 'vat' AND code = '*'",
            (tenant_id, source),
        ).fetchone()
        return row[0] if row and row[0] else None

    def _movement(self, tenant_id: str, account: str, date_from: datetime.date, date_to: datetime.date) -> tuple[Decimal, Decimal]:
        row = self._connection.execute(
            """
            SELECT COALESCE(SUM(l.debit), 0), COALESCE(SUM(l.credit), 0)
            FROM finance.journal_lines l JOIN finance.journal_entries e ON e.id = l.entry_id
            WHERE l.tenant_id = %s AND l.account_code = %s AND e.status = ANY(%s) AND e.entry_date BETWEEN %s AND %s
            """,
            (tenant_id, account, BOOKED, date_from, date_to),
        ).fetchone()
        return row[0], row[1]

    def sales_by_rate(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT vat_rate, SUM(base), SUM(vat) FROM (
                SELECT l.vat_rate, l.amount AS base, ROUND(l.amount * l.vat_rate / 100, 2) AS vat
                FROM finance.invoice_lines l JOIN finance.invoices i ON i.id = l.invoice_id
                WHERE i.tenant_id = %(t)s AND i.status = ANY(%(statuses)s) AND i.invoice_date BETWEEN %(a)s AND %(b)s
                UNION ALL
                SELECT l.vat_rate, -l.amount, -ROUND(l.amount * l.vat_rate / 100, 2)
                FROM finance.credit_note_lines l JOIN finance.credit_notes c ON c.id = l.credit_note_id
                WHERE c.tenant_id = %(t)s AND c.credit_date BETWEEN %(a)s AND %(b)s
            ) x GROUP BY vat_rate ORDER BY vat_rate DESC
            """,
            {"t": tenant_id, "statuses": COUNTED_STATUSES, "a": date_from, "b": date_to},
        ).fetchall()
        return [{"vat_rate": rate, "base": base, "vat": vat, "exempt": rate == 0} for rate, base, vat in rows]

    def report(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, Any]:
        by_rate = self.sales_by_rate(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        warnings: list[str] = []
        collected_account = self._rule_account(tenant_id, "invoice", "credit")
        deductible_account = self._rule_account(tenant_id, "purchase_invoice", "debit")
        collected = deductible = None
        if collected_account is None:
            warnings.append("NO_COLLECTED_VAT_ACCOUNT")
        else:
            debit, credit = self._movement(tenant_id, collected_account, date_from, date_to)
            collected = credit - debit
        if deductible_account is None:
            warnings.append("NO_DEDUCTIBLE_VAT_ACCOUNT")
        else:
            debit, credit = self._movement(tenant_id, deductible_account, date_from, date_to)
            deductible = debit - credit
        payable = (collected or ZERO) - (deductible or ZERO) if collected is not None or deductible is not None else None
        return {
            "date_from": date_from, "date_to": date_to,
            "sales_by_rate": by_rate,
            "sales_base": sum((r["base"] for r in by_rate), ZERO),
            "sales_vat": sum((r["vat"] for r in by_rate), ZERO),
            "ledger": {
                "collected_account": collected_account, "deductible_account": deductible_account,
                "collected": collected, "deductible": deductible, "payable": payable,
            },
            "warnings": warnings,
        }

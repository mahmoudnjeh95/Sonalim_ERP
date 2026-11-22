"""What the company owes its suppliers: the aged balance by supplier and a supplier's account statement.

Read only, from procurement's own tables. Payments come from `invoice_payment_deltas` (written when treasury
posts or cancels a disbursement); the disbursement's number and date are looked up in treasury when it is
installed, so the statement shows the voucher a payment was made with."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg

from core.domain.result import Err
from modules.procurement.domain.payables import bucket_for, days_overdue, empty_buckets

ZERO = Decimal("0")
OPEN_STATUSES = ("validated", "partially_paid")


class PayablesService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _open_invoices(self, tenant_id: str, partner_id: str | None, today: datetime.date) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s", "status = ANY(%s)"], [tenant_id, list(OPEN_STATUSES)]
        if partner_id is not None:
            clauses.append("partner_id = %s")
            params.append(partner_id)
        rows = self._connection.execute(
            f"""
            SELECT id, partner_id, number, supplier_invoice_number, invoice_date, due_date, amount, amount_paid, status
            FROM procurement.purchase_invoices WHERE {' AND '.join(clauses)} ORDER BY invoice_date, id
            """,
            params,
        ).fetchall()
        invoices = []
        for invoice_id, partner, number, supplier_number, invoice_date, due_date, amount, paid, status in rows:
            remaining = amount - paid
            if remaining < 1:  # under one franc is settled, as everywhere in purchase invoices
                continue
            late = days_overdue(due_date, today)
            invoices.append({
                "id": invoice_id, "partner_id": partner, "number": number, "supplier_invoice_number": supplier_number,
                "invoice_date": invoice_date, "due_date": due_date, "amount": amount, "amount_paid": paid,
                "remaining": remaining, "overdue": remaining if late else ZERO, "days_overdue": late,
                "bucket": bucket_for(late), "status": status,
            })
        return invoices

    def _partner_names(self, tenant_id: str, partner_ids: list[str]) -> dict[str, str]:
        if not partner_ids:
            return {}
        return dict(self._connection.execute(
            "SELECT id, name FROM core.partners WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, partner_ids)).fetchall())

    def aging(self, *, tenant_id: str, today: datetime.date | None = None) -> list[dict[str, Any]]:
        """The aged balance by supplier: what is owed, and how much of it is past its due date, by lateness."""
        today = today or datetime.date.today()
        rows: dict[str, dict[str, Any]] = {}
        for invoice in self._open_invoices(tenant_id, None, today):
            row = rows.setdefault(invoice["partner_id"], {
                "partner_id": invoice["partner_id"], "remaining": ZERO, "overdue": ZERO, "max_days_overdue": 0,
                "invoices": 0, **empty_buckets()})
            row["remaining"] += invoice["remaining"]
            row["overdue"] += invoice["overdue"]
            row["invoices"] += 1
            row["max_days_overdue"] = max(row["max_days_overdue"], invoice["days_overdue"])
            row[f"bucket_{invoice['bucket']}"] += invoice["remaining"]
        names = self._partner_names(tenant_id, list(rows))
        result = [{**row, "partner_name": names.get(partner_id)} for partner_id, row in rows.items()]
        return sorted(result, key=lambda r: (-r["overdue"], -r["remaining"]))

    def _treasury_document(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        try:
            from modules.treasury.api.posting_service import TreasuryPostingService
        except ImportError:  # treasury is an optional dependency
            return None
        found = TreasuryPostingService(self._connection).document_lines(tenant_id=tenant_id, document_id=document_id)
        return None if isinstance(found, Err) else {"number": found.value["number"], "date": found.value["date"]}

    def statement(self, *, tenant_id: str, partner_id: str, date_from: datetime.date | None = None,
                  date_to: datetime.date | None = None, today: datetime.date | None = None) -> dict[str, Any]:
        """The supplier's account from our side: invoices (credit: we owe more), credit notes and payments
        (debit), oldest first, with a running balance (positive = we owe) from the opening balance at `date_from`."""
        today = today or datetime.date.today()
        c = self._connection
        entries: list[dict[str, Any]] = []
        for invoice_id, number, supplier_number, day, due, amount_due, incl in c.execute(
            """
            SELECT id, number, supplier_invoice_number, invoice_date, due_date, amount, total_incl_tax
            FROM procurement.purchase_invoices
            WHERE tenant_id = %s AND partner_id = %s AND status NOT IN ('draft', 'cancelled')
            """,
            (tenant_id, partner_id),
        ).fetchall():
            entries.append({"date": day, "kind": "invoice", "reference": number or supplier_number, "due_date": due,
                            "debit": ZERO, "credit": incl, "invoice_id": invoice_id})
        for number, day, total, invoice_number in c.execute(
            """
            SELECT n.number, n.note_date, n.total_incl_tax, i.number
            FROM procurement.purchase_credit_notes n JOIN procurement.purchase_invoices i ON i.id = n.invoice_id
            WHERE n.tenant_id = %s AND n.partner_id = %s AND n.status = 'validated'
            """,
            (tenant_id, partner_id),
        ).fetchall():
            entries.append({"date": day, "kind": "credit_note", "reference": number, "due_date": None, "debit": total,
                            "credit": ZERO, "against": invoice_number})
        documents: dict[str, dict[str, Any] | None] = {}
        for document_id, amount, applied_at, invoice_number in c.execute(
            """
            SELECT d.document_id, d.amount, d.applied_at, i.number
            FROM procurement.invoice_payment_deltas d JOIN procurement.purchase_invoices i ON i.id = d.invoice_id
            WHERE i.tenant_id = %s AND i.partner_id = %s
            """,
            (tenant_id, partner_id),
        ).fetchall():
            if document_id not in documents:
                documents[document_id] = self._treasury_document(tenant_id, document_id)
            document = documents[document_id]
            entries.append({
                "date": (document or {}).get("date") or applied_at.date(),
                "kind": "payment" if amount > 0 else "payment_reversed",
                "reference": (document or {}).get("number") or document_id, "due_date": None, "against": invoice_number,
                "debit": amount if amount > 0 else ZERO, "credit": -amount if amount < 0 else ZERO,
            })
        order = {"invoice": 0, "credit_note": 1, "payment": 2, "payment_reversed": 3}
        entries.sort(key=lambda e: (e["date"], order[e["kind"]], str(e["reference"])))
        opening = ZERO
        lines: list[dict[str, Any]] = []
        balance = ZERO
        for entry in entries:
            if date_from and entry["date"] < date_from:
                opening += entry["credit"] - entry["debit"]
                continue
            if date_to and entry["date"] > date_to:
                continue
            if not lines:
                balance = opening
            balance += entry["credit"] - entry["debit"]
            lines.append({**entry, "balance": balance})
        open_invoices = self._open_invoices(tenant_id, partner_id, today)
        return {
            "partner_id": partner_id, "partner_name": self._partner_names(tenant_id, [partner_id]).get(partner_id),
            "date_from": date_from, "date_to": date_to, "opening_balance": opening,
            "closing_balance": lines[-1]["balance"] if lines else opening, "lines": lines,
            "remaining": sum((i["remaining"] for i in open_invoices), ZERO),
            "overdue": sum((i["overdue"] for i in open_invoices), ZERO), "open_invoices": open_invoices,
        }

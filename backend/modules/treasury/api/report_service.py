from __future__ import annotations


import datetime

from decimal import Decimal
from typing import Any

import psycopg

from core.tabular_export import tabular_response  # noqa: F401  (re-exported for the router)

BUCKETS = (("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, 10**6))


def bucket_for(days: int) -> str:
    """Age of the debt in days (never negative). Used for both sales and purchase reports."""
    days = max(days, 0)
    return next(name for name, low, high in BUCKETS if low <= days <= high)


class InvoiceStatusReportService:
    """Per-partner position on invoices, read through the owning modules' public services so
    treasury never touches finance or procurement tables. Currencies are never summed together."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def sales(self, *, tenant_id: str, today: datetime.date | None = None) -> list[dict[str, Any]]:
        from modules.finance.api.service import InvoiceService

        service = InvoiceService(self._connection)
        rows = []
        for invoice in service.list_invoices(tenant_id):
            if invoice.status == "draft":
                continue
            detail = service.get_invoice(tenant_id=tenant_id, invoice_id=invoice.id).value
            rows.append({
                "invoice_id": invoice.id, "number": detail.get("number"), "partner_id": detail["partner_id"], "currency": detail["currency"],
                "amount": detail["amount"], "paid": detail["amount_paid"], "remaining": detail["remaining"],
                "status": detail["status"], "reference_date": detail["invoice_date"], "due_date": None,
                "invoice_date": detail["invoice_date"],
            })
        return self._with_age(rows, today)

    def purchases(self, *, tenant_id: str, today: datetime.date | None = None) -> list[dict[str, Any]]:
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        rows = []
        for invoice in PurchaseInvoiceService(self._connection).list_invoices(tenant_id=tenant_id):
            if invoice["status"] in ("draft", "cancelled"):
                continue
            rows.append({
                "invoice_id": invoice["id"], "number": invoice["number"], "partner_id": invoice["partner_id"],
                "currency": invoice["currency"], "amount": invoice["amount"], "paid": invoice["amount_paid"],
                "remaining": invoice["remaining"], "status": invoice["status"],
                "reference_date": invoice["due_date"] or invoice["invoice_date"], "due_date": invoice["due_date"],
                "invoice_date": invoice["invoice_date"],
            })
        return self._with_age(rows, today)

    def by_partner_and_document(self, *, tenant_id: str, direction: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The manual's layout: per partner, per receipt or disbursement with its net and withheld amounts,
        the invoices it settled; then the invoices no document touched."""
        names = dict(self._connection.execute("SELECT id, name FROM core.partners WHERE tenant_id = %s", (tenant_id,)).fetchall())
        settled_by: dict[str, list[tuple]] = {}
        for invoice_id, document_id, number, total, withheld in self._connection.execute(
            """
            SELECT a.invoice_id, d.id, d.number, d.total, d.withheld_amount
            FROM treasury.document_allocations a JOIN treasury.documents d ON d.id = a.document_id
            WHERE d.tenant_id = %s AND d.direction = %s AND d.status = 'posted' ORDER BY d.number
            """,
            (tenant_id, direction),
        ).fetchall():
            settled_by.setdefault(invoice_id, []).append((document_id, number, total, withheld))
        partners: dict[str, dict[str, Any]] = {}
        for row in rows:
            partner = partners.setdefault(row["partner_id"], {
                "partner_id": row["partner_id"], "partner_name": names.get(row["partner_id"]), "documents": {}, "without_document": [],
            })
            documents = settled_by.get(row["invoice_id"])
            if not documents:
                partner["without_document"].append(row)
            for document_id, number, total, withheld in documents or []:
                document = partner["documents"].setdefault(document_id, {
                    "document_id": document_id, "number": number, "net_to_pay": total, "withheld": withheld, "invoices": [],
                })
                document["invoices"].append(row)
        ordered = sorted(partners.values(), key=lambda p: p["partner_name"] or "")
        return [{**p, "documents": sorted(p["documents"].values(), key=lambda d: d["number"])} for p in ordered]

    @staticmethod
    def flat_rows(groups: list[dict[str, Any]], *, without_label: str) -> list[list[Any]]:
        """The grouped report as spreadsheet rows, one per invoice under its partner and document."""
        rows: list[list[Any]] = []
        def add(partner: dict[str, Any], label: str, invoice: dict[str, Any]) -> None:
            rows.append([partner["partner_name"], label, invoice["number"] or invoice["invoice_id"], invoice["invoice_date"],
                         invoice["amount"], invoice["paid"], invoice["remaining"], invoice["status"]])
        for partner in groups:
            for document in partner["documents"]:
                for invoice in document["invoices"]:
                    add(partner, document["number"], invoice)
            for invoice in partner["without_document"]:
                add(partner, without_label, invoice)
        return rows

    @staticmethod
    def _with_age(rows: list[dict[str, Any]], today: datetime.date | None) -> list[dict[str, Any]]:
        today = today or datetime.date.today()
        for row in rows:
            age = (today - row["reference_date"]).days if row["remaining"] > 0 else 0
            row["age_days"] = max(age, 0)
            row["bucket"] = bucket_for(age) if row["remaining"] > 0 else None
        return rows

    @staticmethod
    def by_partner(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["partner_id"], row["currency"])
            group = groups.setdefault(key, {
                "partner_id": row["partner_id"], "currency": row["currency"], "invoiced": Decimal("0"), "paid": Decimal("0"),
                "remaining": Decimal("0"), "count": 0, **{f"bucket_{name}": Decimal("0") for name, _, _ in BUCKETS},
            })
            group["invoiced"] += row["amount"]
            group["paid"] += row["paid"]
            group["remaining"] += row["remaining"]
            group["count"] += 1
            if row["bucket"]:
                group[f"bucket_{row['bucket']}"] += row["remaining"]
        return sorted(groups.values(), key=lambda g: (g["partner_id"], g["currency"]))



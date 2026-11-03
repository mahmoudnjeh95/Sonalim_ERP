from __future__ import annotations

import csv
import datetime
import io
from decimal import Decimal
from typing import Any

import psycopg
from fastapi import Response
from openpyxl import Workbook

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
                "invoice_id": invoice.id, "number": None, "partner_id": detail["partner_id"], "currency": detail["currency"],
                "amount": detail["amount"], "paid": detail["amount_paid"], "remaining": detail["remaining"],
                "status": detail["status"], "reference_date": detail["invoice_date"], "due_date": None,
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
            })
        return self._with_age(rows, today)

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


def tabular_response(headers: list[str], rows: list[list[Any]], fmt: str, filename: str) -> Response:
    """CSV or XLSX download of a report. Decimals are written as numbers, not text."""
    if fmt == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append([float(c) if isinstance(c, Decimal) else c for c in row])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return Response(
            buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        "﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )

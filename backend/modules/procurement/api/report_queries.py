"""Read side of purchase invoices for other modules' reports. Warehouse's movements report shows them as
information rows, as the manual lists invoices and credit notes among the movement types; it may not read
procurement's tables, so it calls these. Only lines that name a catalog product are returned, and only
documents that count: validated (or paid) invoices and validated credit notes."""
from __future__ import annotations

import datetime
from typing import Any

import psycopg

_INVOICE_COUNTS = ("validated", "partially_paid", "paid")


def list_invoice_lines_for_report(connection: psycopg.Connection, *, tenant_id: str, date_from: datetime.date | None = None,
                                  date_to: datetime.date | None = None, product_id: str | None = None) -> list[dict[str, Any]]:
    clauses, params = ["i.tenant_id = %s", "i.status = ANY(%s)", "l.product_id IS NOT NULL"], [tenant_id, list(_INVOICE_COUNTS)]
    for column, value, op in (("i.invoice_date", date_from, ">="), ("i.invoice_date", date_to, "<="), ("l.product_id", product_id, "=")):
        if value:
            clauses.append(f"{column} {op} %s")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT l.product_id, l.quantity, i.number, i.invoice_date, i.partner_id, i.id
        FROM procurement.purchase_invoice_lines l JOIN procurement.purchase_invoices i ON i.id = l.invoice_id
        WHERE {' AND '.join(clauses)}
        ORDER BY i.invoice_date DESC, i.number DESC, l.line_no
        """,
        params,
    ).fetchall()
    return [{"product_id": r[0], "quantity": r[1], "number": r[2], "date": r[3], "partner_id": r[4], "document_id": r[5]} for r in rows]


def list_credit_notes_for_report(connection: psycopg.Connection, *, tenant_id: str, date_from: datetime.date | None = None,
                                 date_to: datetime.date | None = None, product_id: str | None = None) -> list[dict[str, Any]]:
    """Credit-note lines carry no product of their own: it is the invoice line's they correct."""
    clauses, params = ["c.tenant_id = %s", "c.status = 'validated'", "il.product_id IS NOT NULL"], [tenant_id]
    for column, value, op in (("c.note_date", date_from, ">="), ("c.note_date", date_to, "<="), ("il.product_id", product_id, "=")):
        if value:
            clauses.append(f"{column} {op} %s")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT il.product_id, cl.quantity, c.number, c.note_date, c.partner_id, c.id
        FROM procurement.purchase_credit_note_lines cl
        JOIN procurement.purchase_credit_notes c ON c.id = cl.credit_note_id
        JOIN procurement.purchase_invoice_lines il ON il.id = cl.invoice_line_id
        WHERE {' AND '.join(clauses)}
        ORDER BY c.note_date DESC, c.number DESC, cl.line_no
        """,
        params,
    ).fetchall()
    return [{"product_id": r[0], "quantity": r[1], "number": r[2], "date": r[3], "partner_id": r[4], "document_id": r[5]} for r in rows]

"""Read side of sales invoices and credit notes for other modules' reports. Warehouse's movements report
shows them as information rows (the manual lists invoices and credit notes among the movement types); it
may not read finance's tables, so it calls these. Only documents that count are returned: issued (or paid)
invoices, and credit notes. Invoices from before invoices had lines (billed whole at order confirmation)
have no product lines, so they don't appear."""
from __future__ import annotations

import datetime
from typing import Any

import psycopg

_INVOICE_COUNTS = ("issued", "partially_paid", "paid")


def _filters(prefix: str, date_column: str, tenant_id: str, date_from, date_to, product_id) -> tuple[list[str], list[Any]]:
    clauses, params = [f"{prefix}.tenant_id = %s"], [tenant_id]
    for column, value, op in ((date_column, date_from, ">="), (date_column, date_to, "<="), ("l.product_id", product_id, "=")):
        if value:
            clauses.append(f"{column} {op} %s")
            params.append(value)
    return clauses, params


def list_invoice_lines_for_report(connection: psycopg.Connection, *, tenant_id: str, date_from: datetime.date | None = None,
                                  date_to: datetime.date | None = None, product_id: str | None = None) -> list[dict[str, Any]]:
    clauses, params = _filters("i", "i.invoice_date", tenant_id, date_from, date_to, product_id)
    clauses.append("i.status = ANY(%s)")
    params.append(list(_INVOICE_COUNTS))
    rows = connection.execute(
        f"""
        SELECT l.product_id, l.quantity, i.number, i.invoice_date, i.partner_id, i.id
        FROM finance.invoice_lines l JOIN finance.invoices i ON i.id = l.invoice_id
        WHERE {' AND '.join(clauses)}
        ORDER BY i.invoice_date DESC, i.number DESC, l.id
        """,
        params,
    ).fetchall()
    return [{"product_id": r[0], "quantity": r[1], "number": r[2], "date": r[3], "partner_id": r[4], "document_id": r[5]} for r in rows]


def list_credit_notes_for_report(connection: psycopg.Connection, *, tenant_id: str, date_from: datetime.date | None = None,
                                 date_to: datetime.date | None = None, product_id: str | None = None) -> list[dict[str, Any]]:
    clauses, params = _filters("c", "c.credit_date", tenant_id, date_from, date_to, product_id)
    rows = connection.execute(
        f"""
        SELECT l.product_id, l.quantity, c.number, c.credit_date, c.partner_id, c.id
        FROM finance.credit_note_lines l JOIN finance.credit_notes c ON c.id = l.credit_note_id
        WHERE {' AND '.join(clauses)}
        ORDER BY c.credit_date DESC, c.number DESC, l.id
        """,
        params,
    ).fetchall()
    return [{"product_id": r[0], "quantity": r[1], "number": r[2], "date": r[3], "partner_id": r[4], "document_id": r[5]} for r in rows]

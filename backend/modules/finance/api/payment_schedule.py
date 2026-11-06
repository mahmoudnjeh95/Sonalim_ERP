"""When a sales invoice falls due: its customer's payment terms, applied once when the invoice is created and
kept on it. Changing the customer's terms or the catalog later never redates an invoice already made."""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import psycopg

from core.domain.payment_terms import parse_installments, schedule
from core.payment_terms import PaymentTermService


def _write(connection: psycopg.Connection, invoice_id: str, code: str | None, rule: list[dict[str, Any]],
           rows: list[tuple[datetime.date, Decimal]]) -> None:
    connection.execute(
        "UPDATE finance.invoices SET due_date = %s, payment_term_code = %s, payment_term_rule = %s WHERE id = %s",
        (rows[-1][0], code, json.dumps(rule), invoice_id),
    )
    connection.execute("DELETE FROM finance.invoice_installments WHERE invoice_id = %s", (invoice_id,))
    for seq, (due_on, amount) in enumerate(rows, start=1):
        connection.execute(
            "INSERT INTO finance.invoice_installments (invoice_id, seq, due_date, amount) VALUES (%s, %s, %s, %s)",
            (invoice_id, seq, due_on, amount),
        )


def apply_customer_terms(connection: psycopg.Connection, *, tenant_id: str, invoice_id: str, partner_id: str,
                         invoice_date: datetime.date) -> datetime.date:
    """Dates a new invoice from its customer's terms, spreading the amount it was stored with. Returns the
    last due date."""
    total = connection.execute("SELECT amount FROM finance.invoices WHERE id = %s AND tenant_id = %s", (invoice_id, tenant_id)).fetchone()[0]
    planned = PaymentTermService(connection).schedule_for(
        tenant_id=tenant_id, partner_id=partner_id, side="customer", invoice_date=invoice_date, amount=Decimal(str(total)))
    rows = [(i["due_date"], i["amount"]) for i in planned["installments"]]
    _write(connection, invoice_id, planned["term"]["code"] if planned["term"] else None, planned["rule"], rows)
    return planned["due_date"]


def redate(connection: psycopg.Connection, *, tenant_id: str, invoice_id: str) -> None:
    """Spreads an invoice's current total over the rule it was given (after its amount or date changed)."""
    row = connection.execute(
        "SELECT amount, COALESCE(invoice_date, created_at::date), payment_term_code, payment_term_rule, partner_id "
        "FROM finance.invoices WHERE id = %s AND tenant_id = %s",
        (invoice_id, tenant_id),
    ).fetchone()
    if row is None:
        return
    amount, invoice_date, code, rule, partner_id = row
    if rule is None:
        apply_customer_terms(connection, tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, invoice_date=invoice_date)
        return
    if rule == []:
        # A due date entered by hand stays where it was put.
        due = connection.execute("SELECT due_date FROM finance.invoices WHERE id = %s", (invoice_id,)).fetchone()[0]
        _write(connection, invoice_id, None, [], [(due, Decimal(str(amount)))])
        return
    installments = parse_installments(rule).value
    _write(connection, invoice_id, code, rule, schedule(invoice_date, Decimal(str(amount)), installments))


def set_single_due_date(connection: psycopg.Connection, *, tenant_id: str, invoice_id: str, due_date: datetime.date) -> None:
    """A due date entered by hand replaces the schedule with a single installment."""
    amount = connection.execute("SELECT amount FROM finance.invoices WHERE id = %s AND tenant_id = %s", (invoice_id, tenant_id)).fetchone()[0]
    _write(connection, invoice_id, None, [], [(due_date, Decimal(str(amount)))])


def installments_of(connection: psycopg.Connection, invoice_ids: list[str]) -> dict[str, list[tuple[datetime.date, Decimal]]]:
    """Each invoice's installments; an invoice dated before terms existed has one, on its due date."""
    if not invoice_ids:
        return {}
    found: dict[str, list[tuple[datetime.date, Decimal]]] = {}
    for invoice_id, due_on, amount in connection.execute(
        "SELECT invoice_id, due_date, amount FROM finance.invoice_installments WHERE invoice_id = ANY(%s) ORDER BY invoice_id, seq",
        (invoice_ids,),
    ).fetchall():
        found.setdefault(invoice_id, []).append((due_on, Decimal(str(amount))))
    return found

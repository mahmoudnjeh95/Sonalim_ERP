"""Sales invoices created from deliveries, and credit notes from returns.

Warehouse says what left (a billable delivery note or a shipped pick list) and what came back (a return
voucher); sales says at what price (the order, read through its public api). Finance never reads either
module's tables. Every entry point is idempotent on the warehouse document, so a replayed event is a no-op."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.tax import breakdown_payload, vat_breakdown
from core.events.outbox import publish_event
from modules.finance.domain.billing import (
    BilledLine,
    CreditableInvoice,
    amount_due,
    document_totals,
    lines_to_credit,
    lines_to_invoice,
    order_prices,
    order_taxes,
)
from modules.finance.domain.entities import status_for_payment

SYSTEM_ACTOR = "system:event-consumer"
INVOICE_PREFIX = "FV"
CREDIT_NOTE_PREFIX = "AVC"
DELIVERY_SOURCES = ("delivery_note", "shipment")


def next_number(connection: psycopg.Connection, tenant_id: str, kind: str, year: int) -> str:
    row = connection.execute(
        """
        INSERT INTO finance.document_counters (tenant_id, kind, year, last_number) VALUES (%s, %s, %s, 1)
        ON CONFLICT (tenant_id, kind, year) DO UPDATE SET last_number = finance.document_counters.last_number + 1
        RETURNING last_number
        """,
        (tenant_id, kind, year),
    ).fetchone()
    return f"{kind}-{year}-{row[0]:06d}"


class DeliveryBillingService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- invoices ---------------------------------------------------------------------------

    @atomic
    def invoice_delivery(
        self, *, tenant_id: str, source_type: str, source_id: str, source_number: str | None, order_id: str,
        delivered: dict[str, Decimal], delivered_on: datetime.date, actor_id: str = SYSTEM_ACTOR,
    ) -> Result[dict[str, Any] | None]:
        """A draft invoice for what one delivery carried, at the order's prices. Ok(None) when there is nothing
        to bill: the order was invoiced at confirmation under the old rule, or the order is already billed in full."""
        if source_type not in DELIVERY_SOURCES:
            return Err("INVALID_SOURCE", f"unknown delivery source {source_type}", f"source de livraison inconnue {source_type}")
        existing = self._connection.execute(
            "SELECT id FROM finance.invoices WHERE tenant_id = %s AND source_type = %s AND source_id = %s",
            (tenant_id, source_type, source_id),
        ).fetchone()
        if existing:
            return self._invoice(tenant_id, existing[0])
        # Serialise deliveries of one order, so two of them can't both bill what is left.
        self._connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"finance-order-billing:{order_id}",))
        # Decision: an order billed when it was confirmed (before invoices followed deliveries) is never billed again.
        if self._connection.execute(
            "SELECT 1 FROM finance.invoices WHERE tenant_id = %s AND source_order_id = %s AND source_type = 'order'",
            (tenant_id, order_id),
        ).fetchone():
            return Ok(None)
        from modules.sales.api.service import SalesOrderService

        order = SalesOrderService(self._connection).get_order(tenant_id=tenant_id, order_id=order_id)
        if isinstance(order, Err):
            return order
        # Billed at the price the order agreed after its discounts (line, then order), with its VAT rate.
        ordered = order_prices(
            (line.product_id, Decimal(str(line.quantity)), order.value.net_unit_price(line)) for line in order.value.lines
        )
        list_prices = order_prices(
            (line.product_id, Decimal(str(line.quantity)), Decimal(str(line.unit_price))) for line in order.value.lines
        )
        taxes = order_taxes(
            (line.product_id, Decimal(str(line.quantity)) * order.value.net_unit_price(line), Decimal(str(line.vat_rate)), line.tax_code)
            for line in order.value.lines
        )
        lines = lines_to_invoice(delivered, ordered, self._invoiced_for_order(tenant_id, order_id),
                                 {p: rate for p, (rate, _) in taxes.items()}, {p: code for p, (_, code) in taxes.items()})
        if not lines:
            return Ok(None)
        invoice_id = str(ULID())
        number = next_number(self._connection, tenant_id, INVOICE_PREFIX, delivered_on.year)
        excl_tax, vat, total = document_totals(lines)
        self._connection.execute(
            """
            INSERT INTO finance.invoices (id, tenant_id, partner_id, amount, currency, status, source_order_id, number,
                                          invoice_date, source_type, source_id, source_number, amount_excl_tax, vat_amount)
            VALUES (%s, %s, %s, %s, 'XOF', 'draft', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (invoice_id, tenant_id, order.value.partner_id, total, order_id, number, delivered_on, source_type, source_id, source_number,
             excl_tax, vat),
        )
        self._insert_lines("finance.invoice_lines", "invoice_id", invoice_id, tenant_id, lines,
                           list_prices={product_id: price for product_id, (_, price) in list_prices.items()})
        from modules.finance.api.payment_schedule import apply_customer_terms

        due_date = apply_customer_terms(self._connection, tenant_id=tenant_id, invoice_id=invoice_id, partner_id=order.value.partner_id,
                                        invoice_date=delivered_on)
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="invoice.created", entity_type="invoice", entity_id=invoice_id,
            payload={"number": number, "source_type": source_type, "source_id": source_id, "order_id": order_id, "amount": str(total),
                     "due_date": due_date.isoformat()},
        )
        return self._invoice(tenant_id, invoice_id)

    def _invoiced_for_order(self, tenant_id: str, order_id: str) -> dict[str, Decimal]:
        rows = self._connection.execute(
            """
            SELECT l.product_id, SUM(l.quantity) FROM finance.invoice_lines l JOIN finance.invoices i ON i.id = l.invoice_id
            WHERE i.tenant_id = %s AND i.source_order_id = %s AND i.source_type IN ('delivery_note', 'shipment')
            GROUP BY l.product_id
            """,
            (tenant_id, order_id),
        ).fetchall()
        return {product_id: Decimal(str(quantity)) for product_id, quantity in rows}

    # ---- credit notes -----------------------------------------------------------------------

    @atomic
    def credit_return(
        self, *, tenant_id: str, return_id: str, return_number: str | None, delivery_note_ids: list[str],
        order_id: str | None, returned: dict[str, Decimal], returned_on: datetime.date, correlation_id: str,
        actor_id: str = SYSTEM_ACTOR,
    ) -> Result[list[dict[str, Any]]]:
        """Credit notes for what a posted return brought back, against the invoices of the deliveries it
        returns to (the latest first). Goods never invoiced are not credited."""
        done = self._connection.execute(
            "SELECT id FROM finance.credit_notes WHERE tenant_id = %s AND source_id = %s ORDER BY number", (tenant_id, return_id)
        ).fetchall()
        if done:
            return Ok([self._credit_note(tenant_id, row[0]) for row in done])
        candidates = self._creditable_invoices(tenant_id, delivery_note_ids, order_id)
        if isinstance(candidates, Err):
            return candidates
        notes = []
        for invoice_id, lines in lines_to_credit(returned, candidates.value).items():
            notes.append(self._issue_credit_note(tenant_id, actor_id, correlation_id, invoice_id, return_id, return_number, returned_on, lines))
        return Ok(notes)

    def _creditable_invoices(self, tenant_id: str, delivery_note_ids: list[str], order_id: str | None) -> Result[list[CreditableInvoice]]:
        rows = []
        if delivery_note_ids:
            rows = self._connection.execute(
                """
                SELECT id, source_type FROM finance.invoices
                WHERE tenant_id = %s AND source_type = 'delivery_note' AND source_id = ANY(%s)
                ORDER BY invoice_date DESC, number DESC
                """,
                (tenant_id, delivery_note_ids),
            ).fetchall()
        if not rows and order_id:
            # An order billed whole at confirmation: its invoice has no lines, so the order says what it carried.
            rows = self._connection.execute(
                "SELECT id, source_type FROM finance.invoices WHERE tenant_id = %s AND source_order_id = %s AND source_type = 'order'",
                (tenant_id, order_id),
            ).fetchall()
        result = []
        for invoice_id, source_type in rows:
            vat_rates: dict[str, Decimal] = {}
            tax_codes: dict[str, str | None] = {}
            if source_type == "order":
                from_order = self._order_lines_of(tenant_id, order_id)
                if isinstance(from_order, Err):
                    return from_order
                lines = from_order.value
            else:
                lines = {}
                for product_id, quantity, price, rate, code in self._connection.execute(
                    "SELECT product_id, SUM(quantity), SUM(quantity * unit_price) / NULLIF(SUM(quantity), 0), MAX(vat_rate), MAX(tax_code) "
                    "FROM finance.invoice_lines WHERE invoice_id = %s GROUP BY product_id",
                    (invoice_id,),
                ).fetchall():
                    lines[product_id] = (Decimal(str(quantity)), Decimal(str(price)))
                    vat_rates[product_id] = Decimal(str(rate))
                    tax_codes[product_id] = code
            credited = {
                product_id: Decimal(str(quantity))
                for product_id, quantity in self._connection.execute(
                    "SELECT l.product_id, SUM(l.quantity) FROM finance.credit_note_lines l JOIN finance.credit_notes c ON c.id = l.credit_note_id "
                    "WHERE c.invoice_id = %s GROUP BY l.product_id",
                    (invoice_id,),
                ).fetchall()
            }
            result.append(CreditableInvoice(invoice_id, lines, credited, vat_rates, tax_codes))
        return Ok(result)

    def _order_lines_of(self, tenant_id: str, order_id: str | None) -> Result[dict[str, tuple[Decimal, Decimal]]]:
        from modules.sales.api.service import SalesOrderService

        order = SalesOrderService(self._connection).get_order(tenant_id=tenant_id, order_id=order_id or "")
        if isinstance(order, Err):
            return order
        return Ok(order_prices(
            (line.product_id, Decimal(str(line.quantity)), order.value.net_unit_price(line)) for line in order.value.lines
        ))

    def _issue_credit_note(self, tenant_id: str, actor_id: str, correlation_id: str, invoice_id: str, return_id: str,
                           return_number: str | None, returned_on: datetime.date, lines: list[BilledLine]) -> dict[str, Any]:
        invoice = self._connection.execute(
            "SELECT partner_id, currency, amount, amount_credited, amount_paid, status FROM finance.invoices WHERE id = %s FOR UPDATE",
            (invoice_id,),
        ).fetchone()
        partner_id, currency, amount, credited, paid, status = invoice
        # Never more than what is still due before this note: the rounding of a line can't take the invoice below zero.
        excl_tax, vat, total = document_totals(lines)
        due = amount_due(amount, credited)
        if total > due:
            vat = (vat * due / total).quantize(Decimal("1")) if total else Decimal("0")
            total, excl_tax = due, due - vat
        credit_note_id = str(ULID())
        number = next_number(self._connection, tenant_id, CREDIT_NOTE_PREFIX, returned_on.year)
        self._connection.execute(
            """
            INSERT INTO finance.credit_notes (id, tenant_id, number, invoice_id, partner_id, source_id, source_number, credit_date, amount,
                                              currency, amount_excl_tax, vat_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (credit_note_id, tenant_id, number, invoice_id, partner_id, return_id, return_number, returned_on, total, currency,
             excl_tax, vat),
        )
        self._insert_lines("finance.credit_note_lines", "credit_note_id", credit_note_id, None, lines)
        new_credited = credited + total
        # A draft keeps its status; an issued invoice's status follows what is now due.
        new_status = status if status == "draft" else status_for_payment(amount_due(amount, new_credited), paid)
        self._connection.execute(
            "UPDATE finance.invoices SET amount_credited = %s, status = %s WHERE id = %s", (new_credited, new_status, invoice_id)
        )
        publish_event(
            self._connection, event_type="finance.credit_note.issued", producer="finance", tenant_id=tenant_id,
            correlation_id=correlation_id,
            event_version="1.2",
            # 1.1 (additive): the VAT inside `amount`; 1.2: its split per tax code
            payload={"credit_note_id": credit_note_id, "number": number, "invoice_id": invoice_id, "partner_id": partner_id,
                     "amount": str(total), "currency": currency, "vat": str(vat),
                     "vat_breakdown": breakdown_payload(vat_breakdown((l.tax_code, l.vat_rate, l.amount) for l in lines))},
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="credit_note.issued", entity_type="credit_note",
            entity_id=credit_note_id, payload={"number": number, "invoice_id": invoice_id, "return_id": return_id, "amount": str(total)},
        )
        return self._credit_note(tenant_id, credit_note_id)

    # ---- reads ------------------------------------------------------------------------------

    def _insert_lines(self, table: str, parent_column: str, parent_id: str, tenant_id: str | None, lines: list[BilledLine],
                      list_prices: dict[str, Decimal] | None = None) -> None:
        for line in lines:
            if tenant_id is None:
                self._connection.execute(
                    f"INSERT INTO {table} (id, {parent_column}, product_id, quantity, unit_price, amount, vat_rate, tax_code) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(ULID()), parent_id, line.product_id, line.quantity, line.unit_price, line.amount, line.vat_rate, line.tax_code),
                )
            else:
                # The list price and the combined discount the net price came from, for the invoice to show.
                list_price = (list_prices or {}).get(line.product_id)
                discount = (Decimal("100") * (1 - line.unit_price / list_price)).quantize(Decimal("0.0001")) if list_price else Decimal("0")
                self._connection.execute(
                    f"INSERT INTO {table} (id, tenant_id, {parent_column}, product_id, quantity, unit_price, amount, vat_rate, list_price, "
                    "discount_rate, tax_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(ULID()), tenant_id, parent_id, line.product_id, line.quantity, line.unit_price, line.amount, line.vat_rate,
                     list_price, max(discount, Decimal("0")), line.tax_code),
                )

    def _invoice(self, tenant_id: str, invoice_id: str) -> Ok:
        from modules.finance.api.service import InvoiceService

        return InvoiceService(self._connection).get_invoice_detail(tenant_id=tenant_id, invoice_id=invoice_id)

    def _credit_note(self, tenant_id: str, credit_note_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            """
            SELECT c.id, c.number, c.invoice_id, i.number, c.partner_id, c.source_id, c.source_number, c.credit_date, c.amount, c.currency,
                   c.amount_excl_tax, c.vat_amount
            FROM finance.credit_notes c JOIN finance.invoices i ON i.id = c.invoice_id
            WHERE c.id = %s AND c.tenant_id = %s
            """,
            (credit_note_id, tenant_id),
        ).fetchone()
        lines = self._connection.execute(
            "SELECT product_id, quantity, unit_price, amount, vat_rate, tax_code FROM finance.credit_note_lines WHERE credit_note_id = %s ORDER BY id",
            (credit_note_id,),
        ).fetchall()
        return {
            "id": row[0], "number": row[1], "invoice_id": row[2], "invoice_number": row[3], "partner_id": row[4],
            "return_id": row[5], "return_number": row[6], "credit_date": row[7], "amount": row[8], "currency": row[9],
            "amount_excl_tax": row[10], "vat_amount": row[11],
            "lines": [{"product_id": l[0], "quantity": l[1], "unit_price": l[2], "amount": l[3], "vat_rate": l[4], "tax_code": l[5]}
                      for l in lines],
        }

    def list_credit_notes(self, *, tenant_id: str, invoice_id: str | None = None) -> list[dict[str, Any]]:
        if invoice_id:
            ids = self._connection.execute(
                "SELECT id FROM finance.credit_notes WHERE tenant_id = %s AND invoice_id = %s ORDER BY number", (tenant_id, invoice_id)
            ).fetchall()
        else:
            ids = self._connection.execute(
                "SELECT id FROM finance.credit_notes WHERE tenant_id = %s ORDER BY credit_date DESC, number DESC", (tenant_id,)
            ).fetchall()
        return [self._credit_note(tenant_id, row[0]) for row in ids]

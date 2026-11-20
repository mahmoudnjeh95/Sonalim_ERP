from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.money import json_number, to_decimal
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.finance.domain.entities import Invoice, check_new_invoice_currency, status_for_payment, transition


_INVOICE_COLUMNS = (
    "id, partner_id, amount, amount_credited, amount_paid, currency, status, COALESCE(invoice_date, created_at::date), number, "
    "source_type, source_id, source_number, source_order_id, due_date, payment_term_code"
)


def _invoice_row(row) -> dict[str, Any]:
    total, credited, paid = row[2], row[3], row[4]
    due = max(total - credited, Decimal("0"))
    return {
        "id": row[0], "partner_id": row[1], "amount": due, "total": total, "amount_credited": credited, "amount_paid": paid,
        # Under one franc is settled (see status_for_payment), so it is not shown as still due.
        "remaining": due - paid if due - paid >= 1 else Decimal("0"),
        # A credit note can bring what is due below what was already paid: that is owed back to the customer.
        "customer_credit": paid - due if paid > due else Decimal("0"),
        "currency": row[5], "status": row[6], "invoice_date": row[7], "number": row[8], "source_type": row[9],
        "source_id": row[10], "source_number": row[11], "source_order_id": row[12],
        "due_date": row[13], "payment_term_code": row[14],
    }


class InvoiceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_draft_invoice(
        self,
        *,
        tenant_id: str,
        partner_id: str,
        amount: Decimal,
        currency: str = "XOF",
        source_order_id: str | None = None,
        actor_id: str | None = None,
    ) -> Invoice:
        from modules.finance.api.billing_service import INVOICE_PREFIX, next_number

        invoice_id = str(ULID())
        amount = to_decimal(amount)
        today = datetime.date.today()
        number = next_number(self._connection, tenant_id, INVOICE_PREFIX, today.year)
        self._connection.execute(
            """
            INSERT INTO finance.invoices (id, tenant_id, partner_id, amount, currency, status, source_order_id, number, invoice_date,
                                          source_type, source_id)
            VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s)
            """,
            (invoice_id, tenant_id, partner_id, amount, currency, source_order_id, number, today,
             "order" if source_order_id else None, source_order_id),
        )
        from modules.finance.api.payment_schedule import apply_customer_terms

        apply_customer_terms(self._connection, tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, invoice_date=today)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id or "system:event-consumer",
            action="invoice.created",
            entity_type="invoice",
            entity_id=invoice_id,
            payload={"partner_id": partner_id, "amount": json_number(amount), "currency": currency, "source_order_id": source_order_id},
        )
        return Invoice(id=invoice_id, partner_id=partner_id, amount=amount, currency=currency, status="draft")

    def list_invoices(self, tenant_id: str, status: str | None = None) -> list[Invoice]:
        if status is not None:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, amount, currency, status, amount_paid
                FROM finance.invoices
                WHERE tenant_id = %s AND status = %s
                ORDER BY id DESC
                """,
                (tenant_id, status),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, amount, currency, status, amount_paid
                FROM finance.invoices
                WHERE tenant_id = %s
                ORDER BY id DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [
            Invoice(
                id=invoice_id, partner_id=partner_id, amount=amount, currency=currency,
                status=invoice_status, amount_paid=amount_paid,
            )
            for invoice_id, partner_id, amount, currency, invoice_status, amount_paid in rows
        ]

    def get_invoice(self, *, tenant_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        """Public read for treasury: what a receipt needs to know before allocating to an invoice. `amount` is
        what is due, the invoiced total less credit notes; `total` is what was invoiced."""
        row = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM finance.invoices WHERE id = %s AND tenant_id = %s",
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"invoice {invoice_id} not found", f"facture {invoice_id} introuvable")
        return Ok(_invoice_row(row))

    def list_invoice_rows(self, *, tenant_id: str, status: str | None = None, source_order_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if source_order_id is not None:
            clauses.append("source_order_id = %s")
            params.append(source_order_id)
        rows = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM finance.invoices WHERE {' AND '.join(clauses)} ORDER BY id DESC", params
        ).fetchall()
        return [_invoice_row(row) for row in rows]

    def get_invoice_detail(self, *, tenant_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        """The invoice with its lines and credit notes, for the invoices screen."""
        from modules.finance.api.billing_service import DeliveryBillingService

        invoice = self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        if isinstance(invoice, Err):
            return invoice
        lines = self._connection.execute(
            "SELECT product_id, quantity, unit_price, amount, vat_rate, list_price, discount_rate FROM finance.invoice_lines "
            "WHERE invoice_id = %s ORDER BY id",
            (invoice_id,),
        ).fetchall()
        totals = self._connection.execute(
            "SELECT COALESCE(amount_excl_tax, amount), vat_amount FROM finance.invoices WHERE id = %s", (invoice_id,)
        ).fetchone()
        return Ok({
            **invoice.value,
            "amount_excl_tax": totals[0],
            "vat_amount": totals[1],
            "lines": [{"product_id": l[0], "quantity": l[1], "unit_price": l[2], "amount": l[3], "vat_rate": l[4], "list_price": l[5],
                       "discount_rate": l[6]} for l in lines],
            "credit_notes": DeliveryBillingService(self._connection).list_credit_notes(tenant_id=tenant_id, invoice_id=invoice_id),
        })

    def apply_payment_delta(
        self, *, tenant_id: str, actor_id: str, invoice_id: str, delta: Decimal, event_type: str, document_id: str
    ) -> Result[dict[str, Any]]:
        """Add (or, negative, take back) a paid amount and re-derive the status.

        Idempotent on (event_type, document_id, invoice_id): a replayed treasury event is a no-op.

        Ledger (D4): this path deliberately publishes no finance.invoice.paid. That event makes the
        ledger post a generic bank entry (invoice_ledger_service.post_paid); an invoice settled
        through treasury must instead be posted once, on the real cash/bank/mobile-money account,
        by the treasury ledger posting (B6). mark_paid refuses invoices that have treasury
        payments (INVOICE_HAS_PAYMENTS), so the two postings can never both fire."""
        already = self._connection.execute(
            "SELECT 1 FROM finance.invoice_payment_deltas WHERE event_type = %s AND document_id = %s AND invoice_id = %s",
            (event_type, document_id, invoice_id),
        ).fetchone()
        if already:
            return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        row = self._connection.execute(
            "SELECT amount - amount_credited, amount_paid, status FROM finance.invoices WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"invoice {invoice_id} not found", f"facture {invoice_id} introuvable")
        amount, amount_paid, status = row  # amount: what is due once credit notes are taken off
        if status in ("draft",):
            return Err("INVOICE_NOT_VALIDATED", "only an issued invoice can be paid", "seule une facture émise peut être payée")
        new_paid = amount_paid + delta
        if new_paid < 0 or new_paid > amount:
            return Err("OVER_ALLOCATION", f"payment {new_paid} is outside 0..{amount} for this invoice",
                       f"un paiement de {new_paid} sort de la plage 0..{amount} pour cette facture")
        new_status = status_for_payment(amount, new_paid)
        self._connection.execute(
            "UPDATE finance.invoices SET amount_paid = %s, status = %s WHERE id = %s", (new_paid, new_status, invoice_id)
        )
        self._connection.execute(
            "INSERT INTO finance.invoice_payment_deltas (event_type, document_id, invoice_id, amount) VALUES (%s, %s, %s, %s)",
            (event_type, document_id, invoice_id, delta),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="invoice.payment_applied",
            entity_type="invoice", entity_id=invoice_id,
            payload={"delta": str(delta), "amount_paid": str(new_paid), "status": new_status},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def admin_update_invoice(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        invoice_id: str,
        partner_id: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        due_date: datetime.date | None = None,
    ) -> Result[Invoice]:
        row = self._connection.execute(
            "SELECT partner_id, amount, currency, status FROM finance.invoices WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"invoice {invoice_id} not found", f"facture {invoice_id} introuvable")

        current_partner_id, current_amount, current_currency, status = row
        updated = Invoice(
            id=invoice_id,
            partner_id=partner_id if partner_id is not None else current_partner_id,
            amount=amount if amount is not None else current_amount,
            currency=currency if currency is not None else current_currency,
            status=status,
        )
        if updated.amount < 0:
            return Err("INVALID_AMOUNT", "amount cannot be negative", "le montant ne peut pas être négatif")
        if updated.currency != current_currency:
            currency_checked = check_new_invoice_currency(updated.currency)
            if isinstance(currency_checked, Err):
                return currency_checked

        self._connection.execute(
            "UPDATE finance.invoices SET partner_id = %s, amount = %s, currency = %s WHERE id = %s AND tenant_id = %s",
            (updated.partner_id, updated.amount, updated.currency, invoice_id, tenant_id),
        )
        from modules.finance.api import payment_schedule

        if due_date is not None:
            payment_schedule.set_single_due_date(self._connection, tenant_id=tenant_id, invoice_id=invoice_id, due_date=due_date)
        elif updated.partner_id != current_partner_id:
            # Another customer, another agreement: the new customer's terms apply.
            self._connection.execute("UPDATE finance.invoices SET payment_term_rule = NULL WHERE id = %s", (invoice_id,))
            payment_schedule.redate(self._connection, tenant_id=tenant_id, invoice_id=invoice_id)
        elif updated.amount != current_amount:
            payment_schedule.redate(self._connection, tenant_id=tenant_id, invoice_id=invoice_id)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="invoice.updated",
            entity_type="invoice",
            entity_id=invoice_id,
            payload={"partner_id": updated.partner_id, "amount": json_number(updated.amount), "currency": updated.currency,
                     "due_date": due_date.isoformat() if due_date else None},
        )
        return Ok(updated)

    def issue_invoice(self, *, tenant_id: str, actor_id: str, invoice_id: str, correlation_id: str) -> Result[Invoice]:
        return self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            invoice_id=invoice_id,
            new_status="issued",
            correlation_id=correlation_id,
            event_type="finance.invoice.issued",
        )

    def mark_paid(self, *, tenant_id: str, actor_id: str, invoice_id: str, correlation_id: str) -> Result[Invoice]:
        return self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            invoice_id=invoice_id,
            new_status="paid",
            correlation_id=correlation_id,
            event_type="finance.invoice.paid",
        )

    def _apply_transition(
        self, *, tenant_id: str, actor_id: str, invoice_id: str, new_status: str, correlation_id: str, event_type: str
    ) -> Result[Invoice]:
        row = self._connection.execute(
            """
            SELECT partner_id, amount, currency, status, amount_paid, vat_amount
            FROM finance.invoices
            WHERE id = %s AND tenant_id = %s
            FOR UPDATE
            """,
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"invoice {invoice_id} not found", f"facture {invoice_id} introuvable")

        partner_id, amount, currency, status, amount_paid, vat_amount = row
        if new_status == "paid" and amount_paid > 0:
            return Err(
                "INVOICE_HAS_PAYMENTS",
                "this invoice already has receipts allocated; its status follows them",
                "cette facture a déjà des encaissements ; son statut les suit",
            )
        current = Invoice(id=invoice_id, partner_id=partner_id, amount=amount, currency=currency, status=status)
        result = transition(current, new_status)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE finance.invoices SET status = %s, amount_paid = CASE WHEN %s::text = 'paid' THEN amount - amount_credited ELSE amount_paid END WHERE id = %s",
            (new_status, new_status, invoice_id),
        )
        publish_event(
            self._connection,
            event_type=event_type,
            producer="finance",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            # 1.1 (additive): the collected VAT inside `amount`
            event_version="1.1",
            payload={"invoice_id": invoice_id, "partner_id": partner_id, "amount": json_number(amount), "currency": currency,
                     "vat": json_number(vat_amount or 0)},
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=f"invoice.{new_status}",
            entity_type="invoice",
            entity_id=invoice_id,
            payload={"from_status": status, "to_status": new_status},
        )
        return result

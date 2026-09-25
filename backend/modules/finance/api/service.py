from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.finance.domain.entities import Invoice, transition


class InvoiceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_draft_invoice(
        self,
        *,
        tenant_id: str,
        partner_id: str,
        amount: float,
        currency: str = "XOF",
        source_order_id: str | None = None,
        actor_id: str | None = None,
    ) -> Invoice:
        invoice_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO finance.invoices (id, tenant_id, partner_id, amount, currency, status, source_order_id)
            VALUES (%s, %s, %s, %s, %s, 'draft', %s)
            """,
            (invoice_id, tenant_id, partner_id, amount, currency, source_order_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id or "system:event-consumer",
            action="invoice.created",
            entity_type="invoice",
            entity_id=invoice_id,
            payload={"partner_id": partner_id, "amount": amount, "currency": currency, "source_order_id": source_order_id},
        )
        return Invoice(id=invoice_id, partner_id=partner_id, amount=amount, currency=currency, status="draft")

    def list_invoices(self, tenant_id: str, status: str | None = None) -> list[Invoice]:
        if status is not None:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, amount, currency, status
                FROM finance.invoices
                WHERE tenant_id = %s AND status = %s
                ORDER BY id DESC
                """,
                (tenant_id, status),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, amount, currency, status
                FROM finance.invoices
                WHERE tenant_id = %s
                ORDER BY id DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [
            Invoice(id=invoice_id, partner_id=partner_id, amount=float(amount), currency=currency, status=invoice_status)
            for invoice_id, partner_id, amount, currency, invoice_status in rows
        ]

    def admin_update_invoice(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        invoice_id: str,
        partner_id: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
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
            amount=amount if amount is not None else float(current_amount),
            currency=currency if currency is not None else current_currency,
            status=status,
        )
        if updated.amount < 0:
            return Err("INVALID_AMOUNT", "amount cannot be negative", "le montant ne peut pas être négatif")

        self._connection.execute(
            "UPDATE finance.invoices SET partner_id = %s, amount = %s, currency = %s WHERE id = %s AND tenant_id = %s",
            (updated.partner_id, updated.amount, updated.currency, invoice_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="invoice.updated",
            entity_type="invoice",
            entity_id=invoice_id,
            payload={"partner_id": updated.partner_id, "amount": updated.amount, "currency": updated.currency},
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
            SELECT partner_id, amount, currency, status
            FROM finance.invoices
            WHERE id = %s AND tenant_id = %s
            FOR UPDATE
            """,
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"invoice {invoice_id} not found", f"facture {invoice_id} introuvable")

        partner_id, amount, currency, status = row
        current = Invoice(id=invoice_id, partner_id=partner_id, amount=float(amount), currency=currency, status=status)
        result = transition(current, new_status)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE finance.invoices SET status = %s WHERE id = %s",
            (new_status, invoice_id),
        )
        publish_event(
            self._connection,
            event_type=event_type,
            producer="finance",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"invoice_id": invoice_id, "partner_id": partner_id, "amount": float(amount), "currency": currency},
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

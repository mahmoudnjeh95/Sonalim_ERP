from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.procurement.domain.purchase_invoice import (
    PAYABLE_STATUSES,
    check_lines_total,
    check_payment_delta,
    check_transition,
    remaining,
    status_for_payment,
)

COLUMNS = (
    "id, number, partner_id, supplier_invoice_number, purchase_order_id, invoice_date, due_date, "
    "currency, amount, amount_paid, status, note, created_at, validated_at"
)


def _not_found(invoice_id: str) -> Err:
    return Err("NOT_FOUND", f"purchase invoice {invoice_id} not found", f"facture d'achat {invoice_id} introuvable")


def _to_dict(row: tuple) -> dict[str, Any]:
    (invoice_id, number, partner_id, supplier_number, po_id, invoice_date, due_date,
     currency, amount, amount_paid, status, note, created_at, validated_at) = row
    return {
        "id": invoice_id,
        "number": number,
        "partner_id": partner_id,
        "supplier_invoice_number": supplier_number,
        "purchase_order_id": po_id,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "currency": currency,
        "amount": amount,
        "amount_paid": amount_paid,
        "remaining": remaining(amount, amount_paid),
        "status": status,
        "note": note,
        "created_at": created_at,
        "validated_at": validated_at,
    }


class PurchaseInvoiceService:
    """Supplier invoices. Callers commit; this class only executes writes."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads -------------------------------------------------------------------------------

    def get_invoice(self, *, tenant_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_invoices WHERE id = %s AND tenant_id = %s",
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return _not_found(invoice_id)
        return Ok(_to_dict(row))

    def list_lines(self, *, tenant_id: str, invoice_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT id, description, quantity, unit_price
            FROM procurement.purchase_invoice_lines
            WHERE invoice_id = %s AND tenant_id = %s
            ORDER BY id
            """,
            (invoice_id, tenant_id),
        ).fetchall()
        return [{"id": r[0], "description": r[1], "quantity": r[2], "unit_price": r[3]} for r in rows]

    def list_invoices(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        partner_id: str | None = None,
        overdue: bool = False,
        today: datetime.date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if status:
            clauses.append("status = %s")
            params.append(status)
        if partner_id:
            clauses.append("partner_id = %s")
            params.append(partner_id)
        if overdue:
            clauses.append("status IN ('validated', 'partially_paid') AND due_date IS NOT NULL AND due_date < %s")
            params.append(today or datetime.date.today())
        rows = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_invoices WHERE {' AND '.join(clauses)} "
            "ORDER BY invoice_date DESC, id DESC",
            params,
        ).fetchall()
        return [_to_dict(r) for r in rows]

    # ---- writes ------------------------------------------------------------------------------

    def create_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        partner_id: str,
        supplier_invoice_number: str,
        invoice_date: datetime.date,
        amount: Decimal,
        currency: str = "XOF",
        due_date: datetime.date | None = None,
        purchase_order_id: str | None = None,
        note: str | None = None,
        lines: list[dict] | None = None,
    ) -> Result[dict[str, Any]]:
        lines = lines or []
        checked = self._check_lines(amount, lines)
        if isinstance(checked, Err):
            return checked
        if self._supplier_number_taken(tenant_id, partner_id, supplier_invoice_number, exclude_id=None):
            return _duplicate()

        invoice_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO procurement.purchase_invoices
                (id, tenant_id, partner_id, supplier_invoice_number, purchase_order_id, invoice_date,
                 due_date, currency, amount, note, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (invoice_id, tenant_id, partner_id, supplier_invoice_number, purchase_order_id, invoice_date,
             due_date, currency, amount, note, actor_id),
        )
        self._replace_lines(tenant_id, invoice_id, lines)
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.created",
            entity_type="purchase_invoice", entity_id=invoice_id,
            payload={"partner_id": partner_id, "amount": str(amount), "currency": currency},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def update_draft(self, *, tenant_id: str, actor_id: str, invoice_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("INVOICE_NOT_DRAFT", "only a draft purchase invoice can be edited", "seule une facture d'achat brouillon peut être modifiée")

        allowed = {"partner_id", "supplier_invoice_number", "purchase_order_id", "invoice_date", "due_date", "currency", "amount", "note"}
        values = {k: v for k, v in changes.items() if k in allowed}
        lines = changes.get("lines")
        amount = values.get("amount", current["amount"])
        if lines is not None:
            checked = self._check_lines(amount, lines)
        else:
            existing = self.list_lines(tenant_id=tenant_id, invoice_id=invoice_id)
            checked = self._check_lines(amount, existing)
        if isinstance(checked, Err):
            return checked
        partner_id = values.get("partner_id", current["partner_id"])
        supplier_number = values.get("supplier_invoice_number", current["supplier_invoice_number"])
        if self._supplier_number_taken(tenant_id, partner_id, supplier_number, exclude_id=invoice_id):
            return _duplicate()

        if values:
            assignments = ", ".join(f"{column} = %s" for column in values)
            self._connection.execute(
                f"UPDATE procurement.purchase_invoices SET {assignments} WHERE id = %s AND tenant_id = %s",
                [*values.values(), invoice_id, tenant_id],
            )
        if lines is not None:
            self._replace_lines(tenant_id, invoice_id, lines)
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.updated",
            entity_type="purchase_invoice", entity_id=invoice_id,
            payload={k: str(v) for k, v in values.items()},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def validate(self, *, tenant_id: str, actor_id: str, invoice_id: str, correlation_id: str) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        moved = check_transition(current["status"], "validated")
        if isinstance(moved, Err):
            return moved

        number = self._next_number(tenant_id, current["invoice_date"].year)
        self._connection.execute(
            "UPDATE procurement.purchase_invoices SET status = 'validated', number = %s, validated_at = NOW() "
            "WHERE id = %s AND tenant_id = %s",
            (number, invoice_id, tenant_id),
        )
        publish_event(
            self._connection, event_type="procurement.purchase_invoice.validated", producer="procurement",
            tenant_id=tenant_id, correlation_id=correlation_id,
            payload={
                "invoice_id": invoice_id,
                "partner_id": current["partner_id"],
                "amount": str(current["amount"]),
                "currency": current["currency"],
                "due_date": current["due_date"].isoformat() if current["due_date"] else None,
            },
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.validated",
            entity_type="purchase_invoice", entity_id=invoice_id, payload={"number": number},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def cancel(self, *, tenant_id: str, actor_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        moved = check_transition(current["status"], "cancelled")
        if isinstance(moved, Err):
            return moved
        if current["amount_paid"] > 0:
            return Err("INVOICE_HAS_PAYMENTS", "a purchase invoice with payments cannot be cancelled", "une facture d'achat avec des paiements ne peut pas être annulée")
        self._connection.execute(
            "UPDATE procurement.purchase_invoices SET status = 'cancelled' WHERE id = %s AND tenant_id = %s",
            (invoice_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.cancelled",
            entity_type="purchase_invoice", entity_id=invoice_id, payload={},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def apply_payment_delta(self, *, tenant_id: str, actor_id: str, invoice_id: str, delta: Decimal) -> Result[dict[str, Any]]:
        """Add (or, negative, take back) a paid amount and re-derive the status. Called by the
        treasury event consumer; a payment can only land on a validated/partially paid invoice."""
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        if delta > 0 and current["status"] not in PAYABLE_STATUSES:
            return Err("INVOICE_NOT_VALIDATED", "only a validated purchase invoice can be paid", "seule une facture d'achat validée peut être payée")
        if current["status"] in ("draft", "cancelled"):
            return Err("INVOICE_NOT_VALIDATED", "only a validated purchase invoice can be paid", "seule une facture d'achat validée peut être payée")
        new_paid = check_payment_delta(current["amount"], current["amount_paid"], delta)
        if isinstance(new_paid, Err):
            return new_paid
        new_status = status_for_payment(current["amount"], new_paid.value)
        self._connection.execute(
            "UPDATE procurement.purchase_invoices SET amount_paid = %s, status = %s WHERE id = %s AND tenant_id = %s",
            (new_paid.value, new_status, invoice_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.payment_applied",
            entity_type="purchase_invoice", entity_id=invoice_id,
            payload={"delta": str(delta), "amount_paid": str(new_paid.value), "status": new_status},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    # ---- helpers -----------------------------------------------------------------------------

    def _lock(self, tenant_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_invoices WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return _not_found(invoice_id)
        return _to_dict(row)  # type: ignore[return-value]

    def _check_lines(self, amount: Decimal, lines: list[dict]) -> Result[None]:
        return check_lines_total(
            Decimal(str(amount)),
            [(Decimal(str(line["quantity"])), Decimal(str(line["unit_price"]))) for line in lines],
        )

    def _replace_lines(self, tenant_id: str, invoice_id: str, lines: list[dict]) -> None:
        self._connection.execute(
            "DELETE FROM procurement.purchase_invoice_lines WHERE invoice_id = %s AND tenant_id = %s",
            (invoice_id, tenant_id),
        )
        for line in lines:
            self._connection.execute(
                "INSERT INTO procurement.purchase_invoice_lines (id, tenant_id, invoice_id, description, quantity, unit_price) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, invoice_id, line["description"], line["quantity"], line["unit_price"]),
            )

    def _supplier_number_taken(self, tenant_id: str, partner_id: str, number: str, *, exclude_id: str | None) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM procurement.purchase_invoices WHERE tenant_id = %s AND partner_id = %s "
            "AND supplier_invoice_number = %s AND (%s::text IS NULL OR id <> %s)",
            (tenant_id, partner_id, number, exclude_id, exclude_id),
        ).fetchone()
        return row is not None

    def _next_number(self, tenant_id: str, year: int) -> str:
        row = self._connection.execute(
            """
            INSERT INTO procurement.invoice_counters (tenant_id, year, last_number) VALUES (%s, %s, 1)
            ON CONFLICT (tenant_id, year) DO UPDATE SET last_number = procurement.invoice_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, year),
        ).fetchone()
        return f"FA-{year}-{row[0]:06d}"


def _duplicate() -> Err:
    return Err(
        "DUPLICATE_SUPPLIER_INVOICE",
        "this supplier already has an invoice with that number",
        "ce fournisseur a déjà une facture avec ce numéro",
    )

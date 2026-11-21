from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.tax_codes import TaxCodeService
from core.events.outbox import publish_event
from modules.procurement.domain.purchase_invoice import (
    DEFAULT_VAT_RATE,
    PAYABLE_STATUSES,
    ZERO,
    Line,
    OrderLineFacts,
    Totals,
    check_has_amount,
    check_line,
    check_new_invoice_currency,
    check_not_over_received,
    check_payment_delta,
    check_transition,
    compute_totals,
    match_warnings,
    remaining,
    status_for_payment,
    supplier_credit,
)

COLUMNS = (
    "id, number, partner_id, supplier_invoice_number, purchase_order_id, invoice_date, due_date, "
    "currency, amount, amount_paid, status, note, created_at, validated_at, "
    "total_gross, total_discount, total_excl_tax, total_vat, total_incl_tax, credited_amount"
)
LINE_COLUMNS = (
    "id, line_no, product_id, description, quantity, uom_id, unit_price, discount_rate, vat_rate, "
    "purchase_order_line_id, receipt_id"
)
HEADER_FIELDS = {"partner_id", "supplier_invoice_number", "purchase_order_id", "invoice_date", "due_date", "currency", "note"}
TWO_PLACES = Decimal("0.01")


def _not_found(invoice_id: str) -> Err:
    return Err("NOT_FOUND", f"purchase invoice {invoice_id} not found", f"facture d'achat {invoice_id} introuvable")


def _to_dict(row: tuple) -> dict[str, Any]:
    (invoice_id, number, partner_id, supplier_number, po_id, invoice_date, due_date, currency, amount, amount_paid,
     status, note, created_at, validated_at, gross, discount, excl, vat, incl, credited) = row
    return {
        "id": invoice_id,
        "number": number,
        "partner_id": partner_id,
        "supplier_invoice_number": supplier_number,
        "purchase_order_id": po_id,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "currency": currency,
        # What is due: the total including tax less validated credit notes.
        "amount": amount,
        "amount_paid": amount_paid,
        "remaining": remaining(amount, amount_paid),
        "supplier_credit": supplier_credit(amount, amount_paid),
        "status": status,
        "note": note,
        "created_at": created_at,
        "validated_at": validated_at,
        "total_gross": gross,
        "total_discount": discount,
        "total_excl_tax": excl,
        "total_vat": vat,
        "total_incl_tax": incl,
        "credited_amount": credited,
    }


def _line_dict(row: tuple) -> dict[str, Any]:
    keys = ["id", "line_no", "product_id", "description", "quantity", "uom_id", "unit_price", "discount_rate", "vat_rate",
            "purchase_order_line_id", "receipt_id"]
    line = dict(zip(keys, row, strict=True))
    amounts = Line(line["quantity"], line["unit_price"], line["discount_rate"], line["vat_rate"])
    line["total_excl_tax"] = amounts.net.quantize(TWO_PLACES)
    line["total_vat"] = amounts.vat.quantize(TWO_PLACES)
    line["total_incl_tax"] = (amounts.net + amounts.vat).quantize(TWO_PLACES)
    return line


def _duplicate() -> Err:
    return Err(
        "DUPLICATE_SUPPLIER_INVOICE",
        "this supplier already has an invoice with that number",
        "ce fournisseur a déjà une facture avec ce numéro",
    )


class PurchaseInvoiceService:
    """Supplier invoices. Callers commit; this class only executes writes."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- settings ----------------------------------------------------------------------------

    def default_vat_rate(self, *, tenant_id: str) -> Decimal:
        row = self._connection.execute(
            "SELECT default_vat_rate FROM procurement.invoice_settings WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        stored = row[0] if row else DEFAULT_VAT_RATE
        # The default is the tenant's default purchase tax code (core.tax_codes); the stored value is the
        # fallback and what the catalogue adopts the first time it is filled.
        code_rate = TaxCodeService(self._connection).default_rate(tenant_id=tenant_id, side="purchase", legacy_rate=stored)
        return code_rate if code_rate is not None else stored

    def set_default_vat_rate(self, *, tenant_id: str, actor_id: str, rate: Decimal) -> Result[dict[str, Any]]:
        if not ZERO <= rate <= Decimal("100"):
            return Err("INVALID_VAT_RATE", "a VAT rate is between 0 and 100 %", "un taux de TVA est compris entre 0 et 100 %")
        before = self.default_vat_rate(tenant_id=tenant_id)
        self._connection.execute(
            """
            INSERT INTO procurement.invoice_settings (tenant_id, default_vat_rate) VALUES (%s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET default_vat_rate = EXCLUDED.default_vat_rate, updated_at = NOW()
            """,
            (tenant_id, rate),
        )
        made_default = TaxCodeService(self._connection).set_default_rate(tenant_id=tenant_id, actor_id=actor_id, side="purchase", rate=rate)
        if isinstance(made_default, Err):
            return made_default
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.settings_changed",
                     entity_type="purchase_invoice_settings", entity_id=tenant_id,
                     payload={"default_vat_rate": {"from": str(before), "to": str(rate)}})
        return Ok({"default_vat_rate": rate})

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
            f"SELECT {LINE_COLUMNS} FROM procurement.purchase_invoice_lines WHERE invoice_id = %s AND tenant_id = %s "
            "ORDER BY line_no, id",
            (invoice_id, tenant_id),
        ).fetchall()
        return [_line_dict(r) for r in rows]

    def list_receipt_ids(self, *, tenant_id: str, invoice_id: str) -> list[str]:
        rows = self._connection.execute(
            "SELECT receipt_id FROM procurement.purchase_invoice_receipts WHERE invoice_id = %s AND tenant_id = %s ORDER BY receipt_id",
            (invoice_id, tenant_id),
        ).fetchall()
        return [r[0] for r in rows]

    def get_detail(self, *, tenant_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        """The invoice with its lines, the receipts it bills, its three-way-match warnings and credit notes."""
        invoice = self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        if isinstance(invoice, Err):
            return invoice
        from modules.procurement.api.credit_note_service import PurchaseCreditNoteService

        lines = self.list_lines(tenant_id=tenant_id, invoice_id=invoice_id)
        return Ok({
            **invoice.value,
            "lines": lines,
            "receipt_ids": self.list_receipt_ids(tenant_id=tenant_id, invoice_id=invoice_id),
            "warnings": self._warnings(tenant_id, invoice_id, lines) if invoice.value["status"] != "cancelled" else [],
            "credit_notes": PurchaseCreditNoteService(self._connection).list_credit_notes(tenant_id=tenant_id, invoice_id=invoice_id),
        })

    def list_invoices(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        partner_id: str | None = None,
        overdue: bool = False,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
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
        if date_from:
            clauses.append("invoice_date >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("invoice_date <= %s")
            params.append(date_to)
        if overdue:
            clauses.append("status IN ('validated', 'partially_paid') AND due_date IS NOT NULL AND due_date < %s")
            params.append(today or datetime.date.today())
        rows = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_invoices WHERE {' AND '.join(clauses)} "
            "ORDER BY invoice_date DESC, id DESC",
            params,
        ).fetchall()
        return [_to_dict(r) for r in rows]

    def invoiceable_receipts(self, *, tenant_id: str, partner_id: str | None = None) -> list[dict[str, Any]]:
        """Confirmed goods receipts with a quantity not yet invoiced, with that quantity per line."""
        rows = self._connection.execute(
            """
            SELECT r.id, r.purchase_order_id, o.supplier_id, r.confirmed_at, r.invoice_number,
                   rl.id, rl.purchase_order_line_id, pl.product_id, p.name, pl.uom_id, rl.quantity,
                   rl.quantity - COALESCE((
                       SELECT SUM(il.quantity) FROM procurement.purchase_invoice_lines il
                       JOIN procurement.purchase_invoices i ON i.id = il.invoice_id
                       WHERE il.receipt_id = r.id AND il.purchase_order_line_id = rl.purchase_order_line_id
                         AND i.status <> 'cancelled'), 0)
                   + COALESCE((
                       SELECT SUM(cl.quantity) FROM procurement.purchase_credit_note_lines cl
                       JOIN procurement.purchase_credit_notes c ON c.id = cl.credit_note_id AND c.status = 'validated'
                       JOIN procurement.purchase_invoice_lines il ON il.id = cl.invoice_line_id
                       WHERE il.receipt_id = r.id AND il.purchase_order_line_id = rl.purchase_order_line_id), 0),
                   CASE WHEN r.currency_code = 'XOF' AND r.base_cost > 0
                        THEN r.base_cost / NULLIF((SELECT SUM(x.quantity) FROM procurement.purchase_order_receipt_lines x
                                                   WHERE x.purchase_order_receipt_id = r.id), 0) END
            FROM procurement.purchase_order_receipts r
            JOIN procurement.purchase_orders o ON o.id = r.purchase_order_id
            JOIN procurement.purchase_order_receipt_lines rl ON rl.purchase_order_receipt_id = r.id
            JOIN procurement.purchase_order_lines pl ON pl.id = rl.purchase_order_line_id
            JOIN core.products p ON p.id = pl.product_id
            WHERE r.tenant_id = %s AND r.status = 'confirmed' AND (%s::text IS NULL OR o.supplier_id = %s)
            ORDER BY r.confirmed_at DESC NULLS LAST, r.id, rl.id
            """,
            (tenant_id, partner_id, partner_id),
        ).fetchall()
        receipts: dict[str, dict[str, Any]] = {}
        for (receipt_id, order_id, supplier_id, confirmed_at, invoice_number, line_id, po_line_id, product_id, product_name,
             uom_id, received, left, goods_price) in rows:
            if left <= 0:
                continue
            receipt = receipts.setdefault(receipt_id, {
                "receipt_id": receipt_id, "purchase_order_id": order_id, "supplier_id": supplier_id,
                "confirmed_at": confirmed_at, "supplier_document": invoice_number, "lines": [],
            })
            receipt["lines"].append({
                "receipt_line_id": line_id, "purchase_order_line_id": po_line_id, "product_id": product_id,
                "product_name": product_name, "uom_id": uom_id, "received": received, "to_invoice": left,
                # The receipt's goods value per unit, freight and customs excluded: what the supplier bills.
                "order_unit_price": goods_price,
            })
        return list(receipts.values())

    # ---- writes ------------------------------------------------------------------------------

    def create_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        partner_id: str,
        supplier_invoice_number: str,
        invoice_date: datetime.date,
        amount: Decimal | None = None,
        currency: str = "XOF",
        due_date: datetime.date | None = None,
        purchase_order_id: str | None = None,
        note: str | None = None,
        lines: list[dict] | None = None,
        receipt_ids: list[str] | None = None,
    ) -> Result[dict[str, Any]]:
        """`amount` alone (no lines) records a header-only invoice as one line without VAT, as before lines
        existed; given with lines it must equal their total including tax."""
        currency_checked = check_new_invoice_currency(currency)
        if isinstance(currency_checked, Err):
            return currency_checked
        if not supplier_invoice_number.strip():
            return Err("SUPPLIER_NUMBER_REQUIRED", "the supplier's invoice number is required",
                       "le numéro de facture du fournisseur est obligatoire")
        if due_date is not None and due_date < invoice_date:
            return Err("INVALID_DUE_DATE", "the due date cannot be before the invoice date",
                       "l'échéance ne peut pas précéder la date de la facture")
        if due_date is None:
            # Left blank, the due date follows the supplier's payment terms (a shared-kernel partner field).
            from core.payment_terms import PaymentTermService

            terms = PaymentTermService(self._connection)
            if terms.partner_terms(tenant_id=tenant_id, partner_id=partner_id)["supplier"] is not None:
                due_date = terms.schedule_for(tenant_id=tenant_id, partner_id=partner_id, side="supplier",
                                              invoice_date=invoice_date, amount=Decimal("1"))["due_date"]
        if not lines:
            if amount is None:
                return Err("LINES_REQUIRED", "an invoice needs at least one line", "une facture doit avoir au moins une ligne")
            lines = [{"description": note or f"Facture {supplier_invoice_number}", "quantity": 1, "unit_price": amount, "vat_rate": 0}]
        prepared = self._prepare_lines(tenant_id, partner_id, lines)
        if isinstance(prepared, Err):
            return prepared
        totals = self._totals(prepared.value, amount)
        if isinstance(totals, Err):
            return totals
        if self._supplier_number_taken(tenant_id, partner_id, supplier_invoice_number, exclude_id=None):
            return _duplicate()
        receipts = self._check_receipts(tenant_id, partner_id, receipt_ids or [])
        if isinstance(receipts, Err):
            return receipts

        invoice_id = str(ULID())
        t = totals.value
        self._connection.execute(
            """
            INSERT INTO procurement.purchase_invoices
                (id, tenant_id, partner_id, supplier_invoice_number, purchase_order_id, invoice_date, due_date, currency,
                 amount, note, created_by, total_gross, total_discount, total_excl_tax, total_vat, total_incl_tax)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (invoice_id, tenant_id, partner_id, supplier_invoice_number.strip(), purchase_order_id, invoice_date, due_date,
             currency, t.incl_tax, note, actor_id, t.gross, t.discount, t.excl_tax, t.vat, t.incl_tax),
        )
        self._replace_lines(tenant_id, invoice_id, prepared.value)
        self._replace_receipts(tenant_id, invoice_id, receipts.value)
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.created",
            entity_type="purchase_invoice", entity_id=invoice_id,
            payload={"partner_id": partner_id, "amount": str(t.incl_tax), "currency": currency, "lines": len(prepared.value)},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    @atomic
    def create_from_receipts(
        self, *, tenant_id: str, actor_id: str, receipt_ids: list[str], supplier_invoice_number: str,
        invoice_date: datetime.date, due_date: datetime.date | None = None, note: str | None = None,
    ) -> Result[dict[str, Any]]:
        """A draft billing what the chosen goods receipts brought in and no invoice has billed yet, priced at the
        goods value each receipt recorded per unit. A receipt with no goods value in F CFA leaves its prices
        at 0 for the user to enter; the draft can't be validated until its total is above zero."""
        if not receipt_ids:
            return Err("RECEIPTS_REQUIRED", "choose at least one goods receipt", "choisissez au moins un bon de réception")
        available = {r["receipt_id"]: r for r in self.invoiceable_receipts(tenant_id=tenant_id)}
        chosen = []
        for receipt_id in dict.fromkeys(receipt_ids):
            receipt = available.get(receipt_id)
            if receipt is None:
                return Err("RECEIPT_NOT_INVOICEABLE",
                           "this goods receipt is unknown, not confirmed or already fully invoiced",
                           "ce bon de réception est inconnu, non confirmé ou déjà entièrement facturé")
            chosen.append(receipt)
        suppliers = {r["supplier_id"] for r in chosen}
        if len(suppliers) != 1 or None in suppliers:
            return Err("RECEIPTS_OTHER_SUPPLIERS", "the goods receipts of one invoice come from one supplier",
                       "les bons de réception d'une facture viennent d'un seul fournisseur")
        orders = {r["purchase_order_id"] for r in chosen}
        default_vat = self.default_vat_rate(tenant_id=tenant_id)
        lines = []
        for receipt in chosen:
            for line in receipt["lines"]:
                price = line["order_unit_price"]
                lines.append({
                    "product_id": line["product_id"], "description": line["product_name"], "quantity": line["to_invoice"],
                    "uom_id": line["uom_id"], "unit_price": round(price, 4) if price is not None else 0, "discount_rate": 0,
                    "vat_rate": default_vat,
                    "purchase_order_line_id": line["purchase_order_line_id"], "receipt_id": receipt["receipt_id"],
                })
        return self.create_draft(
            tenant_id=tenant_id, actor_id=actor_id, partner_id=suppliers.pop(), supplier_invoice_number=supplier_invoice_number,
            invoice_date=invoice_date, due_date=due_date, note=note, lines=lines,
            purchase_order_id=orders.pop() if len(orders) == 1 else None, receipt_ids=[r["receipt_id"] for r in chosen],
        )

    def update_draft(self, *, tenant_id: str, actor_id: str, invoice_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("INVOICE_NOT_DRAFT", "only a draft purchase invoice can be edited", "seule une facture d'achat brouillon peut être modifiée")

        values = {k: v for k, v in changes.items() if k in HEADER_FIELDS}
        if "currency" in values and values["currency"] != current["currency"]:
            currency_checked = check_new_invoice_currency(values["currency"])
            if isinstance(currency_checked, Err):
                return currency_checked
        if "supplier_invoice_number" in values and not str(values["supplier_invoice_number"]).strip():
            return Err("SUPPLIER_NUMBER_REQUIRED", "the supplier's invoice number is required",
                       "le numéro de facture du fournisseur est obligatoire")
        invoice_date = values.get("invoice_date", current["invoice_date"])
        due_date = values.get("due_date", current["due_date"])
        if due_date is not None and due_date < invoice_date:
            return Err("INVALID_DUE_DATE", "the due date cannot be before the invoice date",
                       "l'échéance ne peut pas précéder la date de la facture")
        partner_id = values.get("partner_id", current["partner_id"])
        lines = changes.get("lines")
        amount = changes.get("amount")
        # Lines are rewritten only when they change, so their ids stay stable across header edits.
        rewrite_lines = lines is not None
        if lines is None:
            lines = self.list_lines(tenant_id=tenant_id, invoice_id=invoice_id)
            if amount is not None and len(lines) == 1 and lines[0]["quantity"] == 1 and lines[0]["vat_rate"] == 0 \
                    and lines[0]["discount_rate"] == 0 and not lines[0]["product_id"]:
                # A header-only invoice: its single line follows the new amount.
                lines = [{**lines[0], "unit_price": amount}]
                rewrite_lines = True
        prepared = self._prepare_lines(tenant_id, partner_id, lines)
        if isinstance(prepared, Err):
            return prepared
        totals = self._totals(prepared.value, amount)
        if isinstance(totals, Err):
            return totals
        supplier_number = values.get("supplier_invoice_number", current["supplier_invoice_number"])
        if self._supplier_number_taken(tenant_id, partner_id, supplier_number, exclude_id=invoice_id):
            return _duplicate()
        receipt_ids = changes.get("receipt_ids")
        if receipt_ids is not None or "partner_id" in values:
            receipts = self._check_receipts(
                tenant_id, partner_id,
                receipt_ids if receipt_ids is not None else self.list_receipt_ids(tenant_id=tenant_id, invoice_id=invoice_id))
            if isinstance(receipts, Err):
                return receipts
            self._replace_receipts(tenant_id, invoice_id, receipts.value)

        t = totals.value
        values.update({"amount": t.incl_tax, "total_gross": t.gross, "total_discount": t.discount,
                       "total_excl_tax": t.excl_tax, "total_vat": t.vat, "total_incl_tax": t.incl_tax})
        assignments = ", ".join(f"{column} = %s" for column in values)
        self._connection.execute(
            f"UPDATE procurement.purchase_invoices SET {assignments} WHERE id = %s AND tenant_id = %s",
            [*values.values(), invoice_id, tenant_id],
        )
        if rewrite_lines:
            self._replace_lines(tenant_id, invoice_id, prepared.value)
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.updated",
            entity_type="purchase_invoice", entity_id=invoice_id,
            payload={k: str(v) for k, v in values.items()},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def validate(self, *, tenant_id: str, actor_id: str, invoice_id: str, correlation_id: str,
                 may_exceed_receipts: bool = False) -> Result[dict[str, Any]]:
        """Numbers the invoice and sends it to the ledger. Billing more than the receipts brought in and no
        other invoice billed is refused unless the caller holds the dedicated permission."""
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        moved = check_transition(current["status"], "validated")
        if isinstance(moved, Err):
            return moved
        positive = check_has_amount(Totals(current["total_gross"], current["total_discount"], current["total_excl_tax"],
                                           current["total_vat"], current["total_incl_tax"]))
        if isinstance(positive, Err):
            return positive
        lines = self.list_lines(tenant_id=tenant_id, invoice_id=invoice_id)
        warnings = self._warnings(tenant_id, invoice_id, lines)
        allowed = check_not_over_received(warnings, may_override=may_exceed_receipts)
        if isinstance(allowed, Err):
            return allowed

        number = self._next_number(tenant_id, current["invoice_date"].year)
        self._connection.execute(
            "UPDATE procurement.purchase_invoices SET status = 'validated', number = %s, validated_at = NOW() "
            "WHERE id = %s AND tenant_id = %s",
            (number, invoice_id, tenant_id),
        )
        publish_event(
            self._connection, event_type="procurement.purchase_invoice.validated", producer="procurement",
            tenant_id=tenant_id, correlation_id=correlation_id, event_version="1.1",
            payload={
                "invoice_id": invoice_id,
                "number": number,
                "partner_id": current["partner_id"],
                "amount": str(current["total_incl_tax"]),
                "total_excl_tax": str(current["total_excl_tax"]),
                "total_vat": str(current["total_vat"]),
                # Excluding tax per product, so the ledger can use each product's purchase account.
                "lines": [{"product_id": line["product_id"], "net": str(line["total_excl_tax"])} for line in lines],
                "currency": current["currency"],
                "due_date": current["due_date"].isoformat() if current["due_date"] else None,
            },
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.validated",
            entity_type="purchase_invoice", entity_id=invoice_id,
            payload={"number": number, "warnings": [w["code"] for w in warnings], "override": bool(warnings) and may_exceed_receipts},
        )
        return self.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def cancel(self, *, tenant_id: str, actor_id: str, invoice_id: str, correlation_id: str | None = None) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        moved = check_transition(current["status"], "cancelled")
        if isinstance(moved, Err):
            return moved
        if current["amount_paid"] > 0:
            return Err("INVOICE_HAS_PAYMENTS", "a purchase invoice with payments cannot be cancelled", "une facture d'achat avec des paiements ne peut pas être annulée")
        has_notes = self._connection.execute(
            "SELECT 1 FROM procurement.purchase_credit_notes WHERE invoice_id = %s AND tenant_id = %s AND status <> 'cancelled'",
            (invoice_id, tenant_id),
        ).fetchone()
        if has_notes:
            return Err("INVOICE_HAS_CREDIT_NOTES", "a purchase invoice with credit notes cannot be cancelled",
                       "une facture d'achat avec des avoirs ne peut pas être annulée")
        self._connection.execute(
            "UPDATE procurement.purchase_invoices SET status = 'cancelled' WHERE id = %s AND tenant_id = %s",
            (invoice_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.cancelled",
            entity_type="purchase_invoice", entity_id=invoice_id, payload={"from_status": current["status"]},
        )
        if current["status"] != "draft":
            # Only a validated invoice reached the ledger; the ledger reverses its purchase entry.
            publish_event(
                self._connection, event_type="procurement.purchase_invoice.cancelled", producer="procurement",
                tenant_id=tenant_id, correlation_id=correlation_id or str(uuid4()),
                payload={"invoice_id": invoice_id, "partner_id": current["partner_id"], "amount": str(current["total_incl_tax"]),
                         "currency": current["currency"]},
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

    def apply_credit(self, *, tenant_id: str, invoice_id: str, credit: Decimal) -> Result[dict[str, Any]]:
        """Takes a validated credit note off what is due and re-derives the status. Called by the credit-note
        service in the same transaction; never more than the invoice's total including tax."""
        current = self._lock(tenant_id, invoice_id)
        if isinstance(current, Err):
            return current
        if current["status"] in ("draft", "cancelled"):
            return Err("INVOICE_NOT_VALIDATED", "a credit note applies to a validated purchase invoice",
                       "un avoir s'applique à une facture d'achat validée")
        credited = current["credited_amount"] + credit
        if credited > current["total_incl_tax"]:
            return Err("CREDIT_EXCEEDS_INVOICE",
                       f"credit notes can take at most {current['total_incl_tax'] - current['credited_amount']} off this invoice",
                       f"les avoirs peuvent retirer au plus {current['total_incl_tax'] - current['credited_amount']} de cette facture")
        amount = current["total_incl_tax"] - credited
        new_status = status_for_payment(amount, current["amount_paid"])
        self._connection.execute(
            "UPDATE procurement.purchase_invoices SET credited_amount = %s, amount = %s, status = %s WHERE id = %s AND tenant_id = %s",
            (credited, amount, new_status, invoice_id, tenant_id),
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

    def _prepare_lines(self, tenant_id: str, partner_id: str, lines: list[dict]) -> Result[list[dict[str, Any]]]:
        """Checks and fills each line: a product's name stands in for a missing description, a missing VAT
        rate is the tenant's default, an order line must belong to this supplier's orders."""
        if not lines:
            return Err("LINES_REQUIRED", "an invoice needs at least one line", "une facture doit avoir au moins une ligne")
        default_vat = None
        prepared = []
        for index, line in enumerate(lines, start=1):
            product_id = line.get("product_id") or None
            description = (line.get("description") or "").strip()
            if product_id:
                product = self._connection.execute(
                    "SELECT name, uom_id FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
                ).fetchone()
                if product is None:
                    return Err("NOT_FOUND", f"product {product_id} not found", f"produit {product_id} introuvable")
                description = description or product[0]
            vat_rate = line.get("vat_rate")
            if vat_rate is None:
                default_vat = default_vat if default_vat is not None else self.default_vat_rate(tenant_id=tenant_id)
                vat_rate = default_vat
            values = {
                "line_no": index,
                "product_id": product_id,
                "description": description,
                "quantity": Decimal(str(line["quantity"])),
                "uom_id": line.get("uom_id") or None,
                "unit_price": Decimal(str(line["unit_price"])),
                "discount_rate": Decimal(str(line.get("discount_rate") or 0)),
                "vat_rate": Decimal(str(vat_rate)),
                "purchase_order_line_id": line.get("purchase_order_line_id") or None,
                "receipt_id": line.get("receipt_id") or None,
            }
            checked = check_line(description=values["description"], product_id=product_id, quantity=values["quantity"],
                                 unit_price=values["unit_price"], discount_rate=values["discount_rate"], vat_rate=values["vat_rate"])
            if isinstance(checked, Err):
                return checked
            if values["purchase_order_line_id"]:
                owner = self._connection.execute(
                    "SELECT o.supplier_id FROM procurement.purchase_order_lines l JOIN procurement.purchase_orders o "
                    "ON o.id = l.purchase_order_id WHERE l.id = %s AND l.tenant_id = %s",
                    (values["purchase_order_line_id"], tenant_id),
                ).fetchone()
                if owner is None:
                    return Err("NOT_FOUND", "purchase order line not found", "ligne de commande introuvable")
                if owner[0] != partner_id:
                    return Err("ORDER_OF_ANOTHER_SUPPLIER", "this purchase order belongs to another supplier",
                               "cette commande appartient à un autre fournisseur")
            prepared.append(values)
        return Ok(prepared)

    @staticmethod
    def _totals(lines: list[dict[str, Any]], amount: Decimal | None) -> Result[Totals]:
        totals = compute_totals(Line(l["quantity"], l["unit_price"], l["discount_rate"], l["vat_rate"]) for l in lines)
        if amount is not None and abs(Decimal(str(amount)) - totals.incl_tax) >= 1:
            return Err(
                "TOTAL_MISMATCH",
                f"lines total {totals.incl_tax} including tax differs from invoice amount {amount}",
                f"le total TTC des lignes {totals.incl_tax} diffère du montant de la facture {amount}",
            )
        return Ok(totals)

    def _replace_lines(self, tenant_id: str, invoice_id: str, lines: list[dict[str, Any]]) -> None:
        self._connection.execute(
            "DELETE FROM procurement.purchase_invoice_lines WHERE invoice_id = %s AND tenant_id = %s",
            (invoice_id, tenant_id),
        )
        for line in lines:
            self._connection.execute(
                "INSERT INTO procurement.purchase_invoice_lines (id, tenant_id, invoice_id, line_no, product_id, description, "
                "quantity, uom_id, unit_price, discount_rate, vat_rate, purchase_order_line_id, receipt_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, invoice_id, line["line_no"], line["product_id"], line["description"], line["quantity"],
                 line["uom_id"], line["unit_price"], line["discount_rate"], line["vat_rate"], line["purchase_order_line_id"],
                 line["receipt_id"]),
            )

    def _check_receipts(self, tenant_id: str, partner_id: str, receipt_ids: list[str]) -> Result[list[str]]:
        receipt_ids = list(dict.fromkeys(receipt_ids))
        for receipt_id in receipt_ids:
            row = self._connection.execute(
                "SELECT r.status, o.supplier_id FROM procurement.purchase_order_receipts r JOIN procurement.purchase_orders o "
                "ON o.id = r.purchase_order_id WHERE r.id = %s AND r.tenant_id = %s",
                (receipt_id, tenant_id),
            ).fetchone()
            if row is None:
                return Err("NOT_FOUND", f"goods receipt {receipt_id} not found", f"bon de réception {receipt_id} introuvable")
            if row[0] != "confirmed":
                return Err("RECEIPT_NOT_CONFIRMED", "only a confirmed goods receipt can be invoiced",
                           "seul un bon de réception confirmé peut être facturé")
            if row[1] != partner_id:
                return Err("RECEIPTS_OTHER_SUPPLIERS", "the goods receipts of one invoice come from one supplier",
                           "les bons de réception d'une facture viennent d'un seul fournisseur")
        return Ok(receipt_ids)

    def _replace_receipts(self, tenant_id: str, invoice_id: str, receipt_ids: list[str]) -> None:
        self._connection.execute("DELETE FROM procurement.purchase_invoice_receipts WHERE invoice_id = %s AND tenant_id = %s",
                                 (invoice_id, tenant_id))
        for receipt_id in receipt_ids:
            self._connection.execute(
                "INSERT INTO procurement.purchase_invoice_receipts (invoice_id, receipt_id, tenant_id) VALUES (%s, %s, %s)",
                (invoice_id, receipt_id, tenant_id),
            )

    def _warnings(self, tenant_id: str, invoice_id: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        po_lines = {line["purchase_order_line_id"] for line in lines if line["purchase_order_line_id"]}
        facts: dict[str, OrderLineFacts] = {}
        for po_line in po_lines:
            row = self._connection.execute(
                """
                SELECT (SELECT SUM(r.base_cost * rl.quantity
                                   / NULLIF((SELECT SUM(x.quantity) FROM procurement.purchase_order_receipt_lines x
                                             WHERE x.purchase_order_receipt_id = r.id), 0)) / NULLIF(SUM(rl.quantity), 0)
                        FROM procurement.purchase_order_receipt_lines rl
                        JOIN procurement.purchase_order_receipts r ON r.id = rl.purchase_order_receipt_id
                        WHERE rl.purchase_order_line_id = l.id AND r.status = 'confirmed' AND r.currency_code = 'XOF' AND r.base_cost > 0),
                       COALESCE((SELECT SUM(rl.quantity) FROM procurement.purchase_order_receipt_lines rl
                                 JOIN procurement.purchase_order_receipts r ON r.id = rl.purchase_order_receipt_id AND r.status = 'confirmed'
                                 WHERE rl.purchase_order_line_id = l.id), 0),
                       COALESCE((SELECT SUM(il.quantity) FROM procurement.purchase_invoice_lines il
                                 JOIN procurement.purchase_invoices i ON i.id = il.invoice_id AND i.status <> 'cancelled'
                                 WHERE il.purchase_order_line_id = l.id AND il.invoice_id <> %s), 0)
                       - COALESCE((SELECT SUM(cl.quantity) FROM procurement.purchase_credit_note_lines cl
                                   JOIN procurement.purchase_credit_notes c ON c.id = cl.credit_note_id AND c.status = 'validated'
                                   JOIN procurement.purchase_invoice_lines il ON il.id = cl.invoice_line_id
                                   WHERE il.purchase_order_line_id = l.id AND il.invoice_id <> %s), 0)
                FROM procurement.purchase_order_lines l WHERE l.id = %s AND l.tenant_id = %s
                """,
                (invoice_id, invoice_id, po_line, tenant_id),
            ).fetchone()
            if row is None:
                continue
            goods_price, received, invoiced = row
            facts[po_line] = OrderLineFacts(
                received=Decimal(str(received)), invoiced_elsewhere=Decimal(str(invoiced)),
                order_unit_price=Decimal(str(goods_price)) if goods_price is not None else None,
            )
        return match_warnings(
            [(line["id"], line["purchase_order_line_id"], line["quantity"], line["unit_price"]) for line in lines], facts
        )

    def _supplier_number_taken(self, tenant_id: str, partner_id: str, number: str, *, exclude_id: str | None) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM procurement.purchase_invoices WHERE tenant_id = %s AND partner_id = %s "
            "AND supplier_invoice_number = %s AND (%s::text IS NULL OR id <> %s)",
            (tenant_id, partner_id, number.strip(), exclude_id, exclude_id),
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


def apply_document_delta(
    connection: psycopg.Connection, *, tenant_id: str, actor_id: str, invoice_id: str, delta: Decimal,
    event_type: str, document_id: str,
) -> Result[dict[str, Any]]:
    """`apply_payment_delta` made idempotent on (event_type, document_id, invoice_id), so a replayed
    treasury event never counts a disbursement twice."""
    already = connection.execute(
        "SELECT 1 FROM procurement.invoice_payment_deltas WHERE event_type = %s AND document_id = %s AND invoice_id = %s",
        (event_type, document_id, invoice_id),
    ).fetchone()
    service = PurchaseInvoiceService(connection)
    if already:
        return service.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    result = service.apply_payment_delta(tenant_id=tenant_id, actor_id=actor_id, invoice_id=invoice_id, delta=delta)
    if isinstance(result, Err):
        return result
    connection.execute(
        "INSERT INTO procurement.invoice_payment_deltas (event_type, document_id, invoice_id, amount) VALUES (%s, %s, %s, %s)",
        (event_type, document_id, invoice_id, delta),
    )
    return result

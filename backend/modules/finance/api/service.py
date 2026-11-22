from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.money import json_number, to_decimal
from core.domain.result import Err, Ok, Result
from core.domain.tax import breakdown_payload, vat_breakdown
from core.events.outbox import publish_event
from core.tax_codes import resolve_lines
from modules.finance.domain.billing import ManualLine, check_manual_lines, document_totals
from modules.finance.domain.entities import Invoice, check_new_invoice_currency, status_for_payment, transition


_INVOICE_COLUMNS = (
    "id, partner_id, amount, amount_credited, amount_paid, currency, status, COALESCE(invoice_date, created_at::date), number, "
    "source_type, source_id, source_number, source_order_id, due_date, payment_term_code"
)


LUMP_SUM_DESCRIPTION = "Montant global / Lump sum"


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

        # A single amount is one lump-sum line without VAT, so every invoice is made of lines.
        self._connection.execute("UPDATE finance.invoices SET amount_excl_tax = %s WHERE id = %s", (amount, invoice_id))
        self._connection.execute(
            "INSERT INTO finance.invoice_lines (id, tenant_id, invoice_id, product_id, description, quantity, unit_price, amount, vat_rate) "
            "VALUES (%s, %s, %s, NULL, %s, 1, %s, %s, 0)",
            (str(ULID()), tenant_id, invoice_id, LUMP_SUM_DESCRIPTION, amount, amount),
        )
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

    # ---- lines ------------------------------------------------------------------------------

    def _default_sales_rate(self, tenant_id: str) -> Decimal:
        """The rate a line takes when neither it, its customer nor its product names a tax code: the sales
        settings' default VAT rate, as on sales orders (0 when the sales module is not installed)."""
        try:
            from modules.sales.api.pricing_service import PricingService
        except ImportError:  # sales is an optional dependency
            return Decimal("0")
        return Decimal(str(PricingService(self._connection).get_settings(tenant_id=tenant_id)["default_vat_rate"]))

    def _parse_lines(self, tenant_id: str, partner_id: str, raw: list[dict[str, Any]]) -> Result[list[ManualLine]]:
        """Lines as the API gives them. Each line's tax code and rate come from core.tax_codes (`resolve_lines`):
        the line's own `tax_code` or `vat_rate`, else the customer's code, the product's code, then the default
        sales rate. The code and its rate are copied onto the line, so the VAT register and the ledger see them."""
        for number, line in enumerate(raw, start=1):
            product_id = line.get("product_id") or None
            if product_id and not self._connection.execute(
                    "SELECT 1 FROM core.products WHERE tenant_id = %s AND id = %s", (tenant_id, product_id)).fetchone():
                return Err("NOT_FOUND", f"line {number}: product {product_id} not found", f"ligne {number} : produit {product_id} introuvable")
        taxes = resolve_lines(
            self._connection, tenant_id=tenant_id, side="sales", partner_id=partner_id,
            default_rate=self._default_sales_rate(tenant_id),
            lines=[{"product_id": line.get("product_id") or None, "tax_code": line.get("tax_code") or None,
                    "vat_rate": line.get("vat_rate")} for line in raw],
        )
        if isinstance(taxes, Err):
            return taxes
        parsed = [
            ManualLine(
                product_id=line.get("product_id") or None, description=(line.get("description") or "").strip() or None,
                quantity=to_decimal(line.get("quantity", 1)), list_price=to_decimal(line.get("unit_price", 0)),
                discount_rate=to_decimal(line.get("discount_rate") or 0), vat_rate=to_decimal(tax.rate), tax_code=tax.tax_code)
            for line, tax in zip(raw, taxes.value)
        ]
        return check_manual_lines(parsed)

    def _write_lines(self, tenant_id: str, invoice_id: str, lines: list[ManualLine]) -> None:
        """Replaces the invoice's lines and sets its totals: excluding tax, VAT and what the customer owes."""
        self._connection.execute("DELETE FROM finance.invoice_lines WHERE invoice_id = %s", (invoice_id,))
        for number, line in enumerate(lines, start=1):
            billed = line.billed()
            self._connection.execute(
                "INSERT INTO finance.invoice_lines (id, tenant_id, invoice_id, product_id, description, quantity, unit_price, amount, "
                "vat_rate, list_price, discount_rate, line_no, tax_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, invoice_id, line.product_id, line.description, line.quantity, line.net_unit_price,
                 billed.amount, line.vat_rate, line.list_price, line.discount_rate, number, line.tax_code),
            )
        excl, vat, incl = document_totals(line.billed() for line in lines)
        self._connection.execute(
            "UPDATE finance.invoices SET amount = %s, amount_excl_tax = %s, vat_amount = %s WHERE id = %s", (incl, excl, vat, invoice_id))

    def create_invoice(self, *, tenant_id: str, actor_id: str, partner_id: str, lines: list[dict[str, Any]],
                       invoice_date: datetime.date | None = None, currency: str = "XOF") -> Result[dict[str, Any]]:
        """A draft invoice typed in by hand: priced lines with discount and VAT, numbered, and dated from the
        customer's payment terms."""
        from modules.finance.api.billing_service import INVOICE_PREFIX, next_number
        from modules.finance.api.payment_schedule import apply_customer_terms

        currency_checked = check_new_invoice_currency(currency)
        if isinstance(currency_checked, Err):
            return currency_checked
        if not self._connection.execute("SELECT 1 FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone():
            return Err("NOT_FOUND", f"customer {partner_id} not found", f"client {partner_id} introuvable")
        parsed = self._parse_lines(tenant_id, partner_id, lines)
        if isinstance(parsed, Err):
            return parsed
        invoice_id, day = str(ULID()), invoice_date or datetime.date.today()
        self._connection.execute(
            "INSERT INTO finance.invoices (id, tenant_id, partner_id, amount, currency, status, number, invoice_date) "
            "VALUES (%s, %s, %s, 0, %s, 'draft', %s, %s)",
            (invoice_id, tenant_id, partner_id, currency, next_number(self._connection, tenant_id, INVOICE_PREFIX, day.year), day),
        )
        self._write_lines(tenant_id, invoice_id, parsed.value)
        apply_customer_terms(self._connection, tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, invoice_date=day)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="invoice.created", entity_type="invoice",
                     entity_id=invoice_id, payload={"partner_id": partner_id, "lines": len(parsed.value), "invoice_date": day.isoformat()})
        return self.get_invoice_detail(tenant_id=tenant_id, invoice_id=invoice_id)

    def replace_lines(self, *, tenant_id: str, actor_id: str, invoice_id: str, lines: list[dict[str, Any]],
                      invoice_date: datetime.date | None = None) -> Result[dict[str, Any]]:
        """Re-types a draft invoice's lines (and, if given, its date). An issued invoice is a legal document and
        is changed only by a credit note."""
        from modules.finance.api import payment_schedule

        row = self._connection.execute("SELECT status, partner_id FROM finance.invoices WHERE id = %s AND tenant_id = %s FOR UPDATE",
                                       (invoice_id, tenant_id)).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"invoice {invoice_id} not found", f"facture {invoice_id} introuvable")
        if row[0] != "draft":
            return Err("INVOICE_NOT_DRAFT", "only a draft invoice can be edited", "seule une facture brouillon peut être modifiée")
        parsed = self._parse_lines(tenant_id, row[1], lines)
        if isinstance(parsed, Err):
            return parsed
        self._write_lines(tenant_id, invoice_id, parsed.value)
        if invoice_date is not None:
            self._connection.execute("UPDATE finance.invoices SET invoice_date = %s WHERE id = %s", (invoice_date, invoice_id))
        payment_schedule.redate(self._connection, tenant_id=tenant_id, invoice_id=invoice_id)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="invoice.lines_replaced", entity_type="invoice",
                     entity_id=invoice_id, payload={"lines": len(parsed.value), "invoice_date": invoice_date.isoformat() if invoice_date else None})
        return self.get_invoice_detail(tenant_id=tenant_id, invoice_id=invoice_id)

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
            "SELECT product_id, quantity, unit_price, amount, vat_rate, list_price, discount_rate, tax_code, description "
            "FROM finance.invoice_lines WHERE invoice_id = %s ORDER BY line_no NULLS LAST, id",
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
                       "discount_rate": l[6], "tax_code": l[7], "description": l[8]} for l in lines],
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
        if updated.amount != current_amount:
            # The total comes from the lines. A lump-sum invoice (one line without product) moves its line with it;
            # one with real lines is edited through its lines (draft) or a credit note.
            lump = self._connection.execute(
                "SELECT count(*), count(*) FILTER (WHERE product_id IS NULL AND vat_rate = 0) FROM finance.invoice_lines WHERE invoice_id = %s",
                (invoice_id,)).fetchone()
            if lump[0] > 1 or (lump[0] == 1 and lump[1] == 0):
                return Err("AMOUNT_FROM_LINES", "this invoice's total comes from its lines; edit the lines (draft) or issue a credit note",
                           "le total de cette facture vient de ses lignes ; modifiez les lignes (brouillon) ou émettez un avoir")
        if updated.currency != current_currency:
            currency_checked = check_new_invoice_currency(updated.currency)
            if isinstance(currency_checked, Err):
                return currency_checked

        self._connection.execute(
            "UPDATE finance.invoices SET partner_id = %s, amount = %s, currency = %s WHERE id = %s AND tenant_id = %s",
            (updated.partner_id, updated.amount, updated.currency, invoice_id, tenant_id),
        )
        from modules.finance.api import payment_schedule

        if updated.amount != current_amount:
            self._connection.execute(
                "UPDATE finance.invoice_lines SET unit_price = %s, amount = %s WHERE invoice_id = %s", (updated.amount, updated.amount, invoice_id))
            self._connection.execute("UPDATE finance.invoices SET amount_excl_tax = %s WHERE id = %s", (updated.amount, invoice_id))
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
        if new_status == "issued" and not self._connection.execute(
                "SELECT 1 FROM finance.invoice_lines WHERE invoice_id = %s LIMIT 1", (invoice_id,)).fetchone():
            return Err("INVOICE_EMPTY", "an invoice needs at least one line before it is issued",
                       "une facture a besoin d'au moins une ligne avant d'être émise")
        current = Invoice(id=invoice_id, partner_id=partner_id, amount=amount, currency=currency, status=status)
        result = transition(current, new_status)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE finance.invoices SET status = %s, amount_paid = CASE WHEN %s::text = 'paid' THEN amount - amount_credited ELSE amount_paid END WHERE id = %s",
            (new_status, new_status, invoice_id),
        )
        payload = {"invoice_id": invoice_id, "partner_id": partner_id, "amount": json_number(amount), "currency": currency,
                   "vat": json_number(vat_amount or 0)}
        if event_type == "finance.invoice.issued":
            lines = self._connection.execute(
                "SELECT tax_code, vat_rate, amount FROM finance.invoice_lines WHERE invoice_id = %s", (invoice_id,)
            ).fetchall()
            # An invoice without lines (billed whole from an order before deliveries were billed) has no split.
            payload["vat_breakdown"] = breakdown_payload(vat_breakdown(lines)) if lines else []
        publish_event(
            self._connection,
            event_type=event_type,
            producer="finance",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            # 1.1 (additive): the collected VAT inside `amount`; 1.2 (issued only): its split per tax code
            event_version="1.2" if event_type == "finance.invoice.issued" else "1.1",
            payload=payload,
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

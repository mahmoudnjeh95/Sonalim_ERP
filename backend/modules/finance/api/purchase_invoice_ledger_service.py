"""Purchase invoices into the ledger: the purchase entry when procurement validates an invoice, its
reversal when a validated invoice is cancelled, and the mirror entry of a validated credit note.

Posted like sales invoices (always on, not behind the treasury switch): the account numbers come from
the `purchase_invoice / validated` and `purchase_invoice / vat` posting rules, never from this file, except
that a line whose product names its own purchase account (core.products.accounting_code_purchase) posts
there. The amounts, supplier and currency come from the event payload; procurement's public service is
read only to skip an invoice cancelled since, so the retry of a refused posting never books an invoice that
no longer exists."""
from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.api.tax_register_service import TaxRegisterService, allocated_parts
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import purchase_invoice_entry, to_xof

PROCUREMENT_MODULE = "procurement"
KIND_VALIDATED = "purchase_invoice_validated"
KIND_CREDIT_NOTE = "purchase_credit_note_validated"


class PurchaseInvoiceLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)

    def _is_cancelled(self, tenant_id: str, invoice_id: str) -> bool:
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        invoice = PurchaseInvoiceService(self._connection).get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        return isinstance(invoice, Ok) and invoice.value["status"] == "cancelled"

    def _account_lines(self, tenant_id: str, lines: list[dict] | None) -> list[tuple[str | None, Decimal]]:
        """(product's purchase account or None, value excluding tax) for each line of the payload."""
        if not lines:
            return []
        product_ids = sorted({str(line["product_id"]) for line in lines if line.get("product_id")})
        accounts: dict[str, str] = {}
        if product_ids:
            rows = self._connection.execute(
                "SELECT id, accounting_code_purchase FROM core.products WHERE tenant_id = %s AND id = ANY(%s)",
                (tenant_id, product_ids),
            ).fetchall()
            accounts = {pid: code.strip() for pid, code in rows if code and code.strip()}
        return [(accounts.get(str(line.get("product_id"))), Decimal(str(line["net"]))) for line in lines]

    def _post(self, *, tenant_id: str, source: SourceRef, label: str, reference: str, partner_id: str, amount: object,
              vat: object, lines: list[dict] | None, currency: str, entry_date: datetime.date, correlation_id: str,
              causation_id: str | None, mirror: bool, vat_breakdown: object = None) -> Result[list[dict]]:
        xof = to_xof(amount, currency=currency)
        if isinstance(xof, Err):
            return xof
        vat_amount = Decimal("0")
        if vat and Decimal(str(vat)) != 0:
            vat_xof = to_xof(vat, currency=currency)
            if isinstance(vat_xof, Err):
                return vat_xof
            vat_amount = vat_xof.value
        parts = allocated_parts(vat_breakdown, amount=xof.value, vat=vat_amount)
        entry = purchase_invoice_entry(
            amount=xof.value, vat=vat_amount, partner_id=partner_id, label=label, mirror=mirror,
            lines=self._account_lines(tenant_id, lines), rules=self._rules.rules_for(tenant_id=tenant_id, source="purchase_invoice"),
            vat_lines=[(part.tax_code, part.vat) for part in parts],
        )
        if isinstance(entry, Err):
            return entry
        journal_code, entry_lines = entry.value
        posted = self._posting.post_entry(
            tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, journal_code=journal_code, entry_date=entry_date, label=label,
            lines=entry_lines, correlation_id=correlation_id, source=source, reference=reference, causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        TaxRegisterService(self._connection).record(
            tenant_id=tenant_id, source_rule="purchase_invoice", source=source, entry=posted.value,
            entry_date=posted.value.get("entry_date") or entry_date, parts=parts, sign=-1 if mirror else 1,
            partner_id=partner_id, reference=reference,
        )
        return Ok([posted.value])

    def post_validated(
        self, *, tenant_id: str, invoice_id: str, partner_id: str, amount: object, currency: str,
        validated_on: datetime.date, correlation_id: str, causation_id: str | None = None,
        vat: object = 0, lines: list[dict] | None = None, number: str | None = None, vat_breakdown: object = None,
    ) -> Result[list[dict]]:
        source = SourceRef(PROCUREMENT_MODULE, invoice_id, KIND_VALIDATED)
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        if self._is_cancelled(tenant_id, invoice_id):
            # Cancelled since (a late delivery, or the retry of a refused posting): the cancellation found
            # nothing to reverse, so posting now would never be undone.
            return Ok([])
        return self._post(
            tenant_id=tenant_id, source=source, label=f"Facture d'achat {number or invoice_id}", reference=number or invoice_id,
            partner_id=partner_id, amount=amount, vat=vat, lines=lines, currency=currency, entry_date=validated_on,
            correlation_id=correlation_id, causation_id=causation_id, mirror=False, vat_breakdown=vat_breakdown,
        )

    def post_credit_note(
        self, *, tenant_id: str, credit_note_id: str, partner_id: str, amount: object, vat: object, lines: list[dict] | None,
        currency: str, validated_on: datetime.date, correlation_id: str, causation_id: str | None = None,
        number: str | None = None, vat_breakdown: object = None,
    ) -> Result[list[dict]]:
        """The purchase entry turned around: the supplier is debited, purchases and VAT are credited."""
        source = SourceRef(PROCUREMENT_MODULE, credit_note_id, KIND_CREDIT_NOTE)
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        return self._post(
            tenant_id=tenant_id, source=source, label=f"Avoir fournisseur {number or credit_note_id}",
            reference=number or credit_note_id, partner_id=partner_id, amount=amount, vat=vat, lines=lines, currency=currency,
            entry_date=validated_on, correlation_id=correlation_id, causation_id=causation_id, mirror=True,
            vat_breakdown=vat_breakdown,
        )

    def post_cancelled(
        self, *, tenant_id: str, invoice_id: str, cancelled_on: datetime.date, correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """Reverses the purchase entry; an invoice whose entry was never posted is a no-op."""
        original = self._posting.find_by_source(tenant_id=tenant_id, source=SourceRef(PROCUREMENT_MODULE, invoice_id, KIND_VALIDATED))
        if original is None or original["status"] != "posted":
            return Ok([])
        done = self._posting.reverse_entry(
            tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, entry_id=original["id"], entry_date=cancelled_on,
            correlation_id=correlation_id, causation_id=causation_id,
        )
        if isinstance(done, Err):
            return done
        TaxRegisterService(self._connection).record_reversal(
            tenant_id=tenant_id, original=SourceRef(PROCUREMENT_MODULE, invoice_id, KIND_VALIDATED),
            reversal=SourceRef(PROCUREMENT_MODULE, invoice_id, "purchase_invoice_cancelled"), entry=done.value,
            entry_date=done.value.get("entry_date") or cancelled_on,
        )
        return Ok([done.value])

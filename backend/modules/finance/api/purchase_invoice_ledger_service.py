"""Purchase invoices into the ledger: the purchase entry when procurement validates an invoice, its
reversal when a validated invoice is cancelled.

Posted like sales invoices (always on, not behind the treasury switch): the account numbers come from
the `purchase_invoice / validated` posting rule, never from this file. The amount, supplier and currency
come from the event payload; procurement's public service is read only to skip an invoice cancelled
since, so the retry of a refused posting never books an invoice that no longer exists."""
from __future__ import annotations

import datetime

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import purchase_invoice_entry, to_xof

PROCUREMENT_MODULE = "procurement"
KIND_VALIDATED = "purchase_invoice_validated"


class PurchaseInvoiceLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)

    def _is_cancelled(self, tenant_id: str, invoice_id: str) -> bool:
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        invoice = PurchaseInvoiceService(self._connection).get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        return isinstance(invoice, Ok) and invoice.value["status"] == "cancelled"

    def post_validated(
        self, *, tenant_id: str, invoice_id: str, partner_id: str, amount: object, currency: str,
        validated_on: datetime.date, correlation_id: str, causation_id: str | None = None,
    ) -> Result[list[dict]]:
        source = SourceRef(PROCUREMENT_MODULE, invoice_id, KIND_VALIDATED)
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        if self._is_cancelled(tenant_id, invoice_id):
            # Cancelled since (a late delivery, or the retry of a refused posting): the cancellation found
            # nothing to reverse, so posting now would never be undone.
            return Ok([])
        xof = to_xof(amount, currency=currency)
        if isinstance(xof, Err):
            return xof
        label = f"Facture d'achat {invoice_id}"
        entry = purchase_invoice_entry(
            amount=xof.value, partner_id=partner_id, label=label,
            rules=self._rules.rules_for(tenant_id=tenant_id, source="purchase_invoice"),
        )
        if isinstance(entry, Err):
            return entry
        journal_code, lines = entry.value
        posted = self._posting.post_entry(
            tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, journal_code=journal_code, entry_date=validated_on, label=label,
            lines=lines, correlation_id=correlation_id, source=source, reference=invoice_id, causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        return Ok([posted.value])

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
        return Ok([done.value])

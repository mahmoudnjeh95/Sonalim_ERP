"""Invoices into the ledger: the VTE entry when an invoice is issued, the bank entry when it is paid.

Only the event payload is used, so editing an invoice after it was issued does not change what
was posted; a correction is a manual OD entry."""
from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import invoice_entry, to_xof

INVOICE_MODULE = "finance"
LABELS = {"issued": "Facture {invoice_id}", "paid": "Règlement facture {invoice_id}", "credit_note": "Avoir {invoice_id}"}


class InvoiceLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)

    def post_issued(
        self,
        *,
        tenant_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        issued_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
        vat: object = 0,
    ) -> Result[list[dict]]:
        return self._post(
            "issued", tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, amount=amount,
            currency=currency, entry_date=issued_on, correlation_id=correlation_id, causation_id=causation_id, vat=vat,
        )

    def post_paid(
        self,
        *,
        tenant_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        paid_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        issued = SourceRef(INVOICE_MODULE, invoice_id, "invoice_issued")
        if self._posting.find_by_source(tenant_id=tenant_id, source=issued) is None:
            return Err(
                "INVOICE_NOT_POSTED",
                f"invoice {invoice_id} has no posted sales entry yet, so its payment cannot clear the customer",
                f"la facture {invoice_id} n'a pas encore d'écriture de vente comptabilisée ; son règlement ne peut pas solder le client",
            )
        return self._post(
            "paid", tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, amount=amount,
            currency=currency, entry_date=paid_on, correlation_id=correlation_id, causation_id=causation_id,
        )

    def post_credit_note(
        self,
        *,
        tenant_id: str,
        credit_note_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        number: str | None,
        credited_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
        vat: object = 0,
    ) -> Result[list[dict]]:
        """The mirror of the invoice's VTE entry for what a credit note took back. Like a payment, it waits
        for the invoice's own entry: an invoice still in draft has charged the customer nothing yet."""
        issued = SourceRef(INVOICE_MODULE, invoice_id, "invoice_issued")
        if self._posting.find_by_source(tenant_id=tenant_id, source=issued) is None:
            return Err(
                "INVOICE_NOT_POSTED",
                f"invoice {invoice_id} has no posted sales entry yet, so its credit note cannot reverse it",
                f"la facture {invoice_id} n'a pas encore d'écriture de vente comptabilisée ; son avoir ne peut pas l'annuler",
            )
        return self._post(
            "credit_note", tenant_id=tenant_id, invoice_id=credit_note_id, partner_id=partner_id, amount=amount,
            currency=currency, entry_date=credited_on, correlation_id=correlation_id, causation_id=causation_id,
            label_ref=number or credit_note_id, vat=vat,
        )

    def _post(
        self,
        kind: str,
        *,
        tenant_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        entry_date: datetime.date,
        correlation_id: str,
        causation_id: str | None,
        label_ref: str | None = None,
        vat: object = 0,
    ) -> Result[list[dict]]:
        source = SourceRef(INVOICE_MODULE, invoice_id, f"invoice_{kind}")
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        xof = to_xof(amount, currency=currency)
        if isinstance(xof, Err):
            return xof
        vat_amount = Decimal("0")
        if vat and Decimal(str(vat)) != 0:
            vat_xof = to_xof(vat, currency=currency)
            if isinstance(vat_xof, Err):
                return vat_xof
            vat_amount = vat_xof.value
        label = LABELS[kind].format(invoice_id=label_ref or invoice_id)
        # A credit note has no rule of its own: it reverses the issued invoice's rule.
        entry = invoice_entry(
            "issued" if kind == "credit_note" else kind, amount=xof.value, partner_id=partner_id, label=label,
            rules=self._rules.rules_for(tenant_id=tenant_id, source="invoice"), mirror=kind == "credit_note",
            vat=vat_amount,
        )
        if isinstance(entry, Err):
            return entry
        journal_code, lines = entry.value
        posted = self._posting.post_entry(
            tenant_id=tenant_id,
            actor_id=SYSTEM_ACTOR,
            journal_code=journal_code,
            entry_date=entry_date,
            label=label,
            lines=lines,
            correlation_id=correlation_id,
            source=source,
            reference=invoice_id,
            causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        return Ok([posted.value])

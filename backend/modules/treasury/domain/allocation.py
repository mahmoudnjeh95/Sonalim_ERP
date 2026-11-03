from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from core.domain.result import Err, Ok, Result

METHODS = ("cash", "cheque", "draft", "transfer", "mobile_money")
INSTRUMENT_METHODS = ("cheque", "draft")
# Which kind of treasury account a method may touch. Cheques and drafts name an account only
# when they are collected (deposit slip), so none is required here.
ACCOUNT_KIND_FOR_METHOD = {"cash": "cash", "transfer": "bank", "mobile_money": "mobile_money"}
# Statuses an invoice must be in to receive a payment, per direction of the document.
PAYABLE_INVOICE_STATUSES = {"in": ("issued", "partially_paid"), "out": ("validated", "partially_paid")}


def check_payments(total_payments: Decimal, payments: list[dict[str, Any]], cash_limit: Decimal | None) -> Result[Decimal]:
    """Every payment is positive, instruments carry their identifying fields, and no single cash
    payment exceeds the configured limit (none configured = no cap)."""
    if not payments:
        return Err("NO_PAYMENTS", "a document needs at least one payment", "un document doit comporter au moins un paiement")
    total = Decimal("0")
    for payment in payments:
        amount = Decimal(str(payment["amount"]))
        if amount <= 0:
            return Err("INVALID_AMOUNT", "payment amounts must be positive", "les montants de paiement doivent être positifs")
        if payment["method"] not in METHODS:
            return Err("INVALID_METHOD", f"unknown payment method {payment['method']}", f"mode de paiement inconnu {payment['method']}")
        if payment["method"] in INSTRUMENT_METHODS and not (
            payment.get("number") and payment.get("bank_name") and payment.get("due_date")
        ):
            return Err(
                "INSTRUMENT_FIELDS_REQUIRED",
                "a cheque or draft needs a number, a bank name and a due date",
                "un chèque ou une traite exige un numéro, une banque et une échéance",
            )
        if payment["method"] == "cash" and cash_limit is not None and amount > cash_limit:
            return Err(
                "CASH_LIMIT_EXCEEDED",
                f"a cash payment cannot exceed {cash_limit}",
                f"un paiement en espèces ne peut pas dépasser {cash_limit}",
            )
        total += amount
    return Ok(total)


def check_allocations(
    total: Decimal, allocations: list[tuple[str, Decimal]], *, with_details: bool, reason: str
) -> Result[Decimal]:
    """Returns the unallocated remainder (credit kept on the document).

    With details every franc must be tied to an invoice, except for an advance, which by
    definition pays something not yet invoiced."""
    allocated = sum((amount for _, amount in allocations), Decimal("0"))
    if any(amount <= 0 for _, amount in allocations):
        return Err("INVALID_AMOUNT", "allocated amounts must be positive", "les montants affectés doivent être positifs")
    if len({invoice_id for invoice_id, _ in allocations}) != len(allocations):
        return Err("DUPLICATE_ALLOCATION", "an invoice can appear only once", "une facture ne peut apparaître qu'une fois")
    if allocated > total:
        return Err("OVER_ALLOCATION", f"allocated {allocated} exceeds the payments total {total}",
                   f"le montant affecté {allocated} dépasse le total des paiements {total}")
    if with_details and not allocations:
        return Err("ALLOCATIONS_REQUIRED", "a document with details must allocate to at least one invoice",
                   "un document avec détails doit être affecté à au moins une facture")
    if with_details and reason == "full" and allocated != total:
        return Err("ALLOCATION_MISMATCH", f"allocated {allocated} must equal the payments total {total}",
                   f"le montant affecté {allocated} doit égaler le total des paiements {total}")
    return Ok(total - allocated)


def check_invoice_target(
    invoice: dict[str, Any], amount: Decimal, *, direction: str, document_currency: str, partner_id: str
) -> Result[None]:
    if invoice["status"] not in PAYABLE_INVOICE_STATUSES[direction]:
        return Err("INVOICE_NOT_VALIDATED", "this invoice is not open for payment", "cette facture n'est pas ouverte au paiement")
    if invoice["partner_id"] != partner_id:
        return Err("PARTNER_MISMATCH", "the invoice belongs to another partner", "la facture appartient à un autre partenaire")
    if invoice["currency"] != document_currency:
        return Err("CURRENCY_MISMATCH", "the invoice is in another currency than the payment",
                   "la facture est dans une autre devise que le paiement")
    if amount > invoice["remaining"]:
        return Err("OVER_ALLOCATION", f"{amount} exceeds the {invoice['remaining']} still due on the invoice",
                   f"{amount} dépasse les {invoice['remaining']} restant dus sur la facture")
    return Ok(None)


def check_prior_year(invoice_date: datetime.date, document_date: datetime.date, *, allowed: bool) -> Result[None]:
    if invoice_date.year < document_date.year and not allowed:
        return Err("PRIOR_YEAR_NOT_ALLOWED", "paying an invoice from a previous year needs a dedicated permission",
                   "régler une facture d'une année précédente exige une permission dédiée")
    return Ok(None)

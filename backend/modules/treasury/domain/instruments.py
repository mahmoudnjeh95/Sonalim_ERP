from __future__ import annotations

import datetime
from decimal import Decimal

from core.domain.result import Err, Ok, Result
from modules.treasury.domain.money import check_currency, check_whole

# status -> outcomes reachable from it. `unpaid` is for cheques only: a draft is settled or it
# is not due yet, and the manual reserves the "impayé" outcome for bounced cheques.
OUTCOMES = {"collected", "unpaid"}


def check_outcome(method: str, status: str, outcome: str) -> Result[None]:
    if outcome not in OUTCOMES:
        return Err("INVALID_OUTCOME", f"unknown outcome {outcome}", f"issue inconnue {outcome}")
    if outcome == "collected" and status != "pending":
        return Err("INSTRUMENT_NOT_PENDING", "only a pending cheque or draft can be collected",
                   "seul un chèque ou une traite en attente peut être encaissé")
    if outcome == "unpaid":
        if method != "cheque":
            return Err("UNPAID_CHEQUE_ONLY", "only a cheque can be marked unpaid", "seul un chèque peut être marqué impayé")
        if status not in ("pending", "collected"):
            return Err("INSTRUMENT_NOT_PENDING", "this cheque can no longer be marked unpaid",
                       "ce chèque ne peut plus être marqué impayé")
    return Ok(None)


def check_rejection_fee(amount: Decimal | None, account_id: str | None, *, currency: str) -> Result[Decimal | None]:
    """The bank's optional charge for rejecting a cheque: nothing at all, or a positive amount and the
    account it came out of, in whole francs."""
    if amount is None and not account_id:
        return Ok(None)
    if amount is None:
        return Err("REJECTION_FEE_REQUIRED", "enter the fee amount or remove its account", "saisissez le montant des frais ou retirez le compte")
    if amount <= 0:
        return Err("INVALID_REJECTION_FEE", "a rejection fee must be positive", "les frais de rejet doivent être positifs")
    in_xof = check_currency(currency)
    if isinstance(in_xof, Err):
        return in_xof
    whole = check_whole(amount)
    if isinstance(whole, Err):
        return whole
    if not account_id:
        return Err("REJECTION_FEE_ACCOUNT_REQUIRED", "a rejection fee needs the account it was charged to", "des frais de rejet exigent le compte débité")
    return Ok(amount)


def unpaid_reverses_balance(status_before: str) -> bool:
    """A cheque that bounces after being credited takes the money back; one rejected before
    it was ever credited has nothing to take back."""
    return status_before == "collected"


def alert_start(due_date: datetime.date, offset_days: int) -> datetime.date:
    """First day the alert shows: positive offsets are after the due date, negative before."""
    return due_date + datetime.timedelta(days=offset_days)


def alert_due(due_date: datetime.date, offset_days: int, today: datetime.date) -> bool:
    return today >= alert_start(due_date, offset_days)


def split_reduction(allocations: list[tuple[str, Decimal, Decimal]], amount: Decimal) -> list[tuple[str, Decimal]]:
    """Spread a reduction over a document's invoices, in order, never taking back more than each
    invoice's still-standing allocation. `allocations` are (invoice_id, allocated, already_reversed)."""
    remaining = amount
    out: list[tuple[str, Decimal]] = []
    for invoice_id, allocated, reversed_amount in allocations:
        if remaining <= 0:
            break
        available = allocated - reversed_amount
        if available <= 0:
            continue
        take = min(available, remaining)
        out.append((invoice_id, take))
        remaining -= take
    return out

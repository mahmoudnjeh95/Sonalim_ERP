from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "draft": {"issued"},
    "issued": {"paid"},
    "partially_paid": set(),
    "paid": set(),
}


@dataclass(frozen=True)
class Invoice:
    id: str
    partner_id: str
    amount: float
    currency: str
    status: str
    amount_paid: float = 0.0


def transition(invoice: Invoice, new_status: str) -> Result[Invoice]:
    if new_status not in VALID_TRANSITIONS.get(invoice.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move invoice from {invoice.status} to {new_status}",
            f"impossible de faire passer la facture de {invoice.status} à {new_status}",
        )
    return Ok(
        Invoice(
            id=invoice.id,
            partner_id=invoice.partner_id,
            amount=invoice.amount,
            currency=invoice.currency,
            status=new_status,
        )
    )


def status_for_payment(amount: float, amount_paid: float) -> str:
    """The status an issued invoice has once `amount_paid` has been applied to it."""
    if amount_paid <= 0:
        return "issued"
    if amount_paid >= amount:
        return "paid"
    return "partially_paid"

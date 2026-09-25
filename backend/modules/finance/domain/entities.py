from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "draft": {"issued"},
    "issued": {"paid"},
    "paid": set(),
}


@dataclass(frozen=True)
class Invoice:
    id: str
    partner_id: str
    amount: float
    currency: str
    status: str


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

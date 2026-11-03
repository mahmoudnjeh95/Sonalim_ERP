from __future__ import annotations

from decimal import Decimal

from core.domain.result import Err, Ok, Result

# Payment-driven states (partially_paid, paid) are never requested directly: they are
# derived from amount_paid by `status_for_payment`, so the only manual transitions are these.
MANUAL_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"validated", "cancelled"},
    "validated": {"cancelled"},
    "partially_paid": set(),
    "paid": set(),
    "cancelled": set(),
}

PAYABLE_STATUSES = {"validated", "partially_paid"}
LINES_TOLERANCE = Decimal("0.01")


def check_transition(current: str, target: str) -> Result[None]:
    if target not in MANUAL_TRANSITIONS.get(current, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move purchase invoice from {current} to {target}",
            f"impossible de faire passer la facture d'achat de {current} à {target}",
        )
    return Ok(None)


def remaining(amount: Decimal, amount_paid: Decimal) -> Decimal:
    return max(amount - amount_paid, Decimal("0"))


def status_for_payment(amount: Decimal, amount_paid: Decimal) -> str:
    """The status a validated invoice has once `amount_paid` has been applied."""
    if amount_paid <= 0:
        return "validated"
    if amount_paid >= amount:
        return "paid"
    return "partially_paid"


def check_payment_delta(amount: Decimal, amount_paid: Decimal, delta: Decimal) -> Result[Decimal]:
    new_paid = amount_paid + delta
    if new_paid < 0 or new_paid > amount:
        return Err(
            "OVER_ALLOCATION",
            f"payment of {new_paid} is outside 0..{amount} for this invoice",
            f"un paiement de {new_paid} sort de la plage 0..{amount} pour cette facture",
        )
    return Ok(new_paid)


def check_lines_total(amount: Decimal, lines: list[tuple[Decimal, Decimal]]) -> Result[None]:
    """`lines` are (quantity, unit_price). No lines is valid: the header total stands alone."""
    if not lines:
        return Ok(None)
    total = sum((quantity * unit_price for quantity, unit_price in lines), Decimal("0"))
    if abs(total - amount) > LINES_TOLERANCE:
        return Err(
            "TOTAL_MISMATCH",
            f"lines total {total} differs from invoice amount {amount}",
            f"le total des lignes {total} diffère du montant de la facture {amount}",
        )
    return Ok(None)

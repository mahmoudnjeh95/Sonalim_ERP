"""Treasury works in F CFA only, and F CFA has no cents."""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from core.domain.result import Err, Ok, Result

TREASURY_CURRENCY = "XOF"


def check_currency(currency: str | None) -> Result[None]:
    if currency != TREASURY_CURRENCY:
        return Err(
            "TREASURY_CURRENCY_NOT_XOF",
            f"treasury works in XOF (F CFA) only, not {currency}",
            f"la trésorerie fonctionne uniquement en XOF (F CFA), pas en {currency}",
        )
    return Ok(None)


def check_whole(amount: Decimal) -> Result[None]:
    if amount != amount.to_integral_value():
        return Err(
            "AMOUNT_NOT_WHOLE",
            f"{amount} is not a whole amount of F CFA",
            f"{amount} n'est pas un montant entier en F CFA",
        )
    return Ok(None)


def whole_francs_payable(amount: Decimal) -> Decimal:
    """What can still be paid on an invoice whose amount has cents: payments are whole francs."""
    return amount.to_integral_value(rounding=ROUND_FLOOR)

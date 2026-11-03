from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

COST_PLACES = Decimal("0.0001")


def weighted_average(old_qty: Decimal, old_cost: Decimal, in_qty: Decimal, in_cost: Decimal) -> Decimal:
    """Coût moyen pondéré: (old_qty·old_cost + in_qty·in_cost) / (old_qty + in_qty).

    A negative old quantity (production drove the balance below zero) carries no value, so it
    counts as zero: the incoming cost then stands alone rather than being diluted by a shortfall."""
    if in_qty <= 0:
        raise ValueError("incoming quantity must be positive")
    base_qty = max(old_qty, Decimal("0"))
    average = (base_qty * old_cost + in_qty * in_cost) / (base_qty + in_qty)
    return average.quantize(COST_PLACES, rounding=ROUND_HALF_UP)


def value_of(quantity: Decimal, avg_cost: Decimal) -> Decimal:
    """What a quantity is worth. Negative balances are valued at zero; the report flags them."""
    return (max(quantity, Decimal("0")) * avg_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

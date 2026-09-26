"""XOF has no sub-unit: every amount the hr module stores is a whole, non-negative number of francs."""
from __future__ import annotations

from decimal import Decimal

from core.domain.result import Err


def is_whole_amount(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value >= 0 and value == value.to_integral_value()


def invalid_amount(label_en: str, label_fr: str) -> Err:
    return Err(
        "INVALID_AMOUNT",
        f"{label_en} must be a whole, non-negative number of F CFA",
        f"{label_fr} doit être un nombre entier et positif de F CFA",
    )

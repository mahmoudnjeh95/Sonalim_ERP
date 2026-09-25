from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

BASE_CURRENCY = "XOF"


@dataclass(frozen=True)
class ExchangeRate:
    id: str
    tenant_id: str
    currency_code: str
    rate_to_base: float
    effective_date: str
    source: str


def validate_rate(rate_to_base: float) -> Result[None]:
    if rate_to_base <= 0:
        return Err("INVALID_RATE", "rate_to_base must be positive", "rate_to_base doit être positif")
    return Ok(None)


def convert_to_base(*, amount: float, currency_code: str, rate_to_base: float) -> Result[float]:
    if currency_code == BASE_CURRENCY:
        return Ok(amount)
    validation = validate_rate(rate_to_base)
    if isinstance(validation, Err):
        return validation
    return Ok(amount * rate_to_base)

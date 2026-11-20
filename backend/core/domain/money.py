"""Money at the edges. Inside a module amounts are `Decimal` (the database columns are NUMERIC);
these two helpers are where they come in from callers and go out to JSON."""
from __future__ import annotations

from decimal import Decimal


def to_decimal(value: Decimal | float | int | str) -> Decimal:
    """Through `str`, so a float caller gets the decimal it wrote (0.1 -> Decimal("0.1")), not its
    binary expansion."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("a boolean is not an amount")
    return Decimal(str(value))


def json_number(value: Decimal | float | int | None) -> float | None:
    """A JSON number for an API response or an event/audit payload. FastAPI would write a Decimal as a
    string and `Jsonb` refuses one; the contracts carry money as numbers, as they always have."""
    if value is None:
        return None
    return float(value)

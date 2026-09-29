"""How net pay reaches an employee: one or more methods whose shares add up to 100 %.
Arrangements are dated: the one in force on a day is the latest that started on or before it.
Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.domain.result import Err, Ok, Result

PAYMENT_METHODS = ("bank", "mobile_money", "cash")
MOBILE_OPERATORS = ("orange_money", "moov_money")
WHOLE = Decimal("100")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class PaymentMethod:
    method: str
    share_percent: Decimal
    is_primary: bool = False
    bank_name: str | None = None
    account_no: str | None = None
    mobile_operator: str | None = None
    mobile_number: str | None = None


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalized(method: PaymentMethod) -> PaymentMethod:
    """Keep only the details that apply to the method: a cash line carries no account."""
    bank = method.method == "bank"
    mobile = method.method == "mobile_money"
    return PaymentMethod(
        method=method.method,
        share_percent=method.share_percent,
        is_primary=method.is_primary,
        bank_name=_text(method.bank_name) if bank else None,
        account_no=_text(method.account_no) if bank else None,
        mobile_operator=method.mobile_operator if mobile else None,
        mobile_number=_text(method.mobile_number) if mobile else None,
    )


def _split_refusal(message_en: str, message_fr: str) -> Err:
    return Err("PAYOUT_SPLIT_INVALID", message_en, message_fr)


def validate_payment_set(methods: Sequence[PaymentMethod]) -> Result[tuple[PaymentMethod, ...]]:
    if not methods:
        return _split_refusal("a payment arrangement needs at least one method", "un mode de paiement demande au moins une ligne")
    cleaned: list[PaymentMethod] = []
    for method in methods:
        if method.method not in PAYMENT_METHODS:
            return Err("INVALID_CHOICE", "a method is a bank transfer, mobile money or cash", "un mode est un virement, du mobile money ou des espèces")
        line = _normalized(method)
        if line.method == "bank" and (line.bank_name is None or line.account_no is None):
            return Err(
                "INVALID_PAYMENT_METHOD",
                "a bank transfer needs the bank and the account number (RIB)",
                "un virement demande la banque et le numéro de compte (RIB)",
            )
        if line.method == "mobile_money" and (line.mobile_operator not in MOBILE_OPERATORS or line.mobile_number is None):
            return Err("INVALID_PAYMENT_METHOD", "mobile money needs the operator and the number", "le mobile money demande l'opérateur et le numéro")
        share = line.share_percent
        # Checked before the database: NUMERIC(5,2) would round 33.333 silently.
        if share is None or not share.is_finite() or share <= 0 or share > WHOLE or share != share.quantize(CENT):
            return _split_refusal(
                "each share is above 0 %, at most 100 %, with at most two decimals",
                "chaque part est supérieure à 0 %, au plus 100 %, avec au plus deux décimales",
            )
        cleaned.append(line)
    total = sum((line.share_percent for line in cleaned), Decimal("0"))
    if total != WHOLE:
        return _split_refusal(f"the shares add up to {total} %, not 100 %", f"les parts totalisent {total} %, pas 100 %")
    if sum(1 for line in cleaned if line.is_primary) != 1:
        return _split_refusal("exactly one method is the primary one", "un seul mode doit être le principal")
    return Ok(tuple(cleaned))


def set_in_force(starts: Iterable[datetime.date], day: datetime.date) -> datetime.date | None:
    """The start date of the arrangement in force on `day`: the latest on or before it."""
    return max((start for start in starts if start <= day), default=None)

"""Payment terms: when an invoice falls due. Pure rules, no database.

A term is one or more installments, each a share of the invoice due some days after the invoice date,
optionally moved to the end of that month and then to a given day of the next month: "45 jours fin de
mois le 10" is 45 days, then the end of that month, then the 10th of the month after.
"""
from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class Installment:
    percent: Decimal
    days: int
    end_of_month: bool = False
    day_of_month: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"percent": str(self.percent), "days": self.days, "end_of_month": self.end_of_month, "day_of_month": self.day_of_month}


# The catalog every tenant starts with: (code, French name, English name, installments).
DEFAULT_TERMS: tuple[tuple[str, str, str, tuple[Installment, ...]], ...] = (
    ("COMPTANT", "Comptant", "Cash on delivery", (Installment(Decimal("100"), 0),)),
    ("30N", "30 jours net", "30 days net", (Installment(Decimal("100"), 30),)),
    ("30FDM", "30 jours fin de mois", "30 days end of month", (Installment(Decimal("100"), 30, end_of_month=True),)),
    ("60N", "60 jours net", "60 days net", (Installment(Decimal("100"), 60),)),
    ("45FDM10", "45 jours fin de mois le 10", "45 days end of month, on the 10th",
     (Installment(Decimal("100"), 45, end_of_month=True, day_of_month=10),)),
    ("50C-50/30", "50 % comptant, 50 % à 30 jours", "50% on delivery, 50% at 30 days",
     (Installment(Decimal("50"), 0), Installment(Decimal("50"), 30))),
)


def parse_installments(raw: list[dict[str, Any]]) -> Result[tuple[Installment, ...]]:
    """Validates installments as entered: at least one, shares that add up to exactly 100, days within a year
    and a half, a day of the month between 1 and 31."""
    if not raw:
        return Err("INVALID_PAYMENT_TERM", "a payment term needs at least one installment",
                   "une condition de paiement compte au moins une échéance")
    installments = []
    for item in raw:
        try:
            percent = Decimal(str(item["percent"]))
            days = int(item["days"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return Err("INVALID_PAYMENT_TERM", "each installment needs a percent and a number of days",
                       "chaque échéance a un pourcentage et un nombre de jours")
        day_of_month = item.get("day_of_month")
        if day_of_month in ("", None):
            day_of_month = None
        else:
            day_of_month = int(day_of_month)
            if not 1 <= day_of_month <= 31:
                return Err("INVALID_PAYMENT_TERM", "the day of the month is between 1 and 31", "le jour du mois est compris entre 1 et 31")
        if percent <= 0 or not 0 <= days <= 540:
            return Err("INVALID_PAYMENT_TERM", "a share is above 0 and the delay between 0 and 540 days",
                       "une part est supérieure à 0 et le délai compris entre 0 et 540 jours")
        installments.append(Installment(percent, days, bool(item.get("end_of_month")), day_of_month))
    if sum(i.percent for i in installments) != Decimal("100"):
        return Err("INVALID_PAYMENT_TERM", "the installments' shares must add up to 100%",
                   "les parts des échéances doivent totaliser 100 %")
    return Ok(tuple(installments))


def _last_day(day: datetime.date) -> datetime.date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _first_of_next_month(day: datetime.date) -> datetime.date:
    return (_last_day(day) + datetime.timedelta(days=1))


def _on_day(month_start: datetime.date, day_of_month: int) -> datetime.date:
    return month_start.replace(day=min(day_of_month, calendar.monthrange(month_start.year, month_start.month)[1]))


def due_date(invoice_date: datetime.date, installment: Installment) -> datetime.date:
    day = invoice_date + datetime.timedelta(days=installment.days)
    if installment.end_of_month:
        day = _last_day(day)
        if installment.day_of_month:
            day = _on_day(_first_of_next_month(day), installment.day_of_month)
    elif installment.day_of_month:
        # The next given day of the month on or after the delay.
        candidate = _on_day(day.replace(day=1), installment.day_of_month)
        day = candidate if candidate >= day else _on_day(_first_of_next_month(day), installment.day_of_month)
    return day


def schedule(invoice_date: datetime.date, amount: Decimal, installments: tuple[Installment, ...]) -> list[tuple[datetime.date, Decimal]]:
    """The due dates and amounts, in whole francs; the last installment takes the rounding so they add up."""
    amount = Decimal(str(amount))
    rows: list[tuple[datetime.date, Decimal]] = []
    allotted = Decimal("0")
    for index, installment in enumerate(installments):
        if index == len(installments) - 1:
            share = amount - allotted
        else:
            share = (amount * installment.percent / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            allotted += share
        rows.append((due_date(invoice_date, installment), share))
    return sorted(rows, key=lambda row: row[0])

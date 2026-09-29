"""Leave: types, the days a request counts, monthly accrual and yearly balances. Pure.

Accrual per month and the carry-over cap are properties of a leave type (rows HR confirms),
never constants here. A month's accrual is prorated by the calendar days the person was
employed in it. A year's unused balance (never less than zero) is carried into the next
year, up to the type's cap (no cap when empty).
"""
from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.domain.result import Err, Ok, Result

COUNTS_DAYS = ("calendar", "working")
LEAVE_PRESENCE_STATUSES = ("leave", "sick")
HALF_DAY = Decimal("0.5")
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class LeaveType:
    id: str
    code: str
    paid: bool
    accrual_days_per_month: Decimal
    max_carry_over: Decimal | None
    counts_days: str
    requires_document: bool
    presence_status: str
    active: bool = True

    @property
    def tracks_balance(self) -> bool:
        return self.accrual_days_per_month > 0


def validate_leave_type(
    *,
    code: str,
    name_en: str,
    name_fr: str,
    accrual_days_per_month: Decimal,
    max_carry_over: Decimal | None,
    counts_days: str,
    presence_status: str,
) -> Result[None]:
    if not code.strip() or not name_en.strip() or not name_fr.strip():
        return Err("INVALID_LEAVE_TYPE", "code and both names are required", "le code et les deux libellés sont obligatoires")
    if accrual_days_per_month < 0 or (max_carry_over is not None and max_carry_over < 0):
        return Err("INVALID_LEAVE_TYPE", "day counts cannot be negative", "les nombres de jours ne peuvent pas être négatifs")
    if counts_days not in COUNTS_DAYS:
        return Err("INVALID_LEAVE_TYPE", f"counts_days must be one of {COUNTS_DAYS}", f"counts_days doit être l'un de {COUNTS_DAYS}")
    if presence_status not in LEAVE_PRESENCE_STATUSES:
        return Err(
            "INVALID_LEAVE_TYPE",
            f"presence_status must be one of {LEAVE_PRESENCE_STATUSES}",
            f"presence_status doit être l'un de {LEAVE_PRESENCE_STATUSES}",
        )
    return Ok(None)


def leave_dates(*, start: datetime.date, end: datetime.date, counts_days: str, working_days: set[datetime.date]) -> list[datetime.date]:
    """The dates a request counts: every date, or only the person's working days (no rest day, no public holiday)."""
    every = [start + datetime.timedelta(days=offset) for offset in range((end - start).days + 1)]
    return every if counts_days == "calendar" else [day for day in every if day in working_days]


def requested_days(*, start: datetime.date, end: datetime.date, half_day: bool, counted: list[datetime.date]) -> Result[Decimal]:
    if end < start:
        return Err("INVALID_DATES", "leave end date cannot be before its start date", "la date de fin du congé ne peut pas précéder sa date de début")
    if half_day and start != end:
        return Err("INVALID_LEAVE", "a half day starts and ends on the same date", "une demi-journée commence et finit le même jour")
    if not counted:
        return Err("INVALID_LEAVE", "no leave day falls between these dates", "aucun jour de congé ne tombe entre ces dates")
    return Ok(HALF_DAY if half_day else Decimal(len(counted)))


def month_accrual(*, rate: Decimal, period: datetime.date, employed_from: datetime.date, employed_to: datetime.date | None) -> Decimal:
    last = period.replace(day=calendar.monthrange(period.year, period.month)[1])
    start = max(period, employed_from)
    end = min(last, employed_to) if employed_to is not None else last
    if end < start:
        return Decimal("0.00")
    employed_days = Decimal((end - start).days + 1)
    return (rate * employed_days / Decimal(last.day)).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class YearFigures:
    year: int
    accrued: Decimal
    taken: Decimal
    adjusted: Decimal


@dataclass(frozen=True)
class BalanceView:
    year: int
    carried_over: Decimal
    accrued: Decimal
    taken: Decimal
    adjusted: Decimal

    @property
    def available(self) -> Decimal:
        return self.carried_over + self.accrued + self.adjusted - self.taken


def roll_balances(figures: list[YearFigures], max_carry_over: Decimal | None, *, until: int) -> dict[int, BalanceView]:
    by_year = {item.year: item for item in figures}
    first = min([item.year for item in figures] + [until])
    views: dict[int, BalanceView] = {}
    carried = _ZERO
    for year in range(first, until + 1):
        item = by_year.get(year, YearFigures(year, _ZERO, _ZERO, _ZERO))
        view = BalanceView(year=year, carried_over=carried, accrued=item.accrued, taken=item.taken, adjusted=item.adjusted)
        views[year] = view
        remaining = max(_ZERO, view.available)
        carried = remaining if max_carry_over is None else min(remaining, max_carry_over)
    return views


def check_balance(view: BalanceView, days: Decimal) -> Result[None]:
    if view.available < days:
        return Err(
            "LEAVE_BALANCE_INSUFFICIENT",
            f"only {view.available} day(s) available for {view.year}, {days} requested",
            f"seulement {view.available} jour(s) disponible(s) pour {view.year}, {days} demandé(s)",
        )
    return Ok(None)

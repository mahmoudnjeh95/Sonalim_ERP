"""Final settlement: years of service, the reference salary, and the three indemnities."""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from decimal import Decimal

from modules.payroll.domain.earnings import earning_line
from modules.payroll.domain.inputs import PayslipLine, SettlementInput
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import LEAVE_INDEMNITY, NOTICE_INDEMNITY, SEVERANCE, RuleSet, SeveranceStep

_QTY = Decimal("0.01")


def completed_months(start: datetime.date, end: datetime.date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    return max(months, 0)


def years_of_service(hire_date: datetime.date, end_date: datetime.date) -> Decimal:
    return Decimal(completed_months(hire_date, end_date)) / 12


def reference_salary(recent_gross: Sequence[Decimal], *, months: int, fallback: Decimal) -> Decimal:
    """Average of the `months` most recent monthly gross amounts (newest first); `fallback` if none."""
    window = list(recent_gross)[:months]
    return sum(window, ZERO) / len(window) if window else fallback


def severance_amount(scale: Sequence[SeveranceStep], years: Decimal, reference: Decimal) -> Decimal:
    """Each year inside [years_from, next years_from) earns percent_per_year % of the reference."""
    steps = sorted(scale, key=lambda step: step.years_from)
    total = ZERO
    for index, step in enumerate(steps):
        lower = Decimal(step.years_from)
        if years <= lower:
            break
        upper = Decimal(steps[index + 1].years_from) if index + 1 < len(steps) else None
        span = (years if upper is None else min(years, upper)) - lower
        total += span * percent_of(reference, step.percent_per_year)
    return total


def leave_indemnity(reference: Decimal, unused_days: Decimal, rules: RuleSet) -> Decimal:
    return reference / rules.working_days_per_month * unused_days


def notice_indemnity(reference: Decimal, months: Decimal) -> Decimal:
    return reference * months


def settlement_lines(rules: RuleSet, settlement: SettlementInput) -> list[PayslipLine]:
    reference = settlement.reference_salary
    owed = (
        (LEAVE_INDEMNITY, leave_indemnity(reference, settlement.unused_leave_days, rules), settlement.unused_leave_days),
        (NOTICE_INDEMNITY, notice_indemnity(reference, settlement.notice_months), settlement.notice_months),
        (SEVERANCE, severance_amount(rules.severance_scale, settlement.years_of_service, reference), settlement.years_of_service),
    )
    lines: list[PayslipLine] = []
    for code, amount, qty in owed:
        rounded = rules.round(amount)
        if rounded <= 0:
            continue
        lines.append(earning_line(rules.require(code), rounded, base=rules.round(reference), qty=qty.quantize(_QTY)))
    return lines

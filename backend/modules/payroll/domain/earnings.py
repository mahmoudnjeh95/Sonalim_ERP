"""Step 1 of a payslip: everything the employee earns, up to the gross."""
from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterable, Sequence
from decimal import Decimal

from modules.payroll.domain.inputs import EmployeeInput, OneOffInput, PayslipLine, PresenceInput
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import (
    BASE,
    OVERTIME_BANDS,
    OVERTIME_CODES,
    SENIORITY,
    UNPAID_ABSENCE,
    ComponentMisuse,
    ComponentRule,
    RuleSet,
)

_HOURS = Decimal("0.01")


def period_end(period: datetime.date) -> datetime.date:
    return period.replace(day=calendar.monthrange(period.year, period.month)[1])


def employment_end(employee: EmployeeInput) -> datetime.date | None:
    ends = [day for day in (employee.contract_end, employee.termination_date) if day is not None]
    return min(ends) if ends else None


def covers_whole_month(employee: EmployeeInput, period: datetime.date) -> bool:
    end = employment_end(employee)
    return employee.contract_start <= period and (end is None or end >= period_end(period))


def coverage_factor(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date) -> Decimal:
    """1 for a whole month; otherwise the scheduled days inside the contract over the rule set's
    working days per month, capped at 1 (presence only schedules days while the contract runs)."""
    if covers_whole_month(employee, period):
        return Decimal(1)
    return min(Decimal(presence.scheduled_days), rules.working_days_per_month) / rules.working_days_per_month


def monthly_equivalent(employee: EmployeeInput, rules: RuleSet) -> Decimal:
    if employee.pay_frequency == "daily":
        return employee.base_salary * rules.working_days_per_month
    return employee.base_salary


def hourly_rate(employee: EmployeeInput, rules: RuleSet) -> Decimal:
    return monthly_equivalent(employee, rules) / rules.working_hours_per_month


def earning_line(rule: ComponentRule, amount: Decimal, *, base: Decimal | None = None, qty: Decimal | None = None,
                 rate: Decimal | None = None, source_kind: str | None = None, source_id: str | None = None) -> PayslipLine:
    return PayslipLine(
        section="earning", code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=amount,
        base=base, qty=qty, rate=rate, taxable=rule.taxable, contributable=rule.contributable,
        declaration_code=rule.declaration_code, display_order=rule.display_order,
        source_kind=source_kind, source_id=source_id,
    )


def base_salary_lines(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date) -> list[PayslipLine]:
    base_rule = rules.require(BASE)
    if employee.pay_frequency == "daily":
        # holidays_worked_days is counted in both worked_days and holiday_days (hr's
        # month_summary, see presence.py) -- subtract it once so a worked holiday draws
        # one day rate, not two. Its hours are paid separately as rest_holiday overtime.
        paid_days = presence.worked_days + presence.paid_leave_days + presence.holiday_days - presence.holidays_worked_days
        # A worked rest day is in worked_days too, with all its minutes as rest_holiday overtime;
        # the rule set decides whether it also draws its day rate.
        if rules.daily_rest_day_pay == "overtime_only":
            paid_days -= presence.rest_days_worked
        return [earning_line(base_rule, rules.round(employee.base_salary * paid_days), base=employee.base_salary, qty=Decimal(paid_days))]

    factor = coverage_factor(employee, presence, rules, period)
    base_amount = rules.round(employee.base_salary * factor)
    qty = None if factor == 1 else min(Decimal(presence.scheduled_days), rules.working_days_per_month)
    lines = [earning_line(base_rule, base_amount, base=employee.base_salary, qty=qty)]
    if presence.unpaid_absence_days > 0:
        absence_rule = rules.require(UNPAID_ABSENCE)
        day_rate = employee.base_salary / rules.working_days_per_month
        taken = min(rules.round(day_rate * presence.unpaid_absence_days), base_amount)
        lines.append(earning_line(absence_rule, -taken, base=rules.round(day_rate), qty=Decimal(presence.unpaid_absence_days)))
    return lines


def earned_base(lines: Iterable[PayslipLine]) -> Decimal:
    return sum((line.amount for line in lines if line.code in (BASE, UNPAID_ABSENCE)), ZERO)


def completed_years(start: datetime.date, on: datetime.date) -> int:
    return max(on.year - start.year - ((on.month, on.day) < (start.month, start.day)), 0)


def _seniority_date(employee: EmployeeInput, period: datetime.date) -> datetime.date:
    end = employment_end(employee)
    last = period_end(period)
    return last if end is None or end > last else end


def seniority_line(employee: EmployeeInput, earned: Decimal, rules: RuleSet, period: datetime.date) -> PayslipLine | None:
    years = completed_years(employee.hire_date, _seniority_date(employee, period))
    reached = [step for step in rules.seniority_scale if step.years_from <= years]
    if not reached or earned <= 0:
        return None
    percent = max(reached, key=lambda step: step.years_from).percent
    if percent == 0:
        return None
    return earning_line(rules.require(SENIORITY), rules.round(percent_of(earned, percent)), base=earned, qty=Decimal(years), rate=percent)


def overtime_lines(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet) -> list[PayslipLine]:
    minutes = {"day": presence.ot_minutes_day, "night": presence.ot_minutes_night, "rest_holiday": presence.ot_minutes_rest_holiday}
    hourly = hourly_rate(employee, rules)
    lines: list[PayslipLine] = []
    for band in OVERTIME_BANDS:
        if minutes[band] <= 0:
            continue
        rule = rules.require(OVERTIME_CODES[band])
        multiplier = rules.overtime_multiplier(band)
        hours = Decimal(minutes[band]) / 60
        lines.append(earning_line(rule, rules.round(hours * hourly * multiplier), base=rules.round(hourly),
                                  qty=hours.quantize(_HOURS), rate=multiplier))
    return lines


def _first(*values: Decimal | None) -> Decimal:
    return next((value for value in values if value is not None), ZERO)


def contract_component_lines(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date,
                             *, earned: Decimal) -> list[PayslipLine]:
    factor = coverage_factor(employee, presence, rules, period)
    lines: list[PayslipLine] = []
    for item in employee.components:
        rule = rules.require(item.component_code)
        if rule.kind != "earning":
            raise ComponentMisuse(f"{rule.code} is not an earning; only earnings are written on a contract",
                                  f"{rule.code} n'est pas un gain ; seuls les gains s'inscrivent sur un contrat")
        if rule.formula_type == "fixed":
            amount = _first(item.amount, rule.default_amount)
            lines.append(earning_line(rule, rules.round(amount * factor), base=amount))
        elif rule.formula_type == "rate_x_base":
            rate = _first(item.rate, rule.default_rate)
            base = earned if rule.base_ref == "earned_base" else monthly_equivalent(employee, rules) * factor
            lines.append(earning_line(rule, rules.round(percent_of(base, rate)), base=rules.round(base), rate=rate))
        elif rule.formula_type == "per_day":
            per_day = _first(item.amount, rule.default_amount)
            lines.append(earning_line(rule, rules.round(per_day * presence.worked_days), base=per_day, qty=Decimal(presence.worked_days)))
        else:
            raise ComponentMisuse(f"{rule.code} is a quantity × rate; type its quantity as a monthly input",
                                  f"{rule.code} est une quantité × taux ; saisissez sa quantité en variable du mois")
    return [line for line in lines if line.amount != 0]


def one_off_amount(rule: ComponentRule, item: OneOffInput, presence: PresenceInput) -> tuple[Decimal, Decimal | None, Decimal | None]:
    """(amount, base, qty) of a typed input, by its component's formula."""
    if rule.formula_type == "fixed":
        return _first(item.amount, rule.default_amount), None, None
    if rule.formula_type == "qty_x_rate":
        unit = _first(item.amount, rule.default_amount)
        qty = _first(item.qty)
        return qty * unit, unit, qty
    if rule.formula_type == "per_day":
        unit = _first(item.amount, rule.default_amount)
        days = item.qty if item.qty is not None else Decimal(presence.worked_days)
        return unit * days, unit, days
    raise ComponentMisuse(f"{rule.code} is computed from a base; it cannot be typed as an input",
                          f"{rule.code} se calcule sur une base ; elle ne se saisit pas en variable")


def input_earning_lines(inputs: Sequence[OneOffInput], presence: PresenceInput, rules: RuleSet) -> list[PayslipLine]:
    lines: list[PayslipLine] = []
    for item in inputs:
        rule = rules.require(item.component_code)
        if rule.kind != "earning":
            continue
        amount, base, qty = one_off_amount(rule, item, presence)
        rounded = rules.round(amount)
        if rounded != 0:
            lines.append(earning_line(rule, rounded, base=base, qty=qty, source_kind=item.source_kind, source_id=item.source_id))
    return lines

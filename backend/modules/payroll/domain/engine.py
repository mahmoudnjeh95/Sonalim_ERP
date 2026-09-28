"""The payroll engine: one employee, one month, one rule set -> ordered payslip lines and totals.

Pure (no database, no clock). Each step lives in its own module and is tested alone; this file only
runs them in the spec's order:
  1 earnings -> gross        (earnings.py, settlement.py)
  2 contributable base       (contributions.py)
  3 contributions            (contributions.py)
  4 taxable and tax          (tax.py)
  5 deductions -> net >= 0   (net.py; the overflow is carried and reported as NET_NEGATIVE)
  6 employer cost            (net.py)
"""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result
from modules.payroll.domain.contributions import contributable_earnings, contribution_lines
from modules.payroll.domain.earnings import (
    base_salary_lines,
    contract_component_lines,
    earned_base,
    input_earning_lines,
    overtime_lines,
    seniority_line,
)
from modules.payroll.domain.inputs import (
    SECTIONS,
    EmployeeInput,
    OneOffInput,
    PayslipLine,
    PresenceInput,
    SettlementInput,
    section_total,
)
from modules.payroll.domain.money import ZERO
from modules.payroll.domain.net import (
    CarryForward,
    PayslipTotals,
    apply_net_floor,
    deduction_lines,
    employer_charge_lines,
    payslip_totals,
)
from modules.payroll.domain.rules import ComponentMisuse, RuleSet, RuleSetIncomplete
from modules.payroll.domain.settlement import settlement_lines
from modules.payroll.domain.tax import tax_lines


@dataclass(frozen=True)
class PayslipResult:
    lines: tuple[PayslipLine, ...]
    totals: PayslipTotals
    carry_forwards: tuple[CarryForward, ...]
    warnings: tuple[str, ...]


def order_lines(lines: Sequence[PayslipLine]) -> list[PayslipLine]:
    return sorted(lines, key=lambda line: (SECTIONS.index(line.section), line.display_order, line.code))


def calculate_payslip(
    *,
    employee: EmployeeInput,
    presence: PresenceInput,
    rules: RuleSet,
    period: datetime.date,
    inputs: Sequence[OneOffInput] = (),
    settlement: SettlementInput | None = None,
    include_salary: bool = True,
) -> Result[PayslipResult]:
    try:
        return Ok(_calculate(employee, presence, rules, period, tuple(inputs), settlement, include_salary))
    except RuleSetIncomplete as missing:
        return Err("COMPONENT_MISSING", f"the rule set has no {missing.what_en}", f"le jeu de règles n'a pas de {missing.what_fr}")
    except ComponentMisuse as misuse:
        return Err("COMPONENT_INVALID", misuse.message_en, misuse.message_fr)


def _calculate(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date,
               inputs: tuple[OneOffInput, ...], settlement: SettlementInput | None, include_salary: bool) -> PayslipResult:
    lines: list[PayslipLine] = []
    earned = ZERO
    if include_salary:
        lines += base_salary_lines(employee, presence, rules, period)
        earned = earned_base(lines)
        seniority = seniority_line(employee, earned, rules, period)
        if seniority is not None:
            lines.append(seniority)
        lines += contract_component_lines(employee, presence, rules, period, earned=earned)
        lines += overtime_lines(employee, presence, rules)
    if settlement is not None:
        lines += settlement_lines(rules, settlement)
    lines += input_earning_lines(inputs, presence, rules)

    gross = section_total(lines, "earning")
    contributable = contributable_earnings(lines)
    lines += contribution_lines(rules, gross=gross, contributable=contributable)
    lines += tax_lines(rules, lines, employee.tax_dependants)

    available = gross - section_total(lines, "employee_contribution") - section_total(lines, "tax")
    kept, carried = apply_net_floor(available, deduction_lines(inputs, presence, rules))
    lines += kept
    lines += employer_charge_lines(rules, gross=gross, contributable=contributable, earned=earned, include_fixed=include_salary)

    ordered = tuple(order_lines(lines))
    return PayslipResult(
        lines=ordered,
        totals=payslip_totals(ordered),
        carry_forwards=tuple(carried),
        warnings=("NET_NEGATIVE",) if carried else (),
    )

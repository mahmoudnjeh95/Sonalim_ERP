"""Steps 5 and 6: what is withheld, the net (never below zero), the employer's charges and cost."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from modules.payroll.domain.contributions import contributable_earnings
from modules.payroll.domain.earnings import one_off_amount
from modules.payroll.domain.inputs import SOURCE_KINDS, OneOffInput, PayslipLine, PresenceInput, section_total
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import RuleSet


@dataclass(frozen=True)
class CarryForward:
    """A deduction (or its remainder) the net could not cover, owed next month."""

    component_code: str
    amount: Decimal
    source_kind: str
    source_id: str | None


@dataclass(frozen=True)
class PayslipTotals:
    gross: Decimal
    contributable: Decimal
    taxable: Decimal
    employee_contrib: Decimal
    employer_contrib: Decimal
    employer_charges: Decimal
    tax: Decimal
    deductions: Decimal
    net: Decimal
    employer_cost: Decimal


def deduction_lines(inputs: Sequence[OneOffInput], presence: PresenceInput, rules: RuleSet) -> list[PayslipLine]:
    lines: list[PayslipLine] = []
    for item in inputs:
        rule = rules.require(item.component_code)
        if rule.kind != "deduction":
            continue
        amount, base, qty = one_off_amount(rule, item, presence)
        rounded = rules.round(amount)
        if rounded <= 0:
            continue
        lines.append(PayslipLine(
            section="deduction", code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=rounded,
            base=base, qty=qty, declaration_code=rule.declaration_code, display_order=rule.display_order,
            source_kind=item.source_kind, source_id=item.source_id,
        ))
    return sorted(lines, key=lambda line: SOURCE_KINDS.index(line.source_kind or "input"))


def apply_net_floor(available: Decimal, deductions: Sequence[PayslipLine]) -> tuple[list[PayslipLine], list[CarryForward]]:
    """Take deductions in order while the net stays at or above zero; carry the overflow."""
    kept: list[PayslipLine] = []
    carried: list[CarryForward] = []
    left = max(available, ZERO)
    for line in deductions:
        if line.amount <= left:
            kept.append(line)
            left -= line.amount
            continue
        if left > 0:
            kept.append(replace(line, amount=left))
        carried.append(CarryForward(line.code, line.amount - left, line.source_kind or "input", line.source_id))
        left = ZERO
    return kept, carried


def employer_charge_lines(rules: RuleSet, *, gross: Decimal, contributable: Decimal, earned: Decimal,
                          include_fixed: bool = True) -> list[PayslipLine]:
    """Employer charges (payroll taxes). A fixed charge is per regular payslip, so a correction
    payslip (include_fixed=False) only carries the rate-based ones."""
    bases = {"gross": gross, "contributable": contributable, "earned_base": earned, "base_salary": earned}
    lines: list[PayslipLine] = []
    for rule in rules.employer_charges():
        if rule.formula_type == "rate_x_base":
            base = max(bases[rule.base_ref or "gross"], ZERO)
            rate = rule.default_rate or ZERO
            amount = rules.round(percent_of(base, rate))
        elif include_fixed:
            base, rate, amount = None, None, rules.round(rule.default_amount or ZERO)
        else:
            continue
        if amount == 0:
            continue
        lines.append(PayslipLine(
            section="employer_charge", code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=amount,
            base=base, rate=rate, declaration_code=rule.declaration_code or rule.code, display_order=rule.display_order,
        ))
    return lines


def payslip_totals(lines: Sequence[PayslipLine]) -> PayslipTotals:
    gross = section_total(lines, "earning")
    employee_contrib = section_total(lines, "employee_contribution")
    employer_contrib = section_total(lines, "employer_contribution")
    employer_charges = section_total(lines, "employer_charge")
    tax = section_total(lines, "tax")
    deductions = section_total(lines, "deduction")
    taxable = max((line.base for line in lines if line.section == "tax" and line.base is not None), default=ZERO)
    return PayslipTotals(
        gross=gross,
        contributable=contributable_earnings(lines),
        taxable=taxable,
        employee_contrib=employee_contrib,
        employer_contrib=employer_contrib,
        employer_charges=employer_charges,
        tax=tax,
        deductions=deductions,
        net=gross - employee_contrib - tax - deductions,
        employer_cost=gross + employer_contrib + employer_charges,
    )

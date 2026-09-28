"""Steps 2 and 3: the contributable base, each contribution's ceiling, employee and employer shares."""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import ContributionRule, RuleSet


def contributable_earnings(lines: Iterable[PayslipLine]) -> Decimal:
    total = sum((line.amount for line in lines if line.section == "earning" and line.contributable), ZERO)
    return max(total, ZERO)


def contribution_base(rule: ContributionRule, *, gross: Decimal, contributable: Decimal) -> Decimal:
    base = max(gross if rule.base == "gross" else contributable, ZERO)
    return base if rule.ceiling_monthly is None else min(base, rule.ceiling_monthly)


def contribution_lines(rules: RuleSet, *, gross: Decimal, contributable: Decimal) -> list[PayslipLine]:
    lines: list[PayslipLine] = []
    for rule in sorted(rules.contributions, key=lambda item: (item.display_order, item.code)):
        base = contribution_base(rule, gross=gross, contributable=contributable)
        if base <= 0:
            continue
        for section, rate in (("employee_contribution", rule.employee_rate), ("employer_contribution", rule.employer_rate)):
            amount = rules.round(percent_of(base, rate))
            if amount == 0:
                continue
            lines.append(PayslipLine(
                section=section, code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=amount,
                base=base, rate=rate,
                deductible=section == "employee_contribution" and rule.deductible_from_taxable,
                declaration_code=rule.declaration_code, display_order=rule.display_order,
            ))
    return lines

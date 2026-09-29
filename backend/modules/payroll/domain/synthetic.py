"""A synthetic rule set with round numbers, for engine tests only.

It is NOT the Mali rule set and must never be used to pay anyone: its numbers are chosen so a
payslip can be computed by hand. The Mali draft values live in scripts/payroll_mali_rules.py
and are corrected there by the accountant without touching these tests.
"""
from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal

from modules.payroll.domain.inputs import EmployeeInput
from modules.payroll.domain.rules import (
    ComponentRule,
    ContributionRule,
    FamilyRelief,
    FamilyReliefStep,
    OvertimeRate,
    ProfessionalRelief,
    RuleSet,
    SeniorityStep,
    SeveranceStep,
    TaxBracket,
)

D = Decimal

_MONTHLY_BRACKETS = ((0, 100000, 0), (100000, 300000, 10), (300000, None, 20))


def _component(code, name_en, name_fr, kind, *, taxable=False, contributable=False, formula="fixed",
               base_ref=None, amount=None, rate=None, order=100, section=None, declaration=None) -> ComponentRule:
    default_section = {"earning": "earnings", "deduction": "deductions", "employer_charge": "employer"}[kind]
    return ComponentRule(
        code=code, name_en=name_en, name_fr=name_fr, kind=kind, taxable=taxable, contributable=contributable,
        formula_type=formula, base_ref=base_ref,
        default_amount=None if amount is None else D(amount), default_rate=None if rate is None else D(rate),
        display_order=order, payslip_section=section or default_section, declaration_code=declaration,
    )


def synthetic_rule_set(*, status: str = "confirmed", annualised: bool = False) -> RuleSet:
    factor = 12 if annualised else 1
    brackets = tuple(
        TaxBracket(tax_code="TAX", lower=D(lower * factor), upper=None if upper is None else D(upper * factor),
                   rate=D(rate), annualised=annualised)
        for lower, upper, rate in _MONTHLY_BRACKETS
    )
    return RuleSet(
        id="synthetic",
        country="ZZ",
        valid_from=datetime.date(2020, 1, 1),
        status=status,
        round_to=1,
        round_mode="half_up",
        tax_round_to=10,
        tax_round_mode="down",
        working_days_per_month=D(20),
        working_hours_per_month=D(160),
        components=(
            _component("BASE", "Base salary", "Salaire de base", "earning", taxable=True, contributable=True, order=10),
            _component("UNPAID_ABSENCE", "Unpaid absence", "Absence non payée", "earning", taxable=True, contributable=True, formula="per_day", order=11),
            _component("SENIORITY", "Seniority bonus", "Prime d'ancienneté", "earning", taxable=True, contributable=True, formula="rate_x_base", base_ref="earned_base", order=20),
            _component("OT_DAY", "Overtime (day)", "Heures supplémentaires (jour)", "earning", taxable=True, contributable=True, formula="qty_x_rate", order=30),
            _component("OT_NIGHT", "Overtime (night)", "Heures supplémentaires (nuit)", "earning", taxable=True, contributable=True, formula="qty_x_rate", order=31),
            _component("OT_REST_HOLIDAY", "Overtime (rest day / holiday)", "Heures supplémentaires (repos / férié)", "earning", taxable=True, contributable=True, formula="qty_x_rate", order=32),
            _component("HOUSING", "Housing allowance", "Indemnité de logement", "earning", taxable=True, contributable=True, order=40),
            _component("TRANSPORT", "Transport allowance", "Indemnité de transport", "earning", order=41),
            _component("MEAL", "Meal allowance", "Prime de panier", "earning", formula="per_day", amount=500, order=42),
            _component("BONUS", "Bonus", "Prime exceptionnelle", "earning", taxable=True, contributable=True, order=50),
            _component("LEAVE_INDEMNITY", "Paid-leave indemnity", "Indemnité compensatrice de congés", "earning", taxable=True, contributable=True, formula="per_day", order=60),
            _component("NOTICE_INDEMNITY", "Notice indemnity", "Indemnité de préavis", "earning", taxable=True, contributable=True, order=61),
            _component("SEVERANCE", "Severance pay", "Indemnité de licenciement", "earning", order=62),
            _component("ADVANCE", "Salary advance", "Avance sur salaire", "deduction", order=80),
            _component("LOAN", "Loan instalment", "Échéance de prêt", "deduction", order=81),
            _component("CANTEEN", "Canteen", "Cantine", "deduction", order=82),
            _component("EMP_TAX", "Employer payroll tax", "Taxe patronale", "employer_charge", formula="rate_x_base", base_ref="gross", rate=2, order=90, declaration="EMP_TAX"),
        ),
        contributions=(
            ContributionRule(code="PENSION", name_en="Pension", name_fr="Retraite", base="contributable",
                             employee_rate=D(5), employer_rate=D(10), ceiling_monthly=D(500000),
                             deductible_from_taxable=True, declaration_code="SOCIAL", display_order=10),
            ContributionRule(code="HEALTH", name_en="Health", name_fr="Santé", base="contributable",
                             employee_rate=D(2), employer_rate=D(3), ceiling_monthly=None,
                             deductible_from_taxable=True, declaration_code="HEALTH", display_order=20),
        ),
        tax_brackets=brackets,
        family_reliefs=(
            FamilyRelief(tax_code="TAX", mode="percent_of_tax",
                         steps=(FamilyReliefStep(1, D(10)), FamilyReliefStep(2, D(20))), cap_monthly=None),
        ),
        professional_reliefs=(ProfessionalRelief(tax_code="TAX", percent=D(10), cap_monthly=D(20000)),),
        seniority_scale=(SeniorityStep(3, D(3)), SeniorityStep(5, D(5))),
        overtime_rates=(OvertimeRate("day", D("1.5")), OvertimeRate("night", D(2)), OvertimeRate("rest_holiday", D(2))),
        severance_scale=(SeveranceStep(0, D(20)), SeveranceStep(5, D(25)), SeveranceStep(10, D(30))),
    )


def synthetic_employee(**changes) -> EmployeeInput:
    """400 000 a month, hired 2021-09-01, no end, no dependants — tests change what they need."""
    base = EmployeeInput(
        employee_id="E1",
        base_salary=D(400000),
        pay_frequency="monthly",
        hire_date=datetime.date(2021, 9, 1),
        contract_start=datetime.date(2021, 9, 1),
    )
    return replace(base, **changes)

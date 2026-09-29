"""A rule set as the engine reads it.

Values come from payroll.* rows (loaded by RuleSetService.load); nothing statutory is written
here. Only the component *codes* the engine computes itself are fixed, because the engine needs
to know which row holds the base salary, the overtime bands, and so on.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from modules.payroll.domain.money import round_amount

BASE = "BASE"
UNPAID_ABSENCE = "UNPAID_ABSENCE"
SENIORITY = "SENIORITY"
OT_DAY = "OT_DAY"
OT_NIGHT = "OT_NIGHT"
OT_REST_HOLIDAY = "OT_REST_HOLIDAY"
ADVANCE = "ADVANCE"
LOAN = "LOAN"
LEAVE_INDEMNITY = "LEAVE_INDEMNITY"
NOTICE_INDEMNITY = "NOTICE_INDEMNITY"
SEVERANCE = "SEVERANCE"

OVERTIME_BANDS = ("day", "night", "rest_holiday")
# How a daily-paid worker's worked rest day is paid (see earnings.base_salary_lines).
DAILY_REST_DAY_PAY_MODES = ("overtime_only", "day_rate_and_overtime")
OVERTIME_CODES = {"day": OT_DAY, "night": OT_NIGHT, "rest_holiday": OT_REST_HOLIDAY}

# Components the engine computes itself: code -> (kind, formula_type). A rule set must hold all
# of them before it can be confirmed; their flags (taxable, contributable) and names are data.
SYSTEM_COMPONENTS: dict[str, tuple[str, str]] = {
    BASE: ("earning", "fixed"),
    UNPAID_ABSENCE: ("earning", "per_day"),
    SENIORITY: ("earning", "rate_x_base"),
    OT_DAY: ("earning", "qty_x_rate"),
    OT_NIGHT: ("earning", "qty_x_rate"),
    OT_REST_HOLIDAY: ("earning", "qty_x_rate"),
    LEAVE_INDEMNITY: ("earning", "per_day"),
    NOTICE_INDEMNITY: ("earning", "fixed"),
    SEVERANCE: ("earning", "fixed"),
    ADVANCE: ("deduction", "fixed"),
    LOAN: ("deduction", "fixed"),
}


class RuleSetIncomplete(Exception):
    """The rule set lacks something the payslip needs (a component, an overtime rate…)."""

    def __init__(self, what_en: str, what_fr: str) -> None:
        super().__init__(what_en)
        self.what_en = what_en
        self.what_fr = what_fr


class ComponentMisuse(Exception):
    """A component is used in a way its formula cannot compute (e.g. a qty × rate on a contract)."""

    def __init__(self, message_en: str, message_fr: str) -> None:
        super().__init__(message_en)
        self.message_en = message_en
        self.message_fr = message_fr


@dataclass(frozen=True)
class ComponentRule:
    code: str
    name_en: str
    name_fr: str
    kind: str  # earning | deduction | employer_charge
    taxable: bool
    contributable: bool
    formula_type: str  # fixed | rate_x_base | qty_x_rate | per_day
    base_ref: str | None = None  # base_salary | earned_base | gross | contributable
    default_amount: Decimal | None = None
    default_rate: Decimal | None = None
    display_order: int = 100
    payslip_section: str = "earnings"
    declaration_code: str | None = None


@dataclass(frozen=True)
class ContributionRule:
    code: str
    name_en: str
    name_fr: str
    base: str  # gross | contributable
    employee_rate: Decimal
    employer_rate: Decimal
    ceiling_monthly: Decimal | None
    deductible_from_taxable: bool
    declaration_code: str
    liability_account_code: str | None = None
    display_order: int = 100


@dataclass(frozen=True)
class TaxBracket:
    tax_code: str
    lower: Decimal
    upper: Decimal | None
    rate: Decimal
    annualised: bool


@dataclass(frozen=True)
class FamilyReliefStep:
    dependants: int
    value: Decimal  # percent of the tax, or an amount per month, depending on the relief mode


@dataclass(frozen=True)
class FamilyRelief:
    tax_code: str
    mode: str  # percent_of_tax | amount
    steps: tuple[FamilyReliefStep, ...]
    cap_monthly: Decimal | None = None


@dataclass(frozen=True)
class ProfessionalRelief:
    tax_code: str
    percent: Decimal
    cap_monthly: Decimal | None = None


@dataclass(frozen=True)
class SeniorityStep:
    years_from: int
    percent: Decimal


@dataclass(frozen=True)
class OvertimeRate:
    band_code: str
    multiplier: Decimal


@dataclass(frozen=True)
class SeveranceStep:
    years_from: int
    percent_per_year: Decimal


@dataclass(frozen=True)
class RuleSet:
    id: str
    country: str
    valid_from: datetime.date
    status: str
    round_to: int
    round_mode: str
    tax_round_to: int
    tax_round_mode: str
    working_days_per_month: Decimal
    working_hours_per_month: Decimal
    settlement_reference_months: int = 12
    daily_rest_day_pay: str = "overtime_only"
    components: tuple[ComponentRule, ...] = ()
    contributions: tuple[ContributionRule, ...] = ()
    tax_brackets: tuple[TaxBracket, ...] = ()
    family_reliefs: tuple[FamilyRelief, ...] = ()
    professional_reliefs: tuple[ProfessionalRelief, ...] = ()
    seniority_scale: tuple[SeniorityStep, ...] = ()
    overtime_rates: tuple[OvertimeRate, ...] = ()
    severance_scale: tuple[SeveranceStep, ...] = ()

    def component(self, code: str) -> ComponentRule | None:
        return next((component for component in self.components if component.code == code), None)

    def require(self, code: str) -> ComponentRule:
        component = self.component(code)
        if component is None:
            raise RuleSetIncomplete(f"component {code}", f"rubrique {code}")
        return component

    def overtime_multiplier(self, band: str) -> Decimal:
        rate = next((rate for rate in self.overtime_rates if rate.band_code == band), None)
        if rate is None:
            raise RuleSetIncomplete(f"overtime rate for band {band}", f"taux d'heures supplémentaires de la tranche {band}")
        return rate.multiplier

    def tax_codes(self) -> tuple[str, ...]:
        return tuple(sorted({bracket.tax_code for bracket in self.tax_brackets}))

    def brackets_for(self, tax_code: str) -> tuple[TaxBracket, ...]:
        return tuple(sorted((b for b in self.tax_brackets if b.tax_code == tax_code), key=lambda b: b.lower))

    def family_relief(self, tax_code: str) -> FamilyRelief | None:
        return next((relief for relief in self.family_reliefs if relief.tax_code == tax_code), None)

    def professional_relief(self, tax_code: str) -> ProfessionalRelief | None:
        return next((relief for relief in self.professional_reliefs if relief.tax_code == tax_code), None)

    def employer_charges(self) -> tuple[ComponentRule, ...]:
        charges = [component for component in self.components if component.kind == "employer_charge"]
        return tuple(sorted(charges, key=lambda component: (component.display_order, component.code)))

    def round(self, value: Decimal) -> Decimal:
        return round_amount(value, round_to=self.round_to, mode=self.round_mode)

    def round_tax(self, value: Decimal) -> Decimal:
        return round_amount(value, round_to=self.tax_round_to, mode=self.tax_round_mode)

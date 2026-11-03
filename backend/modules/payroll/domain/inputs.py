"""What the engine is given and what it gives back — plain values, no database."""
from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

# Payslip order: what is earned, what the employee pays, the tax walk, what is withheld, then
# the employer's side (not part of the net).
SECTIONS = (
    "earning",
    "employee_contribution",
    "relief",
    "tax",
    "deduction",
    "employer_contribution",
    "employer_charge",
)
# Where a deduction comes from, in the order they are taken when the net runs short.
SOURCE_KINDS = ("carry_forward", "loan_instalment", "advance", "input")


@dataclass(frozen=True)
class ContractComponent:
    """A recurring component written on the contract (hr.contract_components)."""

    component_code: str
    amount: Decimal | None = None
    rate: Decimal | None = None


@dataclass(frozen=True)
class EmployeeInput:
    employee_id: str
    base_salary: Decimal  # monthly salary, or the day rate when pay_frequency == 'daily'
    pay_frequency: str  # 'monthly' | 'daily'
    hire_date: datetime.date
    contract_start: datetime.date
    contract_end: datetime.date | None = None
    termination_date: datetime.date | None = None
    tax_dependants: int = 0
    components: tuple[ContractComponent, ...] = ()


@dataclass(frozen=True)
class PresenceInput:
    """hr's PresenceService.month_summary for one employee (all counts are ints)."""

    scheduled_days: int = 0
    worked_days: int = 0
    unpaid_absence_days: int = 0
    paid_leave_days: int = 0
    sick_days: int = 0
    holiday_days: int = 0
    holidays_worked_days: int = 0
    rest_days_worked: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    ot_minutes_rest_holiday: int = 0


@dataclass(frozen=True)
class OneOffInput:
    """A monthly input (bonus, canteen…), an advance, a loan instalment or a carried amount."""

    component_code: str
    qty: Decimal | None = None
    amount: Decimal | None = None
    source_kind: str = "input"
    source_id: str | None = None


@dataclass(frozen=True)
class SettlementInput:
    reference_salary: Decimal
    years_of_service: Decimal
    unused_leave_days: Decimal = Decimal(0)
    notice_months: Decimal = Decimal(0)


@dataclass(frozen=True)
class PayslipLine:
    section: str
    code: str
    name_en: str
    name_fr: str
    amount: Decimal
    base: Decimal | None = None
    qty: Decimal | None = None
    rate: Decimal | None = None
    taxable: bool = False
    contributable: bool = False
    deductible: bool = False  # employee contribution that lowers the taxable base
    declaration_code: str | None = None
    display_order: int = 100
    source_kind: str | None = None
    source_id: str | None = None


def section_total(lines: Iterable[PayslipLine], section: str) -> Decimal:
    return sum((line.amount for line in lines if line.section == section), Decimal(0))

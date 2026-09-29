"""The Mali rule-set builder is deterministic and produces a set that could later be confirmed.

No database: a fake service records what create_mali_rule_set would write, and each row goes
through the real service's validators (CHILD_KINDS) and completeness check, so a renamed column
or a value the service would refuse fails here, not in the seed.
"""
from __future__ import annotations

import datetime
import inspect
from decimal import Decimal
from typing import Any

from core.domain.result import Ok
from modules.payroll.api.rule_set_service import CHILD_KINDS, RuleSetService
from modules.payroll.domain.engine import calculate_payslip
from modules.payroll.domain.inputs import ContractComponent, EmployeeInput, OneOffInput, PresenceInput
from modules.payroll.domain.rule_validation import check_complete, relief_from_parameters, validate_rule_set_header
from modules.payroll.domain.rules import (
    ComponentRule,
    ContributionRule,
    FamilyRelief,
    OvertimeRate,
    ProfessionalRelief,
    RuleSet,
    SeniorityStep,
    SeveranceStep,
    TaxBracket,
)
from scripts.payroll_mali_rules import MALI_VALID_FROM, create_mali_rule_set, print_to_confirm

D = Decimal


class RecordingService:
    """Stands in for RuleSetService: records the header and every row, confirms nothing."""

    def __init__(self) -> None:
        self.header: dict[str, Any] | None = None
        self.rows: list[tuple[str, dict[str, Any]]] = []
        self.confirmed = False

    def create_rule_set(self, **kwargs):
        self.header = kwargs
        return Ok({"id": "mali-draft"})

    def add_child(self, *, tenant_id, actor_id, rule_set_id, kind, values):
        assert rule_set_id == "mali-draft"
        self.rows.append((kind, values))
        return Ok({"id": f"row-{len(self.rows)}"})

    def get_rule_set(self, *, tenant_id, rule_set_id):
        return {"id": rule_set_id, "status": "draft", "valid_from": MALI_VALID_FROM.isoformat()}

    def confirm_rule_set(self, **kwargs):
        self.confirmed = True
        raise AssertionError("the seed must leave the Mali rule set as a draft")


def _recorded() -> RecordingService:
    service = RecordingService()
    create_mali_rule_set(service, tenant_id="tenant", actor_id="actor")
    return service


def _as_loaded(service: RecordingService) -> RuleSet:
    """The recorded rows, validated and mapped exactly like RuleSetService.load maps stored rows."""
    header = validate_rule_set_header(service.header)
    assert isinstance(header, Ok), header
    clean: dict[str, list[dict[str, Any]]] = {kind: [] for kind in CHILD_KINDS}
    for kind, values in service.rows:
        checked = CHILD_KINDS[kind].validate(values)
        assert isinstance(checked, Ok), (kind, values, checked)
        clean[kind].append(checked.value)
    reliefs = [relief_from_parameters(row["tax_code"], row["kind"], row["parameters"]) for row in clean["tax_reliefs"]]
    h = header.value
    return RuleSet(
        id="mali-draft", country=h["country"], valid_from=h["valid_from"], status="draft",
        round_to=h["round_to"], round_mode=h["round_mode"], tax_round_to=h["tax_round_to"], tax_round_mode=h["tax_round_mode"],
        working_days_per_month=h["working_days_per_month"], working_hours_per_month=h["working_hours_per_month"],
        settlement_reference_months=h["settlement_reference_months"], daily_rest_day_pay=h["daily_rest_day_pay"],
        components=tuple(ComponentRule(**row) for row in clean["components"]),
        contributions=tuple(ContributionRule(**row) for row in clean["contributions"]),
        tax_brackets=tuple(TaxBracket(tax_code=row["tax_code"], lower=row["lower_bound"], upper=row["upper_bound"],
                                      rate=row["rate"], annualised=row["annualised"]) for row in clean["tax_brackets"]),
        family_reliefs=tuple(relief for relief in reliefs if isinstance(relief, FamilyRelief)),
        professional_reliefs=tuple(relief for relief in reliefs if isinstance(relief, ProfessionalRelief)),
        seniority_scale=tuple(SeniorityStep(**row) for row in clean["seniority_scale"]),
        overtime_rates=tuple(OvertimeRate(**row) for row in clean["overtime_rates"]),
        severance_scale=tuple(SeveranceStep(**row) for row in clean["severance_scale"]),
    )


def test_mali_valid_from_is_the_first_of_a_month():
    assert MALI_VALID_FROM.day == 1


def test_the_header_is_one_the_service_accepts_and_names_the_rest_day_rule():
    header = _recorded().header
    # every argument is a real create_rule_set parameter (a typo would be a TypeError on the server)
    inspect.signature(RuleSetService.create_rule_set).bind(None, **header)
    assert header["country"] == "ML" and header["valid_from"] == MALI_VALID_FROM
    assert header["daily_rest_day_pay"] in ("overtime_only", "day_rate_and_overtime")
    assert isinstance(validate_rule_set_header(header), Ok)


def test_every_row_uses_only_the_services_columns_and_passes_its_validation():
    service = _recorded()
    assert {kind for kind, _ in service.rows} == set(CHILD_KINDS)
    for kind, values in service.rows:
        # the validators drop unknown keys silently, so a misspelt column would be lost, not refused
        assert set(values) <= set(CHILD_KINDS[kind].columns), (kind, sorted(set(values) - set(CHILD_KINDS[kind].columns)))
        assert isinstance(CHILD_KINDS[kind].validate(values), Ok), (kind, values)


def test_the_set_could_be_confirmed_but_the_builder_leaves_it_a_draft():
    service = _recorded()
    assert check_complete(_as_loaded(service)) == []
    assert service.confirmed is False


def test_the_builder_is_deterministic():
    first, second = _recorded(), _recorded()
    assert (first.header, first.rows) == (second.header, second.rows)


def test_the_contributions_declare_under_the_codes_the_employee_identifiers_use():
    # declarations look up an employee's identifier as "<declaration_code>_no" (inps_no, amo_no)
    codes = {values["declaration_code"] for kind, values in _recorded().rows if kind == "contributions"}
    assert codes == {"INPS", "AMO"}


def test_a_month_of_the_seeds_own_shapes_calculates_on_these_rules():
    rules = _as_loaded(_recorded())
    period = datetime.date(2026, 8, 1)
    monthly = EmployeeInput(
        employee_id="M", base_salary=D(250000), pay_frequency="monthly", hire_date=datetime.date(2015, 3, 1),
        contract_start=datetime.date(2015, 3, 1), tax_dependants=3,
        components=(ContractComponent("TRANSPORT", amount=D(15000)), ContractComponent("HOUSING", amount=D(50000))),
    )
    daily = EmployeeInput(
        employee_id="D", base_salary=D(4000), pay_frequency="daily", hire_date=datetime.date(2025, 1, 6),
        contract_start=datetime.date(2025, 1, 6),
    )
    presence = PresenceInput(scheduled_days=26, worked_days=25, unpaid_absence_days=1, ot_minutes_day=240,
                             ot_minutes_night=120, ot_minutes_rest_holiday=480, rest_days_worked=1)
    inputs = [OneOffInput("BONUS", amount=D(25000)), OneOffInput("ADVANCE", amount=D(30000), source_kind="advance"),
              OneOffInput("LOAN", amount=D(25000), source_kind="loan_instalment")]
    for employee in (monthly, daily):
        result = calculate_payslip(employee=employee, presence=presence, rules=rules, period=period, inputs=inputs)
        assert isinstance(result, Ok), (employee.employee_id, result)
        sections = {line.section for line in result.value.lines}
        assert {"earning", "employee_contribution", "tax", "deduction", "employer_contribution", "employer_charge"} <= sections


def test_the_to_confirm_banner_prints_every_table(capsys):
    print_to_confirm()
    out = capsys.readouterr().out
    assert "TO CONFIRM BY ACCOUNTANT" in out and "DRAFT" in out
    service = _recorded()
    for kind, values in service.rows:
        if kind in ("components", "contributions"):
            assert values["code"] in out, values["code"]
    for needle in ("ITS", "family relief", "professional expenses", "seniority", "overtime", "severance",
                   "working days", "working hours", service.header["daily_rest_day_pay"]):
        assert needle in out, needle

"""Helpers the payroll integration tests share. Not imported by production code."""
from __future__ import annotations

import datetime
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from ulid import ULID

from core.domain.result import Ok
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.domain.rule_validation import relief_parameters
from modules.payroll.domain.rules import RuleSet
from modules.payroll.domain.synthetic import synthetic_rule_set

TEST_COUNTRY = "ZZ"  # ISO "user-assigned" code: never a real payroll country


class WrappedConnection:
    """The `db` fixture's connection for router tests: the routes' commit/rollback become no-ops so
    the fixture's final rollback still undoes everything."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def make_user(connection, tenant_id: str) -> str:
    user_id = str(ULID())
    connection.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, tenant_id, f"{user_id}@test.local"),
    )
    return user_id


def rule_rows(rules: RuleSet) -> dict[str, list[dict[str, Any]]]:
    """The domain rule set as the values an admin would type, table by table."""
    return {
        "components": [asdict(component) for component in rules.components],
        "contributions": [asdict(contribution) for contribution in rules.contributions],
        "tax_brackets": [{"tax_code": b.tax_code, "lower_bound": b.lower, "upper_bound": b.upper, "rate": b.rate,
                          "annualised": b.annualised} for b in rules.tax_brackets],
        "tax_reliefs": [{"tax_code": r.tax_code, "kind": "family", "parameters": relief_parameters(r)} for r in rules.family_reliefs]
        + [{"tax_code": r.tax_code, "kind": "professional_expenses", "parameters": relief_parameters(r)} for r in rules.professional_reliefs],
        "seniority_scale": [asdict(step) for step in rules.seniority_scale],
        "overtime_rates": [asdict(rate) for rate in rules.overtime_rates],
        "severance_scale": [asdict(step) for step in rules.severance_scale],
    }


def store_rule_set(connection, *, tenant_id: str, actor_id: str, valid_from: datetime.date, rules: RuleSet | None = None,
                   confirm: bool = True, country: str = TEST_COUNTRY, name: str = "Synthetic test rules") -> str:
    rules = rules or synthetic_rule_set()
    service = RuleSetService(connection)
    created = service.create_rule_set(
        tenant_id=tenant_id, actor_id=actor_id, country=country, name=name, valid_from=valid_from,
        working_days_per_month=rules.working_days_per_month, working_hours_per_month=rules.working_hours_per_month,
        round_to=rules.round_to, round_mode=rules.round_mode, tax_round_to=rules.tax_round_to,
        tax_round_mode=rules.tax_round_mode, settlement_reference_months=rules.settlement_reference_months,
        daily_rest_day_pay=rules.daily_rest_day_pay,
    )
    assert isinstance(created, Ok), created
    rule_set_id = created.value["id"]
    for kind, rows in rule_rows(rules).items():
        for values in rows:
            added = service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind=kind, values=values)
            assert isinstance(added, Ok), added
    if confirm:
        confirmed = service.confirm_rule_set(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id)
        assert isinstance(confirmed, Ok), confirmed
    return rule_set_id


def set_country(connection, *, tenant_id: str, actor_id: str, country: str = TEST_COUNTRY) -> None:
    saved = RuleSetService(connection).save_settings(tenant_id=tenant_id, actor_id=actor_id, country=country)
    assert isinstance(saved, Ok), saved


class FakeSnapshots:
    """Stands in for hr's PayrollSnapshotService with contract-shaped dicts."""

    def __init__(self, employees: list[dict[str, Any]]) -> None:
        self.employees = employees

    def employees_for_period(self, *, tenant_id: str, period: datetime.date,
                             employee_ids: list[str] | None = None) -> list[dict[str, Any]]:
        return [employee for employee in self.employees if employee_ids is None or employee["employee_id"] in employee_ids]


PRESENCE_KEYS = (
    "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "rest_days_worked", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday",
    "night_minutes", "late_minutes",
)


def presence_summary(**counts: int) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in PRESENCE_KEYS}


class FakePresence:
    """Stands in for hr's PresenceService: month summaries by employee, and whether the month is closed."""

    def __init__(self, summaries: dict[str, dict[str, int]] | None = None, *, closed: bool = True) -> None:
        self.summaries = summaries or {}
        self.closed = closed

    def month_summary(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None) -> list[dict[str, Any]]:
        ids = employee_ids if employee_ids is not None else list(self.summaries)
        return [{"employee_id": employee_id, **presence_summary(**self.summaries[employee_id])}
                for employee_id in ids if employee_id in self.summaries]

    def is_month_closed(self, *, tenant_id: str, period: datetime.date) -> bool:
        return self.closed


def snapshot(employee_id: str, *, employee_no: str, full_name: str, base_salary: Decimal = Decimal(400000),
             pay_frequency: str = "monthly", hire_date: datetime.date = datetime.date(2026, 9, 1),
             contract_start: datetime.date | None = None, contract_end: datetime.date | None = None,
             termination_date: datetime.date | None = None, termination_reason: str | None = None,
             department_id: str | None = "dept-a", tax_dependants: int = 0,
             components: tuple[dict[str, Any], ...] = (), payment_methods: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One employee exactly as PayrollSnapshotService.employees_for_period returns it (contract shape)."""
    return {
        "employee_id": employee_id, "employee_no": employee_no, "full_name": full_name,
        "department_id": department_id, "position_id": None, "grade_id": None,
        "hire_date": hire_date, "termination_date": termination_date, "termination_reason": termination_reason,
        "tax_dependants": tax_dependants,
        "contract": {"id": f"contract-{employee_id}", "contract_type": "cdi", "base_salary": base_salary,
                     "weekly_hours": Decimal(40), "pay_frequency": pay_frequency,
                     "start_date": contract_start or hire_date, "end_date": contract_end,
                     "components": [dict(component) for component in components]},
        "payment_methods": payment_methods if payment_methods is not None else [
            {"method": "bank", "bank_name": "BDM", "account_no": f"ML-{employee_no}", "mobile_operator": None,
             "mobile_number": None, "share_percent": Decimal(100), "is_primary": True}],
    }


def approved_run(connection, *, tenant_id: str, calculator: str, approver: str, period: datetime.date,
                 snapshots: Any, presence: Any) -> str:
    """A regular run calculated by one user and approved by another (four-eyes)."""
    from modules.payroll.api.run_service import RunService

    runs = RunService(connection, snapshots=snapshots, presence=presence)
    run_id = runs.create_run(tenant_id=tenant_id, actor_id=calculator, period=period, run_type="regular").value["id"]
    calculated = runs.calculate(tenant_id=tenant_id, actor_id=calculator, run_id=run_id)
    assert isinstance(calculated, Ok), calculated
    approved = runs.approve(tenant_id=tenant_id, actor_id=approver, run_id=run_id)
    assert isinstance(approved, Ok), approved
    return run_id


def insert_run(connection, *, tenant_id: str, actor_id: str, period: datetime.date, status: str = "draft",
               run_type: str = "regular", rule_set_id: str | None = None) -> str:
    """A run row in any status, for tests that need history without calculating it."""
    run_id = str(ULID())
    calculated = status != "draft"
    approved = status in ("approved", "paid", "reversed")
    connection.execute(
        """
        INSERT INTO payroll.runs (id, tenant_id, period, run_type, status, rule_set_id, created_by,
                                  calculated_by, calculated_at, approved_by, approved_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN clock_timestamp() END, %s, CASE WHEN %s THEN clock_timestamp() END)
        """,
        (run_id, tenant_id, period, run_type, status, rule_set_id, actor_id,
         actor_id if calculated else None, calculated, actor_id if approved else None, approved),
    )
    return run_id


def insert_payslip(connection, *, tenant_id: str, run_id: str, employee_id: str, rule_set_id: str,
                   gross: Decimal = Decimal(0), net: Decimal = Decimal(0)) -> str:
    payslip_id = str(ULID())
    connection.execute(
        """
        INSERT INTO payroll.payslips (id, tenant_id, run_id, employee_id, employee_no, full_name, rule_set_id,
            rule_set_status, snapshot, gross, contributable, taxable, employee_contrib, employer_contrib,
            employer_charges, its, deductions, net, employer_cost)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'confirmed', '{}'::jsonb, %s, 0, 0, 0, 0, 0, 0, 0, %s, %s)
        """,
        (payslip_id, tenant_id, run_id, employee_id, employee_id, employee_id, rule_set_id, gross, net, gross),
    )
    return payslip_id

"""What payroll (phase 3) reads from hr for a month, against a real database."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from modules.hr.api.contract_service import ContractService
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.organisation_service import DepartmentService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod

TENANT = "hr-snapshot-test"
SEPTEMBER = datetime.date(2026, 9, 1)
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    department = DepartmentService(db).create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value

    def employee(number: str, hired: datetime.date = D(2020, 1, 1)) -> str:
        return EmployeeService(db).create_employee(
            tenant_id=TENANT, actor_id=actor,
            employee=EmployeeFile(employee_no=number, first_name="Awa", last_name="Traoré", hire_date=hired, department_id=department["id"]),
        ).value["id"]

    def contract(employee_id: str, **overrides) -> dict:
        terms = ContractTerms(**{"employee_id": employee_id, "contract_type": "cdi", "start_date": D(2020, 1, 1), "base_salary": Decimal("250000"), **overrides})
        return ContractService(db).create_contract(tenant_id=TENANT, actor_id=actor, terms=terms).value

    return SimpleNamespace(actor=actor, department_id=department["id"], employee=employee, contract=contract)


def _snapshot(db, period=SEPTEMBER, employee_ids=None):
    return PayrollSnapshotService(db).employees_for_period(tenant_id=TENANT, period=period, employee_ids=employee_ids)


def test_an_employee_under_contract_during_the_month_comes_with_every_field(db, world):
    employee_id = world.employee("S-001")
    world.contract(
        employee_id,
        components=(
            ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),
            ContractComponent(component_code="HOUSING", rate=Decimal("10")),
        ),
    )
    dependants = DependantService(db)
    for dependant in (
        Dependant(kind="spouse", name="Mariam", valid_from=D(2015, 6, 1), dependent_for_tax=True),
        Dependant(kind="child", name="Issa", valid_from=D(2019, 2, 1), dependent_for_tax=True, valid_to=D(2026, 9, 15)),
        Dependant(kind="child", name="Awa", valid_from=D(2010, 1, 1), dependent_for_tax=False),
    ):
        dependants.create_dependant(tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, dependant=dependant)
    payments = PaymentMethodService(db)
    payments.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, valid_from=D(2025, 1, 1),
        methods=[PaymentMethod(method="bank", share_percent=Decimal("100"), is_primary=True, bank_name="BDM-SA", account_no="ML-1")],
    )
    payments.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, valid_from=D(2026, 10, 1),
        methods=[PaymentMethod(method="cash", share_percent=Decimal("100"), is_primary=True)],
    )

    [snapshot] = _snapshot(db)

    assert (snapshot["employee_id"], snapshot["employee_no"], snapshot["full_name"], snapshot["department_id"]) == (
        employee_id, "S-001", "Awa Traoré", world.department_id,
    )
    assert (snapshot["hire_date"], snapshot["termination_date"], snapshot["termination_reason"]) == (D(2020, 1, 1), None, None)
    assert snapshot["tax_dependants"] == 1  # Issa stopped counting on the 15th; the count is taken on the 30th
    contract = snapshot["contract"]
    assert (contract["contract_type"], contract["base_salary"], contract["weekly_hours"], contract["pay_frequency"]) == (
        "cdi", Decimal("250000"), Decimal("40.00"), "monthly",
    )
    assert (contract["start_date"], contract["end_date"]) == (D(2020, 1, 1), None)
    assert contract["components"] == [
        {"component_code": "HOUSING", "amount": None, "rate": Decimal("10.0000")},
        {"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None},
    ]
    assert snapshot["payment_methods"] == [
        {"method": "bank", "bank_name": "BDM-SA", "account_no": "ML-1", "mobile_operator": None, "mobile_number": None,
         "share_percent": Decimal("100.00"), "is_primary": True}
    ]


def test_an_amendment_mid_month_gives_the_new_terms(db, world):
    employee_id = world.employee("S-001")
    old = world.contract(employee_id)
    new = ContractService(db).amend_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=old["id"], effective_date=D(2026, 9, 15), changes={"base_salary": Decimal("300000")}
    ).value
    [snapshot] = _snapshot(db)
    assert (snapshot["contract"]["id"], snapshot["contract"]["base_salary"], snapshot["contract"]["start_date"]) == (
        new["id"], Decimal("300000"), D(2026, 9, 15),
    )


def test_someone_who_left_during_the_month_is_in_it_with_the_exit_and_not_after(db, world):
    employee_id = world.employee("S-001")
    world.contract(employee_id)
    EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, termination_date=D(2026, 9, 20), termination_reason="resignation"
    )
    [snapshot] = _snapshot(db)
    assert (snapshot["termination_date"], snapshot["termination_reason"], snapshot["contract"]["end_date"]) == (
        D(2026, 9, 20), "resignation", D(2026, 9, 20),
    )
    assert _snapshot(db, period=D(2026, 10, 1)) == []


def test_a_draft_contract_puts_nobody_on_the_payroll(db, world):
    employee_id = world.employee("S-001")
    world.contract(employee_id, status="draft")
    assert _snapshot(db) == []


def test_someone_hired_during_the_month_is_in_it_with_no_payment_method_yet(db, world):
    employee_id = world.employee("S-001", hired=D(2026, 9, 10))
    world.contract(employee_id, start_date=D(2026, 9, 10))
    [snapshot] = _snapshot(db)
    assert (snapshot["contract"]["start_date"], snapshot["payment_methods"], snapshot["tax_dependants"]) == (D(2026, 9, 10), [], 0)


def test_the_list_can_be_narrowed_to_some_employees(db, world):
    first, second = world.employee("S-001"), world.employee("S-002")
    world.contract(first)
    world.contract(second)
    assert [s["employee_no"] for s in _snapshot(db)] == ["S-001", "S-002"]
    assert [s["employee_id"] for s in _snapshot(db, employee_ids=[second])] == [second]


def test_a_period_must_be_the_first_of_the_month(db):
    with pytest.raises(ValueError):
        PayrollSnapshotService(db).employees_for_period(tenant_id=TENANT, period=D(2026, 9, 15))

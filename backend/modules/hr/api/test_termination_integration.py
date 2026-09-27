"""Leaving: the exit closes the contract in force on that day and is recorded on the file."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.contract_service import ContractService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.contract import ContractTerms
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-termination-test"
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor,
        employee=EmployeeFile(employee_no="T-001", first_name="Seydou", last_name="Diarra", hire_date=D(2024, 1, 1)),
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def _contract(db, world, **overrides) -> dict:
    terms = ContractTerms(
        **{"employee_id": world.employee_id, "contract_type": "cdi", "start_date": D(2024, 1, 1), "base_salary": Decimal("120000"), **overrides}
    )
    return ContractService(db).create_contract(tenant_id=TENANT, actor_id=world.actor, terms=terms).value


def _terminate(db, world, day=D(2026, 9, 30), reason="resignation"):
    return EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, termination_date=day, termination_reason=reason
    )


def test_terminating_closes_the_contract_in_force_and_flags_the_file(db, world):
    contract = _contract(db, world)
    left = _terminate(db, world)
    assert isinstance(left, Ok)
    assert (left.value["status"], left.value["termination_date"], left.value["termination_reason"]) == ("terminated", "2026-09-30", "resignation")
    closed = ContractService(db).get_contract(tenant_id=TENANT, contract_id=contract["id"])
    assert (closed["end_date"], closed["end_reason"], closed["status"]) == ("2026-09-30", "resignation", "terminated")
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'employee.terminated'", (world.employee_id,)
    ).fetchone()[0]
    assert payload["closed_contract_ids"] == [contract["id"]]


def test_a_cdd_left_at_its_term_expires(db, world):
    cdd = _contract(db, world, contract_type="cdd", end_date=D(2026, 12, 31))
    _terminate(db, world, day=D(2026, 12, 31), reason="term_reached")
    assert ContractService(db).get_contract(tenant_id=TENANT, contract_id=cdd["id"])["status"] == "expired"


def test_a_signed_contract_starting_after_the_exit_blocks_it(db, world):
    _contract(db, world, start_date=D(2027, 1, 1))
    refused = _terminate(db, world)
    assert isinstance(refused, Err) and refused.code == "CONTRACT_AFTER_TERMINATION"
    assert EmployeeService(db).get_employee(tenant_id=TENANT, employee_id=world.employee_id)["status"] == "active"


def test_an_employee_leaves_once_and_gets_no_new_contract_after(db, world):
    _contract(db, world)
    assert isinstance(_terminate(db, world), Ok)
    assert _terminate(db, world).code == "ALREADY_TERMINATED"
    refused = ContractService(db).create_contract(
        tenant_id=TENANT, actor_id=world.actor,
        terms=ContractTerms(employee_id=world.employee_id, contract_type="cdi", start_date=D(2027, 1, 1), base_salary=Decimal("1")),
    )
    assert isinstance(refused, Err) and refused.code == "EMPLOYEE_TERMINATED"


def test_leaving_without_a_contract_still_records_the_exit(db, world):
    left = _terminate(db, world)
    assert left.value["status"] == "terminated"


def test_the_route_needs_manage_employees_and_answers_409_when_already_gone(hr_api):
    hr_api.grant("hr.manage_employees")
    body = {"employee_no": "T-9", "first_name": "Awa", "last_name": "Koné", "hire_date": "2024-01-01"}
    employee_id = hr_api.client.post("/hr/employees", json=body).json()["id"]
    exit_body = {"termination_date": "2026-09-30", "termination_reason": "resignation"}
    first = hr_api.client.post(f"/hr/employees/{employee_id}/terminate", json=exit_body)
    assert first.status_code == 200 and first.json()["status"] == "terminated"
    assert hr_api.client.post(f"/hr/employees/{employee_id}/terminate", json=exit_body).status_code == 409

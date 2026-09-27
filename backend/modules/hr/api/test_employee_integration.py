"""The employee file against a real database (rolled back after each test)."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.organisation_service import DepartmentService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-employee-test"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _file(**overrides) -> EmployeeFile:
    return EmployeeFile(**{"employee_no": "E-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": datetime.date(2024, 3, 1), **overrides})


def test_a_created_file_reads_back_with_its_names_resolved(db, actor):
    department = DepartmentService(db).create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value
    created = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor, employee=_file(department_id=department["id"], national_id="NINA-1", badge_no="B-1")
    )
    assert isinstance(created, Ok)
    record = created.value
    assert (record["full_name"], record["department_name"], record["national_id"], record["hire_date"]) == (
        "Awa Traoré", "Production", "NINA-1", "2024-03-01",
    )
    [row] = EmployeeService(db).list_employees(TENANT)
    assert (row["badge_no"], row["contract_type"]) == ("B-1", None)
    assert "national_id" not in row


def test_a_badge_is_given_to_one_employee_only(db, actor):
    service = EmployeeService(db)
    assert isinstance(service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(badge_no="B-1")), Ok)
    refused = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(employee_no="E-002", badge_no="B-1"))
    assert isinstance(refused, Err) and refused.code == "BADGE_TAKEN"
    assert len(service.list_employees(TENANT)) == 1  # the savepoint left the transaction usable


def test_employees_without_a_badge_do_not_collide(db, actor):
    service = EmployeeService(db)
    assert isinstance(service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(badge_no=" ")), Ok)
    assert isinstance(service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(employee_no="E-002")), Ok)


def test_a_duplicate_employee_number_is_refused(db, actor):
    service = EmployeeService(db)
    service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file())
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file()).code == "DUPLICATE_EMPLOYEE_NO"


def test_a_user_account_links_to_one_employee_and_is_found_back(db, actor):
    service = EmployeeService(db)
    first = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(user_id=actor, national_id="NINA-1")).value
    own = service.get_by_user(tenant_id=TENANT, user_id=actor)
    assert (own["id"], own["user_email"], own["national_id"]) == (first["id"], f"{actor}@test.local", "NINA-1")
    refused = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(employee_no="E-002", user_id=actor))
    assert isinstance(refused, Err) and refused.code == "USER_ALREADY_LINKED"
    assert service.get_by_user(tenant_id=TENANT, user_id="someone-else") is None


def test_unknown_references_are_refused(db, actor):
    service = EmployeeService(db)
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(department_id="nowhere")).code == "NOT_FOUND"
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(user_id="nobody")).code == "NOT_FOUND"


def test_an_edit_leaves_unmentioned_fields_alone_and_audits_only_names_of_sensitive_ones(db, actor):
    service = EmployeeService(db)
    created = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(phone="70 00 00 00")).value
    updated = service.update_employee(
        tenant_id=TENANT, actor_id=actor, employee_id=created["id"], changes={"national_id": "NINA-9", "site": "Usine"}
    )
    assert (updated.value["phone"], updated.value["national_id"], updated.value["site"]) == ("70 00 00 00", "NINA-9", "Usine")
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'employee.updated'", (created["id"],)
    ).fetchone()[0]
    assert payload == {"changed": {"site": "Usine"}, "sensitive_changed": ["national_id"]}


def test_an_edit_can_clear_a_field(db, actor):
    service = EmployeeService(db)
    created = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(phone="70 00 00 00")).value
    cleared = service.update_employee(tenant_id=TENANT, actor_id=actor, employee_id=created["id"], changes={"phone": None})
    assert cleared.value["phone"] is None


def test_leaving_is_not_an_edit(db, actor):
    service = EmployeeService(db)
    created = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file()).value
    refused = service.update_employee(
        tenant_id=TENANT, actor_id=actor, employee_id=created["id"],
        changes={"status": "terminated", "termination_date": datetime.date(2026, 9, 30), "termination_reason": "resignation"},
    )
    assert isinstance(refused, Err) and refused.code == "INVALID_TRANSITION"
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(
        employee_no="E-002", status="terminated", termination_date=datetime.date(2026, 9, 30), termination_reason="resignation",
    )).code == "INVALID_STATUS"

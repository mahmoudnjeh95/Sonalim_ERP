"""Departments, positions and grades against a real database (rolled back after each test)."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.organisation_service import DepartmentService, GradeService, PositionService

TENANT = "hr-organisation-test"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _actions(db, entity_id: str) -> list[str]:
    rows = db.execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (entity_id,)).fetchall()
    return sorted(row[0] for row in rows)


def test_a_duplicate_department_code_is_refused_and_the_transaction_stays_usable(db, actor):
    service = DepartmentService(db)
    assert isinstance(service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production"), Ok)
    refused = service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Autre")
    assert isinstance(refused, Err) and refused.code == "DUPLICATE_CODE"
    assert [d["code"] for d in service.list_departments(TENANT)] == ["PROD"]


def test_a_department_edit_changes_only_what_it_names_and_is_audited(db, actor):
    service = DepartmentService(db)
    created = service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value
    updated = service.update_department(tenant_id=TENANT, actor_id=actor, department_id=created["id"], changes={"name": "Production pâtes"})
    assert (updated.value["code"], updated.value["name"]) == ("PROD", "Production pâtes")
    assert _actions(db, created["id"]) == ["department.created", "department.updated"]


def test_an_unknown_manager_or_department_is_refused(db, actor):
    service = DepartmentService(db)
    refused = service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production", manager_employee_id="nobody")
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND"
    assert service.update_department(tenant_id=TENANT, actor_id=actor, department_id="nothing", changes={}).code == "NOT_FOUND"


def test_a_position_lists_its_department_and_headcount(db, actor):
    department = DepartmentService(db).create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value
    positions = PositionService(db)
    created = positions.create_position(
        tenant_id=TENANT, actor_id=actor, code="OP-EXT", title="Opérateur extrusion", department_id=department["id"], headcount_budget=12
    )
    assert isinstance(created, Ok)
    db.execute(
        "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, position_id) "
        "VALUES (%s, %s, 'P-1', 'Awa', 'Traoré', '2024-01-01', %s)",
        (str(ULID()), TENANT, created.value["id"]),
    )
    listed = positions.list_positions(TENANT)
    assert [(p["code"], p["department_name"], p["headcount_budget"], p["headcount"]) for p in listed] == [
        ("OP-EXT", "Production", 12, 1)
    ]


def test_a_position_budget_can_be_cleared_and_a_taken_code_refused(db, actor):
    positions = PositionService(db)
    first = positions.create_position(tenant_id=TENANT, actor_id=actor, code="OP", title="Opérateur", headcount_budget=3).value
    second = positions.create_position(tenant_id=TENANT, actor_id=actor, code="MAG", title="Magasinier").value
    cleared = positions.update_position(tenant_id=TENANT, actor_id=actor, position_id=first["id"], changes={"headcount_budget": None})
    assert cleared.value["headcount_budget"] is None
    taken = positions.update_position(tenant_id=TENANT, actor_id=actor, position_id=second["id"], changes={"code": "OP"})
    assert isinstance(taken, Err) and taken.code == "DUPLICATE_CODE"


def test_a_grade_revision_is_a_new_row_but_the_same_date_twice_is_refused(db, actor):
    grades = GradeService(db)
    first = dict(
        tenant_id=TENANT, actor_id=actor, code="OS1", category="3", echelon="A",
        base_salary=Decimal("75000"), valid_from=datetime.date(2026, 1, 1),
    )
    assert isinstance(grades.create_grade(**first), Ok)
    assert isinstance(grades.create_grade(**{**first, "valid_from": datetime.date(2027, 1, 1), "base_salary": Decimal("80000")}), Ok)
    refused = grades.create_grade(**first)
    assert isinstance(refused, Err) and refused.code == "DUPLICATE_CODE"
    assert [(g["valid_from"], g["base_salary"]) for g in grades.list_grades(TENANT)] == [
        ("2027-01-01", Decimal("80000")),
        ("2026-01-01", Decimal("75000")),
    ]

"""Departments, positions and grades: how the plant is organised and the pay grid it follows."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace
from decimal import Decimal

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, execute_guarded, json_safe, missing_reference
from modules.hr.domain.organisation import (
    DepartmentInput,
    GradeInput,
    PositionInput,
    validate_department,
    validate_grade,
    validate_position,
)

_DEPARTMENT_TAKEN = {
    "departments_tenant_id_code_key": Err("DUPLICATE_CODE", "department code already exists", "ce code de département existe déjà")
}
_POSITION_TAKEN = {"hr_positions_code_key": Err("DUPLICATE_CODE", "position code already exists", "ce code de poste existe déjà")}
_GRADE_TAKEN = {
    "hr_grades_code_valid_from_key": Err(
        "DUPLICATE_CODE", "this grade already has a row from that date", "cette catégorie a déjà une ligne à cette date"
    )
}

_DEPARTMENTS = """
    SELECT d.id, d.code, d.name, d.manager_employee_id, m.first_name || ' ' || m.last_name,
           COUNT(e.id) FILTER (WHERE e.status <> 'terminated')
    FROM hr.departments d
    LEFT JOIN hr.employees m ON m.id = d.manager_employee_id
    LEFT JOIN hr.employees e ON e.department_id = d.id AND e.tenant_id = d.tenant_id
    WHERE d.tenant_id = %s {extra}
    GROUP BY d.id, m.first_name, m.last_name
    ORDER BY d.name
"""
_POSITIONS = """
    SELECT p.id, p.code, p.title, p.department_id, d.name, p.headcount_budget,
           COUNT(e.id) FILTER (WHERE e.status <> 'terminated')
    FROM hr.positions p
    LEFT JOIN hr.departments d ON d.id = p.department_id
    LEFT JOIN hr.employees e ON e.position_id = p.id AND e.tenant_id = p.tenant_id
    WHERE p.tenant_id = %s {extra}
    GROUP BY p.id, d.name
    ORDER BY p.code
"""
_GRADES = "SELECT id, code, category, echelon, base_salary, valid_from FROM hr.grades WHERE tenant_id = %s {extra} ORDER BY code, valid_from DESC"


def _department(row) -> dict:
    return {"id": row[0], "code": row[1], "name": row[2], "manager_employee_id": row[3], "manager_name": row[4], "employee_count": row[5]}


def _position(row) -> dict:
    return {
        "id": row[0],
        "code": row[1],
        "title": row[2],
        "department_id": row[3],
        "department_name": row[4],
        "headcount_budget": row[5],
        "headcount": row[6],
    }


def _grade(row) -> dict:
    return {"id": row[0], "code": row[1], "category": row[2], "echelon": row[3], "base_salary": row[4], "valid_from": row[5].isoformat()}


class DepartmentService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_departments(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(_DEPARTMENTS.format(extra=""), (tenant_id,)).fetchall()
        return [_department(row) for row in rows]

    def get_department(self, *, tenant_id: str, department_id: str) -> dict | None:
        row = self.connection.execute(_DEPARTMENTS.format(extra="AND d.id = %s"), (tenant_id, department_id)).fetchone()
        return None if row is None else _department(row)

    def create_department(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, manager_employee_id: str | None = None
    ) -> Result[dict]:
        validated = validate_department(DepartmentInput(code=code, name=name, manager_employee_id=manager_employee_id))
        if isinstance(validated, Err):
            return validated
        department = validated.value
        refused = missing_reference(self.connection, "hr.employees", tenant_id, department.manager_employee_id, "manager", "responsable")
        if refused:
            return refused
        department_id = str(ULID())
        refused = execute_guarded(
            self.connection,
            "INSERT INTO hr.departments (id, tenant_id, code, name, manager_employee_id) VALUES (%s, %s, %s, %s, %s)",
            (department_id, tenant_id, department.code, department.name, department.manager_employee_id),
            _DEPARTMENT_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="department.created",
            entity_type="department", entity_id=department_id, payload=json_safe(department),
        )
        return Ok(self.get_department(tenant_id=tenant_id, department_id=department_id))

    def update_department(self, *, tenant_id: str, actor_id: str, department_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            "SELECT code, name, manager_employee_id FROM hr.departments WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (department_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "department not found", "département introuvable")
        current = DepartmentInput(*row)
        validated = validate_department(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        department = validated.value
        refused = missing_reference(self.connection, "hr.employees", tenant_id, department.manager_employee_id, "manager", "responsable")
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            "UPDATE hr.departments SET code = %s, name = %s, manager_employee_id = %s WHERE id = %s AND tenant_id = %s",
            (department.code, department.name, department.manager_employee_id, department_id, tenant_id),
            _DEPARTMENT_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="department.updated",
            entity_type="department", entity_id=department_id, payload=change_payload(asdict(current), asdict(department)),
        )
        return Ok(self.get_department(tenant_id=tenant_id, department_id=department_id))


class PositionService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_positions(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(_POSITIONS.format(extra=""), (tenant_id,)).fetchall()
        return [_position(row) for row in rows]

    def get_position(self, *, tenant_id: str, position_id: str) -> dict | None:
        row = self.connection.execute(_POSITIONS.format(extra="AND p.id = %s"), (tenant_id, position_id)).fetchone()
        return None if row is None else _position(row)

    def create_position(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        title: str,
        department_id: str | None = None,
        headcount_budget: int | None = None,
    ) -> Result[dict]:
        validated = validate_position(PositionInput(code=code, title=title, department_id=department_id, headcount_budget=headcount_budget))
        if isinstance(validated, Err):
            return validated
        position = validated.value
        refused = missing_reference(self.connection, "hr.departments", tenant_id, position.department_id, "department", "département")
        if refused:
            return refused
        position_id = str(ULID())
        refused = execute_guarded(
            self.connection,
            "INSERT INTO hr.positions (id, tenant_id, code, title, department_id, headcount_budget) VALUES (%s, %s, %s, %s, %s, %s)",
            (position_id, tenant_id, position.code, position.title, position.department_id, position.headcount_budget),
            _POSITION_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="position.created",
            entity_type="position", entity_id=position_id, payload=json_safe(position),
        )
        return Ok(self.get_position(tenant_id=tenant_id, position_id=position_id))

    def update_position(self, *, tenant_id: str, actor_id: str, position_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            "SELECT code, title, department_id, headcount_budget FROM hr.positions WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (position_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "position not found", "poste introuvable")
        current = PositionInput(*row)
        validated = validate_position(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        position = validated.value
        refused = missing_reference(self.connection, "hr.departments", tenant_id, position.department_id, "department", "département")
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            "UPDATE hr.positions SET code = %s, title = %s, department_id = %s, headcount_budget = %s WHERE id = %s AND tenant_id = %s",
            (position.code, position.title, position.department_id, position.headcount_budget, position_id, tenant_id),
            _POSITION_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="position.updated",
            entity_type="position", entity_id=position_id, payload=change_payload(asdict(current), asdict(position)),
        )
        return Ok(self.get_position(tenant_id=tenant_id, position_id=position_id))


class GradeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_grades(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(_GRADES.format(extra=""), (tenant_id,)).fetchall()
        return [_grade(row) for row in rows]

    def get_grade(self, *, tenant_id: str, grade_id: str) -> dict | None:
        row = self.connection.execute(_GRADES.format(extra="AND id = %s"), (tenant_id, grade_id)).fetchone()
        return None if row is None else _grade(row)

    def create_grade(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        category: str,
        echelon: str,
        base_salary: Decimal,
        valid_from: datetime.date,
    ) -> Result[dict]:
        validated = validate_grade(GradeInput(code=code, category=category, echelon=echelon, base_salary=base_salary, valid_from=valid_from))
        if isinstance(validated, Err):
            return validated
        grade = validated.value
        grade_id = str(ULID())
        refused = execute_guarded(
            self.connection,
            "INSERT INTO hr.grades (id, tenant_id, code, category, echelon, base_salary, valid_from) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (grade_id, tenant_id, grade.code, grade.category, grade.echelon, grade.base_salary, grade.valid_from),
            _GRADE_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="grade.created",
            entity_type="grade", entity_id=grade_id, payload=json_safe(grade),
        )
        return Ok(self.get_grade(tenant_id=tenant_id, grade_id=grade_id))

    def update_grade(self, *, tenant_id: str, actor_id: str, grade_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            "SELECT code, category, echelon, base_salary, valid_from FROM hr.grades WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (grade_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "grade not found", "catégorie introuvable")
        current = GradeInput(*row)
        validated = validate_grade(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        grade = validated.value
        refused = execute_guarded(
            self.connection,
            "UPDATE hr.grades SET code = %s, category = %s, echelon = %s, base_salary = %s, valid_from = %s WHERE id = %s AND tenant_id = %s",
            (grade.code, grade.category, grade.echelon, grade.base_salary, grade.valid_from, grade_id, tenant_id),
            _GRADE_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="grade.updated",
            entity_type="grade", entity_id=grade_id, payload=change_payload(asdict(current), asdict(grade)),
        )
        return Ok(self.get_grade(tenant_id=tenant_id, grade_id=grade_id))

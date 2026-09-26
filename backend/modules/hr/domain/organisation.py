"""Departments, positions and grades: shape rules, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from core.domain.result import Err, Ok, Result
from modules.hr.domain.money import invalid_amount, is_whole_amount


@dataclass(frozen=True)
class DepartmentInput:
    code: str
    name: str
    manager_employee_id: str | None = None


@dataclass(frozen=True)
class PositionInput:
    code: str
    title: str
    department_id: str | None = None
    headcount_budget: int | None = None


@dataclass(frozen=True)
class GradeInput:
    code: str
    category: str
    echelon: str
    base_salary: Decimal | None
    valid_from: datetime.date | None


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def validate_department(department: DepartmentInput) -> Result[DepartmentInput]:
    if _blank(department.code) or _blank(department.name):
        return Err("INVALID_DEPARTMENT", "department code and name are required", "le code et le nom du département sont obligatoires")
    return Ok(
        DepartmentInput(
            code=department.code.strip(),
            name=department.name.strip(),
            manager_employee_id=department.manager_employee_id or None,
        )
    )


def validate_position(position: PositionInput) -> Result[PositionInput]:
    if _blank(position.code) or _blank(position.title):
        return Err("INVALID_POSITION", "position code and title are required", "le code et l'intitulé du poste sont obligatoires")
    if position.headcount_budget is not None and position.headcount_budget < 0:
        return Err("INVALID_POSITION", "the headcount budget cannot be negative", "l'effectif budgété ne peut pas être négatif")
    return Ok(
        PositionInput(
            code=position.code.strip(),
            title=position.title.strip(),
            department_id=position.department_id or None,
            headcount_budget=position.headcount_budget,
        )
    )


def validate_grade(grade: GradeInput) -> Result[GradeInput]:
    if _blank(grade.code) or _blank(grade.category) or _blank(grade.echelon) or grade.valid_from is None:
        return Err(
            "INVALID_GRADE",
            "grade code, category, echelon and start date are required",
            "le code, la catégorie, l'échelon et la date de début de la grille sont obligatoires",
        )
    if not is_whole_amount(grade.base_salary):
        return invalid_amount("the grade minimum", "le minimum de la catégorie")
    return Ok(
        GradeInput(
            code=grade.code.strip(),
            category=grade.category.strip(),
            echelon=grade.echelon.strip(),
            base_salary=grade.base_salary,
            valid_from=grade.valid_from,
        )
    )

"""Request bodies of the hr routes. A PATCH body's unset fields mean "leave it as it is" (the
router passes model_dump(exclude_unset=True)); a field sent as null means "clear it"."""
from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    code: str
    name: str
    manager_employee_id: str | None = None


class DepartmentPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    manager_employee_id: str | None = None


class PositionCreate(BaseModel):
    code: str
    title: str
    department_id: str | None = None
    headcount_budget: int | None = None


class PositionPatch(BaseModel):
    code: str | None = None
    title: str | None = None
    department_id: str | None = None
    headcount_budget: int | None = None


class GradeCreate(BaseModel):
    code: str
    category: str
    echelon: str
    base_salary: Decimal
    valid_from: datetime.date


class GradePatch(BaseModel):
    code: str | None = None
    category: str | None = None
    echelon: str | None = None
    base_salary: Decimal | None = None
    valid_from: datetime.date | None = None

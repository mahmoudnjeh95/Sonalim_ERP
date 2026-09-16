from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.domain.result import Err, Ok, Result

EMPLOYEE_STATUSES = {"active", "on_leave", "inactive"}
LEAVE_STATUSES = {"pending", "approved", "rejected", "cancelled"}


@dataclass(frozen=True)
class Employee:
    id: str
    employee_no: str
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    department_id: str | None
    job_title: str | None
    hire_date: date
    status: str


def validate_employee(*, employee_no: str, first_name: str, last_name: str, hire_date: date, status: str) -> Result[None]:
    if not employee_no.strip() or not first_name.strip() or not last_name.strip():
        return Err("INVALID_EMPLOYEE", "employee number and names are required")
    if status not in EMPLOYEE_STATUSES:
        return Err("INVALID_STATUS", f"status must be one of {sorted(EMPLOYEE_STATUSES)}")
    return Ok(None)


def validate_leave(*, start_date: date, end_date: date, status: str = "pending") -> Result[None]:
    if end_date < start_date:
        return Err("INVALID_DATES", "leave end date cannot be before its start date")
    if status not in LEAVE_STATUSES:
        return Err("INVALID_STATUS", f"status must be one of {sorted(LEAVE_STATUSES)}")
    return Ok(None)

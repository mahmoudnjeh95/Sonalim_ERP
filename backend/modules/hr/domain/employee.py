"""The employee file: who the person is, how HR reaches them, where they sit in the plant and
how their employment ended. Pure rules, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, fields, replace

from core.domain.result import Err, Ok, Result

EMPLOYEE_STATUSES = ("active", "on_leave", "inactive", "terminated")
GENDERS = ("male", "female")
MARITAL_STATUSES = ("single", "married", "divorced", "widowed")
# Why a contract or an employment ended. 'amended' only ever ends a contract: an avenant
# replaces it with a new one and the person stays employed.
END_REASONS = (
    "term_reached",
    "resignation",
    "dismissal",
    "trial_termination",
    "mutual_agreement",
    "retirement",
    "death",
    "amended",
    "other",
)
TERMINATION_REASONS = tuple(reason for reason in END_REASONS if reason != "amended")


@dataclass(frozen=True)
class EmployeeFile:
    employee_no: str
    first_name: str
    last_name: str
    hire_date: datetime.date
    status: str = "active"
    email: str | None = None
    phone: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    user_id: str | None = None
    gender: str | None = None
    birth_date: datetime.date | None = None
    birth_place: str | None = None
    nationality: str | None = None
    national_id: str | None = None
    inps_no: str | None = None
    amo_no: str | None = None
    marital_status: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    badge_no: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    site: str | None = None
    termination_date: datetime.date | None = None
    termination_reason: str | None = None


# Field names in declaration order; they are also the column names in hr.employees.
FIELDS = tuple(field.name for field in fields(EmployeeFile))
EDITABLE_FIELDS = tuple(name for name in FIELDS if name != "employee_no")
_REQUIRED_TEXT = ("employee_no", "first_name", "last_name")


def _normalized(employee: EmployeeFile) -> EmployeeFile:
    """Trim every text field; an optional one left blank is stored as NULL, not ''."""
    values: dict[str, object] = {}
    for name in FIELDS:
        value = getattr(employee, name)
        if isinstance(value, str):
            value = value.strip()
            if value == "" and name not in _REQUIRED_TEXT:
                value = None
        values[name] = value
    return EmployeeFile(**values)


def validate_employee_file(employee: EmployeeFile) -> Result[EmployeeFile]:
    candidate = _normalized(employee)
    if not candidate.employee_no or not candidate.first_name or not candidate.last_name or candidate.hire_date is None:
        return Err(
            "INVALID_EMPLOYEE",
            "employee number, names and hire date are required",
            "le matricule, les noms et la date d'embauche sont obligatoires",
        )
    if candidate.status not in EMPLOYEE_STATUSES:
        return Err(
            "INVALID_STATUS",
            f"status must be one of {', '.join(EMPLOYEE_STATUSES)}",
            f"le statut doit être l'un de {', '.join(EMPLOYEE_STATUSES)}",
        )
    if candidate.gender is not None and candidate.gender not in GENDERS:
        return Err("INVALID_CHOICE", "unknown gender", "sexe inconnu")
    if candidate.marital_status is not None and candidate.marital_status not in MARITAL_STATUSES:
        return Err("INVALID_CHOICE", "unknown marital status", "situation matrimoniale inconnue")
    if candidate.birth_date is not None and candidate.birth_date >= candidate.hire_date:
        return Err("INVALID_DATES", "the birth date must precede the hire date", "la date de naissance doit précéder la date d'embauche")
    terminated = candidate.status == "terminated"
    if terminated != (candidate.termination_date is not None and candidate.termination_reason is not None):
        return Err(
            "INVALID_TERMINATION",
            "a person who left has an exit date and reason, and only they do",
            "une personne sortie a une date et un motif de sortie, et elle seule",
        )
    if candidate.termination_reason is not None and candidate.termination_reason not in TERMINATION_REASONS:
        return Err("INVALID_TERMINATION", "unknown exit reason", "motif de sortie inconnu")
    if candidate.termination_date is not None and candidate.termination_date < candidate.hire_date:
        return Err("INVALID_DATES", "the exit date cannot precede the hire date", "la date de sortie ne peut pas précéder la date d'embauche")
    return Ok(candidate)


def terminate(employee: EmployeeFile, *, termination_date: datetime.date, termination_reason: str) -> Result[EmployeeFile]:
    """The file of someone who leaves on `termination_date` (the last day worked)."""
    if employee.status == "terminated":
        return Err("ALREADY_TERMINATED", "this employee has already left", "cet employé est déjà sorti")
    return validate_employee_file(
        replace(employee, status="terminated", termination_date=termination_date, termination_reason=termination_reason)
    )

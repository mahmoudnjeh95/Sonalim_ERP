"""The employee file: list, read, create and edit. Leaving closes contracts, so
terminate_employee (Task 7) works with ContractService."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, execute_guarded, iso_dates, missing_reference
from modules.hr.domain.employee import EDITABLE_FIELDS, FIELDS, EmployeeFile, validate_employee_file
from modules.hr.domain.sensitive import EMPLOYEE_FIELDS

_UNIQUE_REFUSALS = {
    "employees_tenant_id_employee_no_key": Err("DUPLICATE_EMPLOYEE_NO", "employee number already exists", "ce matricule existe déjà"),
    "hr_employees_badge_key": Err(
        "BADGE_TAKEN", "this badge number is already given to another employee", "ce numéro de badge est déjà attribué à un autre employé"
    ),
    "hr_employees_user_key": Err(
        "USER_ALREADY_LINKED", "this user account is already linked to another employee", "ce compte utilisateur est déjà lié à un autre employé"
    ),
}
_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")
_REFERENCES = (
    ("department_id", "hr.departments", "department", "département"),
    ("position_id", "hr.positions", "position", "poste"),
    ("grade_id", "hr.grades", "grade", "catégorie"),
)
_INSERT = f"INSERT INTO hr.employees (id, tenant_id, {', '.join(FIELDS)}) VALUES ({', '.join(['%s'] * (len(FIELDS) + 2))})"
_UPDATE = "UPDATE hr.employees SET " + ", ".join(f"{name} = %s" for name in EDITABLE_FIELDS) + " WHERE id = %s AND tenant_id = %s"
_FILE_COLUMNS = ", ".join(f"e.{name}" for name in FIELDS)
_SELECT_FILE = f"""
    SELECT e.id, {_FILE_COLUMNS}, d.name, p.title, g.code, u.email
    FROM hr.employees e
    LEFT JOIN hr.departments d ON d.id = e.department_id
    LEFT JOIN hr.positions p ON p.id = e.position_id
    LEFT JOIN hr.grades g ON g.id = e.grade_id
    LEFT JOIN core.users u ON u.id = e.user_id
    WHERE e.id = %s AND e.tenant_id = %s
"""


def _file_record(row) -> dict:
    count = len(FIELDS)
    employee = EmployeeFile(*row[1 : 1 + count])
    department_name, position_title, grade_code, user_email = row[1 + count :]
    return {
        "id": row[0],
        **iso_dates(asdict(employee)),
        "full_name": f"{employee.first_name} {employee.last_name}",
        "department_name": department_name,
        "position_title": position_title,
        "grade_code": grade_code,
        "user_email": user_email,
    }


class EmployeeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_employees(self, tenant_id: str, status: str | None = None, *, today: datetime.date | None = None) -> list[dict]:
        """Every file of the tenant with its place and the contract in force on `today`.
        No sensitive field is selected here."""
        day = today or datetime.date.today()
        params: list[object] = [day, day, tenant_id]
        clause = "WHERE e.tenant_id = %s"
        if status:
            clause += " AND e.status = %s"
            params.append(status)
        rows = self.connection.execute(
            f"""
            SELECT e.id, e.employee_no, e.first_name, e.last_name, e.email, e.phone, e.department_id, d.name,
                   e.job_title, e.hire_date, e.status, e.position_id, p.title, e.grade_id, g.code, e.site,
                   e.badge_no, e.user_id, e.termination_date, c.contract_type, c.end_date
            FROM hr.employees e
            LEFT JOIN hr.departments d ON d.id = e.department_id
            LEFT JOIN hr.positions p ON p.id = e.position_id
            LEFT JOIN hr.grades g ON g.id = e.grade_id
            LEFT JOIN LATERAL (
                SELECT contract_type, end_date FROM hr.contracts
                WHERE employee_id = e.id AND tenant_id = e.tenant_id AND status <> 'draft'
                  AND start_date <= %s AND (end_date IS NULL OR end_date >= %s)
                ORDER BY start_date DESC
                LIMIT 1
            ) c ON TRUE
            {clause}
            ORDER BY e.last_name, e.first_name
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0],
                "employee_no": r[1],
                "first_name": r[2],
                "last_name": r[3],
                "full_name": f"{r[2]} {r[3]}",
                "email": r[4],
                "phone": r[5],
                "department_id": r[6],
                "department_name": r[7],
                "job_title": r[8],
                "hire_date": r[9].isoformat(),
                "status": r[10],
                "position_id": r[11],
                "position_title": r[12],
                "grade_id": r[13],
                "grade_code": r[14],
                "site": r[15],
                "badge_no": r[16],
                "user_id": r[17],
                "termination_date": r[18].isoformat() if r[18] else None,
                "contract_type": r[19],
                "contract_end_date": r[20].isoformat() if r[20] else None,
            }
            for r in rows
        ]

    def get_employee(self, *, tenant_id: str, employee_id: str) -> dict | None:
        row = self.connection.execute(_SELECT_FILE, (employee_id, tenant_id)).fetchone()
        return None if row is None else _file_record(row)

    def get_by_user(self, *, tenant_id: str, user_id: str) -> dict | None:
        """The file of the employee who signs in as `user_id`, unmasked: it is their own."""
        row = self.connection.execute(
            "SELECT id FROM hr.employees WHERE tenant_id = %s AND user_id = %s", (tenant_id, user_id)
        ).fetchone()
        return None if row is None else self.get_employee(tenant_id=tenant_id, employee_id=row[0])

    def create_employee(self, *, tenant_id: str, actor_id: str, employee: EmployeeFile) -> Result[dict]:
        validated = validate_employee_file(employee)
        if isinstance(validated, Err):
            return validated
        candidate = validated.value
        if candidate.status == "terminated":
            return Err("INVALID_STATUS", "a new employee cannot start as having left", "un nouvel employé ne peut pas être créé déjà sorti")
        refused = self._missing_references(tenant_id, candidate)
        if refused:
            return refused
        employee_id = str(ULID())
        refused = execute_guarded(
            self.connection, _INSERT, (employee_id, tenant_id, *(getattr(candidate, name) for name in FIELDS)), _UNIQUE_REFUSALS
        )
        if refused:
            return refused
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="employee.created",
            entity_type="employee",
            entity_id=employee_id,
            payload={
                "employee_no": candidate.employee_no,
                "first_name": candidate.first_name,
                "last_name": candidate.last_name,
                "hire_date": candidate.hire_date.isoformat(),
                "sensitive_set": [name for name in EMPLOYEE_FIELDS if getattr(candidate, name) is not None],
            },
        )
        return Ok(self.get_employee(tenant_id=tenant_id, employee_id=employee_id))

    def update_employee(self, *, tenant_id: str, actor_id: str, employee_id: str, changes: Mapping[str, object]) -> Result[dict]:
        """Edit in place (hr.admin_employees). Leaving is not an edit: it closes the contract too,
        so status 'terminated' is only reached through terminate_employee."""
        unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
        if unknown:
            return Err(
                "INVALID_EMPLOYEE", f"these fields cannot be edited: {', '.join(unknown)}", f"ces champs ne sont pas modifiables : {', '.join(unknown)}"
            )
        current = self._locked(tenant_id, employee_id)
        if current is None:
            return _NOT_FOUND
        validated = validate_employee_file(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        candidate = validated.value
        if candidate.status == "terminated" and current.status != "terminated":
            return Err(
                "INVALID_TRANSITION",
                "an employee leaves through the exit action, which also closes the contract",
                "un employé sort par l'action de sortie, qui clôt aussi son contrat",
            )
        refused = self._missing_references(tenant_id, candidate)
        if refused:
            return refused
        refused = execute_guarded(
            self.connection, _UPDATE, (*(getattr(candidate, name) for name in EDITABLE_FIELDS), employee_id, tenant_id), _UNIQUE_REFUSALS
        )
        if refused:
            return refused
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="employee.updated",
            entity_type="employee",
            entity_id=employee_id,
            payload=change_payload(asdict(current), asdict(candidate), EMPLOYEE_FIELDS),
        )
        return Ok(self.get_employee(tenant_id=tenant_id, employee_id=employee_id))

    def _locked(self, tenant_id: str, employee_id: str) -> EmployeeFile | None:
        row = self.connection.execute(
            f"SELECT {', '.join(FIELDS)} FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)
        ).fetchone()
        return None if row is None else EmployeeFile(*row)

    def _missing_references(self, tenant_id: str, employee: EmployeeFile) -> Err | None:
        for field_name, table, label_en, label_fr in _REFERENCES:
            refused = missing_reference(self.connection, table, tenant_id, getattr(employee, field_name), label_en, label_fr)
            if refused:
                return refused
        if employee.user_id is not None:
            found = self.connection.execute(
                "SELECT 1 FROM core.users WHERE id = %s AND tenant_id = %s", (employee.user_id, tenant_id)
            ).fetchone()
            if found is None:
                return Err("NOT_FOUND", "user account not found", "compte utilisateur introuvable")
        return None

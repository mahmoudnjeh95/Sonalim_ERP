from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.entities import Employee, validate_employee, validate_leave

# Re-exported: the dashboard route and later phases import it from here.
from modules.hr.api.organisation_service import DepartmentService  # noqa: F401


class EmployeeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_employees(self, tenant_id: str, status: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = "WHERE e.tenant_id = %s"
        if status:
            clause += " AND e.status = %s"
            params.append(status)
        rows = self.connection.execute(f"""
            SELECT e.id, e.employee_no, e.first_name, e.last_name, e.email, e.phone,
                   e.department_id, d.name, e.job_title, e.hire_date, e.status
            FROM hr.employees e LEFT JOIN hr.departments d ON d.id = e.department_id
            {clause} ORDER BY e.last_name, e.first_name
        """, params).fetchall()
        return [self._employee(row) for row in rows]

    def create_employee(self, *, tenant_id: str, actor_id: str, employee_no: str, first_name: str, last_name: str,
                        email: str | None, phone: str | None, department_id: str | None, job_title: str | None,
                        hire_date: datetime.date, status: str = "active") -> Result[dict]:
        validation = validate_employee(employee_no=employee_no, first_name=first_name, last_name=last_name, hire_date=hire_date, status=status)
        if isinstance(validation, Err):
            return validation
        if department_id and self.connection.execute("SELECT 1 FROM hr.departments WHERE id = %s AND tenant_id = %s", (department_id, tenant_id)).fetchone() is None:
            return Err("NOT_FOUND", "department not found", "département introuvable")
        employee_id = str(ULID())
        try:
            self.connection.execute("""
                INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, email, phone, department_id, job_title, hire_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, tenant_id, employee_no, first_name, last_name, email, phone, department_id, job_title, hire_date, status))
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_EMPLOYEE_NO", "employee number already exists", "ce matricule existe déjà")
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="employee.created", entity_type="employee", entity_id=employee_id, payload={"employee_no": employee_no})
        return Ok({"id": employee_id, "employee_no": employee_no, "first_name": first_name, "last_name": last_name, "email": email, "phone": phone, "department_id": department_id, "job_title": job_title, "hire_date": hire_date.isoformat(), "status": status})

    def update_employee(self, *, tenant_id: str, actor_id: str, employee_id: str, first_name: str | None = None,
                        last_name: str | None = None, email: str | None = None, phone: str | None = None,
                        department_id: str | None = None, job_title: str | None = None, hire_date: datetime.date | None = None,
                        status: str | None = None) -> Result[dict]:
        row = self.connection.execute("SELECT employee_no, first_name, last_name, email, phone, department_id, job_title, hire_date, status FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)).fetchone()
        if row is None:
            return Err("NOT_FOUND", "employee not found", "employé introuvable")
        values = (row[0], first_name if first_name is not None else row[1], last_name if last_name is not None else row[2], email if email is not None else row[3], phone if phone is not None else row[4], department_id if department_id is not None else row[5], job_title if job_title is not None else row[6], hire_date if hire_date is not None else row[7], status if status is not None else row[8])
        validation = validate_employee(employee_no=values[0], first_name=values[1], last_name=values[2], hire_date=values[7], status=values[8])
        if isinstance(validation, Err):
            return validation
        self.connection.execute("UPDATE hr.employees SET first_name=%s, last_name=%s, email=%s, phone=%s, department_id=%s, job_title=%s, hire_date=%s, status=%s WHERE id=%s AND tenant_id=%s", (*values[1:], employee_id, tenant_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="employee.updated", entity_type="employee", entity_id=employee_id, payload={"first_name": values[1], "last_name": values[2], "status": values[8]})
        return Ok({"id": employee_id, "employee_no": values[0], "first_name": values[1], "last_name": values[2], "email": values[3], "phone": values[4], "department_id": values[5], "job_title": values[6], "hire_date": values[7].isoformat(), "status": values[8]})

    @staticmethod
    def _employee(row) -> dict:
        return {"id": row[0], "employee_no": row[1], "first_name": row[2], "last_name": row[3], "email": row[4], "phone": row[5], "department_id": row[6], "department_name": row[7], "job_title": row[8], "hire_date": row[9].isoformat(), "status": row[10]}


class LeaveService:
    def __init__(self, connection: psycopg.Connection) -> None: self.connection = connection

    def list_requests(self, tenant_id: str, status: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]; clause = "WHERE l.tenant_id=%s"
        if status: clause += " AND l.status=%s"; params.append(status)
        rows = self.connection.execute(f"SELECT l.id,l.employee_id,e.first_name,e.last_name,l.leave_type,l.start_date,l.end_date,l.reason,l.status,l.reviewed_by FROM hr.leave_requests l JOIN hr.employees e ON e.id=l.employee_id {clause} ORDER BY l.start_date DESC", params).fetchall()
        return [{"id":r[0],"employee_id":r[1],"employee_name":f"{r[2]} {r[3]}","leave_type":r[4],"start_date":r[5].isoformat(),"end_date":r[6].isoformat(),"reason":r[7],"status":r[8],"reviewed_by":r[9]} for r in rows]

    def create_request(self, *, tenant_id: str, actor_id: str, employee_id: str, leave_type: str, start_date: datetime.date, end_date: datetime.date, reason: str | None) -> Result[dict]:
        validation = validate_leave(start_date=start_date, end_date=end_date)
        if isinstance(validation, Err): return validation
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id=%s AND tenant_id=%s", (employee_id, tenant_id)).fetchone() is None: return Err("NOT_FOUND", "employee not found", "employé introuvable")
        request_id = str(ULID()); self.connection.execute("INSERT INTO hr.leave_requests (id,tenant_id,employee_id,leave_type,start_date,end_date,reason) VALUES (%s,%s,%s,%s,%s,%s,%s)", (request_id,tenant_id,employee_id,leave_type,start_date,end_date,reason))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.created", entity_type="leave_request", entity_id=request_id, payload={"employee_id":employee_id,"start_date":start_date.isoformat(),"end_date":end_date.isoformat()})
        return Ok({"id":request_id,"employee_id":employee_id,"leave_type":leave_type,"start_date":start_date.isoformat(),"end_date":end_date.isoformat(),"reason":reason,"status":"pending"})

    def review_request(self, *, tenant_id: str, actor_id: str, request_id: str, status: str) -> Result[dict]:
        if status not in {"approved", "rejected", "cancelled"}: return Err("INVALID_STATUS", "invalid leave decision", "décision de congé invalide")
        row = self.connection.execute("SELECT employee_id, leave_type, start_date, end_date, reason, status FROM hr.leave_requests WHERE id=%s AND tenant_id=%s FOR UPDATE", (request_id,tenant_id)).fetchone()
        if row is None: return Err("NOT_FOUND", "leave request not found", "demande de congé introuvable")
        if row[5] != "pending": return Err("INVALID_TRANSITION", "only pending leave can be reviewed", "seul un congé en attente peut être passé en revue")
        self.connection.execute("UPDATE hr.leave_requests SET status=%s, reviewed_by=%s WHERE id=%s AND tenant_id=%s", (status,actor_id,request_id,tenant_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.status_changed", entity_type="leave_request", entity_id=request_id, payload={"from_status":"pending","to_status":status})
        return Ok({"id":request_id,"employee_id":row[0],"leave_type":row[1],"start_date":row[2].isoformat(),"end_date":row[3].isoformat(),"reason":row[4],"status":status,"reviewed_by":actor_id})

from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.entities import validate_leave

# Re-exported: the dashboard route and later phases (phase 5: EmployeeService.get_by_user)
# import these from here.
from modules.hr.api.employee_service import EmployeeService  # noqa: F401
from modules.hr.api.organisation_service import DepartmentService  # noqa: F401


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

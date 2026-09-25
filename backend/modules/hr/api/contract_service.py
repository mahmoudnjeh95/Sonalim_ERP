from __future__ import annotations

import datetime
import psycopg
from ulid import ULID
from core.audit import record_audit
from core.domain.result import Err, Ok, Result

class ContractService:
    def __init__(self, connection: psycopg.Connection) -> None: self.connection = connection

    def list_contracts(self, tenant_id: str, employee_id: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]; clause = "WHERE c.tenant_id=%s"
        if employee_id: clause += " AND c.employee_id=%s"; params.append(employee_id)
        rows = self.connection.execute(f"SELECT c.id,c.employee_id,e.first_name,e.last_name,c.contract_type,c.start_date,c.end_date,c.salary,c.currency,c.status FROM hr.contracts c JOIN hr.employees e ON e.id=c.employee_id {clause} ORDER BY c.start_date DESC", params).fetchall()
        return [{"id":r[0],"employee_id":r[1],"employee_name":f"{r[2]} {r[3]}","contract_type":r[4],"start_date":r[5].isoformat(),"end_date":r[6].isoformat() if r[6] else None,"salary":float(r[7]),"currency":r[8],"status":r[9]} for r in rows]

    def create_contract(self, *, tenant_id: str, actor_id: str, employee_id: str, contract_type: str, start_date: datetime.date, end_date: datetime.date | None, salary: float, currency: str, status: str = "active") -> Result[dict]:
        if salary < 0 or (end_date and end_date < start_date): return Err(
            "INVALID_CONTRACT",
            "salary must be positive and end date cannot precede start date",
            "le salaire doit être positif et la date de fin ne peut pas précéder la date de début",
        )
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id=%s AND tenant_id=%s", (employee_id, tenant_id)).fetchone() is None: return Err("NOT_FOUND", "employee not found", "employé introuvable")
        contract_id = str(ULID()); self.connection.execute("INSERT INTO hr.contracts (id,tenant_id,employee_id,contract_type,start_date,end_date,salary,currency,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (contract_id,tenant_id,employee_id,contract_type,start_date,end_date,salary,currency,status))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="contract.created", entity_type="contract", entity_id=contract_id, payload={"employee_id":employee_id,"contract_type":contract_type})
        return Ok({"id":contract_id,"employee_id":employee_id,"contract_type":contract_type,"start_date":start_date.isoformat(),"end_date":end_date.isoformat() if end_date else None,"salary":salary,"currency":currency,"status":status})

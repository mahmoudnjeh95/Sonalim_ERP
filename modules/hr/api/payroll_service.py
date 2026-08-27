from __future__ import annotations

import datetime
import psycopg
from ulid import ULID
from core.audit import record_audit
from core.domain.result import Err, Ok, Result


class AttendanceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_records(self, *, tenant_id: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[dict]:
        clauses = ["a.tenant_id = %s"]; params: list[object] = [tenant_id]
        if date_from: clauses.append("a.attendance_date >= %s"); params.append(date_from)
        if date_to: clauses.append("a.attendance_date <= %s"); params.append(date_to)
        rows = self.connection.execute(f"SELECT a.id,a.employee_id,e.first_name,e.last_name,a.attendance_date,a.status,a.hours_worked,a.note FROM hr.attendance_records a JOIN hr.employees e ON e.id=a.employee_id WHERE {' AND '.join(clauses)} ORDER BY a.attendance_date DESC,e.last_name", params).fetchall()
        return [{"id":r[0],"employee_id":r[1],"employee_name":f"{r[2]} {r[3]}","attendance_date":r[4].isoformat(),"status":r[5],"hours_worked":float(r[6]),"note":r[7]} for r in rows]

    def record(self, *, tenant_id: str, actor_id: str, employee_id: str, attendance_date: datetime.date, status: str, hours_worked: float, note: str | None) -> Result[dict]:
        if status not in {"present", "absent", "late", "remote", "half_day", "leave"} or hours_worked < 0:
            return Err("INVALID_ATTENDANCE", "invalid attendance status or hours")
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id=%s AND tenant_id=%s", (employee_id, tenant_id)).fetchone() is None: return Err("NOT_FOUND", "employee not found")
        record_id = str(ULID())
        self.connection.execute("INSERT INTO hr.attendance_records (id,tenant_id,employee_id,attendance_date,status,hours_worked,note) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,employee_id,attendance_date) DO UPDATE SET status=EXCLUDED.status,hours_worked=EXCLUDED.hours_worked,note=EXCLUDED.note", (record_id,tenant_id,employee_id,attendance_date,status,hours_worked,note))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="attendance.recorded", entity_type="attendance", entity_id=f"{employee_id}:{attendance_date.isoformat()}", payload={"employee_id":employee_id,"date":attendance_date.isoformat(),"status":status})
        return Ok({"id":record_id,"employee_id":employee_id,"attendance_date":attendance_date.isoformat(),"status":status,"hours_worked":hours_worked,"note":note})


class PayrollService:
    def __init__(self, connection: psycopg.Connection) -> None: self.connection = connection

    def list_runs(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute("SELECT id,period_month,status FROM hr.payroll_runs WHERE tenant_id=%s ORDER BY period_month DESC", (tenant_id,)).fetchall()
        return [{"id":r[0],"period_month":r[1].isoformat(),"status":r[2]} for r in rows]

    def get_payslips(self, *, tenant_id: str, run_id: str | None = None) -> list[dict]:
        clauses = ["i.tenant_id=%s"]; params: list[object] = [tenant_id]
        if run_id: clauses.append("i.payroll_run_id=%s"); params.append(run_id)
        rows = self.connection.execute(f"SELECT i.id,i.payroll_run_id,r.period_month,i.employee_id,e.first_name,e.last_name,i.base_salary,i.bonuses,i.deductions,i.taxes,i.net_salary,i.currency,r.status FROM hr.payroll_items i JOIN hr.payroll_runs r ON r.id=i.payroll_run_id JOIN hr.employees e ON e.id=i.employee_id WHERE {' AND '.join(clauses)} ORDER BY r.period_month DESC,e.last_name", params).fetchall()
        return [{"id":r[0],"payroll_run_id":r[1],"period_month":r[2].isoformat(),"employee_id":r[3],"employee_name":f"{r[4]} {r[5]}","base_salary":float(r[6]),"bonuses":float(r[7]),"deductions":float(r[8]),"taxes":float(r[9]),"net_salary":float(r[10]),"currency":r[11],"status":r[12]} for r in rows]

    def create_run(self, *, tenant_id: str, actor_id: str, period_month: datetime.date, bonuses: float, deductions: float, taxes: float) -> Result[dict]:
        if period_month.day != 1 or min(bonuses, deductions, taxes) < 0: return Err("INVALID_PAYROLL", "payroll period must be the first day of a month and amounts cannot be negative")
        run_id = str(ULID())
        try: self.connection.execute("INSERT INTO hr.payroll_runs (id,tenant_id,period_month,status) VALUES (%s,%s,%s,'calculated')", (run_id,tenant_id,period_month))
        except psycopg.errors.UniqueViolation: return Err("DUPLICATE_PERIOD", "a payroll run already exists for this month")
        employees = self.connection.execute("SELECT e.id,COALESCE(c.salary,0),COALESCE(c.currency,'USD') FROM hr.employees e LEFT JOIN LATERAL (SELECT salary,currency FROM hr.contracts WHERE employee_id=e.id AND tenant_id=e.tenant_id AND status='active' ORDER BY start_date DESC LIMIT 1) c ON TRUE WHERE e.tenant_id=%s AND e.status != 'inactive'", (tenant_id,)).fetchall()
        for employee_id, salary, currency in employees:
            net = float(salary) + bonuses - deductions - taxes
            self.connection.execute("INSERT INTO hr.payroll_items (id,tenant_id,payroll_run_id,employee_id,base_salary,bonuses,deductions,taxes,net_salary,currency) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (str(ULID()),tenant_id,run_id,employee_id,salary,bonuses,deductions,taxes,net,currency))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.calculated", entity_type="payroll_run", entity_id=run_id, payload={"period_month":period_month.isoformat(),"employee_count":len(employees)})
        return Ok({"id":run_id,"period_month":period_month.isoformat(),"status":"calculated","employee_count":len(employees)})

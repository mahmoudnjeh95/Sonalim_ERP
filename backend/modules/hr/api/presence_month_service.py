"""Closing and reopening a month of presence.

Close refuses while any working day of an employed person has no presence row (or no schedule
says which days they work), or while a leave request touching the month is pending. It then
writes the public-holiday days nobody recorded, locks every row of the month, posts the month's
leave accrual, and publishes hr.presence_month.closed (payload {period}).
Reopen (hr.admin_presence) needs a reason and is refused while an approved payroll run exists
for the month (hr.presence_month_payroll_locks, fed by the payroll events); it unlocks the rows.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.hr.api.leave_service import LeaveBalanceService
from modules.hr.api.presence_service import PresenceService, employed_between, is_employed, month_bounds
from modules.hr.api.schedule_service import HolidayService, ScheduleService
from modules.hr.domain.presence import DayFigures
from modules.hr.domain.schedule import ResolvedDay, date_range

CLOSED_EVENT = "hr.presence_month.closed"
INVALID_PERIOD = Err("INVALID_PERIOD", "a period is the first day of a month", "une période est le premier jour d'un mois")


class PresenceMonthService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_months(self, *, tenant_id: str, year: int) -> list[dict]:
        stored = {
            row[0]: row
            for row in self.connection.execute(
                "SELECT period, status, closed_by, closed_at FROM hr.presence_months WHERE tenant_id = %s AND EXTRACT(YEAR FROM period) = %s",
                (tenant_id, year),
            ).fetchall()
        }
        locked = {
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT period FROM hr.presence_month_payroll_locks WHERE tenant_id = %s AND EXTRACT(YEAR FROM period) = %s",
                (tenant_id, year),
            ).fetchall()
        }
        months = []
        for month in range(1, 13):
            period = datetime.date(year, month, 1)
            row = stored.get(period)
            months.append({
                "period": period.isoformat(),
                "status": row[1] if row else "open",
                "closed_by": row[2] if row else None,
                "closed_at": row[3].isoformat() if row and row[3] else None,
                "payroll_locked": period in locked,
            })
        return months

    def gaps(self, *, tenant_id: str, period: datetime.date) -> list[dict]:
        first, last = month_bounds(period)
        return self._scan(tenant_id, first, last)[0]

    def _scan(self, tenant_id: str, first: datetime.date, last: datetime.date) -> tuple[list[dict], list[tuple[dict, datetime.date, ResolvedDay]]]:
        """The gaps, and the public-holiday working days nobody recorded (written on close)."""
        employees = employed_between(self.connection, tenant_id=tenant_id, date_from=first, date_to=last)
        if not employees:
            return [], []
        ids = [employee["id"] for employee in employees]
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=first, date_to=last)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=first, date_to=last)
        existing = PresenceService(self.connection).existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=first, date_to=last)
        gaps: list[dict] = []
        holiday_days: list[tuple[dict, datetime.date, ResolvedDay]] = []
        for employee in employees:
            for day in date_range(first, last):
                if not is_employed(employee, day) or (employee["id"], day) in existing:
                    continue
                resolved_day = resolved[employee["id"]][day]
                label = {
                    "employee_id": employee["id"], "employee_no": employee["employee_no"],
                    "full_name": employee["full_name"], "work_date": day.isoformat(),
                }
                if not resolved_day.assigned:
                    gaps.append({**label, "reason": "no_schedule"})
                elif resolved_day.is_working_day and day in holidays:
                    holiday_days.append((employee, day, resolved_day))
                elif resolved_day.is_working_day:
                    gaps.append({**label, "reason": "missing"})
        return gaps, holiday_days

    def close(self, *, tenant_id: str, actor_id: str, period: datetime.date, correlation_id: str | None = None) -> Result[dict]:
        if period.day != 1:
            return INVALID_PERIOD
        first, last = month_bounds(period)
        current = self.connection.execute(
            "SELECT status FROM hr.presence_months WHERE tenant_id = %s AND period = %s FOR UPDATE", (tenant_id, first)
        ).fetchone()
        if current is not None and current[0] == "closed":
            return Err("INVALID_TRANSITION", "presence for this month is already closed", "la présence de ce mois est déjà clôturée")
        pending = self.connection.execute(
            "SELECT count(*) FROM hr.leave_requests WHERE tenant_id = %s AND status = 'pending' AND start_date <= %s AND end_date >= %s",
            (tenant_id, last, first),
        ).fetchone()[0]
        if pending:
            return Err(
                "LEAVE_PENDING",
                f"{pending} leave request(s) touching this month are still pending",
                f"{pending} demande(s) de congé touchant ce mois sont encore en attente",
            )
        gaps, holiday_days = self._scan(tenant_id, first, last)
        if gaps:
            sample = ", ".join(f"{gap['employee_no']} {gap['work_date']}" for gap in gaps[:5])
            return Err(
                "PRESENCE_INCOMPLETE",
                f"{len(gaps)} working day(s) have no presence (for example {sample})",
                f"{len(gaps)} jour(s) de travail sans présence (par exemple {sample})",
            )
        presence = PresenceService(self.connection)
        for employee, day, resolved_day in holiday_days:
            presence.upsert_day(
                tenant_id=tenant_id, actor_id=actor_id, employee_id=employee["id"], work_date=day,
                figures=DayFigures(status="holiday", schedule_id=resolved_day.schedule_id, scheduled_minutes=0, worked_minutes=0),
                source="holiday", justified=True,
            )
        locked = self.connection.execute(
            "UPDATE hr.presence_days SET locked = TRUE WHERE tenant_id = %s AND work_date BETWEEN %s AND %s", (tenant_id, first, last)
        ).rowcount
        accruals = LeaveBalanceService(self.connection).post_month_accruals(tenant_id=tenant_id, period=first)
        self.connection.execute(
            """
            INSERT INTO hr.presence_months (tenant_id, period, status, closed_by, closed_at) VALUES (%s, %s, 'closed', %s, NOW())
            ON CONFLICT (tenant_id, period) DO UPDATE SET status = 'closed', closed_by = EXCLUDED.closed_by, closed_at = NOW()
            """,
            (tenant_id, first, actor_id),
        )
        publish_event(
            self.connection, event_type=CLOSED_EVENT, producer="hr", tenant_id=tenant_id,
            correlation_id=correlation_id or str(ULID()), payload={"period": first.isoformat()},
        )
        outcome = {"period": first.isoformat(), "status": "closed", "locked_rows": locked, "holiday_rows": len(holiday_days), "accruals_posted": accruals}
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_month.closed",
            entity_type="presence_month", entity_id=first.isoformat(), payload=outcome,
        )
        return Ok(outcome)

    def reopen(self, *, tenant_id: str, actor_id: str, period: datetime.date, reason: str) -> Result[dict]:
        if period.day != 1:
            return INVALID_PERIOD
        if not (reason or "").strip():
            return Err("INVALID_REOPEN", "a reason is required to reopen a month", "un motif est obligatoire pour rouvrir un mois")
        current = self.connection.execute(
            "SELECT status FROM hr.presence_months WHERE tenant_id = %s AND period = %s FOR UPDATE", (tenant_id, period)
        ).fetchone()
        if current is None or current[0] != "closed":
            return Err("INVALID_TRANSITION", "only a closed month can be reopened", "seul un mois clôturé peut être rouvert")
        runs = self.connection.execute(
            "SELECT count(*) FROM hr.presence_month_payroll_locks WHERE tenant_id = %s AND period = %s", (tenant_id, period)
        ).fetchone()[0]
        if runs:
            return Err(
                "PRESENCE_PAYROLL_APPROVED",
                "an approved payroll run exists for this month; reverse it before reopening presence",
                "une paie approuvée existe pour ce mois ; annulez-la avant de rouvrir la présence",
            )
        first, last = month_bounds(period)
        unlocked = self.connection.execute(
            "UPDATE hr.presence_days SET locked = FALSE WHERE tenant_id = %s AND work_date BETWEEN %s AND %s", (tenant_id, first, last)
        ).rowcount
        self.connection.execute(
            "UPDATE hr.presence_months SET status = 'open', reopened_by = %s, reopened_at = NOW() WHERE tenant_id = %s AND period = %s",
            (actor_id, tenant_id, period),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_month.reopened",
            entity_type="presence_month", entity_id=period.isoformat(),
            payload={"period": period.isoformat(), "reason": reason.strip(), "unlocked_rows": unlocked},
        )
        return Ok({"period": period.isoformat(), "status": "open", "unlocked_rows": unlocked})

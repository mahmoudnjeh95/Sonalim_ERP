"""Daily presence: the supervisor grid (a team on a day or a week), one person's month,
saving what the supervisor typed, and the answers payroll asks for.

Helpers at module level (month bounds, closed months, who is employed) are shared by the
clock, leave and month-close services of this module.
"""
from __future__ import annotations

import calendar
import datetime
from typing import Iterable

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
from modules.hr.domain.presence import DayFigures, ManualEntry, default_status, figures_for_entry, validate_entry
from modules.hr.domain.schedule import date_range

_RECORD_KEYS = (
    "id", "status", "source", "scheduled_minutes", "worked_minutes", "late_minutes", "ot_minutes_day",
    "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "justified", "note", "locked", "leave_request_id",
)


def month_bounds(period: datetime.date) -> tuple[datetime.date, datetime.date]:
    """First and last day of the month `period` opens. A period is always a first of month."""
    if period.day != 1:
        raise ValueError("a period is the first day of a month")
    return period, period.replace(day=calendar.monthrange(period.year, period.month)[1])


def closed_periods(connection: psycopg.Connection, tenant_id: str, dates: Iterable[datetime.date]) -> list[datetime.date]:
    periods = sorted({day.replace(day=1) for day in dates})
    if not periods:
        return []
    rows = connection.execute(
        "SELECT period FROM hr.presence_months WHERE tenant_id = %s AND period = ANY(%s) AND status = 'closed' ORDER BY period",
        (tenant_id, periods),
    ).fetchall()
    return [row[0] for row in rows]


def month_closed_error(periods: list[datetime.date]) -> Err:
    months = ", ".join(period.strftime("%Y-%m") for period in periods)
    return Err("PRESENCE_MONTH_CLOSED", f"presence is closed for {months}", f"la présence est clôturée pour {months}")


def employed_between(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    date_from: datetime.date,
    date_to: datetime.date,
    department_id: str | None = None,
    employee_ids: list[str] | None = None,
) -> list[dict]:
    """Employees employed on at least one day of [date_from, date_to], by hire and termination dates."""
    clauses = [
        "e.tenant_id = %s", "e.status <> 'inactive'", "e.hire_date <= %s",
        "(e.termination_date IS NULL OR e.termination_date >= %s)",
    ]
    params: list[object] = [tenant_id, date_to, date_from]
    if department_id:
        clauses.append("e.department_id = %s")
        params.append(department_id)
    if employee_ids is not None:
        clauses.append("e.id = ANY(%s)")
        params.append(list(employee_ids))
    rows = connection.execute(
        f"""
        SELECT e.id, e.employee_no, e.first_name || ' ' || e.last_name, e.department_id, e.hire_date, e.termination_date, e.badge_no
        FROM hr.employees e
        WHERE {' AND '.join(clauses)}
        ORDER BY e.employee_no
        """,
        params,
    ).fetchall()
    return [
        {"id": r[0], "employee_no": r[1], "full_name": r[2], "department_id": r[3], "hire_date": r[4], "termination_date": r[5], "badge_no": r[6]}
        for r in rows
    ]


def is_employed(employee: dict, day: datetime.date) -> bool:
    return employee["hire_date"] <= day and (employee["termination_date"] is None or day <= employee["termination_date"])


class PresenceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- reads ------------------------------------------------------------------
    def grid(self, *, tenant_id: str, work_date: datetime.date, department_id: str | None = None, schedule_id: str | None = None) -> list[dict]:
        return self._rows(tenant_id=tenant_id, date_from=work_date, date_to=work_date, department_id=department_id, schedule_id=schedule_id)

    def week(self, *, tenant_id: str, date_from: datetime.date, department_id: str | None = None, schedule_id: str | None = None) -> list[dict]:
        return self._rows(
            tenant_id=tenant_id, date_from=date_from, date_to=date_from + datetime.timedelta(days=6),
            department_id=department_id, schedule_id=schedule_id,
        )

    def employee_month(self, *, tenant_id: str, employee_id: str, period: datetime.date) -> Result[dict]:
        first, last = month_bounds(period)
        rows = self._rows(tenant_id=tenant_id, date_from=first, date_to=last, employee_ids=[employee_id])
        if not rows:
            return Err("NOT_FOUND", "employee not found or not employed this month", "employé introuvable ou non employé ce mois-ci")
        return Ok({**rows[0], "period": first.isoformat(), "closed": self.is_month_closed(tenant_id=tenant_id, period=first)})

    def is_month_closed(self, *, tenant_id: str, period: datetime.date) -> bool:
        row = self.connection.execute(
            "SELECT status FROM hr.presence_months WHERE tenant_id = %s AND period = %s", (tenant_id, period)
        ).fetchone()
        return row is not None and row[0] == "closed"

    def existing_days(
        self, *, tenant_id: str, employee_ids: list[str], date_from: datetime.date, date_to: datetime.date
    ) -> dict[tuple[str, datetime.date], dict]:
        if not employee_ids:
            return {}
        rows = self.connection.execute(
            f"""
            SELECT employee_id, work_date, {', '.join(_RECORD_KEYS)}
            FROM hr.presence_days
            WHERE tenant_id = %s AND employee_id = ANY(%s) AND work_date BETWEEN %s AND %s
            """,
            (tenant_id, list(employee_ids), date_from, date_to),
        ).fetchall()
        return {(row[0], row[1]): dict(zip(_RECORD_KEYS, row[2:])) for row in rows}

    def _rows(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        department_id: str | None = None,
        schedule_id: str | None = None,
        employee_ids: list[str] | None = None,
    ) -> list[dict]:
        employees = employed_between(
            self.connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to,
            department_id=department_id, employee_ids=employee_ids,
        )
        if not employees:
            return []
        ids = [employee["id"] for employee in employees]
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        existing = self.existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        rows = []
        for employee in employees:
            days = []
            for day in date_range(date_from, date_to):
                resolved_day = resolved[employee["id"]][day]
                days.append({
                    "work_date": day.isoformat(),
                    "employed": is_employed(employee, day),
                    "assigned": resolved_day.assigned,
                    "schedule_id": resolved_day.schedule_id,
                    "schedule_code": resolved_day.schedule_code,
                    "is_working_day": resolved_day.is_working_day,
                    "is_holiday": day in holidays,
                    "planned_minutes": resolved_day.window.scheduled_minutes if resolved_day.window else 0,
                    "default_status": default_status(resolved_day, is_holiday=day in holidays),
                    "record": existing.get((employee["id"], day)),
                })
            if schedule_id and not any(day["schedule_id"] == schedule_id for day in days):
                continue
            rows.append({
                "employee_id": employee["id"], "employee_no": employee["employee_no"], "full_name": employee["full_name"],
                "department_id": employee["department_id"], "days": days,
            })
        return rows

    # ---- writes -----------------------------------------------------------------
    def save_days(self, *, tenant_id: str, actor_id: str, entries: list[ManualEntry]) -> Result[dict]:
        """Saves what a supervisor typed. Overwrites clock and holiday days (a person's decision
        wins over the device), never an approved leave day, never a closed month."""
        if not entries:
            return Err("INVALID_PRESENCE", "nothing to save", "rien à enregistrer")
        keys = [(entry.employee_id, entry.work_date) for entry in entries]
        if len(set(keys)) != len(keys):
            return Err("INVALID_PRESENCE", "the same employee and day appear twice", "le même employé et le même jour apparaissent deux fois")
        for entry in entries:
            validation = validate_entry(entry)
            if isinstance(validation, Err):
                day = entry.work_date.isoformat()
                return Err(validation.code, f"{day}: {validation.message}", f"{day} : {validation.message_fr}")
        night = PresenceSettingsService(self.connection).night_window(tenant_id=tenant_id)
        if isinstance(night, Err):
            return night
        closed = closed_periods(self.connection, tenant_id, (entry.work_date for entry in entries))
        if closed:
            return month_closed_error(closed)
        date_from = min(entry.work_date for entry in entries)
        date_to = max(entry.work_date for entry in entries)
        ids = sorted({entry.employee_id for entry in entries})
        employees = {
            employee["id"]: employee
            for employee in employed_between(self.connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to, employee_ids=ids)
        }
        for entry in entries:
            employee = employees.get(entry.employee_id)
            if employee is None or not is_employed(employee, entry.work_date):
                day = entry.work_date.isoformat()
                return Err("NOT_EMPLOYED", f"employee {entry.employee_id} is not employed on {day}", f"l'employé {entry.employee_id} n'est pas en poste le {day}")
        existing = self.existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        for entry in entries:
            before = existing.get((entry.employee_id, entry.work_date))
            if before is not None and before["source"] == "leave":
                number = employees[entry.employee_id]["employee_no"]
                day = entry.work_date.isoformat()
                return Err(
                    "PRESENCE_DAY_FROM_LEAVE",
                    f"{day} is an approved leave day of {number}; change the leave request instead",
                    f"le {day} est un jour de congé approuvé de {number} ; modifiez plutôt la demande de congé",
                )
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        for entry in entries:
            window = resolved[entry.employee_id][entry.work_date].window
            figures = figures_for_entry(entry, window, night.value, is_holiday=entry.work_date in holidays)
            day_id = self.upsert_day(
                tenant_id=tenant_id, actor_id=actor_id, employee_id=entry.employee_id, work_date=entry.work_date,
                figures=figures, source="manual", justified=entry.justified, note=entry.note,
            )
            before = existing.get((entry.employee_id, entry.work_date))
            record_audit(
                self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_day.saved",
                entity_type="presence_day", entity_id=day_id,
                payload={
                    "employee_id": entry.employee_id, "work_date": entry.work_date.isoformat(),
                    "from_status": before["status"] if before else None, "from_source": before["source"] if before else None,
                    "to_status": figures.status, "worked_minutes": figures.worked_minutes,
                },
            )
        return Ok({"saved": len(entries)})

    def upsert_day(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        employee_id: str,
        work_date: datetime.date,
        figures: DayFigures,
        source: str,
        justified: bool = False,
        note: str | None = None,
        leave_request_id: str | None = None,
        clock_import_id: str | None = None,
    ) -> str:
        """Writes one day, inserting or overwriting. Callers decide who may overwrite whom and check the month is open."""
        row = self.connection.execute(
            """
            INSERT INTO hr.presence_days (id, tenant_id, employee_id, work_date, status, schedule_id, scheduled_minutes,
                                          worked_minutes, late_minutes, ot_minutes_day, ot_minutes_night,
                                          ot_minutes_rest_holiday, night_minutes, source, justified, note,
                                          leave_request_id, clock_import_id, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, employee_id, work_date) DO UPDATE SET
                status = EXCLUDED.status, schedule_id = EXCLUDED.schedule_id,
                scheduled_minutes = EXCLUDED.scheduled_minutes, worked_minutes = EXCLUDED.worked_minutes,
                late_minutes = EXCLUDED.late_minutes, ot_minutes_day = EXCLUDED.ot_minutes_day,
                ot_minutes_night = EXCLUDED.ot_minutes_night, ot_minutes_rest_holiday = EXCLUDED.ot_minutes_rest_holiday,
                night_minutes = EXCLUDED.night_minutes, source = EXCLUDED.source, justified = EXCLUDED.justified,
                note = EXCLUDED.note, leave_request_id = EXCLUDED.leave_request_id,
                clock_import_id = EXCLUDED.clock_import_id, updated_by = EXCLUDED.updated_by, updated_at = NOW()
            RETURNING id
            """,
            (
                str(ULID()), tenant_id, employee_id, work_date, figures.status, figures.schedule_id, figures.scheduled_minutes,
                figures.worked_minutes, figures.late_minutes, figures.ot_minutes_day, figures.ot_minutes_night,
                figures.ot_minutes_rest_holiday, figures.night_minutes, source, justified, note, leave_request_id,
                clock_import_id, actor_id,
            ),
        ).fetchone()
        return row[0]

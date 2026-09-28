"""Leave types, leave requests with approval, and balances (monthly accrual, carry-over, adjustments).

Approving a request takes its days from the balance of the start date's year and writes one
presence day per counted day with source 'leave' (none for a half day: the person also works
that day). Cancelling an approved request, or editing it, first undoes that. Every one of
these refuses a closed month. Audit payloads hold Decimals as strings (JSON has no Decimal).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.presence_service import (
    PresenceService,
    closed_periods,
    employed_between,
    is_employed,
    month_bounds,
    month_closed_error,
)
from modules.hr.api.schedule_service import HolidayService, ScheduleService
from modules.hr.domain.entities import validate_leave
from modules.hr.domain.leave import (
    BalanceView,
    LeaveType,
    YearFigures,
    check_balance,
    leave_dates,
    month_accrual,
    requested_days,
    roll_balances,
    validate_leave_type,
)
from modules.hr.domain.presence import DayFigures
from modules.hr.domain.schedule import ResolvedDay, date_range

TYPE_NOT_FOUND = Err("NOT_FOUND", "leave type not found", "type de congé introuvable")
REQUEST_NOT_FOUND = Err("NOT_FOUND", "leave request not found", "demande de congé introuvable")
EMPLOYEE_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")
LEAVE_OVERLAP = Err(
    "LEAVE_OVERLAP",
    "the employee already has a pending or approved leave on these dates",
    "l'employé a déjà un congé en attente ou approuvé sur ces dates",
)
_TYPE_KEYS = (
    "id", "code", "name_en", "name_fr", "paid", "accrual_days_per_month", "max_carry_over", "counts_days",
    "requires_document", "presence_status", "confirmed", "active",
)
_REQUEST_KEYS = (
    "id", "employee_id", "leave_type_id", "leave_type", "start_date", "end_date", "days", "half_day", "status",
    "document_ref", "reason", "balance_year",
)
_LIST_COLUMNS = """
    r.id, r.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, r.leave_type_id, t.code, t.name_en,
    t.name_fr, r.leave_type, r.start_date, r.end_date, r.days, r.half_day, r.reason, r.document_ref, r.status,
    r.reviewed_by, r.reviewed_at, r.review_note
"""


def _domain_type(row: dict) -> LeaveType:
    return LeaveType(
        id=row["id"], code=row["code"], paid=row["paid"], accrual_days_per_month=row["accrual_days_per_month"],
        max_carry_over=row["max_carry_over"], counts_days=row["counts_days"], requires_document=row["requires_document"],
        presence_status=row["presence_status"], active=row["active"],
    )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class _Plan:
    dates: list[datetime.date]
    days: Decimal
    resolved: dict[datetime.date, ResolvedDay]
    holidays: set[datetime.date]


class LeaveTypeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_types(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            f"SELECT {', '.join(_TYPE_KEYS)} FROM hr.leave_types WHERE tenant_id = %s ORDER BY code", (tenant_id,)
        ).fetchall()
        return [dict(zip(_TYPE_KEYS, row)) for row in rows]

    def get_type(self, *, tenant_id: str, leave_type_id: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(_TYPE_KEYS)} FROM hr.leave_types WHERE tenant_id = %s AND id = %s", (tenant_id, leave_type_id)
        ).fetchone()
        return dict(zip(_TYPE_KEYS, row)) if row else None

    def create_type(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name_en: str,
        name_fr: str,
        paid: bool,
        accrual_days_per_month: Decimal,
        max_carry_over: Decimal | None,
        counts_days: str,
        requires_document: bool,
        presence_status: str,
        confirmed: bool = False,
    ) -> Result[dict]:
        validation = validate_leave_type(
            code=code, name_en=name_en, name_fr=name_fr, accrual_days_per_month=accrual_days_per_month,
            max_carry_over=max_carry_over, counts_days=counts_days, presence_status=presence_status,
        )
        if isinstance(validation, Err):
            return validation
        if self.connection.execute("SELECT 1 FROM hr.leave_types WHERE tenant_id = %s AND code = %s", (tenant_id, code.strip())).fetchone():
            return Err("DUPLICATE_CODE", f"leave type code {code.strip()} already exists", f"le code de type de congé {code.strip()} existe déjà")
        leave_type_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.leave_types (id, tenant_id, code, name_en, name_fr, paid, accrual_days_per_month, max_carry_over,
                                        counts_days, requires_document, presence_status, confirmed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                leave_type_id, tenant_id, code.strip(), name_en.strip(), name_fr.strip(), paid, accrual_days_per_month,
                max_carry_over, counts_days, requires_document, presence_status, confirmed,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_type.created",
            entity_type="leave_type", entity_id=leave_type_id,
            payload={
                "code": code.strip(), "paid": paid, "accrual_days_per_month": _text(accrual_days_per_month),
                "max_carry_over": _text(max_carry_over), "counts_days": counts_days, "confirmed": confirmed,
            },
        )
        return Ok(self.get_type(tenant_id=tenant_id, leave_type_id=leave_type_id))

    def update_type(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        leave_type_id: str,
        name_en: str | None = None,
        name_fr: str | None = None,
        paid: bool | None = None,
        accrual_days_per_month: Decimal | None = None,
        max_carry_over: Decimal | None = None,
        clear_max_carry_over: bool = False,
        counts_days: str | None = None,
        requires_document: bool | None = None,
        presence_status: str | None = None,
        confirmed: bool | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        current = self.get_type(tenant_id=tenant_id, leave_type_id=leave_type_id)
        if current is None:
            return TYPE_NOT_FOUND
        if paid is not None and paid != current["paid"]:
            closed = self.connection.execute(
                """
                SELECT DISTINCT date_trunc('month', p.work_date)::date FROM hr.presence_days p
                JOIN hr.leave_requests r ON r.id = p.leave_request_id
                JOIN hr.presence_months m ON m.tenant_id = p.tenant_id AND m.period = date_trunc('month', p.work_date)::date
                WHERE p.tenant_id = %s AND r.leave_type_id = %s AND m.status = 'closed'
                ORDER BY 1
                """,
                (tenant_id, leave_type_id),
            ).fetchall()
            if closed:
                return month_closed_error([row[0] for row in closed])
        changes = {
            key: value
            for key, value in {
                "name_en": name_en, "name_fr": name_fr, "paid": paid, "accrual_days_per_month": accrual_days_per_month,
                "max_carry_over": max_carry_over, "counts_days": counts_days, "requires_document": requires_document,
                "presence_status": presence_status, "confirmed": confirmed, "active": active,
            }.items()
            if value is not None
        }
        if clear_max_carry_over:
            changes["max_carry_over"] = None
        merged = {**current, **changes}
        validation = validate_leave_type(
            code=merged["code"], name_en=merged["name_en"], name_fr=merged["name_fr"],
            accrual_days_per_month=merged["accrual_days_per_month"], max_carry_over=merged["max_carry_over"],
            counts_days=merged["counts_days"], presence_status=merged["presence_status"],
        )
        if isinstance(validation, Err):
            return validation
        self.connection.execute(
            """
            UPDATE hr.leave_types
            SET name_en = %s, name_fr = %s, paid = %s, accrual_days_per_month = %s, max_carry_over = %s, counts_days = %s,
                requires_document = %s, presence_status = %s, confirmed = %s, active = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                merged["name_en"], merged["name_fr"], merged["paid"], merged["accrual_days_per_month"], merged["max_carry_over"],
                merged["counts_days"], merged["requires_document"], merged["presence_status"], merged["confirmed"],
                merged["active"], leave_type_id, tenant_id,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_type.updated",
            entity_type="leave_type", entity_id=leave_type_id,
            payload={key: _text(value) if isinstance(value, Decimal) else value for key, value in changes.items()},
        )
        return Ok(self.get_type(tenant_id=tenant_id, leave_type_id=leave_type_id))


class LeaveBalanceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _ensure(self, tenant_id: str, employee_id: str, leave_type_id: str, year: int) -> str:
        self.connection.execute(
            """
            INSERT INTO hr.leave_balances (id, tenant_id, employee_id, leave_type_id, year) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id, leave_type_id, year) DO NOTHING
            """,
            (str(ULID()), tenant_id, employee_id, leave_type_id, year),
        )
        return self.connection.execute(
            "SELECT id FROM hr.leave_balances WHERE tenant_id = %s AND employee_id = %s AND leave_type_id = %s AND year = %s",
            (tenant_id, employee_id, leave_type_id, year),
        ).fetchone()[0]

    def add_taken(self, *, tenant_id: str, employee_id: str, leave_type_id: str, year: int, days: Decimal) -> None:
        balance_id = self._ensure(tenant_id, employee_id, leave_type_id, year)
        self.connection.execute("UPDATE hr.leave_balances SET taken = taken + %s WHERE id = %s", (days, balance_id))

    def balance_view(self, *, tenant_id: str, employee_id: str, leave_type: LeaveType, year: int) -> BalanceView:
        rows = self.connection.execute(
            """
            SELECT year, accrued, taken, adjusted FROM hr.leave_balances
            WHERE tenant_id = %s AND employee_id = %s AND leave_type_id = %s AND year <= %s
            ORDER BY year
            """,
            (tenant_id, employee_id, leave_type.id, year),
        ).fetchall()
        return roll_balances([YearFigures(*row) for row in rows], leave_type.max_carry_over, until=year)[year]

    def balances(self, *, tenant_id: str, year: int, employee_id: str | None = None) -> list[dict]:
        types = {row["id"]: row for row in LeaveTypeService(self.connection).list_types(tenant_id=tenant_id)}
        params: list[object] = [tenant_id, year]
        clause = ""
        if employee_id:
            clause = " AND b.employee_id = %s"
            params.append(employee_id)
        rows = self.connection.execute(
            f"""
            SELECT b.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, b.leave_type_id, b.year,
                   b.accrued, b.taken, b.adjusted
            FROM hr.leave_balances b
            JOIN hr.employees e ON e.id = b.employee_id
            WHERE b.tenant_id = %s AND b.year <= %s{clause}
            ORDER BY e.employee_no, b.leave_type_id, b.year
            """,
            params,
        ).fetchall()
        grouped: dict[tuple[str, str], dict] = {}
        for r in rows:
            item = grouped.setdefault((r[0], r[3]), {"employee_no": r[1], "full_name": r[2], "figures": []})
            item["figures"].append(YearFigures(r[4], r[5], r[6], r[7]))
        result = []
        for (row_employee_id, leave_type_id), item in grouped.items():
            leave_type = types[leave_type_id]
            view = roll_balances(item["figures"], leave_type["max_carry_over"], until=year)[year]
            result.append({
                "employee_id": row_employee_id, "employee_no": item["employee_no"], "full_name": item["full_name"],
                "leave_type_id": leave_type_id, "leave_type_code": leave_type["code"],
                "tracks_balance": leave_type["accrual_days_per_month"] > 0, "year": year,
                "carried_over": view.carried_over, "accrued": view.accrued, "taken": view.taken,
                "adjusted": view.adjusted, "available": view.available,
            })
        return result

    def adjust(
        self, *, tenant_id: str, actor_id: str, employee_id: str, leave_type_id: str, year: int, delta: Decimal, reason: str
    ) -> Result[dict]:
        if not reason.strip():
            return Err("INVALID_ADJUSTMENT", "a reason is required", "un motif est obligatoire")
        if delta == 0:
            return Err("INVALID_ADJUSTMENT", "the adjustment cannot be zero", "l'ajustement ne peut pas être nul")
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s", (employee_id, tenant_id)).fetchone() is None:
            return EMPLOYEE_NOT_FOUND
        if LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=leave_type_id) is None:
            return TYPE_NOT_FOUND
        balance_id = self._ensure(tenant_id, employee_id, leave_type_id, year)
        self.connection.execute("UPDATE hr.leave_balances SET adjusted = adjusted + %s WHERE id = %s", (delta, balance_id))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_balance.adjusted",
            entity_type="leave_balance", entity_id=balance_id,
            payload={"employee_id": employee_id, "leave_type_id": leave_type_id, "year": year, "delta": str(delta), "reason": reason.strip()},
        )
        return Ok(next(b for b in self.balances(tenant_id=tenant_id, year=year, employee_id=employee_id) if b["leave_type_id"] == leave_type_id))

    def post_month_accruals(self, *, tenant_id: str, period: datetime.date) -> int:
        """Posts the month's accrual of every accruing type for everyone employed in it. Re-posting replaces."""
        first, last = month_bounds(period)
        accruing = [
            _domain_type(row)
            for row in LeaveTypeService(self.connection).list_types(tenant_id=tenant_id)
            if row["active"] and row["accrual_days_per_month"] > 0
        ]
        if not accruing:
            return 0
        posted = 0
        for employee in employed_between(self.connection, tenant_id=tenant_id, date_from=first, date_to=last):
            for leave_type in accruing:
                days = month_accrual(
                    rate=leave_type.accrual_days_per_month, period=first,
                    employed_from=employee["hire_date"], employed_to=employee["termination_date"],
                )
                self.connection.execute(
                    """
                    INSERT INTO hr.leave_accruals (tenant_id, employee_id, leave_type_id, period, days) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, employee_id, leave_type_id, period) DO UPDATE SET days = EXCLUDED.days, posted_at = NOW()
                    """,
                    (tenant_id, employee["id"], leave_type.id, first, days),
                )
                balance_id = self._ensure(tenant_id, employee["id"], leave_type.id, first.year)
                self.connection.execute(
                    """
                    UPDATE hr.leave_balances SET accrued = (
                        SELECT COALESCE(SUM(days), 0) FROM hr.leave_accruals
                        WHERE tenant_id = %s AND employee_id = %s AND leave_type_id = %s AND period BETWEEN %s AND %s
                    ) WHERE id = %s
                    """,
                    (tenant_id, employee["id"], leave_type.id, datetime.date(first.year, 1, 1), datetime.date(first.year, 12, 31), balance_id),
                )
                posted += 1
        return posted


class LeaveRequestService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- reads ------------------------------------------------------------------
    def list_requests(self, *, tenant_id: str, status: str | None = None, employee_id: str | None = None) -> list[dict]:
        clauses = ["r.tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status:
            clauses.append("r.status = %s")
            params.append(status)
        if employee_id:
            clauses.append("r.employee_id = %s")
            params.append(employee_id)
        return self._query(clauses, params)

    def _request(self, tenant_id: str, request_id: str) -> dict:
        return self._query(["r.tenant_id = %s", "r.id = %s"], [tenant_id, request_id])[0]

    def _query(self, clauses: list[str], params: list[object]) -> list[dict]:
        rows = self.connection.execute(
            f"""
            SELECT {_LIST_COLUMNS}
            FROM hr.leave_requests r
            JOIN hr.employees e ON e.id = r.employee_id
            LEFT JOIN hr.leave_types t ON t.id = r.leave_type_id
            WHERE {' AND '.join(clauses)}
            ORDER BY r.start_date DESC, e.employee_no
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "employee_id": r[1], "employee_no": r[2], "full_name": r[3], "leave_type_id": r[4],
                "leave_type_code": r[5], "leave_type_name_en": r[6], "leave_type_name_fr": r[7], "legacy_leave_type": r[8],
                "start_date": r[9].isoformat(), "end_date": r[10].isoformat(), "days": r[11], "half_day": r[12],
                "reason": r[13], "document_ref": r[14], "status": r[15], "reviewed_by": r[16],
                "reviewed_at": r[17].isoformat() if r[17] else None, "review_note": r[18],
            }
            for r in rows
        ]

    def _locked(self, tenant_id: str, request_id: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(_REQUEST_KEYS)} FROM hr.leave_requests WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (request_id, tenant_id),
        ).fetchone()
        return dict(zip(_REQUEST_KEYS, row)) if row else None

    def _overlapping(self, tenant_id: str, employee_id: str, start: datetime.date, end: datetime.date, exclude_id: str | None) -> bool:
        return self.connection.execute(
            """
            SELECT 1 FROM hr.leave_requests
            WHERE tenant_id = %s AND employee_id = %s AND status IN ('pending', 'approved')
              AND start_date <= %s AND end_date >= %s AND id <> %s
            """,
            (tenant_id, employee_id, end, start, exclude_id or ""),
        ).fetchone() is not None

    def _plan(
        self, *, tenant_id: str, employee_id: str, leave_type: LeaveType, start_date: datetime.date, end_date: datetime.date, half_day: bool
    ) -> Result[_Plan]:
        dates_ok = validate_leave(start_date=start_date, end_date=end_date)
        if isinstance(dates_ok, Err):
            return dates_ok
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s", (employee_id, tenant_id)).fetchone() is None:
            return EMPLOYEE_NOT_FOUND
        employees = employed_between(self.connection, tenant_id=tenant_id, date_from=start_date, date_to=end_date, employee_ids=[employee_id])
        if not employees or not all(is_employed(employees[0], day) for day in date_range(start_date, end_date)):
            return Err("NOT_EMPLOYED", "the employee is not employed on every day of this leave", "l'employé n'est pas en poste sur tous les jours de ce congé")
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=[employee_id], date_from=start_date, date_to=end_date)[employee_id]
        holidays = set(HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=start_date, date_to=end_date))
        if leave_type.counts_days == "working" and not all(day.assigned for day in resolved.values()):
            return Err(
                "NO_SCHEDULE",
                "the employee has no schedule on some of these dates, so working days cannot be counted",
                "l'employé n'a pas d'horaire sur certaines de ces dates : les jours ouvrés ne peuvent pas être comptés",
            )
        working = {day for day, resolved_day in resolved.items() if resolved_day.is_working_day and day not in holidays}
        dates = leave_dates(start=start_date, end=end_date, counts_days=leave_type.counts_days, working_days=working)
        days = requested_days(start=start_date, end=end_date, half_day=half_day, counted=dates)
        if isinstance(days, Err):
            return days
        return Ok(_Plan(dates=dates, days=days.value, resolved=resolved, holidays=holidays))

    def _type_of(self, tenant_id: str, request: dict) -> Result[LeaveType]:
        if request["leave_type_id"] is None:
            return Err(
                "INVALID_LEAVE",
                "this old request has no leave type: set one before deciding it",
                "cette ancienne demande n'a pas de type de congé : indiquez-en un avant de la traiter",
            )
        row = LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=request["leave_type_id"])
        return TYPE_NOT_FOUND if row is None else Ok(_domain_type(row))

    # ---- effects of an approved request -------------------------------------------
    def _apply(self, *, tenant_id: str, actor_id: str, request: dict, leave_type: LeaveType) -> Result[None]:
        planned = self._plan(
            tenant_id=tenant_id, employee_id=request["employee_id"], leave_type=leave_type,
            start_date=request["start_date"], end_date=request["end_date"], half_day=request["half_day"],
        )
        if isinstance(planned, Err):
            return planned
        plan = planned.value
        closed = closed_periods(self.connection, tenant_id, plan.dates)
        if closed:
            return month_closed_error(closed)
        year = request["start_date"].year
        balances = LeaveBalanceService(self.connection)
        if leave_type.tracks_balance:
            enough = check_balance(balances.balance_view(tenant_id=tenant_id, employee_id=request["employee_id"], leave_type=leave_type, year=year), plan.days)
            if isinstance(enough, Err):
                return enough
        presence = PresenceService(self.connection)
        if not request["half_day"]:
            existing = presence.existing_days(tenant_id=tenant_id, employee_ids=[request["employee_id"]], date_from=min(plan.dates), date_to=max(plan.dates))
            worked = [day.isoformat() for day in plan.dates if (existing.get((request["employee_id"], day)) or {}).get("worked_minutes", 0) > 0]
            if worked:
                listed = ", ".join(worked)
                return Err("LEAVE_OVERLAPS_WORK", f"the employee worked on {listed}", f"l'employé a travaillé le {listed}")
        balances.add_taken(tenant_id=tenant_id, employee_id=request["employee_id"], leave_type_id=leave_type.id, year=year, days=plan.days)
        if not request["half_day"]:
            for day in plan.dates:
                resolved_day = plan.resolved[day]
                expected = resolved_day.window is not None and day not in plan.holidays
                figures = DayFigures(
                    status=leave_type.presence_status, schedule_id=resolved_day.schedule_id,
                    scheduled_minutes=resolved_day.window.scheduled_minutes if expected else 0, worked_minutes=0,
                )
                presence.upsert_day(
                    tenant_id=tenant_id, actor_id=actor_id, employee_id=request["employee_id"], work_date=day,
                    figures=figures, source="leave", justified=True, leave_request_id=request["id"],
                )
        self.connection.execute("UPDATE hr.leave_requests SET days = %s, balance_year = %s WHERE id = %s", (plan.days, year, request["id"]))
        return Ok(None)

    def _unapply(self, *, tenant_id: str, request: dict) -> Result[None]:
        closed = closed_periods(self.connection, tenant_id, date_range(request["start_date"], request["end_date"]))
        if closed:
            return month_closed_error(closed)
        if request["leave_type_id"] is not None and request["days"] is not None:
            LeaveBalanceService(self.connection).add_taken(
                tenant_id=tenant_id, employee_id=request["employee_id"], leave_type_id=request["leave_type_id"],
                year=request["balance_year"] or request["start_date"].year, days=-request["days"],
            )
        self.connection.execute("DELETE FROM hr.presence_days WHERE tenant_id = %s AND leave_request_id = %s", (tenant_id, request["id"]))
        return Ok(None)

    def _decide(self, tenant_id: str, actor_id: str, request: dict, status: str, note: str | None) -> None:
        self.connection.execute(
            "UPDATE hr.leave_requests SET status = %s, reviewed_by = %s, reviewed_at = NOW(), review_note = %s WHERE id = %s AND tenant_id = %s",
            (status, actor_id, note, request["id"], tenant_id),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.status_changed",
            entity_type="leave_request", entity_id=request["id"],
            payload={"from_status": request["status"], "to_status": status, "days": _text(request["days"]), "note": note},
        )

    # ---- writes -----------------------------------------------------------------
    def create_request(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        employee_id: str,
        leave_type_id: str,
        start_date: datetime.date,
        end_date: datetime.date,
        half_day: bool = False,
        reason: str | None = None,
        document_ref: str | None = None,
    ) -> Result[dict]:
        row = LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=leave_type_id)
        if row is None or not row["active"]:
            return TYPE_NOT_FOUND
        leave_type = _domain_type(row)
        plan = self._plan(tenant_id=tenant_id, employee_id=employee_id, leave_type=leave_type, start_date=start_date, end_date=end_date, half_day=half_day)
        if isinstance(plan, Err):
            return plan
        if self._overlapping(tenant_id, employee_id, start_date, end_date, exclude_id=None):
            return LEAVE_OVERLAP
        request_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.leave_requests (id, tenant_id, employee_id, leave_type, leave_type_id, start_date, end_date, days,
                                           half_day, reason, document_ref, balance_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request_id, tenant_id, employee_id, leave_type.code, leave_type.id, start_date, end_date, plan.value.days,
                half_day, reason, document_ref, start_date.year,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.created",
            entity_type="leave_request", entity_id=request_id,
            payload={
                "employee_id": employee_id, "leave_type": leave_type.code, "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(), "days": str(plan.value.days), "half_day": half_day,
            },
        )
        return Ok(self._request(tenant_id, request_id))

    def approve(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None = None) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        if request["status"] != "pending":
            return Err("INVALID_TRANSITION", "only a pending leave request can be approved", "seule une demande de congé en attente peut être approuvée")
        leave_type = self._type_of(tenant_id, request)
        if isinstance(leave_type, Err):
            return leave_type
        if leave_type.value.requires_document and not (request["document_ref"] or "").strip():
            return Err(
                "LEAVE_DOCUMENT_REQUIRED",
                "this leave type needs a supporting document before approval",
                "ce type de congé exige un justificatif avant approbation",
            )
        applied = self._apply(tenant_id=tenant_id, actor_id=actor_id, request=request, leave_type=leave_type.value)
        if isinstance(applied, Err):
            return applied
        self._decide(tenant_id, actor_id, request, "approved", note)
        return Ok(self._request(tenant_id, request_id))

    def reject(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None = None) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        if request["status"] != "pending":
            return Err("INVALID_TRANSITION", "only a pending leave request can be rejected", "seule une demande de congé en attente peut être refusée")
        self._decide(tenant_id, actor_id, request, "rejected", note)
        return Ok(self._request(tenant_id, request_id))

    def cancel(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None = None) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        if request["status"] not in ("pending", "approved"):
            return Err(
                "INVALID_TRANSITION",
                "only a pending or approved leave request can be cancelled",
                "seule une demande de congé en attente ou approuvée peut être annulée",
            )
        if request["status"] == "approved":
            undone = self._unapply(tenant_id=tenant_id, request=request)
            if isinstance(undone, Err):
                return undone
        self._decide(tenant_id, actor_id, request, "cancelled", note)
        return Ok(self._request(tenant_id, request_id))

    def update_request(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        request_id: str,
        leave_type_id: str | None = None,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
        half_day: bool | None = None,
        reason: str | None = None,
        document_ref: str | None = None,
    ) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        new_type_id = leave_type_id or request["leave_type_id"]
        if new_type_id is None:
            return Err("INVALID_LEAVE", "choose a leave type", "choisissez un type de congé")
        row = LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=new_type_id)
        if row is None:
            return TYPE_NOT_FOUND
        leave_type = _domain_type(row)
        updated = {
            **request,
            "leave_type_id": new_type_id,
            "leave_type": leave_type.code,
            "start_date": start_date or request["start_date"],
            "end_date": end_date or request["end_date"],
            "half_day": half_day if half_day is not None else request["half_day"],
            "reason": reason if reason is not None else request["reason"],
            "document_ref": document_ref if document_ref is not None else request["document_ref"],
        }
        if request["status"] == "approved":
            undone = self._unapply(tenant_id=tenant_id, request=request)
            if isinstance(undone, Err):
                return undone
        plan = self._plan(
            tenant_id=tenant_id, employee_id=request["employee_id"], leave_type=leave_type,
            start_date=updated["start_date"], end_date=updated["end_date"], half_day=updated["half_day"],
        )
        if isinstance(plan, Err):
            return plan
        if self._overlapping(tenant_id, request["employee_id"], updated["start_date"], updated["end_date"], exclude_id=request_id):
            return LEAVE_OVERLAP
        self.connection.execute(
            """
            UPDATE hr.leave_requests
            SET leave_type_id = %s, leave_type = %s, start_date = %s, end_date = %s, half_day = %s, days = %s,
                reason = %s, document_ref = %s, balance_year = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                new_type_id, leave_type.code, updated["start_date"], updated["end_date"], updated["half_day"], plan.value.days,
                updated["reason"], updated["document_ref"], updated["start_date"].year, request_id, tenant_id,
            ),
        )
        if request["status"] == "approved":
            applied = self._apply(tenant_id=tenant_id, actor_id=actor_id, request={**updated, "days": plan.value.days}, leave_type=leave_type)
            if isinstance(applied, Err):
                return applied
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.updated",
            entity_type="leave_request", entity_id=request_id,
            payload={
                "leave_type": leave_type.code, "start_date": updated["start_date"].isoformat(),
                "end_date": updated["end_date"].isoformat(), "half_day": updated["half_day"],
                "days": str(plan.value.days), "document_ref": updated["document_ref"],
            },
        )
        return Ok(self._request(tenant_id, request_id))

"""Schedules, weekly rotations, schedule assignments, public holidays and presence settings.

Every mutation takes the acting user and writes its audit row in the caller's transaction;
the router commits. Nothing here holds a statutory or plant value: they are rows.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.schedule import (
    Assignment,
    ResolvedDay,
    RotationPattern,
    Schedule,
    ScheduleDay,
    date_range,
    resolve_days,
    validate_assignment,
    validate_holiday,
    validate_presence_settings,
    validate_rotation,
    validate_schedule,
)

SCHEDULE_NOT_FOUND = Err("NOT_FOUND", "schedule not found", "horaire introuvable")
ROTATION_NOT_FOUND = Err("NOT_FOUND", "rotation not found", "roulement introuvable")
ASSIGNMENT_NOT_FOUND = Err("NOT_FOUND", "schedule assignment not found", "affectation d'horaire introuvable")
EMPLOYEE_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")
HOLIDAY_NOT_FOUND = Err("NOT_FOUND", "public holiday not found", "jour férié introuvable")
SETTINGS_MISSING = Err(
    "PRESENCE_SETTINGS_MISSING",
    "the presence settings are not set (HR > Schedules & holidays > Settings)",
    "les paramètres de présence ne sont pas renseignés (RH > Horaires et jours fériés > Paramètres)",
)
_SETTING_FIELDS = ("night_start_minute", "night_end_minute", "punch_attach_minutes", "punch_dedupe_seconds", "late_grace_minutes")


def _schedule_days(items: list[dict]) -> list[ScheduleDay]:
    return [
        ScheduleDay(int(item["weekday"]), int(item["start_minute"]), int(item["end_minute"]), int(item.get("break_minutes") or 0))
        for item in items
    ]


class ScheduleService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- schedules ----------------------------------------------------------------
    def list_schedules(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT s.id, s.code, s.name, s.is_night, s.active,
                   COALESCE(
                       json_agg(
                           json_build_object('weekday', d.weekday, 'start_minute', d.start_minute,
                                             'end_minute', d.end_minute, 'break_minutes', d.break_minutes)
                           ORDER BY d.weekday
                       ) FILTER (WHERE d.weekday IS NOT NULL),
                       '[]'::json
                   )
            FROM hr.work_schedules s
            LEFT JOIN hr.work_schedule_days d ON d.schedule_id = s.id
            WHERE s.tenant_id = %s
            GROUP BY s.id
            ORDER BY s.code
            """,
            (tenant_id,),
        ).fetchall()
        return [{"id": r[0], "code": r[1], "name": r[2], "is_night": r[3], "active": r[4], "days": r[5]} for r in rows]

    def _schedule(self, tenant_id: str, schedule_id: str) -> dict | None:
        return next((s for s in self.list_schedules(tenant_id=tenant_id) if s["id"] == schedule_id), None)

    def create_schedule(self, *, tenant_id: str, actor_id: str, code: str, name: str, is_night: bool, days: list[dict]) -> Result[dict]:
        schedule_days = _schedule_days(days)
        validation = validate_schedule(code=code, name=name, days=schedule_days)
        if isinstance(validation, Err):
            return validation
        if self._code_taken("hr.work_schedules", tenant_id, code.strip()):
            return Err("DUPLICATE_CODE", f"schedule code {code.strip()} already exists", f"le code d'horaire {code.strip()} existe déjà")
        schedule_id = str(ULID())
        self.connection.execute(
            "INSERT INTO hr.work_schedules (id, tenant_id, code, name, is_night) VALUES (%s, %s, %s, %s, %s)",
            (schedule_id, tenant_id, code.strip(), name.strip(), is_night),
        )
        self._write_days(tenant_id, schedule_id, schedule_days)
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="work_schedule.created",
            entity_type="work_schedule", entity_id=schedule_id, payload={"code": code.strip(), "days": days},
        )
        return Ok(self._schedule(tenant_id, schedule_id))

    def update_schedule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        schedule_id: str,
        code: str | None = None,
        name: str | None = None,
        is_night: bool | None = None,
        active: bool | None = None,
        days: list[dict] | None = None,
    ) -> Result[dict]:
        current = self._schedule(tenant_id, schedule_id)
        if current is None:
            return SCHEDULE_NOT_FOUND
        new_code = code.strip() if code is not None else current["code"]
        new_name = name.strip() if name is not None else current["name"]
        schedule_days = _schedule_days(days if days is not None else current["days"])
        validation = validate_schedule(code=new_code, name=new_name, days=schedule_days)
        if isinstance(validation, Err):
            return validation
        if new_code != current["code"] and self._code_taken("hr.work_schedules", tenant_id, new_code):
            return Err("DUPLICATE_CODE", f"schedule code {new_code} already exists", f"le code d'horaire {new_code} existe déjà")
        self.connection.execute(
            "UPDATE hr.work_schedules SET code = %s, name = %s, is_night = %s, active = %s WHERE id = %s AND tenant_id = %s",
            (
                new_code, new_name,
                is_night if is_night is not None else current["is_night"],
                active if active is not None else current["active"],
                schedule_id, tenant_id,
            ),
        )
        if days is not None:
            self.connection.execute("DELETE FROM hr.work_schedule_days WHERE schedule_id = %s AND tenant_id = %s", (schedule_id, tenant_id))
            self._write_days(tenant_id, schedule_id, schedule_days)
        changes = {k: v for k, v in {"code": code, "name": name, "is_night": is_night, "active": active, "days": days}.items() if v is not None}
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="work_schedule.updated",
            entity_type="work_schedule", entity_id=schedule_id, payload=changes,
        )
        return Ok(self._schedule(tenant_id, schedule_id))

    def _write_days(self, tenant_id: str, schedule_id: str, days: list[ScheduleDay]) -> None:
        for day in days:
            self.connection.execute(
                """
                INSERT INTO hr.work_schedule_days (schedule_id, tenant_id, weekday, start_minute, end_minute, break_minutes)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (schedule_id, tenant_id, day.weekday, day.start_minute, day.end_minute, day.break_minutes),
            )

    def _code_taken(self, table: str, tenant_id: str, code: str) -> bool:
        # `table` is always one of this module's own table names, never user input.
        return self.connection.execute(f"SELECT 1 FROM {table} WHERE tenant_id = %s AND code = %s", (tenant_id, code)).fetchone() is not None

    def _missing_schedules(self, tenant_id: str, schedule_ids: list[str]) -> bool:
        wanted = set(schedule_ids)
        found = {
            row[0]
            for row in self.connection.execute(
                "SELECT id FROM hr.work_schedules WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, list(wanted))
            ).fetchall()
        }
        return found != wanted

    # ---- rotations ----------------------------------------------------------------
    def list_rotations(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT p.id, p.code, p.name, p.anchor_date, p.active,
                   COALESCE(array_agg(st.schedule_id ORDER BY st.position) FILTER (WHERE st.schedule_id IS NOT NULL), '{}')
            FROM hr.rotation_patterns p
            LEFT JOIN hr.rotation_pattern_steps st ON st.pattern_id = p.id
            WHERE p.tenant_id = %s
            GROUP BY p.id
            ORDER BY p.code
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {"id": r[0], "code": r[1], "name": r[2], "anchor_date": r[3].isoformat(), "active": r[4], "schedule_ids": list(r[5])}
            for r in rows
        ]

    def _rotation(self, tenant_id: str, rotation_id: str) -> dict | None:
        return next((r for r in self.list_rotations(tenant_id=tenant_id) if r["id"] == rotation_id), None)

    def create_rotation(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, anchor_date: datetime.date, schedule_ids: list[str]
    ) -> Result[dict]:
        validation = validate_rotation(code=code, name=name, anchor_date=anchor_date, schedule_ids=schedule_ids)
        if isinstance(validation, Err):
            return validation
        if self._missing_schedules(tenant_id, schedule_ids):
            return SCHEDULE_NOT_FOUND
        if self._code_taken("hr.rotation_patterns", tenant_id, code.strip()):
            return Err("DUPLICATE_CODE", f"rotation code {code.strip()} already exists", f"le code de roulement {code.strip()} existe déjà")
        rotation_id = str(ULID())
        self.connection.execute(
            "INSERT INTO hr.rotation_patterns (id, tenant_id, code, name, anchor_date) VALUES (%s, %s, %s, %s, %s)",
            (rotation_id, tenant_id, code.strip(), name.strip(), anchor_date),
        )
        self._write_steps(tenant_id, rotation_id, schedule_ids)
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rotation_pattern.created",
            entity_type="rotation_pattern", entity_id=rotation_id,
            payload={"code": code.strip(), "anchor_date": anchor_date.isoformat(), "schedule_ids": schedule_ids},
        )
        return Ok(self._rotation(tenant_id, rotation_id))

    def update_rotation(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        rotation_id: str,
        code: str | None = None,
        name: str | None = None,
        anchor_date: datetime.date | None = None,
        schedule_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        current = self._rotation(tenant_id, rotation_id)
        if current is None:
            return ROTATION_NOT_FOUND
        new_code = code.strip() if code is not None else current["code"]
        new_name = name.strip() if name is not None else current["name"]
        new_anchor = anchor_date or datetime.date.fromisoformat(current["anchor_date"])
        new_steps = schedule_ids if schedule_ids is not None else current["schedule_ids"]
        validation = validate_rotation(code=new_code, name=new_name, anchor_date=new_anchor, schedule_ids=new_steps)
        if isinstance(validation, Err):
            return validation
        if self._missing_schedules(tenant_id, new_steps):
            return SCHEDULE_NOT_FOUND
        if new_code != current["code"] and self._code_taken("hr.rotation_patterns", tenant_id, new_code):
            return Err("DUPLICATE_CODE", f"rotation code {new_code} already exists", f"le code de roulement {new_code} existe déjà")
        self.connection.execute(
            "UPDATE hr.rotation_patterns SET code = %s, name = %s, anchor_date = %s, active = %s WHERE id = %s AND tenant_id = %s",
            (new_code, new_name, new_anchor, active if active is not None else current["active"], rotation_id, tenant_id),
        )
        if schedule_ids is not None:
            self.connection.execute("DELETE FROM hr.rotation_pattern_steps WHERE pattern_id = %s AND tenant_id = %s", (rotation_id, tenant_id))
            self._write_steps(tenant_id, rotation_id, schedule_ids)
        changes = {
            k: v
            for k, v in {
                "code": code, "name": name, "anchor_date": anchor_date.isoformat() if anchor_date else None,
                "schedule_ids": schedule_ids, "active": active,
            }.items()
            if v is not None
        }
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rotation_pattern.updated",
            entity_type="rotation_pattern", entity_id=rotation_id, payload=changes,
        )
        return Ok(self._rotation(tenant_id, rotation_id))

    def _write_steps(self, tenant_id: str, rotation_id: str, schedule_ids: list[str]) -> None:
        for position, schedule_id in enumerate(schedule_ids):
            self.connection.execute(
                "INSERT INTO hr.rotation_pattern_steps (pattern_id, tenant_id, position, schedule_id) VALUES (%s, %s, %s, %s)",
                (rotation_id, tenant_id, position, schedule_id),
            )

    # ---- assignments --------------------------------------------------------------
    def list_assignments(self, *, tenant_id: str, employee_id: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = ""
        if employee_id:
            clause = " AND a.employee_id = %s"
            params.append(employee_id)
        rows = self.connection.execute(
            f"""
            SELECT a.id, a.employee_id, e.employee_no, e.first_name || ' ' || e.last_name,
                   a.schedule_id, s.code, a.rotation_pattern_id, p.code, a.rotation_offset_weeks, a.valid_from, a.valid_to
            FROM hr.schedule_assignments a
            JOIN hr.employees e ON e.id = a.employee_id
            LEFT JOIN hr.work_schedules s ON s.id = a.schedule_id
            LEFT JOIN hr.rotation_patterns p ON p.id = a.rotation_pattern_id
            WHERE a.tenant_id = %s{clause}
            ORDER BY e.employee_no, a.valid_from
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "employee_id": r[1], "employee_no": r[2], "full_name": r[3],
                "schedule_id": r[4], "schedule_code": r[5], "rotation_pattern_id": r[6], "rotation_code": r[7],
                "rotation_offset_weeks": r[8], "valid_from": r[9].isoformat(), "valid_to": r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]

    def _one_assignment(self, tenant_id: str, assignment_id: str) -> dict | None:
        return next((a for a in self.list_assignments(tenant_id=tenant_id) if a["id"] == assignment_id), None)

    def _check_target(self, tenant_id: str, schedule_id: str | None, rotation_pattern_id: str | None) -> Result[None]:
        if schedule_id and self._missing_schedules(tenant_id, [schedule_id]):
            return SCHEDULE_NOT_FOUND
        if rotation_pattern_id and self._rotation(tenant_id, rotation_pattern_id) is None:
            return ROTATION_NOT_FOUND
        return Ok(None)

    def create_assignment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        employee_id: str,
        valid_from: datetime.date,
        valid_to: datetime.date | None = None,
        schedule_id: str | None = None,
        rotation_pattern_id: str | None = None,
        rotation_offset_weeks: int = 0,
    ) -> Result[dict]:
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s", (employee_id, tenant_id)).fetchone() is None:
            return EMPLOYEE_NOT_FOUND
        target = self._check_target(tenant_id, schedule_id, rotation_pattern_id)
        if isinstance(target, Err):
            return target
        validation = validate_assignment(
            valid_from=valid_from, valid_to=valid_to, schedule_id=schedule_id, rotation_pattern_id=rotation_pattern_id,
            rotation_offset_weeks=rotation_offset_weeks, others=self._assignments(tenant_id, [employee_id]).get(employee_id, []),
        )
        if isinstance(validation, Err):
            return validation
        assignment_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.schedule_assignments (id, tenant_id, employee_id, schedule_id, rotation_pattern_id,
                                                 rotation_offset_weeks, valid_from, valid_to)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (assignment_id, tenant_id, employee_id, schedule_id, rotation_pattern_id, rotation_offset_weeks, valid_from, valid_to),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="schedule_assignment.created",
            entity_type="schedule_assignment", entity_id=assignment_id,
            payload={
                "employee_id": employee_id, "schedule_id": schedule_id, "rotation_pattern_id": rotation_pattern_id,
                "rotation_offset_weeks": rotation_offset_weeks, "valid_from": valid_from.isoformat(),
                "valid_to": valid_to.isoformat() if valid_to else None,
            },
        )
        return Ok(self._one_assignment(tenant_id, assignment_id))

    def update_assignment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        assignment_id: str,
        valid_from: datetime.date | None = None,
        valid_to: datetime.date | None = None,
        clear_valid_to: bool = False,
        schedule_id: str | None = None,
        rotation_pattern_id: str | None = None,
        rotation_offset_weeks: int | None = None,
    ) -> Result[dict]:
        current = self._one_assignment(tenant_id, assignment_id)
        if current is None:
            return ASSIGNMENT_NOT_FOUND
        new_schedule, new_rotation = current["schedule_id"], current["rotation_pattern_id"]
        if schedule_id is not None and rotation_pattern_id is not None:
            new_schedule, new_rotation = schedule_id, rotation_pattern_id  # refused below by the domain
        elif schedule_id is not None:
            new_schedule, new_rotation = schedule_id, None
        elif rotation_pattern_id is not None:
            new_schedule, new_rotation = None, rotation_pattern_id
        new_from = valid_from or datetime.date.fromisoformat(current["valid_from"])
        stored_to = datetime.date.fromisoformat(current["valid_to"]) if current["valid_to"] else None
        new_to = None if clear_valid_to else (valid_to if valid_to is not None else stored_to)
        new_offset = rotation_offset_weeks if rotation_offset_weeks is not None else current["rotation_offset_weeks"]
        target = self._check_target(tenant_id, new_schedule, new_rotation)
        if isinstance(target, Err):
            return target
        others = [a for a in self._assignments(tenant_id, [current["employee_id"]]).get(current["employee_id"], []) if a.id != assignment_id]
        validation = validate_assignment(
            valid_from=new_from, valid_to=new_to, schedule_id=new_schedule, rotation_pattern_id=new_rotation,
            rotation_offset_weeks=new_offset, others=others,
        )
        if isinstance(validation, Err):
            return validation
        self.connection.execute(
            """
            UPDATE hr.schedule_assignments
            SET schedule_id = %s, rotation_pattern_id = %s, rotation_offset_weeks = %s, valid_from = %s, valid_to = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (new_schedule, new_rotation, new_offset, new_from, new_to, assignment_id, tenant_id),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="schedule_assignment.updated",
            entity_type="schedule_assignment", entity_id=assignment_id,
            payload={
                "schedule_id": new_schedule, "rotation_pattern_id": new_rotation, "rotation_offset_weeks": new_offset,
                "valid_from": new_from.isoformat(), "valid_to": new_to.isoformat() if new_to else None,
            },
        )
        return Ok(self._one_assignment(tenant_id, assignment_id))

    def _assignments(
        self, tenant_id: str, employee_ids: list[str], date_from: datetime.date | None = None, date_to: datetime.date | None = None
    ) -> dict[str, list[Assignment]]:
        params: list[object] = [tenant_id, list(employee_ids)]
        clause = ""
        if date_from is not None and date_to is not None:
            clause = " AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)"
            params += [date_to, date_from]
        rows = self.connection.execute(
            f"""
            SELECT id, employee_id, valid_from, valid_to, schedule_id, rotation_pattern_id, rotation_offset_weeks
            FROM hr.schedule_assignments
            WHERE tenant_id = %s AND employee_id = ANY(%s){clause}
            ORDER BY valid_from
            """,
            params,
        ).fetchall()
        grouped: dict[str, list[Assignment]] = {}
        for r in rows:
            grouped.setdefault(r[1], []).append(
                Assignment(id=r[0], employee_id=r[1], valid_from=r[2], valid_to=r[3], schedule_id=r[4], rotation_pattern_id=r[5], rotation_offset_weeks=r[6])
            )
        return grouped

    # ---- resolution ---------------------------------------------------------------
    def resolve(
        self, *, tenant_id: str, employee_ids: list[str], date_from: datetime.date, date_to: datetime.date
    ) -> dict[str, dict[datetime.date, ResolvedDay]]:
        schedules = {
            item["id"]: Schedule(id=item["id"], code=item["code"], is_night=item["is_night"], days=tuple(_schedule_days(item["days"])))
            for item in self.list_schedules(tenant_id=tenant_id)
        }
        patterns = {
            item["id"]: RotationPattern(id=item["id"], anchor_date=datetime.date.fromisoformat(item["anchor_date"]), schedule_ids=tuple(item["schedule_ids"]))
            for item in self.list_rotations(tenant_id=tenant_id)
            if item["schedule_ids"]
        }
        assignments = self._assignments(tenant_id, employee_ids, date_from, date_to)
        dates = date_range(date_from, date_to)
        return {
            employee_id: resolve_days(assignments=assignments.get(employee_id, []), patterns=patterns, schedules=schedules, dates=dates)
            for employee_id in employee_ids
        }


class HolidayService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_holidays(self, *, tenant_id: str, year: int | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = ""
        if year is not None:
            clause = " AND EXTRACT(YEAR FROM holiday_date) = %s"
            params.append(year)
        rows = self.connection.execute(
            f"SELECT id, country_code, holiday_date, name, paid, confirmed FROM hr.public_holidays WHERE tenant_id = %s{clause} ORDER BY holiday_date",
            params,
        ).fetchall()
        return [
            {"id": r[0], "country_code": r[1], "holiday_date": r[2].isoformat(), "name": r[3], "paid": r[4], "confirmed": r[5]}
            for r in rows
        ]

    def _holiday(self, tenant_id: str, holiday_id: str) -> dict | None:
        return next((h for h in self.list_holidays(tenant_id=tenant_id) if h["id"] == holiday_id), None)

    def _taken(self, tenant_id: str, country_code: str, holiday_date: datetime.date) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM hr.public_holidays WHERE tenant_id = %s AND country_code = %s AND holiday_date = %s",
            (tenant_id, country_code, holiday_date),
        ).fetchone() is not None

    def create_holiday(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        country_code: str,
        holiday_date: datetime.date,
        name: str,
        paid: bool = True,
        confirmed: bool = False,
    ) -> Result[dict]:
        from modules.hr.api.presence_service import closed_periods, month_closed_error

        country = country_code.strip().upper()
        validation = validate_holiday(country_code=country, name=name)
        if isinstance(validation, Err):
            return validation
        closed = closed_periods(self.connection, tenant_id, [holiday_date])
        if closed:
            return month_closed_error(closed)
        if self._taken(tenant_id, country, holiday_date):
            return Err(
                "DUPLICATE_HOLIDAY",
                f"a public holiday already exists on {holiday_date.isoformat()} for {country}",
                f"un jour férié existe déjà le {holiday_date.isoformat()} pour {country}",
            )
        holiday_id = str(ULID())
        self.connection.execute(
            "INSERT INTO hr.public_holidays (id, tenant_id, country_code, holiday_date, name, paid, confirmed) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (holiday_id, tenant_id, country, holiday_date, name.strip(), paid, confirmed),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="public_holiday.created",
            entity_type="public_holiday", entity_id=holiday_id,
            payload={"country_code": country, "holiday_date": holiday_date.isoformat(), "name": name.strip(), "paid": paid, "confirmed": confirmed},
        )
        return Ok(self._holiday(tenant_id, holiday_id))

    def update_holiday(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        holiday_id: str,
        holiday_date: datetime.date | None = None,
        name: str | None = None,
        paid: bool | None = None,
        confirmed: bool | None = None,
    ) -> Result[dict]:
        from modules.hr.api.presence_service import closed_periods, month_closed_error

        current = self._holiday(tenant_id, holiday_id)
        if current is None:
            return HOLIDAY_NOT_FOUND
        new_date = holiday_date or datetime.date.fromisoformat(current["holiday_date"])
        current_date = datetime.date.fromisoformat(current["holiday_date"])
        closed = closed_periods(self.connection, tenant_id, {current_date, new_date})
        if closed:
            return month_closed_error(closed)
        new_name = name.strip() if name is not None else current["name"]
        validation = validate_holiday(country_code=current["country_code"], name=new_name)
        if isinstance(validation, Err):
            return validation
        if new_date.isoformat() != current["holiday_date"] and self._taken(tenant_id, current["country_code"], new_date):
            return Err(
                "DUPLICATE_HOLIDAY",
                f"a public holiday already exists on {new_date.isoformat()} for {current['country_code']}",
                f"un jour férié existe déjà le {new_date.isoformat()} pour {current['country_code']}",
            )
        self.connection.execute(
            "UPDATE hr.public_holidays SET holiday_date = %s, name = %s, paid = %s, confirmed = %s WHERE id = %s AND tenant_id = %s",
            (
                new_date, new_name,
                paid if paid is not None else current["paid"],
                confirmed if confirmed is not None else current["confirmed"],
                holiday_id, tenant_id,
            ),
        )
        changes = {
            k: v
            for k, v in {"holiday_date": holiday_date.isoformat() if holiday_date else None, "name": name, "paid": paid, "confirmed": confirmed}.items()
            if v is not None
        }
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="public_holiday.updated",
            entity_type="public_holiday", entity_id=holiday_id, payload=changes,
        )
        return Ok(self._holiday(tenant_id, holiday_id))

    def holiday_map(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[datetime.date, bool]:
        """Every public holiday date in the range, mapped to whether it is paid."""
        rows = self.connection.execute(
            """
            SELECT holiday_date, bool_or(paid) FROM hr.public_holidays
            WHERE tenant_id = %s AND holiday_date BETWEEN %s AND %s
            GROUP BY holiday_date
            """,
            (tenant_id, date_from, date_to),
        ).fetchall()
        return {row[0]: row[1] for row in rows}


class PresenceSettingsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def get(self, *, tenant_id: str) -> dict:
        row = self.connection.execute(
            f"SELECT {', '.join(_SETTING_FIELDS)}, confirmed_at FROM hr.presence_settings WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        if row is None:
            return {**{field: None for field in _SETTING_FIELDS}, "confirmed": False, "confirmed_at": None}
        values = dict(zip(_SETTING_FIELDS, row[:5]))
        return {**values, "confirmed": row[5] is not None, "confirmed_at": row[5].isoformat() if row[5] else None}

    def update(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        night_start_minute: int | None,
        night_end_minute: int | None,
        punch_attach_minutes: int | None,
        punch_dedupe_seconds: int | None,
        late_grace_minutes: int | None,
        confirm: bool = False,
    ) -> Result[dict]:
        values = {
            "night_start_minute": night_start_minute, "night_end_minute": night_end_minute,
            "punch_attach_minutes": punch_attach_minutes, "punch_dedupe_seconds": punch_dedupe_seconds,
            "late_grace_minutes": late_grace_minutes,
        }
        validation = validate_presence_settings(**values)
        if isinstance(validation, Err):
            return validation
        # Any save that is not an explicit confirmation clears the confirmation: a changed
        # value has not been checked yet.
        self.connection.execute(
            """
            INSERT INTO hr.presence_settings (tenant_id, night_start_minute, night_end_minute, punch_attach_minutes,
                                              punch_dedupe_seconds, late_grace_minutes, confirmed_by, confirmed_at,
                                              updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                night_start_minute = EXCLUDED.night_start_minute, night_end_minute = EXCLUDED.night_end_minute,
                punch_attach_minutes = EXCLUDED.punch_attach_minutes, punch_dedupe_seconds = EXCLUDED.punch_dedupe_seconds,
                late_grace_minutes = EXCLUDED.late_grace_minutes, confirmed_by = EXCLUDED.confirmed_by,
                confirmed_at = EXCLUDED.confirmed_at, updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (
                tenant_id, night_start_minute, night_end_minute, punch_attach_minutes, punch_dedupe_seconds,
                late_grace_minutes, actor_id if confirm else None, confirm, actor_id,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_settings.updated",
            entity_type="presence_settings", entity_id=tenant_id, payload={**values, "confirmed": confirm},
        )
        return Ok(self.get(tenant_id=tenant_id))

    def night_window(self, *, tenant_id: str) -> Result[tuple[int, int]]:
        settings = self.get(tenant_id=tenant_id)
        if settings["night_start_minute"] is None or settings["night_end_minute"] is None:
            return SETTINGS_MISSING
        return Ok((settings["night_start_minute"], settings["night_end_minute"]))

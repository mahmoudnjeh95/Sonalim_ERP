"""Clock-device profiles and CSV imports: stage a file, review its rows, then commit it into
punches and presence days, or discard it.

Committing re-pairs every stored punch of the people in the file over the covered days (from
every import, so a second partial file completes the first) and writes the days. A day a
person entered by hand, or an approved leave day, is kept and listed as a conflict when the
clock disagrees; everything else is written with source 'clock' ('holiday' for an unworked
public holiday). Scheduled days without any punch become absences for the people in the file.
An unset duplicate window or grace means none (0): only identical punches merge, any delay is
lateness. The night window and the attachment minutes have no such reading and are required.
"""
from __future__ import annotations

import datetime

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.presence_service import PresenceService, closed_periods, employed_between, is_employed, month_closed_error
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
from modules.hr.domain.clock_csv import ClockProfile, parse_clock_csv, validate_profile
from modules.hr.domain.pairing import PairingConfig, Punch, WorkDay, pair_punches
from modules.hr.domain.presence import PROTECTED_SOURCES, DayFigures
from modules.hr.domain.schedule import ONE_DAY, date_range

PROFILE_NOT_FOUND = Err("NOT_FOUND", "clock profile not found", "profil de pointeuse introuvable")
IMPORT_NOT_FOUND = Err("NOT_FOUND", "clock import not found", "import de pointage introuvable")
NOT_STAGED = Err(
    "IMPORT_NOT_STAGED",
    "only an import waiting for review can be committed or discarded",
    "seul un import en attente de vérification peut être importé ou écarté",
)
PAIRING_SETTINGS_MISSING = Err(
    "PRESENCE_SETTINGS_MISSING",
    "set the night-work window and the punch attachment minutes before importing (HR > Schedules & holidays > Settings)",
    "renseignez la plage de nuit et les minutes de rattachement des pointages avant d'importer (RH > Horaires et jours fériés > Paramètres)",
)
_PROFILE_KEYS = (
    "id", "code", "name", "delimiter", "has_header", "badge_column", "timestamp_column", "time_column",
    "timestamp_format", "direction_column", "in_values", "out_values", "active",
)
_IMPORT_COLUMNS = (
    "i.id, i.profile_id, p.code, i.file_name, i.date_from, i.date_to, i.status, i.total_rows, i.valid_rows, "
    "i.error_rows, i.uploaded_by, u.email, i.uploaded_at, i.decided_at, i.result"
)


def _optional(value: str | None) -> str | None:
    """None leaves an optional column alone at the call site; an empty string means 'no column'."""
    if value is None:
        return None
    return value.strip() or None


def _values(values: list[str] | None) -> list[str]:
    return [value.strip() for value in values or [] if value.strip()]


def _to_profile(profile: dict) -> ClockProfile:
    return ClockProfile(
        delimiter=profile["delimiter"], has_header=profile["has_header"], badge_column=profile["badge_column"],
        timestamp_column=profile["timestamp_column"], timestamp_format=profile["timestamp_format"],
        time_column=profile["time_column"], direction_column=profile["direction_column"],
        in_values=tuple(profile["in_values"]), out_values=tuple(profile["out_values"]),
    )


class ClockProfileService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_profiles(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            f"SELECT {', '.join(_PROFILE_KEYS)} FROM hr.clock_profiles WHERE tenant_id = %s ORDER BY code", (tenant_id,)
        ).fetchall()
        return [dict(zip(_PROFILE_KEYS, row)) for row in rows]

    def get_profile(self, *, tenant_id: str, profile_id: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(_PROFILE_KEYS)} FROM hr.clock_profiles WHERE tenant_id = %s AND id = %s", (tenant_id, profile_id)
        ).fetchone()
        return dict(zip(_PROFILE_KEYS, row)) if row else None

    def create_profile(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str,
        delimiter: str,
        has_header: bool,
        badge_column: str,
        timestamp_column: str,
        timestamp_format: str,
        time_column: str | None = None,
        direction_column: str | None = None,
        in_values: list[str] | None = None,
        out_values: list[str] | None = None,
    ) -> Result[dict]:
        time_column, direction_column = _optional(time_column), _optional(direction_column)
        validation = validate_profile(
            code=code, name=name, delimiter=delimiter, has_header=has_header, badge_column=badge_column,
            timestamp_column=timestamp_column, timestamp_format=timestamp_format, time_column=time_column,
            direction_column=direction_column,
        )
        if isinstance(validation, Err):
            return validation
        if self.connection.execute("SELECT 1 FROM hr.clock_profiles WHERE tenant_id = %s AND code = %s", (tenant_id, code.strip())).fetchone():
            return Err("DUPLICATE_CODE", f"clock profile code {code.strip()} already exists", f"le code de profil {code.strip()} existe déjà")
        profile_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.clock_profiles (id, tenant_id, code, name, delimiter, has_header, badge_column, timestamp_column,
                                           time_column, timestamp_format, direction_column, in_values, out_values)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                profile_id, tenant_id, code.strip(), name.strip(), delimiter, has_header, badge_column.strip(),
                timestamp_column.strip(), time_column, timestamp_format, direction_column, _values(in_values), _values(out_values),
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_profile.created",
            entity_type="clock_profile", entity_id=profile_id, payload={"code": code.strip(), "name": name.strip()},
        )
        return Ok(self.get_profile(tenant_id=tenant_id, profile_id=profile_id))

    def update_profile(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        name: str | None = None,
        delimiter: str | None = None,
        has_header: bool | None = None,
        badge_column: str | None = None,
        timestamp_column: str | None = None,
        timestamp_format: str | None = None,
        time_column: str | None = None,
        direction_column: str | None = None,
        in_values: list[str] | None = None,
        out_values: list[str] | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        current = self.get_profile(tenant_id=tenant_id, profile_id=profile_id)
        if current is None:
            return PROFILE_NOT_FOUND
        changes = {
            key: value
            for key, value in {
                "name": name, "delimiter": delimiter, "has_header": has_header, "badge_column": badge_column,
                "timestamp_column": timestamp_column, "timestamp_format": timestamp_format, "active": active,
                "in_values": _values(in_values) if in_values is not None else None,
                "out_values": _values(out_values) if out_values is not None else None,
            }.items()
            if value is not None
        }
        if time_column is not None:
            changes["time_column"] = _optional(time_column)
        if direction_column is not None:
            changes["direction_column"] = _optional(direction_column)
        merged = {**current, **changes}
        validation = validate_profile(
            code=merged["code"], name=merged["name"], delimiter=merged["delimiter"], has_header=merged["has_header"],
            badge_column=merged["badge_column"], timestamp_column=merged["timestamp_column"],
            timestamp_format=merged["timestamp_format"], time_column=merged["time_column"], direction_column=merged["direction_column"],
        )
        if isinstance(validation, Err):
            return validation
        self.connection.execute(
            """
            UPDATE hr.clock_profiles
            SET name = %s, delimiter = %s, has_header = %s, badge_column = %s, timestamp_column = %s, time_column = %s,
                timestamp_format = %s, direction_column = %s, in_values = %s, out_values = %s, active = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                merged["name"], merged["delimiter"], merged["has_header"], merged["badge_column"], merged["timestamp_column"],
                merged["time_column"], merged["timestamp_format"], merged["direction_column"], merged["in_values"],
                merged["out_values"], merged["active"], profile_id, tenant_id,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_profile.updated",
            entity_type="clock_profile", entity_id=profile_id, payload=changes,
        )
        return Ok(self.get_profile(tenant_id=tenant_id, profile_id=profile_id))


class ClockImportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    @staticmethod
    def _header(row) -> dict:
        return {
            "id": row[0], "profile_id": row[1], "profile_code": row[2], "file_name": row[3],
            "date_from": row[4].isoformat(), "date_to": row[5].isoformat(), "status": row[6],
            "total_rows": row[7], "valid_rows": row[8], "error_rows": row[9], "uploaded_by": row[10],
            "uploaded_by_email": row[11], "uploaded_at": row[12].isoformat(),
            "decided_at": row[13].isoformat() if row[13] else None, "result": row[14],
        }

    def list_imports(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            f"""
            SELECT {_IMPORT_COLUMNS}
            FROM hr.clock_imports i
            JOIN hr.clock_profiles p ON p.id = i.profile_id
            LEFT JOIN core.users u ON u.id = i.uploaded_by
            WHERE i.tenant_id = %s
            ORDER BY i.uploaded_at DESC
            """,
            (tenant_id,),
        ).fetchall()
        return [self._header(row) for row in rows]

    def get_import(self, *, tenant_id: str, import_id: str) -> Result[dict]:
        row = self.connection.execute(
            f"""
            SELECT {_IMPORT_COLUMNS}
            FROM hr.clock_imports i
            JOIN hr.clock_profiles p ON p.id = i.profile_id
            LEFT JOIN core.users u ON u.id = i.uploaded_by
            WHERE i.tenant_id = %s AND i.id = %s
            """,
            (tenant_id, import_id),
        ).fetchone()
        if row is None:
            return IMPORT_NOT_FOUND
        lines = self.connection.execute(
            """
            SELECT r.line_no, r.raw, r.badge_no, r.employee_id, e.employee_no, e.first_name || ' ' || e.last_name,
                   r.punched_at, r.direction, r.error_code
            FROM hr.clock_import_rows r
            LEFT JOIN hr.employees e ON e.id = r.employee_id
            WHERE r.import_id = %s
            ORDER BY r.line_no
            """,
            (import_id,),
        ).fetchall()
        rows = [
            {
                "line_no": r[0], "raw": r[1], "badge_no": r[2], "employee_id": r[3], "employee_no": r[4], "full_name": r[5],
                "punched_at": r[6].isoformat() if r[6] else None, "direction": r[7], "error_code": r[8],
            }
            for r in lines
        ]
        return Ok({**self._header(row), "rows": rows})

    def stage(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        file_name: str,
        content: str,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Result[dict]:
        if not file_name.strip():
            return Err("INVALID_IMPORT", "the file name is required", "le nom du fichier est obligatoire")
        if date_to < date_from:
            return Err("INVALID_IMPORT", "the covered days end before they start", "la période couverte se termine avant de commencer")
        profile = ClockProfileService(self.connection).get_profile(tenant_id=tenant_id, profile_id=profile_id)
        if profile is None or not profile["active"]:
            return PROFILE_NOT_FOUND
        parsed = parse_clock_csv(content, _to_profile(profile))
        if isinstance(parsed, Err):
            return parsed
        rows = parsed.value
        badges = sorted({row.badge_no for row in rows if row.badge_no})
        employee_by_badge = dict(
            self.connection.execute(
                "SELECT badge_no, id FROM hr.employees WHERE tenant_id = %s AND badge_no = ANY(%s)", (tenant_id, badges)
            ).fetchall()
        )
        stamps = [row.punched_at for row in rows if row.punched_at is not None]
        known: set[tuple[str, datetime.datetime]] = set()
        if stamps:
            known = {
                (r[0], r[1])
                for r in self.connection.execute(
                    """
                    SELECT badge_no, punched_at FROM hr.clock_punches
                    WHERE tenant_id = %s AND badge_no = ANY(%s) AND punched_at BETWEEN %s AND %s
                    """,
                    (tenant_id, badges, min(stamps), max(stamps)),
                ).fetchall()
            }
        lowest, highest = date_from - ONE_DAY, date_to + ONE_DAY
        import_id = str(ULID())
        staged = []
        for row in rows:
            error = row.error_code
            employee_id = employee_by_badge.get(row.badge_no) if row.badge_no else None
            if error is None and employee_id is None:
                error = "UNKNOWN_BADGE"
            if error is None and not lowest <= row.punched_at.date() <= highest:
                error = "OUTSIDE_RANGE"
            if error is None and (row.badge_no, row.punched_at) in known:
                error = "DUPLICATE_PUNCH"
            staged.append((str(ULID()), tenant_id, import_id, row.line_no, row.raw, row.badge_no, employee_id, row.punched_at, row.direction, error))
        errors = sum(1 for item in staged if item[-1] is not None)
        self.connection.execute(
            """
            INSERT INTO hr.clock_imports (id, tenant_id, profile_id, file_name, date_from, date_to, total_rows,
                                          valid_rows, error_rows, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (import_id, tenant_id, profile_id, file_name.strip(), date_from, date_to, len(staged), len(staged) - errors, errors, actor_id),
        )
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO hr.clock_import_rows (id, tenant_id, import_id, line_no, raw, badge_no, employee_id,
                                                  punched_at, direction, error_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                staged,
            )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_import.staged",
            entity_type="clock_import", entity_id=import_id,
            payload={
                "file_name": file_name.strip(), "profile_id": profile_id, "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(), "total_rows": len(staged), "error_rows": errors,
            },
        )
        return self.get_import(tenant_id=tenant_id, import_id=import_id)

    def commit(self, *, tenant_id: str, actor_id: str, import_id: str) -> Result[dict]:
        header = self.connection.execute(
            "SELECT status, date_from, date_to FROM hr.clock_imports WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (import_id, tenant_id),
        ).fetchone()
        if header is None:
            return IMPORT_NOT_FOUND
        status, date_from, date_to = header
        if status != "staged":
            return NOT_STAGED
        settings = PresenceSettingsService(self.connection).get(tenant_id=tenant_id)
        if settings["night_start_minute"] is None or settings["night_end_minute"] is None or settings["punch_attach_minutes"] is None:
            return PAIRING_SETTINGS_MISSING
        config = PairingConfig(
            night_start_minute=settings["night_start_minute"], night_end_minute=settings["night_end_minute"],
            attach_minutes=settings["punch_attach_minutes"], dedupe_seconds=settings["punch_dedupe_seconds"] or 0,
            late_grace_minutes=settings["late_grace_minutes"] or 0,
        )
        closed = closed_periods(self.connection, tenant_id, date_range(date_from, date_to))
        if closed:
            return month_closed_error(closed)
        valid = self.connection.execute(
            "SELECT employee_id, badge_no, punched_at, direction FROM hr.clock_import_rows WHERE import_id = %s AND error_code IS NULL ORDER BY line_no",
            (import_id,),
        ).fetchall()
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO hr.clock_punches (id, tenant_id, employee_id, badge_no, punched_at, direction, import_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, badge_no, punched_at) DO NOTHING
                """,
                [(str(ULID()), tenant_id, r[0], r[1], r[2], r[3], import_id) for r in valid],
            )
        outcome = self._apply(
            tenant_id=tenant_id, actor_id=actor_id, import_id=import_id, employee_ids=sorted({r[0] for r in valid}),
            date_from=date_from, date_to=date_to, config=config,
        )
        self.connection.execute(
            "UPDATE hr.clock_imports SET status = 'committed', decided_by = %s, decided_at = NOW(), result = %s WHERE id = %s",
            (actor_id, Jsonb(outcome), import_id),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_import.committed",
            entity_type="clock_import", entity_id=import_id,
            payload={"days_written": outcome["days_written"], "conflicts": len(outcome["conflicts"]), "anomalies": len(outcome["anomalies"])},
        )
        return Ok({"id": import_id, **outcome})

    def discard(self, *, tenant_id: str, actor_id: str, import_id: str) -> Result[dict]:
        header = self.connection.execute(
            "SELECT status FROM hr.clock_imports WHERE id = %s AND tenant_id = %s FOR UPDATE", (import_id, tenant_id)
        ).fetchone()
        if header is None:
            return IMPORT_NOT_FOUND
        if header[0] != "staged":
            return NOT_STAGED
        self.connection.execute(
            "UPDATE hr.clock_imports SET status = 'discarded', decided_by = %s, decided_at = NOW() WHERE id = %s", (actor_id, import_id)
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_import.discarded",
            entity_type="clock_import", entity_id=import_id, payload={},
        )
        return self.get_import(tenant_id=tenant_id, import_id=import_id)

    def _punches(self, tenant_id: str, employee_ids: list[str], first: datetime.date, until: datetime.date) -> dict[str, list[Punch]]:
        rows = self.connection.execute(
            """
            SELECT employee_id, punched_at, direction FROM hr.clock_punches
            WHERE tenant_id = %s AND employee_id = ANY(%s) AND punched_at >= %s AND punched_at < %s
            ORDER BY punched_at
            """,
            (tenant_id, employee_ids, datetime.datetime.combine(first, datetime.time()), datetime.datetime.combine(until, datetime.time())),
        ).fetchall()
        grouped: dict[str, list[Punch]] = {}
        for employee_id, punched_at, direction in rows:
            grouped.setdefault(employee_id, []).append(Punch(punched_at, direction))
        return grouped

    def _apply(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        import_id: str,
        employee_ids: list[str],
        date_from: datetime.date,
        date_to: datetime.date,
        config: PairingConfig,
    ) -> dict:
        outcome: dict = {
            "days_written": 0, "conflicts": [], "anomalies": [], "unscheduled": [],
            "duplicate_punches": 0, "outside_range_punches": 0,
        }
        employees = employed_between(self.connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to, employee_ids=employee_ids)
        if not employees:
            return outcome
        ids = [employee["id"] for employee in employees]
        # One neighbouring day on each side: a night shift of the day before owns the first
        # morning's out-punch, and the last day's night shift ends the morning after.
        context_from, context_to = date_from - ONE_DAY, date_to + ONE_DAY
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=context_from, date_to=context_to)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=context_from, date_to=context_to)
        punches = self._punches(tenant_id, ids, context_from, context_to + ONE_DAY)
        presence = PresenceService(self.connection)
        existing = presence.existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        for employee in employees:
            days = resolved[employee["id"]]
            work_days = [
                WorkDay(work_date=day, window=days[day].window, is_holiday=day in holidays, in_range=date_from <= day <= date_to)
                for day in date_range(context_from, context_to)
            ]
            result = pair_punches(punches.get(employee["id"], []), work_days, config)
            outcome["duplicate_punches"] += result.duplicate_punches
            outcome["outside_range_punches"] += result.outside_range_punches
            who = {"employee_id": employee["id"], "employee_no": employee["employee_no"], "full_name": employee["full_name"]}
            for day in result.days:
                if not is_employed(employee, day.work_date):
                    continue
                label = {**who, "work_date": day.work_date.isoformat()}
                if not days[day.work_date].assigned:
                    if day.first_punch is not None:
                        outcome["unscheduled"].append(label)
                    continue
                if day.anomalies:
                    outcome["anomalies"].append({**label, "codes": list(day.anomalies)})
                before = existing.get((employee["id"], day.work_date))
                if before is not None and before["source"] in PROTECTED_SOURCES:
                    if (before["status"], before["worked_minutes"]) != (day.status, day.worked_minutes):
                        outcome["conflicts"].append({
                            **label, "kept_status": before["status"], "kept_source": before["source"],
                            "clock_status": day.status, "clock_worked_minutes": day.worked_minutes,
                        })
                    continue
                figures = DayFigures(
                    status=day.status, schedule_id=days[day.work_date].schedule_id, scheduled_minutes=day.scheduled_minutes,
                    worked_minutes=day.worked_minutes, late_minutes=day.late_minutes, ot_minutes_day=day.ot_minutes_day,
                    ot_minutes_night=day.ot_minutes_night, ot_minutes_rest_holiday=day.ot_minutes_rest_holiday,
                    night_minutes=day.night_minutes,
                )
                presence.upsert_day(
                    tenant_id=tenant_id, actor_id=actor_id, employee_id=employee["id"], work_date=day.work_date,
                    figures=figures, source="holiday" if day.status == "holiday" else "clock",
                    justified=day.status == "holiday", note=", ".join(day.anomalies) or None, clock_import_id=import_id,
                )
                outcome["days_written"] += 1
        return outcome

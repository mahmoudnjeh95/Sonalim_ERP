"""Recurring preventive programs: the rule that produces a due job again and again
(`domain/programs.py` does the pure date arithmetic), the sweep that materialises
each occurrence as a job once it falls inside its lead-time window, the overdue
notice for a materialised job nobody has acted on, and the calendar the frontend
draws from (real jobs plus a projection of occurrences that have no job yet).

Materialising an occurrence is left entirely to `JobService.create_job`: it is the
one place that snapshots checkpoints, assigns a number and sends the "job due"
notification, and its own `(program_id, occurrence_date)` uniqueness (look-ahead +
`ON CONFLICT DO NOTHING`) is what makes running the sweep twice, or the worker and
a manual "run due" racing each other, safe. This service adds only what `create_job`
does not already do: deciding which dates are due, falling back to "every active
checkpoint of the machine" when a program names none, and raising the overdue
notice once a materialised job's due date has passed unactioned.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.maintenance.api import notifications
from modules.maintenance.api.job_queries import list_jobs
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.map_service import MapService
from modules.maintenance.domain.programs import due_occurrences, next_occurrence, occurrences, validate_program

__all__ = ["ProgramService"]

_ENTITY = "maintenance_program"

_PROGRAM_COLUMNS = (
    "p.id, p.equipment_id, e.name, p.name, p.description, p.interval_value, p.interval_unit, "
    "p.start_date, p.lead_days, p.estimated_minutes, p.default_team_id, t.name, p.stops_machine, "
    "p.active, p.created_at"
)
_PROGRAM_FROM = (
    "FROM maintenance.programs p "
    "JOIN maintenance.equipment e ON e.id = p.equipment_id "
    "LEFT JOIN maintenance.teams t ON t.id = p.default_team_id"
)


def _not_found(program_id: str) -> Err:
    return Err("NOT_FOUND", f"program {program_id} not found", f"programme {program_id} introuvable")


class ProgramService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- CRUD ---------------------------------------------------------------

    def list_programs(self, tenant_id: str, today: datetime.date) -> list[dict]:
        rows = self._connection.execute(
            f"SELECT {_PROGRAM_COLUMNS} FROM maintenance.programs p "
            f"JOIN maintenance.equipment e ON e.id = p.equipment_id "
            f"LEFT JOIN maintenance.teams t ON t.id = p.default_team_id "
            f"WHERE p.tenant_id = %s ORDER BY p.created_at",
            (tenant_id,),
        ).fetchall()
        return [self._program_dict(row, today) for row in rows]

    def create_program(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        equipment_id: str,
        name: str,
        description: str | None,
        interval_value: int,
        interval_unit: str,
        start_date: datetime.date,
        lead_days: int,
        estimated_minutes: int | None,
        default_team_id: str | None,
        stops_machine: bool,
        checkpoint_ids: list[str],
    ) -> Result[dict]:
        name = (name or "").strip()
        valid = validate_program(
            interval_value=interval_value, interval_unit=interval_unit, lead_days=lead_days, name=name
        )
        if isinstance(valid, Err):
            return valid

        equipment = self._connection.execute(
            "SELECT 1 FROM maintenance.equipment WHERE id = %s AND tenant_id = %s", (equipment_id, tenant_id)
        ).fetchone()
        if equipment is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found", f"équipement {equipment_id} introuvable")

        if default_team_id is not None:
            team = self._connection.execute(
                "SELECT 1 FROM maintenance.teams WHERE id = %s AND tenant_id = %s", (default_team_id, tenant_id)
            ).fetchone()
            if team is None:
                return Err("UNKNOWN_TEAM", f"team {default_team_id} not found", f"équipe {default_team_id} introuvable")

        checked = self._checkpoints_on_machine(tenant_id, equipment_id, checkpoint_ids)
        if isinstance(checked, Err):
            return checked

        program_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO maintenance.programs
                (id, tenant_id, equipment_id, name, description, interval_value, interval_unit, start_date,
                 lead_days, estimated_minutes, default_team_id, stops_machine, active, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
            """,
            (
                program_id, tenant_id, equipment_id, name, (description or "").strip() or None,
                interval_value, interval_unit, start_date, lead_days, estimated_minutes, default_team_id,
                stops_machine, actor_id,
            ),
        )
        for checkpoint_id in checked.value:
            self._connection.execute(
                "INSERT INTO maintenance.program_checkpoints (program_id, checkpoint_id) VALUES (%s, %s)",
                (program_id, checkpoint_id),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="program.created",
            entity_type=_ENTITY,
            entity_id=program_id,
            payload={"name": name, "equipment_id": equipment_id, "interval_value": interval_value, "interval_unit": interval_unit},
        )
        return Ok(self._get(tenant_id, program_id, start_date))

    def update_program(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        program_id: str,
        name: str | None = None,
        description: str | None = None,
        description_set: bool = False,
        interval_value: int | None = None,
        interval_unit: str | None = None,
        start_date: datetime.date | None = None,
        lead_days: int | None = None,
        estimated_minutes: int | None = None,
        estimated_minutes_set: bool = False,
        default_team_id: str | None = None,
        default_team_id_set: bool = False,
        stops_machine: bool | None = None,
        checkpoint_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        row = self._connection.execute(
            """
            SELECT equipment_id, name, interval_value, interval_unit, start_date, lead_days, active
            FROM maintenance.programs WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (program_id, tenant_id),
        ).fetchone()
        if row is None:
            return _not_found(program_id)
        equipment_id, current_name, current_value, current_unit, current_start, current_lead, was_active = row

        new_name = current_name if name is None else name.strip()
        new_value = current_value if interval_value is None else interval_value
        new_unit = current_unit if interval_unit is None else interval_unit
        new_lead = current_lead if lead_days is None else lead_days
        valid = validate_program(interval_value=new_value, interval_unit=new_unit, lead_days=new_lead, name=new_name)
        if isinstance(valid, Err):
            return valid

        if default_team_id_set and default_team_id is not None:
            team = self._connection.execute(
                "SELECT 1 FROM maintenance.teams WHERE id = %s AND tenant_id = %s", (default_team_id, tenant_id)
            ).fetchone()
            if team is None:
                return Err("UNKNOWN_TEAM", f"team {default_team_id} not found", f"équipe {default_team_id} introuvable")

        if checkpoint_ids is not None:
            checked = self._checkpoints_on_machine(tenant_id, equipment_id, checkpoint_ids)
            if isinstance(checked, Err):
                return checked
            checkpoint_ids = checked.value

        sets = ["name = %s", "interval_value = %s", "interval_unit = %s", "lead_days = %s"]
        params: list[object] = [new_name, new_value, new_unit, new_lead]
        if start_date is not None:
            sets.append("start_date = %s")
            params.append(start_date)
        if description_set:
            sets.append("description = %s")
            params.append((description or "").strip() or None)
        if estimated_minutes_set:
            sets.append("estimated_minutes = %s")
            params.append(estimated_minutes)
        if default_team_id_set:
            sets.append("default_team_id = %s")
            params.append(default_team_id)
        if stops_machine is not None:
            sets.append("stops_machine = %s")
            params.append(stops_machine)
        if active is not None:
            sets.append("active = %s")
            params.append(active)
        if active and not was_active:
            # A program switched back on picks up from today: the occurrences that fell
            # while it was paused are not raised as a batch of overdue jobs.
            sets.append("last_generated_date = GREATEST(last_generated_date, %s)")
            params.append(datetime.date.today() - datetime.timedelta(days=1))
        params.append(program_id)
        self._connection.execute(f"UPDATE maintenance.programs SET {', '.join(sets)} WHERE id = %s", params)

        if checkpoint_ids is not None:
            self._connection.execute("DELETE FROM maintenance.program_checkpoints WHERE program_id = %s", (program_id,))
            for checkpoint_id in checkpoint_ids:
                self._connection.execute(
                    "INSERT INTO maintenance.program_checkpoints (program_id, checkpoint_id) VALUES (%s, %s)",
                    (program_id, checkpoint_id),
                )

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="program.updated",
            entity_type=_ENTITY,
            entity_id=program_id,
            payload={"active": active},
        )
        effective_start = start_date if start_date is not None else current_start
        return Ok(self._get(tenant_id, program_id, effective_start))

    def set_checkpoints(self, *, tenant_id: str, actor_id: str, program_id: str, checkpoint_ids: list[str]) -> Result[dict]:
        return self.update_program(tenant_id=tenant_id, actor_id=actor_id, program_id=program_id, checkpoint_ids=checkpoint_ids)

    # ---- sweep ---------------------------------------------------------------

    def tenants_with_active_programs(self) -> list[str]:
        rows = self._connection.execute("SELECT DISTINCT tenant_id FROM maintenance.programs WHERE active").fetchall()
        return [row[0] for row in rows]

    def run_due(self, *, tenant_id: str, today: datetime.date) -> dict:
        """Materialises every occurrence whose notice window has opened, then raises the
        overdue notice for a materialised job whose due date has passed with nobody
        having been told yet. Safe to call twice, and safe against the worker thread and
        a manual `POST /programs/run-due` racing each other: the only write that can
        collide (`JobService.create_job`'s insert) is itself idempotent on
        `(program_id, occurrence_date)`."""
        created = 0
        rows = self._connection.execute(
            """
            SELECT id, equipment_id, name, description, interval_value, interval_unit, start_date, lead_days,
                   stops_machine, default_team_id, created_at, last_generated_date
            FROM maintenance.programs WHERE tenant_id = %s AND active
            """,
            (tenant_id,),
        ).fetchall()
        jobs = JobService(self._connection)
        for (
            program_id, equipment_id, name, description, interval_value, interval_unit, start_date, lead_days,
            stops_machine, default_team_id, created_at, last_generated_date,
        ) in rows:
            # The program remembers how far it has generated, so jobs that disappear
            # (the go-live reset wipes them) are never raised a second time.
            not_before = created_at.date()
            if last_generated_date is not None:
                not_before = max(not_before, last_generated_date + datetime.timedelta(days=1))
            dates = due_occurrences(start_date, interval_value, interval_unit, lead_days, today, not_before)
            if not dates:
                continue
            # Resolve against the machine's *currently* active checkpoints, never the
            # program's stored ids verbatim: a selected point may have been archived since
            # the program was saved, and a due program must never be dropped over that.
            # An empty selection already means "every active checkpoint" (brief/spec); a
            # selection that has gone entirely stale falls back the same way, via the same
            # intersection, rather than a separate branch.
            active = MapService(self._connection).active_checkpoints(tenant_id=tenant_id, equipment_id=equipment_id)
            selected = set(self._program_checkpoint_ids(program_id))
            checkpoint_ids = [c["id"] for c in active if not selected or c["id"] in selected]
            tasks = [] if checkpoint_ids else [{"label": name, "action": "other"}]
            # Advances only over occurrences that now have a job, and stops at the first
            # refused one so the next sweep tries it again.
            generated_through = None
            for occurrence_date in dates:
                result = jobs.create_job(
                    tenant_id=tenant_id,
                    actor_id="system:maintenance-sweep",
                    equipment_id=equipment_id,
                    title=name,
                    description=description,
                    kind="preventive",
                    priority="normal",
                    due_date=occurrence_date,
                    stops_machine=stops_machine,
                    checkpoint_ids=checkpoint_ids,
                    tasks=tasks,
                    team_id=default_team_id,
                    program_id=program_id,
                    occurrence_date=occurrence_date,
                )
                if isinstance(result, Ok):
                    created += 1
                    generated_through = occurrence_date
                elif result.code == "ALREADY_EXISTS":
                    generated_through = occurrence_date
                else:
                    # The checkpoint-archived case is already handled above (resolved against
                    # the machine's active checkpoints before calling create_job, with the
                    # ad-hoc fallback when none remain), so create_job should not refuse here
                    # in practice. This is a last-resort guard for a genuinely unexpected error
                    # (e.g. the equipment itself vanished mid-sweep): logged and skipped so one
                    # bad program's occurrence never takes down every other program's sweep in
                    # the same run; it is simply tried again on the next sweep.
                    print(
                        f"Maintenance sweep: program {program_id} occurrence {occurrence_date} refused: {result.code}",
                        flush=True,
                    )
                    break
            if generated_through is not None:
                self._connection.execute(
                    "UPDATE maintenance.programs SET last_generated_date = %s WHERE id = %s",
                    (generated_through, program_id),
                )

        overdue_notified = self._notify_overdue(tenant_id, today)
        return {"created": created, "overdue_notified": overdue_notified}

    def _notify_overdue(self, tenant_id: str, today: datetime.date) -> int:
        rows = self._connection.execute(
            """
            SELECT j.id, j.number, j.chef_user_id, e.name
            FROM maintenance.jobs j
            JOIN maintenance.equipment e ON e.id = j.equipment_id
            WHERE j.tenant_id = %s AND j.due_date < %s AND j.status NOT IN ('closed', 'cancelled')
              AND j.overdue_notified_at IS NULL
            """,
            (tenant_id, today),
        ).fetchall()
        for job_id, number, chef_user_id, equipment_name in rows:
            recipients = [chef_user_id, *notifications.supervisors(self._connection, tenant_id)]
            notifications.notify_job(
                self._connection,
                tenant_id=tenant_id,
                user_ids=recipients,
                kind=notifications.JOB_OVERDUE,
                job_id=job_id,
                number=number,
                equipment_name=equipment_name,
            )
            self._connection.execute(
                "UPDATE maintenance.jobs SET overdue_notified_at = NOW() WHERE id = %s", (job_id,)
            )
        return len(rows)

    # ---- calendar ---------------------------------------------------------------

    def calendar(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date, today: datetime.date) -> dict:
        """`CalendarResponse`: the window's real jobs, plus a projection of each active
        program's future occurrences that have no job yet (never before `today`, since a
        past unmaterialised occurrence is the sweep's job to raise, not the calendar's to
        suggest)."""
        jobs = list_jobs(self._connection, tenant_id, date_from=date_from, date_to=date_to, today=today)

        programs = self._connection.execute(
            """
            SELECT id, equipment_id, name, interval_value, interval_unit, start_date, last_generated_date
            FROM maintenance.programs WHERE tenant_id = %s AND active
            """,
            (tenant_id,),
        ).fetchall()
        equipment_names = {}
        if programs:
            eq_rows = self._connection.execute(
                "SELECT id, name FROM maintenance.equipment WHERE id = ANY(%s)",
                ([row[1] for row in programs],),
            ).fetchall()
            equipment_names = dict(eq_rows)

        projected: list[dict] = []
        window_start = max(date_from, today)
        for program_id, equipment_id, name, interval_value, interval_unit, start_date, last_generated_date in programs:
            # Dates the sweep has already passed are never raised again, so they are not
            # projected either.
            program_start = window_start
            if last_generated_date is not None:
                program_start = max(program_start, last_generated_date + datetime.timedelta(days=1))
            dates = occurrences(start_date, interval_value, interval_unit, program_start, date_to)
            if not dates:
                continue
            existing = self._connection.execute(
                "SELECT occurrence_date FROM maintenance.jobs WHERE program_id = %s AND occurrence_date = ANY(%s)",
                (program_id, dates),
            ).fetchall()
            has_job = {row[0] for row in existing}
            for occurrence_date in dates:
                if occurrence_date in has_job:
                    continue
                projected.append(
                    {
                        "program_id": program_id,
                        "program_name": name,
                        "equipment_id": equipment_id,
                        "equipment_name": equipment_names.get(equipment_id),
                        "date": occurrence_date.isoformat(),
                    }
                )
        return {"jobs": jobs, "projected": projected}

    # ---- internals ---------------------------------------------------------------

    def _get(self, tenant_id: str, program_id: str, today: datetime.date) -> dict:
        row = self._connection.execute(
            f"SELECT {_PROGRAM_COLUMNS} {_PROGRAM_FROM} WHERE p.id = %s AND p.tenant_id = %s",
            (program_id, tenant_id),
        ).fetchone()
        return self._program_dict(row, today)

    def _program_dict(self, row: tuple, today: datetime.date) -> dict:
        (
            program_id, equipment_id, equipment_name, name, description, interval_value, interval_unit,
            start_date, lead_days, estimated_minutes, default_team_id, default_team_name, stops_machine,
            active, _created_at,
        ) = row
        return {
            "id": program_id,
            "equipment_id": equipment_id,
            "equipment_name": equipment_name,
            "name": name,
            "description": description,
            "interval_value": interval_value,
            "interval_unit": interval_unit,
            "start_date": start_date.isoformat(),
            "lead_days": lead_days,
            "estimated_minutes": estimated_minutes,
            "default_team_id": default_team_id,
            "default_team_name": default_team_name,
            "stops_machine": stops_machine,
            "active": active,
            "checkpoint_ids": self._program_checkpoint_ids(program_id),
            "next_occurrence": next_occurrence(start_date, interval_value, interval_unit, today).isoformat()
            if active
            else None,
        }

    def _program_checkpoint_ids(self, program_id: str) -> list[str]:
        rows = self._connection.execute(
            "SELECT checkpoint_id FROM maintenance.program_checkpoints WHERE program_id = %s", (program_id,)
        ).fetchall()
        return [row[0] for row in rows]

    def _checkpoints_on_machine(self, tenant_id: str, equipment_id: str, checkpoint_ids: list[str]) -> Result[list[str]]:
        """Every id must be an active checkpoint of this machine; empty stays empty (meaning
        "every active checkpoint, resolved at occurrence time")."""
        distinct_ids = list(dict.fromkeys(checkpoint_ids))
        if not distinct_ids:
            return Ok([])
        found = MapService(self._connection).checkpoints_by_ids(tenant_id=tenant_id, ids=distinct_ids)
        if isinstance(found, Err):
            return found
        foreign = [c["id"] for c in found.value if self._view_equipment(c["view_id"]) != equipment_id]
        if foreign:
            return Err(
                "UNKNOWN_CHECKPOINT",
                f"checkpoint(s) not on this machine: {', '.join(foreign)}",
                f"point(s) de contrôle absent(s) de cette machine : {', '.join(foreign)}",
            )
        return Ok(distinct_ids)

    def _view_equipment(self, view_id: str) -> str | None:
        row = self._connection.execute("SELECT equipment_id FROM maintenance.equipment_views WHERE id = %s", (view_id,)).fetchone()
        return None if row is None else row[0]

"""The life of a maintenance job: created (by a supervisor or the program sweep),
assigned to a chef, delegated point by point, recorded through the guided check,
submitted, reviewed -- with rejected points sent back to rework -- then closed.

The rules themselves (which status allows what, what a submit needs, what a review
does) are pure functions in `domain/jobs.py`; this service loads the rows, asks the
rule, and writes the outcome together with one timeline row, one audit row and the
notifications the spec lists. Nothing here ever edits or deletes a past entry or
review: history is append-only.
"""
from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.maintenance.api import notifications
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.map_service import ALLOWED_IMAGE_MIME, MAX_IMAGE_BYTES, MapService
from modules.maintenance.api.people import active_employee_names, user_names
from modules.maintenance.domain.jobs import (
    CHECK_ACTIONS,
    JOB_KINDS,
    JOB_PRIORITIES,
    OUTCOMES,
    VERDICTS,
    CheckSnapshot,
    EntrySummary,
    apply_review,
    can_assign,
    can_cancel,
    can_close,
    can_delegate,
    can_record_entry,
    entry_timing,
    status_after_entry,
    validate_submit,
)

__all__ = ["JobService"]

_ENTITY = "maintenance_job"

# A job that stops its machine holds it from its first entry until it is closed or
# cancelled: while it is being worked, awaiting review, or back in rework.
_HOLDING_STATUSES = ["in_progress", "submitted", "rework"]


@dataclass(frozen=True)
class _Job:
    id: str
    number: str
    equipment_id: str
    equipment_name: str
    title: str
    status: str
    stops_machine: bool
    chef_user_id: str | None
    started_at: datetime.datetime | None


@dataclass(frozen=True)
class _Assignee:
    team_id: str | None
    team_name: str | None
    chef_user_id: str | None
    chef_name: str | None

    def payload(self) -> dict:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "chef_user_id": self.chef_user_id,
            "chef_name": self.chef_name,
        }


def _clean(text: str | None) -> str | None:
    """A typed text with its edges trimmed; blank becomes None."""
    stripped = (text or "").strip()
    return stripped or None


def _job_not_found(job_id: str) -> Err:
    return Err("NOT_FOUND", f"job {job_id} not found", f"intervention {job_id} introuvable")


class JobService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- create ------------------------------------------------------------

    def create_job(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        equipment_id: str,
        title: str,
        description: str | None,
        kind: str,
        priority: str,
        due_date: datetime.date,
        stops_machine: bool,
        checkpoint_ids: list[str],
        tasks: list[dict],
        team_id: str | None = None,
        chef_user_id: str | None = None,
        program_id: str | None = None,
        occurrence_date: datetime.date | None = None,
    ) -> Result[str]:
        """Creates a job and returns its id.

        Its checks are a snapshot: the given checkpoints (in the map's order: view,
        then point) followed by the ad-hoc `tasks` (`{label, action, instructions?}`).
        It starts `assigned` when a chef is known -- given, or the given team's -- and
        `planned` otherwise. A program occurrence (`program_id` + `occurrence_date`)
        is only ever materialised once: a second call returns `ALREADY_EXISTS`.
        """
        title = (title or "").strip()
        if not title:
            return Err("INVALID_TITLE", "a job title is required", "le titre de l'intervention est obligatoire")
        if kind not in JOB_KINDS:
            return Err("INVALID_KIND", f"unknown job kind: {kind}", f"type d'intervention inconnu : {kind}")
        if priority not in JOB_PRIORITIES:
            return Err("INVALID_PRIORITY", f"unknown priority: {priority}", f"priorité inconnue : {priority}")
        if (program_id is None) != (occurrence_date is None):
            return Err(
                "INVALID_OCCURRENCE",
                "a program job needs both its program and its occurrence date",
                "une intervention de programme doit indiquer son programme et sa date d'occurrence",
            )

        equipment = self._connection.execute(
            "SELECT name FROM maintenance.equipment WHERE id = %s AND tenant_id = %s", (equipment_id, tenant_id)
        ).fetchone()
        if equipment is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found", f"équipement {equipment_id} introuvable")
        equipment_name = equipment[0]

        if program_id is not None and self._occurrence_exists(program_id, occurrence_date):
            return self._already_exists(occurrence_date)

        checks = self._checks_to_snapshot(tenant_id, equipment_id, checkpoint_ids, tasks)
        if isinstance(checks, Err):
            return checks
        if not checks.value:
            return Err(
                "NO_CHECKS",
                "a job needs at least one checkpoint or task",
                "une intervention doit comporter au moins un point de contrôle ou une tâche",
            )

        resolved = self._resolve_assignee(tenant_id, team_id, chef_user_id)
        if isinstance(resolved, Err):
            return resolved
        assignee = resolved.value
        status = "assigned" if assignee.chef_user_id is not None else "planned"

        # One numbering sequence per tenant: whoever holds the lock reads max + 1, and
        # holds it until commit, so two concurrent creations never share a number.
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{tenant_id}:maintenance_job_number",)
        )
        number = self._next_number(tenant_id)

        job_id = str(ULID())
        inserted = self._connection.execute(
            """
            INSERT INTO maintenance.jobs
                (id, tenant_id, number, equipment_id, kind, priority, title, description, program_id, occurrence_date,
                 due_date, stops_machine, status, team_id, chef_user_id, created_by, assigned_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END)
            ON CONFLICT (program_id, occurrence_date) DO NOTHING
            RETURNING id
            """,
            (
                job_id,
                tenant_id,
                number,
                equipment_id,
                kind,
                priority,
                title,
                _clean(description),
                program_id,
                occurrence_date,
                due_date,
                stops_machine,
                status,
                assignee.team_id,
                assignee.chef_user_id,
                actor_id,
                status == "assigned",
            ),
        ).fetchone()
        if inserted is None:
            # The same occurrence was materialised by a concurrent sweep between our look and our insert.
            return self._already_exists(occurrence_date)

        for index, check in enumerate(checks.value, start=1):
            self._connection.execute(
                """
                INSERT INTO maintenance.job_checks
                    (id, tenant_id, job_id, sort_order, checkpoint_id, view_id, x_pct, y_pct,
                     label, action, instructions, measure_unit, requires_photo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()),
                    tenant_id,
                    job_id,
                    index,
                    check["checkpoint_id"],
                    check["view_id"],
                    check["x_pct"],
                    check["y_pct"],
                    check["label"],
                    check["action"],
                    check["instructions"],
                    check["measure_unit"],
                    check["requires_photo"],
                ),
            )

        created_payload = {
            "number": number,
            "title": title,
            "kind": kind,
            "priority": priority,
            "due_date": due_date.isoformat(),
            "checks": len(checks.value),
            "program_id": program_id,
        }
        self._event(tenant_id, job_id, actor_id, "created", created_payload)
        if status == "assigned":
            self._event(tenant_id, job_id, actor_id, "assigned", assignee.payload())
        self._audit(
            tenant_id,
            actor_id,
            job_id,
            "job.created",
            {**created_payload, "equipment_id": equipment_id, "status": status, **assignee.payload()},
        )

        # Who is told (spec table): a program job coming due and an urgent job go to the
        # supervisors and the chef; any other job only tells the chef it was assigned to.
        recipients: list[str | None] = [assignee.chef_user_id]
        if program_id is not None:
            notice = notifications.JOB_DUE
            recipients += notifications.supervisors(self._connection, tenant_id)
        elif priority == "urgent":
            notice = notifications.JOB_URGENT
            recipients += notifications.supervisors(self._connection, tenant_id)
        else:
            notice = notifications.JOB_ASSIGNED
        notifications.notify_job(
            self._connection,
            tenant_id=tenant_id,
            user_ids=recipients,
            kind=notice,
            job_id=job_id,
            number=number,
            equipment_name=equipment_name,
            body=title,
        )
        return Ok(job_id)

    # ---- assign / delegate -----------------------------------------------------

    def assign_job(
        self, *, tenant_id: str, actor_id: str, job_id: str, team_id: str | None, chef_user_id: str | None
    ) -> Result[None]:
        """Gives the job its chef (and, optionally, team). A team given without a chef
        brings its own. Allowed while the job is `planned` or still only `assigned`."""
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        allowed = can_assign(job.status)
        if isinstance(allowed, Err):
            return allowed

        resolved = self._resolve_assignee(tenant_id, team_id, chef_user_id)
        if isinstance(resolved, Err):
            return resolved
        assignee = resolved.value
        if assignee.chef_user_id is None:
            return Err(
                "CHEF_REQUIRED",
                "a job is assigned to a chef: give one, or a team that has one",
                "une intervention s'assigne à un chef d'atelier : indiquez-en un, ou une équipe qui en a un",
            )

        self._connection.execute(
            "UPDATE maintenance.jobs SET team_id = %s, chef_user_id = %s, status = 'assigned', assigned_at = NOW() WHERE id = %s",
            (assignee.team_id, assignee.chef_user_id, job.id),
        )
        self._event(tenant_id, job.id, actor_id, "assigned", assignee.payload())
        self._audit(tenant_id, actor_id, job.id, "job.assigned", {"from_status": job.status, **assignee.payload()})
        self._notify(tenant_id, job, [assignee.chef_user_id], notifications.JOB_ASSIGNED, body=job.title)
        return Ok(None)

    def delegate(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        job_id: str,
        assignments: list[tuple[str, str | None]],
        actor_can_plan: bool,
    ) -> Result[None]:
        """Sets who each given check is handed to (`(check_id, employee_id)`; None hands it
        back to nobody). Only the job's chef, or a supervisor, may delegate."""
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        refused = self._refuse_unless_runs_job(job, actor_id, actor_can_plan)
        if refused is not None:
            return refused
        allowed = can_delegate(job.status)
        if isinstance(allowed, Err):
            return allowed

        if not assignments:
            return Ok(None)

        labels = self._check_labels(job.id)
        unknown_checks = [check_id for check_id, _ in assignments if check_id not in labels]
        if unknown_checks:
            return Err(
                "UNKNOWN_CHECK",
                f"check {unknown_checks[0]} is not part of this job",
                f"le point {unknown_checks[0]} ne fait pas partie de cette intervention",
            )
        employee_ids = [employee_id for _, employee_id in assignments if employee_id is not None]
        names = active_employee_names(self._connection, tenant_id, employee_ids)
        unknown_employees = [employee_id for employee_id in employee_ids if employee_id not in names]
        if unknown_employees:
            return self._unknown_employee(unknown_employees[0])

        for check_id, employee_id in assignments:
            self._connection.execute(
                "UPDATE maintenance.job_checks SET assignee_employee_id = %s WHERE id = %s", (employee_id, check_id)
            )
        payload = {
            "assignments": [
                {
                    "check_id": check_id,
                    "label": labels[check_id],
                    "employee_id": employee_id,
                    "employee_name": names.get(employee_id) if employee_id is not None else None,
                }
                for check_id, employee_id in assignments
            ]
        }
        self._event(tenant_id, job.id, actor_id, "delegated", payload)
        self._audit(tenant_id, actor_id, job.id, "job.delegated", payload)
        return Ok(None)

    # ---- guided check ------------------------------------------------------

    def record_entry(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        job_id: str,
        check_id: str,
        performer_employee_id: str,
        outcome: str,
        note: str | None,
        measured_value: float | None,
        started_at: datetime.datetime | None,
        finished_at: datetime.datetime | None,
        manual_minutes: float | None,
        photo: tuple[bytes, str] | None,
        actor_can_plan: bool,
        now: datetime.datetime,
    ) -> Result[None]:
        """Records one point of the guided check: who did it, when, for how long, the
        outcome, and the photo/measure if any. Appends an entry under the check's current
        attempt and marks the check `done`; the first entry of a job starts it (and stops
        the machine if the job says so)."""
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        refused = self._refuse_unless_runs_job(job, actor_id, actor_can_plan)
        if refused is not None:
            return refused

        check = self._connection.execute(
            "SELECT label, state, attempt FROM maintenance.job_checks WHERE id = %s AND job_id = %s FOR UPDATE",
            (check_id, job.id),
        ).fetchone()
        if check is None:
            return Err("NOT_FOUND", f"check {check_id} not found on this job", f"point {check_id} introuvable sur cette intervention")
        label, check_state, attempt = check

        allowed = can_record_entry(job.status, check_state)
        if isinstance(allowed, Err):
            return allowed
        if outcome not in OUTCOMES:
            return Err("INVALID_OUTCOME", f"unknown outcome: {outcome}", f"résultat inconnu : {outcome}")
        performer = active_employee_names(self._connection, tenant_id, [performer_employee_id])
        if performer_employee_id not in performer:
            return self._unknown_employee(performer_employee_id)

        if any(stamp is not None and stamp.tzinfo is None for stamp in (started_at, finished_at)):
            return Err(
                "INVALID_TIMING",
                "started_at and finished_at must carry a UTC offset",
                "les heures de début et de fin doivent indiquer leur fuseau horaire",
            )
        timed = entry_timing(started_at=started_at, finished_at=finished_at, manual_minutes=manual_minutes, now=now)
        if isinstance(timed, Err):
            return timed
        timing = timed.value

        photo_bytes, photo_mime = photo if photo is not None else (None, None)
        if photo is not None and (photo_mime not in ALLOWED_IMAGE_MIME or not photo_bytes or len(photo_bytes) > MAX_IMAGE_BYTES):
            return Err(
                "INVALID_IMAGE",
                "photo must be JPEG, PNG or WebP and at most 10 MB",
                "la photo doit être au format JPEG, PNG ou WebP et faire au plus 10 Mo",
            )

        entry_id = str(ULID())
        # clock_timestamp(), not the NOW() default: "the latest entry of an attempt" must
        # stay well defined even when two entries are written in one transaction.
        self._connection.execute(
            """
            INSERT INTO maintenance.check_entries
                (id, tenant_id, check_id, attempt, performer_employee_id, recorded_by, started_at, finished_at,
                 duration_seconds, duration_source, outcome, note, measured_value, photo, photo_mime, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
            """,
            (
                entry_id,
                tenant_id,
                check_id,
                attempt,
                performer_employee_id,
                actor_id,
                timing.started_at,
                timing.finished_at,
                timing.seconds,
                timing.source,
                outcome,
                _clean(note),
                measured_value,
                psycopg.Binary(photo_bytes) if photo_bytes is not None else None,
                photo_mime,
            ),
        )
        self._connection.execute("UPDATE maintenance.job_checks SET state = 'done' WHERE id = %s", (check_id,))

        new_status = status_after_entry(job.status)
        if new_status != job.status:
            self._connection.execute(
                "UPDATE maintenance.jobs SET status = %s, started_at = COALESCE(started_at, %s) WHERE id = %s",
                (new_status, now, job.id),
            )
            stopped = False
            if job.stops_machine:
                moved = self._move_equipment(
                    tenant_id, actor_id, job.equipment_id, to_status="maintenance", only_from=("operational", "down")
                )
                if isinstance(moved, Err):
                    return moved
                stopped = moved.value
            self._event(tenant_id, job.id, actor_id, "started", {"equipment_stopped": stopped})

        payload = {
            "check_id": check_id,
            "label": label,
            "attempt": attempt,
            "entry_id": entry_id,
            "outcome": outcome,
            "performer_employee_id": performer_employee_id,
            "performer_name": performer[performer_employee_id],
            "duration_seconds": timing.seconds,
            "duration_source": timing.source,
        }
        self._event(tenant_id, job.id, actor_id, "check_done", payload)
        self._audit(tenant_id, actor_id, job.id, "job.check_recorded", payload)
        return Ok(None)

    def submit(self, *, tenant_id: str, actor_id: str, job_id: str, actor_can_plan: bool) -> Result[None]:
        """Hands the job to the supervisors for review, once every point has its entry
        (with the photo / measure the point asks for)."""
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        refused = self._refuse_unless_runs_job(job, actor_id, actor_can_plan)
        if refused is not None:
            return refused
        valid = validate_submit(job.status, self._snapshots(job.id))
        if isinstance(valid, Err):
            return valid

        self._connection.execute(
            "UPDATE maintenance.jobs SET status = 'submitted', submitted_at = NOW() WHERE id = %s", (job.id,)
        )
        self._event(tenant_id, job.id, actor_id, "submitted", {"from_status": job.status})
        self._audit(tenant_id, actor_id, job.id, "job.submitted", {"from_status": job.status})
        self._notify(
            tenant_id, job, notifications.supervisors(self._connection, tenant_id), notifications.JOB_SUBMITTED, body=job.title
        )
        return Ok(None)

    # ---- review / close / cancel -------------------------------------------------

    def review(
        self, *, tenant_id: str, actor_id: str, job_id: str, verdicts: list[tuple[str, str, str | None]]
    ) -> Result[None]:
        """One verdict per submitted point: `(check_id, "accepted" | "rejected", reason)`.
        An accepted point is locked; a rejected one goes back to `pending` on a new attempt
        (its earlier entries stay) and sends the job to `rework`. With no rejection the job
        stays `submitted`, ready to be closed."""
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        verdicts = [(check_id, verdict, _clean(reason)) for check_id, verdict, reason in verdicts]
        invalid = [verdict for _, verdict, _ in verdicts if verdict not in VERDICTS]
        if invalid:
            return Err("INVALID_VERDICT", f"unknown verdict: {invalid[0]}", f"verdict inconnu : {invalid[0]}")

        checks = self._snapshots(job.id)
        reviewed = apply_review(job.status, checks, verdicts)
        if isinstance(reviewed, Err):
            return reviewed
        outcome = reviewed.value
        if not verdicts:
            # Nothing was awaiting review (every point is already accepted): nothing to record.
            return Ok(None)

        attempts = {check.id: check.attempt for check in checks}
        for check_id, verdict, reason in verdicts:
            self._connection.execute(
                """
                INSERT INTO maintenance.check_reviews (id, tenant_id, check_id, attempt, verdict, reason, reviewer_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, clock_timestamp())
                """,
                (str(ULID()), tenant_id, check_id, attempts[check_id], verdict, reason, actor_id),
            )
        self._connection.execute(
            "UPDATE maintenance.job_checks SET state = 'accepted' WHERE id = ANY(%s)", (list(outcome.accepted_ids),)
        )
        # A rejected point is never left "rejected": it reopens at once, on the next attempt.
        self._connection.execute(
            "UPDATE maintenance.job_checks SET state = 'pending', attempt = attempt + 1 WHERE id = ANY(%s)",
            (list(outcome.rejected_ids),),
        )
        if outcome.next_status != job.status:
            self._connection.execute("UPDATE maintenance.jobs SET status = %s WHERE id = %s", (outcome.next_status, job.id))

        labels = self._check_labels(job.id)
        reasons = {check_id: reason for check_id, _, reason in verdicts}
        payload = {
            "accepted": [{"check_id": check_id, "label": labels[check_id]} for check_id in outcome.accepted_ids],
            "rejected": [
                {"check_id": check_id, "label": labels[check_id], "reason": reasons[check_id]}
                for check_id in outcome.rejected_ids
            ],
        }
        self._event(tenant_id, job.id, actor_id, "rework" if outcome.rejected_ids else "reviewed", payload)
        self._audit(tenant_id, actor_id, job.id, "job.reviewed", {"to_status": outcome.next_status, **payload})
        if outcome.rejected_ids:
            count = len(outcome.rejected_ids)
            self._notify(
                tenant_id,
                job,
                [job.chef_user_id],
                notifications.JOB_REWORK,
                body=f"{count} point(s) to redo",
                body_fr=f"{count} point(s) à reprendre",
            )
        return Ok(None)

    def close(self, *, tenant_id: str, actor_id: str, job_id: str) -> Result[None]:
        """Closes a submitted job whose every point was accepted; a machine the job had
        stopped goes back to `operational`, unless another stopping job still holds it."""
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        allowed = can_close(job.status, self._snapshots(job.id))
        if isinstance(allowed, Err):
            return allowed

        self._connection.execute(
            "UPDATE maintenance.jobs SET status = 'closed', closed_at = NOW(), closed_by = %s WHERE id = %s",
            (actor_id, job.id),
        )
        released = self._release_equipment(tenant_id, actor_id, job)
        if isinstance(released, Err):
            return released
        restarted = released.value
        self._event(tenant_id, job.id, actor_id, "closed", {"equipment_restarted": restarted})
        self._audit(tenant_id, actor_id, job.id, "job.closed", {"equipment_restarted": restarted})
        self._notify(tenant_id, job, [job.chef_user_id], notifications.JOB_CLOSED, body=job.title)
        return Ok(None)

    def cancel(self, *, tenant_id: str, actor_id: str, job_id: str, reason: str | None) -> Result[None]:
        """Cancels a job that is not closed yet; the reason is mandatory and kept. A machine
        the job had stopped is released like on close, so it is never left stuck in `maintenance`."""
        reason = _clean(reason)
        if reason is None:
            return Err(
                "REASON_REQUIRED",
                "a reason is required to cancel a job",
                "un motif est requis pour annuler une intervention",
            )
        job = self._locked_job(tenant_id, job_id)
        if job is None:
            return _job_not_found(job_id)
        allowed = can_cancel(job.status)
        if isinstance(allowed, Err):
            return allowed

        self._connection.execute(
            "UPDATE maintenance.jobs SET status = 'cancelled', cancelled_at = NOW(), cancel_reason = %s WHERE id = %s",
            (reason, job.id),
        )
        released = self._release_equipment(tenant_id, actor_id, job)
        if isinstance(released, Err):
            return released
        payload = {"from_status": job.status, "reason": reason, "equipment_restarted": released.value}
        self._event(tenant_id, job.id, actor_id, "cancelled", payload)
        self._audit(tenant_id, actor_id, job.id, "job.cancelled", payload)
        self._notify(tenant_id, job, [job.chef_user_id], notifications.JOB_CANCELLED, body=reason)
        return Ok(None)

    # ---- internals -----------------------------------------------------------

    def _locked_job(self, tenant_id: str, job_id: str) -> _Job | None:
        """The job row, locked for the rest of the transaction so that two mutations of
        the same job (two entries, a submit and an entry...) run one after the other."""
        row = self._connection.execute(
            """
            SELECT j.id, j.number, j.equipment_id, e.name, j.title, j.status, j.stops_machine, j.chef_user_id,
                   j.started_at
            FROM maintenance.jobs j
            JOIN maintenance.equipment e ON e.id = j.equipment_id
            WHERE j.id = %s AND j.tenant_id = %s
            FOR UPDATE OF j
            """,
            (job_id, tenant_id),
        ).fetchone()
        return None if row is None else _Job(*row)

    @staticmethod
    def _refuse_unless_runs_job(job: _Job, actor_id: str, actor_can_plan: bool) -> Err | None:
        """Running a job (delegating, recording, submitting) is for its chef; a supervisor may step in."""
        if actor_can_plan or (job.chef_user_id is not None and job.chef_user_id == actor_id):
            return None
        return Err(
            "NOT_JOB_CHEF",
            "only the chef this job is assigned to can do this",
            "seul le chef d'atelier à qui l'intervention est assignée peut faire cela",
        )

    @staticmethod
    def _unknown_employee(employee_id: str) -> Err:
        return Err(
            "UNKNOWN_EMPLOYEE",
            f"{employee_id} is not an active employee",
            f"{employee_id} n'est pas un salarié actif",
        )

    @staticmethod
    def _already_exists(occurrence_date: datetime.date | None) -> Err:
        return Err(
            "ALREADY_EXISTS",
            f"the job of this program for {occurrence_date} already exists",
            f"l'intervention de ce programme pour le {occurrence_date} existe déjà",
        )

    def _occurrence_exists(self, program_id: str, occurrence_date: datetime.date | None) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM maintenance.jobs WHERE program_id = %s AND occurrence_date = %s",
                (program_id, occurrence_date),
            ).fetchone()
            is not None
        )

    def _next_number(self, tenant_id: str) -> str:
        """`MT-<year>-<seq>`, seq restarting at 0001 each year. Call with the numbering lock held."""
        prefix = f"MT-{datetime.date.today().year}-"
        highest = self._connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTRING(number FROM %s) AS INT)), 0)
            FROM maintenance.jobs
            WHERE tenant_id = %s AND number ~ %s
            """,
            (len(prefix) + 1, tenant_id, f"^{prefix}[0-9]+$"),
        ).fetchone()[0]
        return f"{prefix}{highest + 1:04d}"

    def _checks_to_snapshot(
        self, tenant_id: str, equipment_id: str, checkpoint_ids: Iterable[str], tasks: Iterable[dict]
    ) -> Result[list[dict]]:
        """The rows to copy into `job_checks`: the machine's checkpoints asked for, then the ad-hoc tasks."""
        found = MapService(self._connection).checkpoints_by_ids(tenant_id=tenant_id, ids=list(checkpoint_ids))
        if isinstance(found, Err):
            return found

        # checkpoints_by_ids only proves the points exist and are active: they must also
        # sit on one of *this* machine's views.
        views = self._connection.execute(
            """
            SELECT id FROM maintenance.equipment_views
            WHERE tenant_id = %s AND equipment_id = %s
            ORDER BY sort_order, created_at, id
            """,
            (tenant_id, equipment_id),
        ).fetchall()
        view_rank = {row[0]: rank for rank, row in enumerate(views)}
        foreign = [c["id"] for c in found.value if c["view_id"] not in view_rank]
        if foreign:
            return Err(
                "UNKNOWN_CHECKPOINT",
                f"checkpoint(s) not on this machine: {', '.join(foreign)}",
                f"point(s) de contrôle absent(s) de cette machine : {', '.join(foreign)}",
            )

        # The map's order: view, then point. sorted() is stable, so points that tie keep the order they were asked in.
        ordered = sorted(found.value, key=lambda c: (view_rank[c["view_id"]], c["sort_order"]))
        checks = [
            {
                "checkpoint_id": c["id"],
                "view_id": c["view_id"],
                "x_pct": c["x_pct"],
                "y_pct": c["y_pct"],
                "label": c["label"],
                "action": c["action"],
                "instructions": c["instructions"],
                "measure_unit": c["measure_unit"],
                "requires_photo": c["requires_photo"],
            }
            for c in ordered
        ]

        for task in tasks:
            label = (task.get("label") or "").strip()
            if not label:
                return Err("INVALID_TASK", "every task needs a label", "chaque tâche doit avoir un libellé")
            action = task.get("action")
            if action not in CHECK_ACTIONS:
                return Err("INVALID_ACTION", f"unknown action: {action}", f"action inconnue : {action}")
            checks.append(
                {
                    "checkpoint_id": None,
                    "view_id": None,
                    "x_pct": None,
                    "y_pct": None,
                    "label": label,
                    "action": action,
                    "instructions": _clean(task.get("instructions")),
                    "measure_unit": None,
                    "requires_photo": False,
                }
            )
        return Ok(checks)

    def _resolve_assignee(self, tenant_id: str, team_id: str | None, chef_user_id: str | None) -> Result[_Assignee]:
        """The team and chef a job is given to. A team given without a chef brings its own."""
        team_id, chef_user_id = team_id or None, chef_user_id or None
        team_name = None
        if team_id is not None:
            team = self._connection.execute(
                "SELECT name, chef_user_id FROM maintenance.teams WHERE id = %s AND tenant_id = %s", (team_id, tenant_id)
            ).fetchone()
            if team is None:
                return Err("UNKNOWN_TEAM", f"team {team_id} not found", f"équipe {team_id} introuvable")
            team_name = team[0]
            if chef_user_id is None:
                chef_user_id = team[1]

        chef_name = None
        if chef_user_id is not None:
            chef_name = user_names(self._connection, tenant_id, [chef_user_id]).get(chef_user_id)
            if chef_name is None:
                return Err("UNKNOWN_CHEF", f"user {chef_user_id} not found", f"utilisateur {chef_user_id} introuvable")
        return Ok(_Assignee(team_id=team_id, team_name=team_name, chef_user_id=chef_user_id, chef_name=chef_name))

    def _snapshots(self, job_id: str) -> list[CheckSnapshot]:
        """Every check of the job with the latest entry of its *current* attempt, as the domain rules read them."""
        rows = self._connection.execute(
            """
            SELECT c.id, c.state, c.attempt, c.action, c.requires_photo,
                   latest.id, latest.outcome, latest.has_photo, latest.measured_value
            FROM maintenance.job_checks c
            LEFT JOIN LATERAL (
                SELECT en.id, en.outcome, en.photo IS NOT NULL AS has_photo, en.measured_value
                FROM maintenance.check_entries en
                WHERE en.check_id = c.id AND en.attempt = c.attempt
                ORDER BY en.created_at DESC, en.id DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE c.job_id = %s
            ORDER BY c.sort_order, c.id
            """,
            (job_id,),
        ).fetchall()
        return [
            CheckSnapshot(
                id=check_id,
                state=state,
                attempt=attempt,
                action=action,
                requires_photo=requires_photo,
                latest_entry=None
                if entry_id is None
                else EntrySummary(
                    attempt=attempt,
                    outcome=outcome,
                    has_photo=has_photo,
                    measured_value=float(measured_value) if measured_value is not None else None,
                ),
            )
            for check_id, state, attempt, action, requires_photo, entry_id, outcome, has_photo, measured_value in rows
        ]

    def _check_labels(self, job_id: str) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT id, label FROM maintenance.job_checks WHERE job_id = %s", (job_id,)
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def _release_equipment(self, tenant_id: str, actor_id: str, job: _Job) -> Result[bool]:
        """Puts back to `operational` the machine a job had stopped, now that this job has
        ended (its row is already closed or cancelled). Ok(True) when the machine moved.

        Nothing moves when the job never stopped it (not a stopping job, or never started),
        when the machine is not in `maintenance` any more (someone moved it by hand), or
        while another started stopping job on the same machine still holds it.
        """
        if not job.stops_machine or job.started_at is None:
            return Ok(False)
        # Lock the machine before looking at the other jobs: two stopping jobs ending at the
        # same moment then run one after the other, and the second one sees the first as ended
        # instead of each seeing the other as still open and both leaving the machine stopped.
        machine = self._connection.execute(
            "SELECT status FROM maintenance.equipment WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (job.equipment_id, tenant_id),
        ).fetchone()
        if machine is None or machine[0] != "maintenance":
            return Ok(False)
        still_held = self._connection.execute(
            """
            SELECT 1 FROM maintenance.jobs
            WHERE tenant_id = %s AND equipment_id = %s AND id <> %s
              AND stops_machine AND started_at IS NOT NULL AND status = ANY(%s)
            LIMIT 1
            """,
            (tenant_id, job.equipment_id, job.id, _HOLDING_STATUSES),
        ).fetchone()
        if still_held is not None:
            return Ok(False)
        return self._move_equipment(
            tenant_id, actor_id, job.equipment_id, to_status="operational", only_from=("maintenance",)
        )

    def _move_equipment(
        self, tenant_id: str, actor_id: str, equipment_id: str, *, to_status: str, only_from: tuple[str, ...]
    ) -> Result[bool]:
        """Moves the machine to `to_status` if it currently sits in one of `only_from`;
        otherwise leaves it alone (already there, or put elsewhere by hand). Ok(True) when it moved."""
        row = self._connection.execute(
            "SELECT status FROM maintenance.equipment WHERE id = %s AND tenant_id = %s FOR UPDATE", (equipment_id, tenant_id)
        ).fetchone()
        if row is None or row[0] not in only_from:
            return Ok(False)
        moved = EquipmentService(self._connection).transition_status(
            tenant_id=tenant_id, actor_id=actor_id, equipment_id=equipment_id, new_status=to_status
        )
        if isinstance(moved, Err):
            return moved
        return Ok(True)

    def _event(self, tenant_id: str, job_id: str, actor_id: str, kind: str, payload: dict) -> None:
        """One timeline row. Stamped with clock_timestamp() so the rows of one transaction keep their order."""
        self._connection.execute(
            """
            INSERT INTO maintenance.job_events (id, tenant_id, job_id, at, actor_id, kind, payload)
            VALUES (%s, %s, %s, clock_timestamp(), %s, %s, %s)
            """,
            (str(ULID()), tenant_id, job_id, actor_id, kind, Jsonb(payload)),
        )

    def _audit(self, tenant_id: str, actor_id: str, job_id: str, action: str, payload: dict) -> None:
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type=_ENTITY,
            entity_id=job_id,
            payload=payload,
        )

    def _notify(
        self,
        tenant_id: str,
        job: _Job,
        user_ids: Iterable[str | None],
        kind: str,
        *,
        body: str | None = None,
        body_fr: str | None = None,
    ) -> None:
        notifications.notify_job(
            self._connection,
            tenant_id=tenant_id,
            user_ids=user_ids,
            kind=kind,
            job_id=job.id,
            number=job.number,
            equipment_name=job.equipment_name,
            body=body,
            body_fr=body_fr,
        )

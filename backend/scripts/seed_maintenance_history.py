"""Dev-only history for the maintenance logbook: five months of closed jobs on the demo
machines (monthly preventive rounds with trending measures, a corrective job sent back
once), and their status changes. Run after scripts.seed_maintenance:

    .venv/Scripts/python -m scripts.seed_maintenance_history

Idempotent: does nothing when a job titled "Historique démo" already exists. Only adds
maintenance rows and the audit rows EquipmentService writes; backdates their timestamps
(dev data only -- the services always write NOW()).
"""
from __future__ import annotations

import datetime

from core.db import get_connection
from core.domain.result import Err
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.people import active_employees
from scripts.seed_maintenance import make_placeholder_png

TENANT = "demo"
DEMO_EMAIL = "demo@sonalim-erp.local"
MARKER = "Historique démo"
UTC = datetime.timezone.utc
MONTHS = 5


def _check(result, context: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{context}: {result.code} — {result.message}")
    return result.value


PHOTO = (make_placeholder_png(320, 240, (230, 230, 230), (60, 90, 140)), "image/png")


def _photo(requires_photo: bool):
    """A point that asks for a photo cannot be submitted without one."""
    return PHOTO if requires_photo else None


def _set_job(connection, job_id: str, **columns) -> None:
    for column, value in columns.items():
        connection.execute(f"UPDATE maintenance.jobs SET {column} = %s WHERE id = %s", (value, job_id))


def _close_round(jobs: JobService, connection, actor: str, people: list[dict], job_id: str, done_at: datetime.datetime,
                 months_ago: int, machine_index: int) -> None:
    checks = connection.execute(
        "SELECT id, action, requires_photo FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order, id", (job_id,)
    ).fetchall()
    for index, (check_id, action, requires_photo) in enumerate(checks):
        started = done_at + datetime.timedelta(minutes=12 * index)
        finished = started + datetime.timedelta(minutes=8 + index)
        outcome = "issue" if (months_ago == 2 and index == 0) else "ok"
        _check(jobs.record_entry(
            tenant_id=TENANT, actor_id=actor, job_id=job_id, check_id=check_id,
            performer_employee_id=people[index % len(people)]["id"], outcome=outcome,
            note="bruit anormal" if outcome == "issue" else None,
            measured_value=(62 + 2 * (MONTHS - months_ago) + machine_index) if action == "measure" else None,
            started_at=started, finished_at=finished, manual_minutes=None, photo=_photo(requires_photo),
            actor_can_plan=True, now=finished,
        ), "record entry")
    _check(jobs.submit(tenant_id=TENANT, actor_id=actor, job_id=job_id, actor_can_plan=True), "submit")
    _check(jobs.review(tenant_id=TENANT, actor_id=actor, job_id=job_id, verdicts=[(c[0], "accepted", None) for c in checks]), "review")
    _check(jobs.close(tenant_id=TENANT, actor_id=actor, job_id=job_id), "close")


def seed() -> None:
    with get_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM maintenance.jobs WHERE tenant_id = %s AND title LIKE %s", (TENANT, f"{MARKER}%")
        ).fetchone():
            print("already seeded")
            return
        demo = connection.execute("SELECT id FROM core.users WHERE tenant_id = %s AND email = %s", (TENANT, DEMO_EMAIL)).fetchone()
        if demo is None:
            raise RuntimeError("demo user not found — run scripts.seed_dev first")
        actor = demo[0]
        people = active_employees(connection, TENANT)
        if not people:
            raise RuntimeError("no active HR employee — run the HR seed first")
        machines = connection.execute(
            """
            SELECT DISTINCT e.id, e.name FROM maintenance.equipment e
            JOIN maintenance.equipment_views v ON v.equipment_id = e.id
            WHERE e.tenant_id = %s AND e.archived_at IS NULL
            ORDER BY e.name LIMIT 2
            """,
            (TENANT,),
        ).fetchall()
        if not machines:
            raise RuntimeError("no machine with a photo map — run scripts.seed_maintenance first")

        jobs = JobService(connection)
        equipment = EquipmentService(connection)
        today = datetime.date.today()
        for machine_index, (machine_id, machine_name) in enumerate(machines):
            points = [row[0] for row in connection.execute(
                """
                SELECT cp.id FROM maintenance.checkpoints cp JOIN maintenance.equipment_views v ON v.id = cp.view_id
                WHERE v.equipment_id = %s AND cp.archived_at IS NULL ORDER BY v.sort_order, cp.sort_order, cp.id
                """,
                (machine_id,),
            ).fetchall()]
            if not points:
                print(f"{machine_name}: no checkpoint on its plan, skipped")
                continue
            for months_ago in range(MONTHS, 0, -1):
                due = (today.replace(day=1) - datetime.timedelta(days=30 * months_ago)).replace(day=10 + machine_index)
                job_id = _check(jobs.create_job(
                    tenant_id=TENANT, actor_id=actor, equipment_id=machine_id, title=f"{MARKER} — ronde mensuelle",
                    description=None, kind="preventive", priority="normal", due_date=due, stops_machine=False,
                    checkpoint_ids=points, tasks=[], chef_user_id=actor,
                ), "create preventive")
                done_at = datetime.datetime.combine(due, datetime.time(9, 0), tzinfo=UTC)
                _close_round(jobs, connection, actor, people, job_id, done_at, months_ago, machine_index)
                # One round of the five is closed a day and a half late.
                closed_at = done_at + datetime.timedelta(hours=36 if months_ago == 3 else 6)
                _set_job(connection, job_id, created_at=done_at - datetime.timedelta(days=5), started_at=done_at,
                         submitted_at=done_at + datetime.timedelta(hours=2), closed_at=closed_at)
            print(f"{machine_name}: {MONTHS} closed preventive rounds")

            # A breakdown two months ago: down, maintenance while repaired, back to operational.
            # Only from operational: the workflow seed may have left a machine held by an open job.
            current = connection.execute("SELECT status FROM maintenance.equipment WHERE id = %s", (machine_id,)).fetchone()[0]
            if current != "operational":
                print(f"{machine_name}: status is {current}, breakdown story skipped")
                continue
            broke = datetime.datetime.combine(today - datetime.timedelta(days=58 + machine_index), datetime.time(7, 40), tzinfo=UTC)
            for status in ("down", "maintenance", "operational"):
                _check(equipment.transition_status(tenant_id=TENANT, actor_id=actor, equipment_id=machine_id, new_status=status), status)
            # The three rows share this transaction's NOW(): place each by the status it moved to.
            for status, offset in (("down", 0), ("maintenance", 45), ("operational", 330)):
                connection.execute(
                    """
                    UPDATE core.audit_log SET occurred_at = %s
                    WHERE id = (
                        SELECT id FROM core.audit_log
                        WHERE entity_id = %s AND action = 'equipment.status_changed' AND payload->>'to_status' = %s
                        ORDER BY occurred_at DESC LIMIT 1
                    )
                    """,
                    (broke + datetime.timedelta(minutes=offset), machine_id, status),
                )
            corrective = _check(jobs.create_job(
                tenant_id=TENANT, actor_id=actor, equipment_id=machine_id, title=f"{MARKER} — panne vis principale",
                description="Bruit puis arrêt de la vis", kind="corrective", priority="urgent", due_date=broke.date(),
                stops_machine=False, checkpoint_ids=points[:1], tasks=[{"label": "Remplacer le roulement", "action": "replace"}],
                chef_user_id=actor,
            ), "create corrective")
            check_rows = connection.execute(
                "SELECT id, action, requires_photo FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order, id",
                (corrective,),
            ).fetchall()
            checks = [row[0] for row in check_rows]
            needs_photo = {row[0]: row[2] for row in check_rows}
            measure = {row[0]: row[1] == "measure" for row in check_rows}
            repair = broke + datetime.timedelta(minutes=60)
            for check_id in checks:
                _check(jobs.record_entry(
                    tenant_id=TENANT, actor_id=actor, job_id=corrective, check_id=check_id,
                    performer_employee_id=people[0]["id"], outcome="ok", note=None,
                    measured_value=78 if measure[check_id] else None,
                    started_at=repair, finished_at=repair + datetime.timedelta(minutes=50), manual_minutes=None,
                    photo=_photo(needs_photo[check_id]), actor_can_plan=True, now=repair + datetime.timedelta(minutes=50),
                ), "record corrective")
            _check(jobs.submit(tenant_id=TENANT, actor_id=actor, job_id=corrective, actor_can_plan=True), "submit corrective")
            _check(jobs.review(
                tenant_id=TENANT, actor_id=actor, job_id=corrective,
                verdicts=[(checks[0], "rejected", "serrage à refaire")] + [(c, "accepted", None) for c in checks[1:]],
            ), "review corrective")
            redo = repair + datetime.timedelta(hours=2)
            _check(jobs.record_entry(
                tenant_id=TENANT, actor_id=actor, job_id=corrective, check_id=checks[0],
                performer_employee_id=people[-1]["id"], outcome="ok", note="resserré",
                measured_value=70 if measure[checks[0]] else None,
                started_at=redo, finished_at=redo + datetime.timedelta(minutes=15), manual_minutes=None,
                photo=_photo(needs_photo[checks[0]]), actor_can_plan=True, now=redo + datetime.timedelta(minutes=15),
            ), "redo corrective")
            _check(jobs.submit(tenant_id=TENANT, actor_id=actor, job_id=corrective, actor_can_plan=True), "resubmit")
            _check(jobs.review(tenant_id=TENANT, actor_id=actor, job_id=corrective, verdicts=[(checks[0], "accepted", None)]), "accept")
            _check(jobs.close(tenant_id=TENANT, actor_id=actor, job_id=corrective), "close corrective")
            _set_job(connection, corrective, created_at=broke, started_at=repair, closed_at=broke + datetime.timedelta(hours=6))
            print(f"{machine_name}: one breakdown with a sent-back point and its status changes")
        connection.commit()


if __name__ == "__main__":
    seed()

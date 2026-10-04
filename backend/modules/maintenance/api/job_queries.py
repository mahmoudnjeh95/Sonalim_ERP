"""Read side of maintenance jobs: the list (`JobListItem`) and the full page of one job
(`JobDetail`: its checks with every attempt's entries and reviews, and its timeline),
serialised exactly as the API contract names them.

Kept apart from `JobService` so the calendar (programs) and the parts requests can
reuse the same shapes without going through the write service.
"""
from __future__ import annotations

import datetime

import psycopg

from modules.maintenance.api.parts_service import list_part_requests
from modules.maintenance.api.people import employee_names, user_names
from modules.maintenance.api.spare_parts_service import SparePartsService

__all__ = ["entry_photo", "job_detail", "list_jobs"]

_NOT_OVERDUE_STATUSES = ("closed", "cancelled")

# One row per job: its machine, team, progress (checks recorded or accepted out of all)
# and the time spent. Time counts the latest entry of each attempt of each check: a
# point redone before submitting replaces its earlier try, while a rework adds to it.
_JOB_SQL = """
    SELECT j.id, j.number, j.equipment_id, e.code, e.name, j.kind, j.priority, j.title, j.status, j.due_date,
           j.team_id, t.name, j.chef_user_id, j.program_id, j.occurrence_date, j.stops_machine,
           progress.total, progress.done, COALESCE(spent.seconds, 0),
           j.created_at, j.started_at, j.submitted_at, j.closed_at,
           j.description, j.created_by, j.cancel_reason
    FROM maintenance.jobs j
    JOIN maintenance.equipment e ON e.id = j.equipment_id
    LEFT JOIN maintenance.teams t ON t.id = j.team_id
    CROSS JOIN LATERAL (
        SELECT count(*) AS total, count(*) FILTER (WHERE c.state IN ('done', 'accepted')) AS done
        FROM maintenance.job_checks c
        WHERE c.job_id = j.id
    ) progress
    CROSS JOIN LATERAL (
        SELECT sum(latest.duration_seconds) AS seconds
        FROM (
            SELECT DISTINCT ON (en.check_id, en.attempt) en.duration_seconds
            FROM maintenance.check_entries en
            JOIN maintenance.job_checks c ON c.id = en.check_id
            WHERE c.job_id = j.id
            ORDER BY en.check_id, en.attempt, en.created_at DESC, en.id DESC
        ) latest
    ) spent
"""


def _iso(value: datetime.datetime | datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _number(value) -> float | None:
    return float(value) if value is not None else None


def _job_item(row: tuple, user_name: dict[str, str], today: datetime.date) -> dict:
    (
        job_id, number, equipment_id, equipment_code, equipment_name, kind, priority, title, status, due_date,
        team_id, team_name, chef_user_id, program_id, occurrence_date, stops_machine,
        checks_total, checks_done, seconds_spent,
        created_at, started_at, submitted_at, closed_at,
        _description, _created_by, _cancel_reason,
    ) = row
    return {
        "id": job_id,
        "number": number,
        "equipment_id": equipment_id,
        "equipment_code": equipment_code,
        "equipment_name": equipment_name,
        "kind": kind,
        "priority": priority,
        "title": title,
        "status": status,
        "due_date": due_date.isoformat(),
        "team_id": team_id,
        "team_name": team_name,
        "chef_user_id": chef_user_id,
        "chef_name": user_name.get(chef_user_id) if chef_user_id is not None else None,
        "program_id": program_id,
        "occurrence_date": _iso(occurrence_date),
        "stops_machine": stops_machine,
        "checks_total": checks_total,
        "checks_done": checks_done,
        # whole minutes, half up
        "minutes_spent": (int(seconds_spent) + 30) // 60,
        "overdue": due_date < today and status not in _NOT_OVERDUE_STATUSES,
        "created_at": created_at.isoformat(),
        "started_at": _iso(started_at),
        "submitted_at": _iso(submitted_at),
        "closed_at": _iso(closed_at),
    }


def list_jobs(
    connection: psycopg.Connection,
    tenant_id: str,
    *,
    statuses: list[str] | None = None,
    equipment_id: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    chef_user_id: str | None = None,
    today: datetime.date,
) -> list[dict]:
    """The tenant's jobs as `JobListItem`s, latest due date first. `date_from`/`date_to`
    bound the due date (both inclusive); `statuses` keeps the jobs in any of them;
    `chef_user_id` keeps one chef's jobs. `today` decides what is overdue."""
    clauses = ["j.tenant_id = %s"]
    params: list[object] = [tenant_id]
    if statuses:
        clauses.append("j.status = ANY(%s)")
        params.append(list(statuses))
    if equipment_id is not None:
        clauses.append("j.equipment_id = %s")
        params.append(equipment_id)
    if date_from is not None:
        clauses.append("j.due_date >= %s")
        params.append(date_from)
    if date_to is not None:
        clauses.append("j.due_date <= %s")
        params.append(date_to)
    if chef_user_id is not None:
        clauses.append("j.chef_user_id = %s")
        params.append(chef_user_id)

    rows = connection.execute(
        f"{_JOB_SQL} WHERE {' AND '.join(clauses)} ORDER BY j.due_date DESC, j.number DESC", params
    ).fetchall()
    chefs = user_names(connection, tenant_id, [row[12] for row in rows])
    return [_job_item(row, chefs, today) for row in rows]


def job_detail(connection: psycopg.Connection, tenant_id: str, job_id: str, today: datetime.date) -> dict | None:
    """One job as a `JobDetail`, or None when the tenant has no such job."""
    row = connection.execute(f"{_JOB_SQL} WHERE j.id = %s AND j.tenant_id = %s", (job_id, tenant_id)).fetchone()
    if row is None:
        return None
    chef_user_id, description, created_by, cancel_reason = row[12], row[23], row[24], row[25]

    check_rows = connection.execute(
        """
        SELECT id, sort_order, checkpoint_id, view_id, x_pct, y_pct, label, action, instructions, measure_unit,
               requires_photo, assignee_employee_id, state, attempt
        FROM maintenance.job_checks
        WHERE job_id = %s
        ORDER BY sort_order, id
        """,
        (job_id,),
    ).fetchall()
    # Every entry and review of every attempt, oldest first: nothing is ever hidden from the history.
    entry_rows = connection.execute(
        """
        SELECT en.id, en.check_id, en.attempt, en.performer_employee_id, en.recorded_by, en.started_at, en.finished_at,
               en.duration_seconds, en.duration_source, en.outcome, en.note, en.measured_value, en.photo IS NOT NULL
        FROM maintenance.check_entries en
        JOIN maintenance.job_checks c ON c.id = en.check_id
        WHERE c.job_id = %s
        ORDER BY en.created_at, en.id
        """,
        (job_id,),
    ).fetchall()
    review_rows = connection.execute(
        """
        SELECT r.id, r.check_id, r.attempt, r.verdict, r.reason, r.reviewer_id, r.created_at
        FROM maintenance.check_reviews r
        JOIN maintenance.job_checks c ON c.id = r.check_id
        WHERE c.job_id = %s
        ORDER BY r.created_at, r.id
        """,
        (job_id,),
    ).fetchall()
    event_rows = connection.execute(
        "SELECT id, at, actor_id, kind, payload FROM maintenance.job_events WHERE job_id = %s ORDER BY at, id", (job_id,)
    ).fetchall()

    user_name = user_names(
        connection,
        tenant_id,
        [chef_user_id, created_by, *(r[4] for r in entry_rows), *(r[5] for r in review_rows), *(r[2] for r in event_rows)],
    )
    employee_name = employee_names(
        connection, tenant_id, [*(r[11] for r in check_rows), *(r[3] for r in entry_rows)]
    )

    entries: dict[str, list[dict]] = {}
    for (
        entry_id, check_id, attempt, performer_id, recorded_by, started_at, finished_at,
        duration_seconds, duration_source, outcome, note, measured_value, has_photo,
    ) in entry_rows:
        entries.setdefault(check_id, []).append(
            {
                "id": entry_id,
                "attempt": attempt,
                "performer_employee_id": performer_id,
                "performer_name": employee_name.get(performer_id, performer_id),
                "recorded_by": recorded_by,
                "recorded_by_name": user_name.get(recorded_by, recorded_by),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_seconds": duration_seconds,
                "duration_source": duration_source,
                "outcome": outcome,
                "note": note,
                "measured_value": _number(measured_value),
                "has_photo": has_photo,
            }
        )

    reviews: dict[str, list[dict]] = {}
    for review_id, check_id, attempt, verdict, reason, reviewer_id, created_at in review_rows:
        reviews.setdefault(check_id, []).append(
            {
                "id": review_id,
                "attempt": attempt,
                "verdict": verdict,
                "reason": reason,
                "reviewer_id": reviewer_id,
                "reviewer_name": user_name.get(reviewer_id, reviewer_id),
                "created_at": created_at.isoformat(),
            }
        )

    checks = [
        {
            "id": check_id,
            "sort_order": sort_order,
            "checkpoint_id": checkpoint_id,
            "view_id": view_id,
            "x_pct": _number(x_pct),
            "y_pct": _number(y_pct),
            "label": label,
            "action": action,
            "instructions": instructions,
            "measure_unit": measure_unit,
            "requires_photo": requires_photo,
            "assignee_employee_id": assignee_id,
            "assignee_name": employee_name.get(assignee_id) if assignee_id is not None else None,
            "state": state,
            "attempt": attempt,
            "entries": entries.get(check_id, []),
            "reviews": reviews.get(check_id, []),
        }
        for (
            check_id, sort_order, checkpoint_id, view_id, x_pct, y_pct, label, action, instructions, measure_unit,
            requires_photo, assignee_id, state, attempt,
        ) in check_rows
    ]

    # The spare parts each check's point needs, read live from the point with what the
    # spare-parts location has available; a free task (no point) needs none.
    parts = SparePartsService(connection).parts_with_stock(
        tenant_id, [check["checkpoint_id"] for check in checks if check["checkpoint_id"] is not None]
    )
    for check in checks:
        check["parts"] = parts.get(check["checkpoint_id"], []) if check["checkpoint_id"] is not None else []

    timeline = [
        {
            "id": event_id,
            "at": at.isoformat(),
            "actor_id": actor_id,
            # None for an actor that is not a user (the program sweep's "system:maintenance-sweep").
            "actor_name": user_name.get(actor_id) if actor_id is not None else None,
            "kind": kind,
            "payload": payload,
        }
        for event_id, at, actor_id, kind, payload in event_rows
    ]

    return {
        **_job_item(row, user_name, today),
        "description": description,
        "created_by": created_by,
        # A job raised by the sweep has no user behind it: show the actor string itself.
        "created_by_name": user_name.get(created_by, created_by),
        "cancel_reason": cancel_reason,
        "checks": checks,
        "part_requests": _part_requests(connection, tenant_id, job_id),
        "timeline": timeline,
    }


def _part_requests(connection: psycopg.Connection, tenant_id: str, job_id: str) -> list[dict]:
    """The job's spare-parts requests (`PartRequest[]`), newest first."""
    return list_part_requests(connection, tenant_id, job_id=job_id)


def entry_photo(connection: psycopg.Connection, tenant_id: str, entry_id: str) -> tuple[bytes, str] | None:
    """The photo taken for one check entry, as `(bytes, mime)`; None when there is none."""
    row = connection.execute(
        "SELECT photo, photo_mime FROM maintenance.check_entries WHERE id = %s AND tenant_id = %s", (entry_id, tenant_id)
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return bytes(row[0]), row[1]

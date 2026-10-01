"""Maintenance-side in-app notifications: who is told what about a job, in English and French.

A thin layer over `core.notifications.notify` so the services only say *which* event
happened; the wording, the recipients called "supervisors" and the link to the job
page live here, in one place.
"""
from __future__ import annotations

from collections.abc import Iterable

import psycopg

from core.notifications import notify, users_with_permission

__all__ = [
    "JOB_ASSIGNED",
    "JOB_CANCELLED",
    "JOB_CLOSED",
    "JOB_DUE",
    "JOB_OVERDUE",
    "JOB_REWORK",
    "JOB_SUBMITTED",
    "JOB_URGENT",
    "PARTS_APPROVED",
    "PARTS_LINK",
    "PARTS_REJECTED",
    "PARTS_REQUESTED",
    "PLAN_PERMISSION",
    "job_link",
    "notify_job",
    "notify_parts",
    "supervisors",
]

# "Supervisors" are whoever may plan jobs, directly or through a role.
PLAN_PERMISSION = "maintenance.plan_jobs"

JOB_URGENT = "maintenance.job_urgent"
JOB_ASSIGNED = "maintenance.job_assigned"
JOB_DUE = "maintenance.job_due"
JOB_OVERDUE = "maintenance.job_overdue"
JOB_SUBMITTED = "maintenance.job_submitted"
JOB_REWORK = "maintenance.job_rework"
JOB_CLOSED = "maintenance.job_closed"
JOB_CANCELLED = "maintenance.job_cancelled"

# kind -> (English title, French title); both name the job and its machine.
_JOB_TITLES: dict[str, tuple[str, str]] = {
    JOB_URGENT: ("Urgent job {number} on {machine}", "Intervention urgente {number} sur {machine}"),
    JOB_ASSIGNED: ("Job {number} assigned to you on {machine}", "Intervention {number} assignée sur {machine}"),
    JOB_DUE: ("Preventive job {number} is due on {machine}", "Intervention préventive {number} à réaliser sur {machine}"),
    JOB_OVERDUE: ("Job {number} on {machine} is overdue", "Intervention {number} sur {machine} en retard"),
    JOB_SUBMITTED: ("Job {number} on {machine} awaits your review", "Intervention {number} sur {machine} à valider"),
    JOB_REWORK: ("Job {number} on {machine} sent back for rework", "Intervention {number} sur {machine} renvoyée en correction"),
    JOB_CLOSED: ("Job {number} on {machine} closed", "Intervention {number} sur {machine} clôturée"),
    JOB_CANCELLED: ("Job {number} on {machine} cancelled", "Intervention {number} sur {machine} annulée"),
}


PARTS_REQUESTED = "maintenance.parts_requested"
PARTS_APPROVED = "maintenance.parts_approved"
PARTS_REJECTED = "maintenance.parts_rejected"

# Parts notifications open the Parts tab, where the request is decided or read.
PARTS_LINK = "/maintenance?tab=parts"

# kind -> (English title, French title); both name the job and its machine.
_PARTS_TITLES: dict[str, tuple[str, str]] = {
    PARTS_REQUESTED: (
        "Parts requested for job {number} on {machine}",
        "Demande de pièces pour l'intervention {number} sur {machine}",
    ),
    PARTS_APPROVED: (
        "Parts approved for job {number} on {machine}",
        "Pièces validées pour l'intervention {number} sur {machine}",
    ),
    PARTS_REJECTED: (
        "Parts request refused for job {number} on {machine}",
        "Demande de pièces refusée pour l'intervention {number} sur {machine}",
    ),
}


def supervisors(connection: psycopg.Connection, tenant_id: str) -> list[str]:
    """The users notified as "supervisors": every holder of `maintenance.plan_jobs`."""
    return users_with_permission(connection, tenant_id, PLAN_PERMISSION)


def job_link(job_id: str) -> str:
    """The SPA path a job notification opens."""
    return f"/maintenance/jobs/{job_id}"


def notify_job(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    user_ids: Iterable[str | None],
    kind: str,
    job_id: str,
    number: str,
    equipment_name: str,
    body: str | None = None,
    body_fr: str | None = None,
) -> int:
    """One notification per distinct recipient about job `number` on `equipment_name`.

    `kind` picks the title (one of the `JOB_*` constants); `body` carries the detail
    (the job title, a rejection or cancellation reason) and `body_fr` defaults to it,
    since that detail is text the users typed. Empty/None recipients are skipped.
    Returns the number of rows written.
    """
    title, title_fr = _JOB_TITLES[kind]
    return notify(
        connection,
        tenant_id=tenant_id,
        user_ids=[user_id for user_id in user_ids if user_id],
        kind=kind,
        title=title.format(number=number, machine=equipment_name),
        title_fr=title_fr.format(number=number, machine=equipment_name),
        body=body,
        body_fr=body_fr if body_fr is not None else body,
        link=job_link(job_id),
    )


def notify_parts(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    user_ids: Iterable[str | None],
    kind: str,
    number: str,
    equipment_name: str,
    body: str | None = None,
) -> int:
    """One notification per distinct recipient about a parts request on job `number`.

    `kind` picks the title (one of the `PARTS_*` constants); `body` is the note the
    requester or the supervisor typed, the same in both languages. Links to the
    Parts tab. Empty/None recipients are skipped. Returns the number of rows written.
    """
    title, title_fr = _PARTS_TITLES[kind]
    return notify(
        connection,
        tenant_id=tenant_id,
        user_ids=[user_id for user_id in user_ids if user_id],
        kind=kind,
        title=title.format(number=number, machine=equipment_name),
        title_fr=title_fr.format(number=number, machine=equipment_name),
        body=body,
        body_fr=body,
        link=PARTS_LINK,
    )

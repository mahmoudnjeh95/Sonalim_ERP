from __future__ import annotations

import datetime
import math
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

JOB_STATUSES = ("planned", "assigned", "in_progress", "submitted", "rework", "closed", "cancelled")
CHECK_ACTIONS = ("inspect", "lubricate", "tighten", "clean", "replace", "measure", "other")
OUTCOMES = ("ok", "issue", "not_done")
JOB_KINDS = ("preventive", "corrective")
JOB_PRIORITIES = ("normal", "urgent")
VERDICTS = ("accepted", "rejected")

# A job may be assigned (or re-assigned) while it sits in either of these states.
_ASSIGNABLE_STATUSES = {"planned", "assigned"}

# The chef hands checks to team members while the job is theirs to work: once it
# has a chef and until it is submitted (a rework hands it back to them).
_DELEGABLE_STATUSES = {"assigned", "in_progress", "rework"}

# A check can take a new entry only while the job is being worked and the check
# itself has not already been accepted by a reviewer.
_ENTRY_JOB_STATUSES = {"assigned", "in_progress", "rework"}
_ENTRY_CHECK_STATES = {"pending", "done"}

# A job can be cancelled from any state except these two terminal ones.
_NON_CANCELLABLE_STATUSES = {"closed", "cancelled"}

# Clock skew tolerated between a client's "finished now" timestamp and the
# server's own clock, so a slightly-ahead device is not rejected.
_CLOCK_SKEW = datetime.timedelta(minutes=2)


@dataclass(frozen=True)
class EntrySummary:
    attempt: int
    outcome: str
    has_photo: bool
    measured_value: float | None


@dataclass(frozen=True)
class CheckSnapshot:
    id: str
    state: str  # pending | done | accepted
    attempt: int
    action: str
    requires_photo: bool
    latest_entry: EntrySummary | None  # latest entry of the current attempt


def can_assign(status: str) -> Result[None]:
    if status not in _ASSIGNABLE_STATUSES:
        return Err(
            "INVALID_TRANSITION",
            f"cannot assign a job in status {status}",
            f"impossible d'assigner une intervention au statut {status}",
        )
    return Ok(None)


def can_delegate(status: str) -> Result[None]:
    if status not in _DELEGABLE_STATUSES:
        return Err(
            "INVALID_TRANSITION",
            f"cannot delegate the checks of a job in status {status}",
            f"impossible de déléguer les points d'une intervention au statut {status}",
        )
    return Ok(None)


def can_record_entry(status: str, check_state: str) -> Result[None]:
    if check_state == "accepted":
        return Err(
            "CHECK_LOCKED",
            "this check was already accepted and cannot be recorded again",
            "ce point a déjà été accepté et ne peut plus être renseigné",
        )
    if status not in _ENTRY_JOB_STATUSES or check_state not in _ENTRY_CHECK_STATES:
        return Err(
            "INVALID_TRANSITION",
            f"cannot record an entry for a job in status {status}",
            f"impossible d'enregistrer un relevé pour une intervention au statut {status}",
        )
    return Ok(None)


def status_after_entry(status: str) -> str:
    return "in_progress" if status == "assigned" else status


def validate_submit(status: str, checks: list[CheckSnapshot]) -> Result[None]:
    if status not in ("in_progress", "rework"):
        return Err(
            "INVALID_TRANSITION",
            f"cannot submit a job in status {status}",
            f"impossible de soumettre une intervention au statut {status}",
        )

    pending = [c for c in checks if c.state == "pending"]
    if pending:
        return Err(
            "CHECKS_PENDING",
            f"{len(pending)} check(s) are still pending",
            f"{len(pending)} point(s) sont encore en attente",
        )

    for check in checks:
        if check.state != "done":
            continue
        entry = check.latest_entry
        if entry is None:
            return Err(
                "CHECKS_PENDING",
                "a done check has no recorded entry",
                "un point marqué fait n'a pas de relevé enregistré",
            )
        if check.requires_photo and entry.outcome != "not_done" and not entry.has_photo:
            return Err(
                "PHOTO_REQUIRED",
                "a photo is required for this check",
                "une photo est requise pour ce point",
            )
        if check.action == "measure" and entry.outcome != "not_done" and entry.measured_value is None:
            return Err(
                "MEASURE_REQUIRED",
                "a measured value is required for this check",
                "une valeur mesurée est requise pour ce point",
            )

    return Ok(None)


@dataclass(frozen=True)
class ReviewOutcome:
    accepted_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    next_status: str  # "rework" if any rejected else "submitted"


def apply_review(
    status: str,
    checks: list[CheckSnapshot],
    verdicts: list[tuple[str, str, str | None]],
) -> Result[ReviewOutcome]:
    if status != "submitted":
        return Err(
            "INVALID_TRANSITION",
            f"cannot review a job in status {status}",
            f"impossible de relire une intervention au statut {status}",
        )

    done_ids = {c.id for c in checks if c.state == "done"}
    verdict_ids = [check_id for check_id, _, _ in verdicts]

    unknown = [check_id for check_id in verdict_ids if check_id not in done_ids]
    if unknown:
        return Err(
            "UNKNOWN_CHECK",
            f"verdict given for a check that is not awaiting review: {unknown[0]}",
            f"verdict donné pour un point qui n'est pas en attente de relecture : {unknown[0]}",
        )

    if set(verdict_ids) != done_ids or len(verdict_ids) != len(done_ids):
        return Err(
            "REVIEW_INCOMPLETE",
            "every check awaiting review must get exactly one verdict",
            "chaque point en attente de relecture doit recevoir exactement un verdict",
        )

    accepted_ids: list[str] = []
    rejected_ids: list[str] = []
    for check_id, verdict, reason in verdicts:
        if verdict == "rejected":
            if reason is None or not reason.strip():
                return Err(
                    "REASON_REQUIRED",
                    "a reason is required to reject a check",
                    "un motif est requis pour rejeter un point",
                )
            rejected_ids.append(check_id)
        else:
            accepted_ids.append(check_id)

    next_status = "rework" if rejected_ids else "submitted"
    return Ok(
        ReviewOutcome(
            accepted_ids=tuple(accepted_ids),
            rejected_ids=tuple(rejected_ids),
            next_status=next_status,
        )
    )


def can_close(status: str, checks: list[CheckSnapshot]) -> Result[None]:
    if status != "submitted":
        return Err(
            "INVALID_TRANSITION",
            f"cannot close a job in status {status}",
            f"impossible de clôturer une intervention au statut {status}",
        )
    if any(c.state != "accepted" for c in checks):
        return Err(
            "NOT_ALL_ACCEPTED",
            "every check must be accepted before closing the job",
            "tous les points doivent être acceptés avant de clôturer l'intervention",
        )
    return Ok(None)


def can_cancel(status: str) -> Result[None]:
    if status in _NON_CANCELLABLE_STATUSES:
        return Err(
            "INVALID_TRANSITION",
            f"cannot cancel a job in status {status}",
            f"impossible d'annuler une intervention au statut {status}",
        )
    return Ok(None)


@dataclass(frozen=True)
class Timing:
    started_at: datetime.datetime
    finished_at: datetime.datetime
    seconds: int
    source: str


def entry_timing(
    *,
    started_at: datetime.datetime | None,
    finished_at: datetime.datetime | None,
    manual_minutes: float | None,
    now: datetime.datetime,
) -> Result[Timing]:
    timer_mode = started_at is not None and finished_at is not None
    manual_mode = manual_minutes is not None

    if timer_mode and manual_mode:
        return Err(
            "INVALID_TIMING",
            "give either a start/finish timer or a manual duration, not both",
            "indiquez soit un chronométrage, soit une durée manuelle, pas les deux",
        )

    if timer_mode:
        if finished_at <= started_at:
            return Err(
                "INVALID_TIMING",
                "finished_at must be after started_at",
                "l'heure de fin doit être postérieure à l'heure de début",
            )
        if finished_at > now + _CLOCK_SKEW:
            return Err(
                "INVALID_TIMING",
                "finished_at cannot be in the future",
                "l'heure de fin ne peut pas être dans le futur",
            )
        # At least one second: duration_seconds is > 0, and a Start/Finish tapped within
        # a second is still a recorded check.
        seconds = max(1, int((finished_at - started_at).total_seconds()))
        return Ok(Timing(started_at=started_at, finished_at=finished_at, seconds=seconds, source="timer"))

    if manual_mode:
        if not math.isfinite(manual_minutes) or manual_minutes <= 0:
            return Err(
                "INVALID_TIMING",
                "manual duration must be greater than zero",
                "la durée manuelle doit être supérieure à zéro",
            )
        seconds = max(1, int(round(manual_minutes * 60)))
        computed_start = now - datetime.timedelta(seconds=seconds)
        return Ok(Timing(started_at=computed_start, finished_at=now, seconds=seconds, source="manual"))

    return Err(
        "INVALID_TIMING",
        "give either a start/finish timer or a manual duration",
        "indiquez soit un chronométrage, soit une durée manuelle",
    )

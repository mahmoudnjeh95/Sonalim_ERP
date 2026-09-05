from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

# The quality report mirrors a production report's vocabulary deliberately: the
# Validation Center shows both kinds of pending work in one list, and a validator
# should not have to learn two state machines.
QUALITY_REPORT_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"validated", "rejected"},
    "rejected": {"draft"},
    "validated": set(),
}

FOLLOW_UP_TRANSITIONS = {
    "open": {"in_progress", "completed"},
    "in_progress": {"completed"},
    "completed": set(),
}

# The window the specification describes. It is a default, not a constant — a
# per-product policy may override it (see FollowUpPolicyService).
DEFAULT_FOLLOW_UP_WINDOW_DAYS = 40


@dataclass(frozen=True)
class QualityReport:
    id: str
    of_id: str
    report_date: datetime.date
    status: str
    revision: int
    team: str | None = None
    shift: str | None = None
    created_by: str | None = None
    submitted_at: datetime.datetime | None = None
    validated_by: str | None = None
    validated_at: datetime.datetime | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class QualityReportDetail:
    pre_dryer_index: float | None = None
    humidity_percentage: float | None = None
    cooling_index: float | None = None
    pf_index: float | None = None
    sumo_index: float | None = None
    conforming_cartons: float = 0
    non_conforming_cartons: float = 0
    defect_details: str | None = None
    comments: str | None = None
    corrective_action: str | None = None


@dataclass(frozen=True)
class FollowUp:
    id: str
    quality_report_id: str
    of_id: str
    window_ends_on: datetime.date
    observed_on: datetime.date
    status: str
    result: str | None = None
    observation: str | None = None
    actor_id: str | None = None


def transition_quality_report(report: QualityReport, new_status: str) -> Result[QualityReport]:
    if new_status not in QUALITY_REPORT_TRANSITIONS.get(report.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move quality report from {report.status} to {new_status}")
    return Ok(replace(report, status=new_status))


def transition_follow_up(follow_up: FollowUp, new_status: str) -> Result[FollowUp]:
    if new_status not in FOLLOW_UP_TRANSITIONS.get(follow_up.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move follow-up from {follow_up.status} to {new_status}")
    return Ok(replace(follow_up, status=new_status))


def validate_quality_detail(detail: QualityReportDetail) -> Result[None]:
    """Check a quality report's readings for internal sense.

    The indices are measurements, not targets — this refuses impossible values,
    not disappointing ones. Judging whether a reading is acceptable is the
    validator's job, and recording a bad shift honestly is the whole point.
    """
    for field in ("conforming_cartons", "non_conforming_cartons"):
        value = getattr(detail, field)
        if value < 0:
            return Err("INVALID_QUANTITY", f"{field} cannot be negative")
        if abs(value - round(value)) > 1e-6:
            return Err("QUANTITY_MUST_BE_INTEGER", f"{field} must be a whole number of cartons")
    if detail.humidity_percentage is not None and not 0 <= detail.humidity_percentage <= 100:
        return Err("INVALID_PERCENTAGE", "humidity_percentage must be between 0 and 100")
    for field in ("pre_dryer_index", "cooling_index", "pf_index", "sumo_index"):
        value = getattr(detail, field)
        if value is not None and value < 0:
            return Err("INVALID_INDEX", f"{field} cannot be negative")
    if detail.non_conforming_cartons > 0 and not (detail.defect_details or "").strip():
        return Err("MISSING_DEFECT_DETAILS", "non-conforming cartons need defect details")
    return Ok(None)


def is_conforming(detail: QualityReportDetail) -> bool:
    return detail.non_conforming_cartons == 0


def follow_up_window_end(report_date: datetime.date, window_days: int) -> datetime.date:
    return report_date + datetime.timedelta(days=window_days)


def validate_window_days(window_days: int) -> Result[None]:
    if window_days <= 0:
        return Err("INVALID_WINDOW", "the follow-up window must be at least one day")
    if window_days > 3650:
        return Err("INVALID_WINDOW", "a follow-up window longer than ten years is almost certainly a typo")
    return Ok(None)

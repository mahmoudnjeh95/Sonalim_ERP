from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

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

DEFAULT_FOLLOW_UP_WINDOW_DAYS = 40


@dataclass(frozen=True)
class QualityReport:
    id: str
    shift_report_id: str
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
    """Shift-wide notes. Conformity itself lives on ConformityLine, one per product."""

    comments: str | None = None
    corrective_action: str | None = None


@dataclass(frozen=True)
class ConformityLine:
    id: str
    report_id: str
    shift_packing_row_id: str
    of_id: str
    product_id: str
    conforming_cartons: float = 0
    non_conforming_cartons: float = 0
    defect_details: str | None = None


@dataclass(frozen=True)
class FollowUp:
    id: str
    quality_report_id: str
    of_id: str
    conformity_line_id: str | None
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


def validate_conformity_line(line: ConformityLine) -> Result[None]:
    """Check one product's conformity counts for internal sense.

    Same stance as the old report-level check: refuses impossible values, not
    disappointing ones. Judging whether a defect rate is acceptable is the
    validator's job.
    """
    for field in ("conforming_cartons", "non_conforming_cartons"):
        value = getattr(line, field)
        if value < 0:
            return Err("INVALID_QUANTITY", f"{field} cannot be negative")
        if abs(value - round(value)) > 1e-6:
            return Err("QUANTITY_MUST_BE_INTEGER", f"{field} must be a whole number of cartons")
    if line.non_conforming_cartons > 0 and not (line.defect_details or "").strip():
        return Err("MISSING_DEFECT_DETAILS", "non-conforming cartons need defect details")
    return Ok(None)


def is_conforming(lines: list[ConformityLine]) -> bool:
    return all(line.non_conforming_cartons == 0 for line in lines)


def follow_up_window_end(report_date: datetime.date, window_days: int) -> datetime.date:
    return report_date + datetime.timedelta(days=window_days)


def validate_window_days(window_days: int) -> Result[None]:
    if window_days <= 0:
        return Err("INVALID_WINDOW", "the follow-up window must be at least one day")
    if window_days > 3650:
        return Err("INVALID_WINDOW", "a follow-up window longer than ten years is almost certainly a typo")
    return Ok(None)

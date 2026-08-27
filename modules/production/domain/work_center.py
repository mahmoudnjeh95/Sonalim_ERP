from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class WorkCenter:
    id: str
    code: str
    name: str
    hourly_rate: float
    is_blocked: bool
    blocked_reason: str | None


def validate_work_center_code(code: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "work center code is required")
    return Ok(None)


def block_work_center(work_center: WorkCenter, reason: str) -> Result[WorkCenter]:
    if work_center.is_blocked:
        return Err("ALREADY_BLOCKED", f"work center {work_center.id} is already blocked")
    if not reason.strip():
        return Err("REASON_REQUIRED", "a reason is required to block a work center")
    return Ok(
        WorkCenter(
            id=work_center.id,
            code=work_center.code,
            name=work_center.name,
            hourly_rate=work_center.hourly_rate,
            is_blocked=True,
            blocked_reason=reason,
        )
    )


def unblock_work_center(work_center: WorkCenter) -> Result[WorkCenter]:
    if not work_center.is_blocked:
        return Err("NOT_BLOCKED", f"work center {work_center.id} is not blocked")
    return Ok(
        WorkCenter(
            id=work_center.id,
            code=work_center.code,
            name=work_center.name,
            hourly_rate=work_center.hourly_rate,
            is_blocked=False,
            blocked_reason=None,
        )
    )

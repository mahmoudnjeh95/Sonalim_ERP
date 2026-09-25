from __future__ import annotations

from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class WorkCenter:
    id: str
    code: str
    name: str
    hourly_rate: float
    is_blocked: bool
    blocked_reason: str | None
    # 'production' (OFs, shift reports) or 'grinder' (rebroyat runs / OFRs).
    line_type: str = "production"


LINE_TYPES = ("production", "grinder")


def validate_work_center_code(code: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "work center code is required", "le code du poste de charge est obligatoire")
    return Ok(None)


def validate_line_type(line_type: str) -> Result[None]:
    if line_type not in LINE_TYPES:
        return Err(
            "INVALID_LINE_TYPE",
            f"line type must be one of {', '.join(LINE_TYPES)}",
            f"le type de ligne doit être l'un de : {', '.join(LINE_TYPES)}",
        )
    return Ok(None)


def block_work_center(work_center: WorkCenter, reason: str) -> Result[WorkCenter]:
    if work_center.is_blocked:
        return Err(
            "ALREADY_BLOCKED",
            f"work center {work_center.id} is already blocked",
            f"le poste de charge {work_center.id} est déjà bloqué",
        )
    if not reason.strip():
        return Err("REASON_REQUIRED", "a reason is required to block a work center", "une raison est obligatoire pour bloquer un poste de charge")
    return Ok(replace(work_center, is_blocked=True, blocked_reason=reason))


def unblock_work_center(work_center: WorkCenter) -> Result[WorkCenter]:
    if not work_center.is_blocked:
        return Err(
            "NOT_BLOCKED",
            f"work center {work_center.id} is not blocked",
            f"le poste de charge {work_center.id} n'est pas bloqué",
        )
    return Ok(replace(work_center, is_blocked=False, blocked_reason=None))

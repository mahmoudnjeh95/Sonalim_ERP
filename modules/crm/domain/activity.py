from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_KINDS = {"comment", "task", "call"}
VALID_SUBJECT_TYPES = {"lead", "partner", "opportunity"}


@dataclass(frozen=True)
class Activity:
    id: str
    kind: str
    subject_type: str
    subject_id: str
    note: str
    due_at: str | None
    completed_at: str | None


def validate_activity(*, kind: str, subject_type: str, note: str) -> Result[None]:
    if kind not in VALID_KINDS:
        return Err("INVALID_KIND", f"kind must be one of {sorted(VALID_KINDS)}")
    if subject_type not in VALID_SUBJECT_TYPES:
        return Err("INVALID_SUBJECT_TYPE", f"subject_type must be one of {sorted(VALID_SUBJECT_TYPES)}")
    if not note.strip():
        return Err("EMPTY_NOTE", "note is required")
    return Ok(None)

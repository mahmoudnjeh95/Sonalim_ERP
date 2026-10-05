from __future__ import annotations

from datetime import date

from core.domain.result import Err, Ok, Result

LEAVE_STATUSES = {"pending", "approved", "rejected", "cancelled"}


def validate_leave(*, start_date: date, end_date: date, status: str = "pending") -> Result[None]:
    if end_date < start_date:
        return Err(
            "INVALID_DATES", "leave end date cannot be before its start date", "la date de fin du congé ne peut pas précéder sa date de début"
        )
    if status not in LEAVE_STATUSES:
        return Err(
            "INVALID_STATUS", f"status must be one of {sorted(LEAVE_STATUSES)}", f"status doit être l'un de {sorted(LEAVE_STATUSES)}"
        )
    return Ok(None)

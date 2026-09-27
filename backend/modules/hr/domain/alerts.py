"""How far ahead HR is warned. Every horizon is a setting HR records (hr.settings); with none set,
nothing is judged "expiring". Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Mapping

from core.domain.result import Err, Ok, Result

HORIZON_KEYS = ("contract_expiry_horizon_days", "trial_end_horizon_days", "document_expiry_horizon_days")


def validate_horizons(horizons: Mapping[str, int | None], *, today: datetime.date | None = None) -> Result[dict]:
    day = today or datetime.date.today()
    clean: dict[str, int | None] = {}
    for key in HORIZON_KEYS:
        value = horizons.get(key)
        if value is not None and value <= 0:
            return Err(
                "INVALID_SETTING",
                "an alert horizon is a number of days above 0, or empty",
                "un horizon d'alerte est un nombre de jours supérieur à 0, ou vide",
            )
        # No invented cap: refuse only what genuinely cannot be a date (today + horizon
        # overflows datetime.date.max), rather than picking an arbitrary number of days.
        if value is not None:
            try:
                day + datetime.timedelta(days=value)
            except OverflowError:
                return Err(
                    "INVALID_SETTING",
                    "this alert horizon is too far in the future to be a date",
                    "cet horizon d'alerte est trop lointain pour être une date",
                )
        clean[key] = value
    return Ok(clean)


def window_end(today: datetime.date, days: int | None) -> datetime.date | None:
    """The last day inside the horizon, or None when no horizon is set. Never raises: a horizon
    that would overflow a real date clamps at the furthest date Python can represent (this can
    only be reached through a horizon saved before validate_horizons started refusing one that
    doesn't fit, since a fresh save is refused first)."""
    if days is None:
        return None
    try:
        return today + datetime.timedelta(days=days)
    except OverflowError:
        return datetime.date.max


def expiry_state(expires_on: datetime.date | None, today: datetime.date, horizon_days: int | None) -> str | None:
    """'expired' is a fact; 'expiring' needs a horizon HR has set; None when the paper never expires."""
    if expires_on is None:
        return None
    if expires_on < today:
        return "expired"
    end = window_end(today, horizon_days)
    if end is not None and expires_on <= end:
        return "expiring"
    return "valid"

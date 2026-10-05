"""Pure rules behind a machine's history (spec 2026-10-02-maintenance-history-design.md):
status intervals rebuilt from status changes, and every indicator formula.

No database. A figure that cannot be computed is None -- never infinity, never a guess.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err

UTC = datetime.timezone.utc

STOPPED_STATUSES = frozenset({"down", "maintenance"})
# The one production stop type that counts as a breakdown (a built-in code; admin-added types never do).
CORRECTIVE_STOP_TYPE = "corrective"
JOB_KINDS = ("preventive", "corrective")
JOURNAL_STATUSES = ("closed", "cancelled", "all")


@dataclass(frozen=True)
class StatusChange:
    at: datetime.datetime
    from_status: str
    to_status: str


@dataclass(frozen=True)
class Immobilisation:
    minutes: float
    episodes: int


def validate_period(date_from: datetime.date, date_to: datetime.date) -> Err | None:
    if date_from > date_to:
        return Err(
            "INVALID_PERIOD",
            f"the period starts ({date_from}) after it ends ({date_to})",
            f"la période commence ({date_from}) après sa fin ({date_to})",
        )
    return None


def validate_journal_filters(kind: str | None, status: str) -> Err | None:
    if kind is not None and kind not in JOB_KINDS:
        return Err("INVALID_FILTER", f"unknown job kind: {kind}", f"type d'intervention inconnu : {kind}")
    if status not in JOURNAL_STATUSES:
        return Err("INVALID_FILTER", f"unknown journal status: {status}", f"statut de journal inconnu : {status}")
    return None


def period_bounds(
    date_from: datetime.date, date_to: datetime.date, now: datetime.datetime
) -> tuple[datetime.datetime, datetime.datetime]:
    """`from 00:00Z` to `to + 1 day 00:00Z`, capped at now; a period still to come is empty."""
    start = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=UTC)
    end = datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=UTC)
    end = min(end, now)
    return start, max(start, end)


def chain_in_order(changes: list[StatusChange]) -> list[StatusChange]:
    """Oldest first. Changes made in one transaction share their timestamp (NOW()) and their
    ids give no reliable order, so inside such a group the order follows the chain: each
    change starts from the status the previous one ended in."""
    by_time = sorted(changes, key=lambda change: change.at)
    ordered: list[StatusChange] = []
    index = 0
    while index < len(by_time):
        group = [c for c in by_time[index:] if c.at == by_time[index].at]
        index += len(group)
        current = ordered[-1].to_status if ordered else None
        while group:
            following = next((c for c in group if c.from_status == current), None)
            if following is None:
                # Nothing before it in the group: the change no other one leads into starts it.
                ends = {c.to_status for c in group}
                following = next((c for c in group if c.from_status not in ends), group[0])
            ordered.append(following)
            group.remove(following)
            current = following.to_status
    return ordered


def status_at_start(changes: list[StatusChange], start: datetime.datetime, current_status: str) -> str:
    """`changes` oldest first. The last change before the period; else the first change's
    starting status; else the machine never changed and is still in its current status."""
    before = [c for c in changes if c.at < start]
    if before:
        return before[-1].to_status
    if changes:
        return changes[0].from_status
    return current_status


def immobilisation(
    changes: list[StatusChange], start: datetime.datetime, end: datetime.datetime, current_status: str
) -> Immobilisation:
    """Minutes in `down` or `maintenance` within [start, end), and the stretches of it
    (an episode runs from leaving `operational` to coming back; down -> maintenance is one,
    and so is an `operational` that lasted no time at all, as when a cancel passes through it).
    `changes` in chain order (`chain_in_order`)."""
    stopped_since = start if status_at_start(changes, start, current_status) in STOPPED_STATUSES else None
    episodes = 1 if stopped_since is not None else 0
    minutes = 0.0
    released_at: datetime.datetime | None = None
    for change in changes:
        if not (start <= change.at < end):
            continue
        now_stopped = change.to_status in STOPPED_STATUSES
        if stopped_since is not None and not now_stopped:
            minutes += (change.at - stopped_since).total_seconds() / 60
            stopped_since = None
            released_at = change.at
        elif stopped_since is None and now_stopped:
            stopped_since = change.at
            if released_at != change.at:
                episodes += 1
    if stopped_since is not None:
        minutes += (end - stopped_since).total_seconds() / 60
    return Immobilisation(minutes=minutes, episodes=episodes)


def ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _grouped(stops: list[dict], field: str, name: str) -> list[dict]:
    groups: dict[str | None, tuple[int, int]] = {}
    for stop in stops:
        count, minutes = groups.get(stop[field], (0, 0))
        groups[stop[field]] = (count + 1, minutes + stop["minutes"])
    rows = [{name: key, "count": count, "minutes": minutes} for key, (count, minutes) in groups.items()]
    return sorted(rows, key=lambda row: (-row["minutes"], str(row[name])))


def production_block(stops: list[dict], running_minutes: int) -> dict:
    """One machine's production figures from its stops (`minutes`, `downtime_type`,
    `classification`) and its running minutes, both for validated shifts of the period."""
    breakdowns = [stop for stop in stops if stop["downtime_type"] == CORRECTIVE_STOP_TYPE]
    breakdown_minutes = sum(stop["minutes"] for stop in breakdowns)
    return {
        "stops": len(stops),
        "stop_minutes": sum(stop["minutes"] for stop in stops),
        "stops_by_type": _grouped(stops, "downtime_type", "type"),
        "breakdowns": len(breakdowns),
        "breakdown_minutes": breakdown_minutes,
        "breakdowns_by_system": _grouped(breakdowns, "classification", "classification"),
        "running_minutes": running_minutes,
        "mtbf_minutes": ratio(running_minutes, len(breakdowns)),
        "mttr_minutes": ratio(breakdown_minutes, len(breakdowns)),
    }


def maintenance_block(
    *,
    breakdowns: int,
    due: int,
    closed: int,
    closed_on_time: int,
    overdue: int,
    stopped: Immobilisation,
    calendar_minutes: float,
    technician_seconds: int,
    issued_lines: int,
    purchase_lines: int,
    parts_cost: float | None,
    parts_unvalued_quantity: float | None,
    status_changes: int,
) -> dict:
    return {
        "breakdowns": breakdowns,
        "preventive": {"due": due, "closed": closed, "closed_on_time": closed_on_time, "overdue": overdue},
        "immobilised_minutes": stopped.minutes,
        "immobilisations": stopped.episodes,
        "mean_immobilisation_minutes": ratio(stopped.minutes, stopped.episodes),
        "calendar_minutes": calendar_minutes,
        # "calendaire": maintenance records no running time, so the period's clock stands in.
        "calendar_mtbf_minutes": ratio(max(calendar_minutes - stopped.minutes, 0.0), breakdowns),
        "technician_seconds": technician_seconds,
        "parts": {"issued_lines": issued_lines, "purchase_lines": purchase_lines},
        "parts_cost": parts_cost,
        "parts_unvalued_quantity": parts_unvalued_quantity,
        "status_changes": status_changes,
    }


def outcome_counts(latest_outcomes: list[str], checks_total: int) -> dict[str, int]:
    """The latest outcome of each recorded check; a check with no entry yet is pending."""
    return {
        "ok": latest_outcomes.count("ok"),
        "issue": latest_outcomes.count("issue"),
        "not_done": latest_outcomes.count("not_done"),
        "pending": max(checks_total - len(latest_outcomes), 0),
    }

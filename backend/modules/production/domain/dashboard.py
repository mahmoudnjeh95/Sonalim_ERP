"""Rules behind the production dashboard: which shift is running, what colour a
line is, and what "the previous period" means.

Nothing here has a threshold of its own. A line's colour is read off a recorded
OF status and recorded machine statuses; a change against the previous period is
a direction at display precision, never a verdict; the shift clock times are
whatever the plant configured, so an unconfigured tenant simply has no current
shift instead of a guessed one.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

# Which store finished product waits in, and which it is released into.
STORE_ROLES = ("line", "final")

# How an OF is shown on its line. `suspended`: the OF is paused, so machine
# states say nothing about production. A line with no open OF is not shown.
LINE_STATES = ("running", "maintenance", "down", "suspended")


@dataclass(frozen=True)
class ShiftWindow:
    shift: str
    start: datetime.time
    end: datetime.time


def validate_shift_window(*, shift: str, start: datetime.time, end: datetime.time) -> Result[None]:
    if not shift.strip():
        return Err("INVALID_SHIFT", "a shift window needs the shift's name")
    if start == end:
        # Equal times are either no time at all or a full day; a shift is neither.
        return Err("INVALID_TIME_RANGE", "a shift must start and end at different times")
    return Ok(None)


def shift_length_minutes(window: ShiftWindow) -> int:
    """How long a shift runs, in minutes. A window whose end is before its start runs
    through midnight (22:00 to 07:00 is nine hours), which is what the modulo is for."""
    start = window.start.hour * 60 + window.start.minute
    end = window.end.hour * 60 + window.end.minute
    return (end - start) % (24 * 60)


def current_shift(windows: list[ShiftWindow], at: datetime.time) -> ShiftWindow | None:
    """The shift whose window contains `at`, or None when nothing is configured
    for that time.

    A window is start-inclusive and end-exclusive, so the handover minute belongs
    to the incoming shift. A window whose end is before its start runs through
    midnight (23:00 to 07:00).
    """
    for window in windows:
        if window.start < window.end:
            if window.start <= at < window.end:
                return window
        elif at >= window.start or at < window.end:
            return window
    return None


def line_state(*, of_status: str, machine_statuses: list[str]) -> str:
    """The colour of one open OF on its line.

    Green while the OF is ongoing; yellow when a machine on the line is in
    maintenance; red when one is down. Red outranks yellow, so a line with one
    machine in maintenance and another down reads as down.
    """
    if of_status == "suspended":
        return "suspended"
    if "down" in machine_statuses:
        return "down"
    if "maintenance" in machine_statuses:
        return "maintenance"
    return "running"


def previous_period(date_from: datetime.date, date_to: datetime.date) -> tuple[datetime.date, datetime.date]:
    """The equal-length window immediately before [date_from, date_to]."""
    length = (date_to - date_from).days + 1
    previous_to = date_from - datetime.timedelta(days=1)
    return previous_to - datetime.timedelta(days=length - 1), previous_to


def direction(current: float, previous: float | None, *, decimals: int) -> str | None:
    """up / down / flat, compared at the precision the figure is displayed at.

    Comparing raw floats would report "up" for a change nobody can see on screen.
    None when there is nothing to compare against.
    """
    if previous is None:
        return None
    now, before = round(current, decimals), round(previous, decimals)
    if now > before:
        return "up"
    if now < before:
        return "down"
    return "flat"


def team_rotation_schedule(
    *, shifts: list[str], rotation: list[tuple[str, datetime.date, int]], date: datetime.date
) -> list[dict]:
    """Where each team in the 4-team rotation stands on `date`: which of
    `shifts` it is on, or `None` when it is that team's turn to rest.

    `shifts` are the plant's configured shifts, in cycle order (stop 0 is the
    first shift of the day, `len(shifts)` is Rest) -- callers pass them sorted
    by start time, the same order the rest of the board already sorts shifts
    in. `rotation` is one `(team, anchor_date, anchor_stop)` per team:
    `anchor_stop` is where that team stood in the cycle on `anchor_date`. Every
    team advances one stop for every day that passes (or goes back one for
    every day before `anchor_date`); the whole calendar is built from that one
    recorded anchor, nothing else is guessed.
    """
    stops = len(shifts) + 1
    schedule = []
    for team, anchor_date, anchor_stop in rotation:
        stop = (anchor_stop + (date - anchor_date).days) % stops
        schedule.append({"team": team, "shift": shifts[stop] if stop < len(shifts) else None})
    return schedule


def validate_team_rotation(entries: list[dict], *, num_shifts: int) -> Result[None]:
    """A plant-wide team rotation needs exactly one team per stop in the cycle:
    one for each configured shift, plus one resting. Every team shares the same
    anchor date; nothing here guesses at a team name or a stop left out."""
    stops = num_shifts + 1
    if len(entries) != stops:
        return Err("WRONG_TEAM_COUNT", f"the rotation needs exactly {stops} teams (one per shift, plus rest)")
    anchor_dates = {entry["anchor_date"] for entry in entries}
    if len(anchor_dates) != 1:
        return Err("INVALID_ENTRY", "every team must share the same anchor date")
    seen_teams: set[str] = set()
    seen_stops: set[int] = set()
    for entry in entries:
        team = entry["team"].strip()
        stop = entry["anchor_stop"]
        if not team:
            return Err("INVALID_ENTRY", "a rotation entry needs a team")
        if not (0 <= stop < stops):
            return Err("INVALID_ENTRY", f"anchor_stop must be between 0 and {stops - 1}")
        key = team.lower()
        if key in seen_teams:
            return Err("DUPLICATE_ENTRY", f"team {team!r} appears twice")
        seen_teams.add(key)
        if stop in seen_stops:
            return Err("DUPLICATE_ENTRY", f"two teams share stop {stop}")
        seen_stops.add(stop)
    return Ok(None)

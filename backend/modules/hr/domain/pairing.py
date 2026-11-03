"""Turning clock punches into worked days: the pairing engine.

Pure: no database. Rules, each pinned by test_pairing.py:

* Punches of the same second, or of the same direction within `dedupe_seconds`, are one punch.
* A punch belongs to the shift of its own date or of the date before whose window, widened
  by `attach_minutes` on both sides, contains it; when both do, the nearer one (an `in`
  measured to the shift start, an `out` to its end, an `unknown` to either). A punch no
  shift claims belongs to its calendar date (work on a rest day). A night shift therefore
  keeps its morning out-punch: the 23-07 shift of the 3rd owns the 07:00 punch of the 4th.
* Within one day, punches pair in time order: `in` opens, `out` closes, `unknown` does
  whichever is due. An `in` while one is open, or one left open at the end, is MISSING_OUT;
  an `out` with nothing open is MISSING_IN. Unpaired punches add no time, and a forgotten
  punch never shifts the pairing of another day.
* Worked minutes are the paired time less the schedule break (on a working day). Lateness
  is the first arrival (an `in` or `unknown` punch) after the shift start, beyond the grace
  minutes; a day with only an out-punch has no measurable lateness.
* On a working day, worked minutes beyond the scheduled ones are overtime; the part of it
  outside the shift window and inside the night window is night overtime, the rest day
  overtime. On a rest day or a public holiday every worked minute is rest/holiday overtime.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from modules.hr.domain.schedule import ONE_DAY, ShiftWindow, minutes_between, night_overlap_minutes

Interval = tuple[datetime.datetime, datetime.datetime]


@dataclass(frozen=True)
class Punch:
    punched_at: datetime.datetime
    direction: str = "unknown"  # 'in' | 'out' | 'unknown'


@dataclass(frozen=True)
class PairingConfig:
    night_start_minute: int
    night_end_minute: int
    attach_minutes: int
    dedupe_seconds: int = 0
    late_grace_minutes: int = 0


@dataclass(frozen=True)
class WorkDay:
    work_date: datetime.date
    window: ShiftWindow | None  # None: a rest day (or no schedule)
    is_holiday: bool = False
    in_range: bool = True  # False: a neighbouring day loaded only so its punches are not misplaced


@dataclass(frozen=True)
class DayResult:
    work_date: datetime.date
    status: str
    scheduled_minutes: int = 0
    worked_minutes: int = 0
    late_minutes: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    ot_minutes_rest_holiday: int = 0
    night_minutes: int = 0
    first_punch: datetime.datetime | None = None
    last_punch: datetime.datetime | None = None
    anomalies: tuple[str, ...] = ()


@dataclass(frozen=True)
class PairingResult:
    days: list[DayResult]
    duplicate_punches: int
    outside_range_punches: int


def dedupe(punches: list[Punch], dedupe_seconds: int) -> tuple[list[Punch], int]:
    kept: list[Punch] = []
    dropped = 0
    for punch in sorted(punches, key=lambda p: p.punched_at):
        if kept:
            previous = kept[-1]
            gap = (punch.punched_at - previous.punched_at).total_seconds()
            if gap == 0 or (gap <= dedupe_seconds and punch.direction == previous.direction):
                dropped += 1
                continue
        kept.append(punch)
    return kept, dropped


def _distance(punch: Punch, window: ShiftWindow) -> int:
    to_start = abs(minutes_between(window.start, punch.punched_at))
    to_end = abs(minutes_between(window.end, punch.punched_at))
    if punch.direction == "in":
        return to_start
    if punch.direction == "out":
        return to_end
    return min(to_start, to_end)


def attribute(punch: Punch, work_days: dict[datetime.date, WorkDay], attach_minutes: int) -> datetime.date:
    attach = datetime.timedelta(minutes=attach_minutes)
    moment = punch.punched_at
    best: tuple[int, int, datetime.date] | None = None
    for day in (moment.date() - ONE_DAY, moment.date()):
        work_day = work_days.get(day)
        if work_day is None or work_day.window is None:
            continue
        window = work_day.window
        if not window.start - attach <= moment <= window.end + attach:
            continue
        candidate = (_distance(punch, window), -day.toordinal(), day)  # nearer first, then the later day
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best is not None else moment.date()


def pair_group(punches: list[Punch]) -> tuple[list[Interval], list[str]]:
    intervals: list[Interval] = []
    anomalies: list[str] = []
    opened: datetime.datetime | None = None
    for punch in sorted(punches, key=lambda p: p.punched_at):
        direction = punch.direction
        if direction == "unknown":
            direction = "out" if opened is not None else "in"
        if direction == "in":
            if opened is not None:
                anomalies.append("MISSING_OUT")
            opened = punch.punched_at
        elif opened is None:
            anomalies.append("MISSING_IN")
        else:
            intervals.append((opened, punch.punched_at))
            opened = None
    if opened is not None:
        anomalies.append("MISSING_OUT")
    return intervals, anomalies


def _outside(start: datetime.datetime, end: datetime.datetime, window: ShiftWindow) -> list[Interval]:
    segments = []
    if start < window.start:
        segments.append((start, min(end, window.start)))
    if end > window.end:
        segments.append((max(start, window.end), end))
    return [(a, b) for a, b in segments if b > a]


def compute_day(work_day: WorkDay, punches: list[Punch], config: PairingConfig) -> DayResult:
    window = work_day.window
    expected = window is not None and not work_day.is_holiday
    scheduled = window.scheduled_minutes if expected else 0
    if not punches:
        if window is not None and work_day.is_holiday:
            status = "holiday"
        else:
            status = "absent" if expected else "rest"
        return DayResult(work_date=work_day.work_date, status=status, scheduled_minutes=scheduled)
    ordered = sorted(punches, key=lambda p: p.punched_at)
    intervals, anomalies = pair_group(ordered)
    night = (config.night_start_minute, config.night_end_minute)
    raw = sum(minutes_between(start, end) for start, end in intervals)
    worked = raw - (min(window.break_minutes, raw) if expected else 0)
    night_minutes = sum(night_overlap_minutes(start, end, *night) for start, end in intervals)
    arrivals = [punch.punched_at for punch in ordered if punch.direction != "out"]
    late = ot_day = ot_night = ot_rest_holiday = 0
    if expected:
        if arrivals:
            delay = minutes_between(window.start, arrivals[0])
            late = delay if delay > config.late_grace_minutes else 0
        extra = max(0, worked - scheduled)
        outside = [segment for start, end in intervals for segment in _outside(start, end, window)]
        night_outside = sum(night_overlap_minutes(start, end, *night) for start, end in outside)
        ot_night = min(night_outside, extra)
        ot_day = extra - ot_night
    else:
        ot_rest_holiday = worked
    return DayResult(
        work_date=work_day.work_date,
        status="late" if late > 0 else "present",
        scheduled_minutes=scheduled,
        worked_minutes=worked,
        late_minutes=late,
        ot_minutes_day=ot_day,
        ot_minutes_night=ot_night,
        ot_minutes_rest_holiday=ot_rest_holiday,
        night_minutes=night_minutes,
        first_punch=ordered[0].punched_at,
        last_punch=ordered[-1].punched_at,
        anomalies=tuple(anomalies),
    )


def pair_punches(punches: list[Punch], work_days: list[WorkDay], config: PairingConfig) -> PairingResult:
    """One DayResult per in-range work day; punches owned by a context day are counted, not used."""
    kept, duplicates = dedupe(punches, config.dedupe_seconds)
    by_date = {work_day.work_date: work_day for work_day in work_days}
    groups: dict[datetime.date, list[Punch]] = {day: [] for day in by_date}
    outside = 0
    for punch in kept:
        day = attribute(punch, by_date, config.attach_minutes)
        if day in by_date and by_date[day].in_range:
            groups[day].append(punch)
        else:
            outside += 1
    days = [compute_day(by_date[day], groups[day], config) for day in sorted(by_date) if by_date[day].in_range]
    return PairingResult(days=days, duplicate_punches=duplicates, outside_range_punches=outside)

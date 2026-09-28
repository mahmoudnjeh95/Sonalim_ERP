"""Work schedules, weekly rotations and the minute arithmetic presence is built on.

Pure: no database, no clock. Times of day are minutes after local midnight (0..1439).
A shift whose end is not after its start crosses midnight and belongs to the day it
starts on: the 23-07 shift of 3 August is 3 August's shift, although most of it is
worked on the 4th. Weekdays follow datetime.date.weekday(): Monday = 0 ... Sunday = 6.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

MINUTES_PER_DAY = 1440
ONE_DAY = datetime.timedelta(days=1)
_COUNTRY = re.compile(r"^[A-Z]{2}$")


def minutes_between(start: datetime.datetime, end: datetime.datetime) -> int:
    """Whole minutes from `start` to `end`, truncated toward zero (negative when `end` is earlier)."""
    return int((end - start).total_seconds() / 60)


def date_range(first: datetime.date, last: datetime.date) -> list[datetime.date]:
    return [first + datetime.timedelta(days=offset) for offset in range((last - first).days + 1)]


@dataclass(frozen=True)
class ScheduleDay:
    weekday: int
    start_minute: int
    end_minute: int
    break_minutes: int = 0

    @property
    def span_minutes(self) -> int:
        return (self.end_minute - self.start_minute) % MINUTES_PER_DAY


@dataclass(frozen=True)
class Schedule:
    id: str
    code: str
    days: tuple[ScheduleDay, ...]
    is_night: bool = False

    def day(self, weekday: int) -> ScheduleDay | None:
        return next((day for day in self.days if day.weekday == weekday), None)


@dataclass(frozen=True)
class ShiftWindow:
    work_date: datetime.date
    start: datetime.datetime
    end: datetime.datetime
    break_minutes: int
    schedule_id: str

    @property
    def scheduled_minutes(self) -> int:
        return minutes_between(self.start, self.end) - self.break_minutes


def shift_window(schedule: Schedule, work_date: datetime.date) -> ShiftWindow | None:
    """The shift `schedule` plans on `work_date`, or None on a rest day."""
    day = schedule.day(work_date.weekday())
    if day is None:
        return None
    start = datetime.datetime.combine(work_date, datetime.time()) + datetime.timedelta(minutes=day.start_minute)
    return ShiftWindow(
        work_date=work_date,
        start=start,
        end=start + datetime.timedelta(minutes=day.span_minutes),
        break_minutes=day.break_minutes,
        schedule_id=schedule.id,
    )


def validate_schedule(*, code: str, name: str, days: list[ScheduleDay]) -> Result[None]:
    if not code.strip() or not name.strip():
        return Err("INVALID_SCHEDULE", "schedule code and name are required", "le code et le nom de l'horaire sont obligatoires")
    if not days:
        return Err("INVALID_SCHEDULE", "a schedule needs at least one working day", "un horaire doit avoir au moins un jour travaillé")
    weekdays = [day.weekday for day in days]
    if len(set(weekdays)) != len(weekdays):
        return Err("INVALID_SCHEDULE", "a weekday appears twice in the schedule", "un jour de la semaine apparaît deux fois dans l'horaire")
    for day in days:
        if not 0 <= day.weekday <= 6:
            return Err("INVALID_SCHEDULE", "weekday must be between 0 (Monday) and 6 (Sunday)", "le jour doit être compris entre 0 (lundi) et 6 (dimanche)")
        if not (0 <= day.start_minute < MINUTES_PER_DAY and 0 <= day.end_minute < MINUTES_PER_DAY):
            return Err("INVALID_SCHEDULE", "start and end must be times of day", "le début et la fin doivent être des heures de la journée")
        if day.span_minutes == 0:
            return Err("INVALID_SCHEDULE", "a working day cannot start and end at the same time", "une journée de travail ne peut pas commencer et finir à la même heure")
        if not 0 <= day.break_minutes < day.span_minutes:
            return Err("INVALID_SCHEDULE", "the break must be shorter than the shift", "la pause doit être plus courte que le poste")
    return Ok(None)


@dataclass(frozen=True)
class RotationPattern:
    id: str
    anchor_date: datetime.date
    schedule_ids: tuple[str, ...]


def validate_rotation(*, code: str, name: str, anchor_date: datetime.date, schedule_ids: list[str]) -> Result[None]:
    if not code.strip() or not name.strip():
        return Err("INVALID_ROTATION", "rotation code and name are required", "le code et le nom du roulement sont obligatoires")
    if anchor_date.weekday() != 0:
        return Err("INVALID_ROTATION", "week 1 of a rotation starts on a Monday", "la semaine 1 d'un roulement commence un lundi")
    if not schedule_ids:
        return Err("INVALID_ROTATION", "a rotation needs at least one weekly schedule", "un roulement doit avoir au moins un horaire hebdomadaire")
    return Ok(None)


def rotation_schedule_id(pattern: RotationPattern, work_date: datetime.date, offset_weeks: int = 0) -> str:
    """The schedule of the week `work_date` falls in; `offset_weeks` staggers teams on one pattern."""
    monday = work_date - datetime.timedelta(days=work_date.weekday())
    weeks = (monday - pattern.anchor_date).days // 7
    return pattern.schedule_ids[(weeks + offset_weeks) % len(pattern.schedule_ids)]


@dataclass(frozen=True)
class Assignment:
    id: str
    employee_id: str
    valid_from: datetime.date
    valid_to: datetime.date | None
    schedule_id: str | None = None
    rotation_pattern_id: str | None = None
    rotation_offset_weeks: int = 0

    def covers(self, day: datetime.date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)


def validate_assignment(
    *,
    valid_from: datetime.date,
    valid_to: datetime.date | None,
    schedule_id: str | None,
    rotation_pattern_id: str | None,
    rotation_offset_weeks: int,
    others: list[Assignment],
) -> Result[None]:
    if (schedule_id is None) == (rotation_pattern_id is None):
        return Err("INVALID_ASSIGNMENT", "give either a schedule or a rotation", "indiquez soit un horaire, soit un roulement")
    if valid_to is not None and valid_to < valid_from:
        return Err("INVALID_ASSIGNMENT", "the end date cannot precede the start date", "la date de fin ne peut pas précéder la date de début")
    if rotation_offset_weeks < 0:
        return Err("INVALID_ASSIGNMENT", "the team offset cannot be negative", "le décalage d'équipe ne peut pas être négatif")
    far = datetime.date.max
    for other in others:
        if other.valid_from <= (valid_to or far) and valid_from <= (other.valid_to or far):
            return Err(
                "ASSIGNMENT_OVERLAP",
                "the employee already has a schedule on part of these dates",
                "l'employé a déjà un horaire sur une partie de ces dates",
            )
    return Ok(None)


def resolve_schedule_id(assignments: list[Assignment], patterns: dict[str, RotationPattern], day: datetime.date) -> str | None:
    for assignment in assignments:
        if not assignment.covers(day):
            continue
        if assignment.schedule_id is not None:
            return assignment.schedule_id
        pattern = patterns.get(assignment.rotation_pattern_id or "")
        return rotation_schedule_id(pattern, day, assignment.rotation_offset_weeks) if pattern else None
    return None


@dataclass(frozen=True)
class ResolvedDay:
    work_date: datetime.date
    assigned: bool
    schedule_id: str | None = None
    schedule_code: str | None = None
    window: ShiftWindow | None = None

    @property
    def is_working_day(self) -> bool:
        return self.window is not None


def resolve_days(
    *,
    assignments: list[Assignment],
    patterns: dict[str, RotationPattern],
    schedules: dict[str, Schedule],
    dates: list[datetime.date],
) -> dict[datetime.date, ResolvedDay]:
    resolved: dict[datetime.date, ResolvedDay] = {}
    for day in dates:
        schedule_id = resolve_schedule_id(assignments, patterns, day)
        schedule = schedules.get(schedule_id) if schedule_id else None
        if schedule is None:
            resolved[day] = ResolvedDay(work_date=day, assigned=False)
        else:
            resolved[day] = ResolvedDay(
                work_date=day,
                assigned=True,
                schedule_id=schedule.id,
                schedule_code=schedule.code,
                window=shift_window(schedule, day),
            )
    return resolved


def night_overlap_minutes(
    start: datetime.datetime, end: datetime.datetime, night_start_minute: int, night_end_minute: int
) -> int:
    """Minutes of [start, end) inside the nightly window, which may cross midnight."""
    span = (night_end_minute - night_start_minute) % MINUTES_PER_DAY
    if end <= start or span == 0:
        return 0
    total = 0
    day = start.date() - ONE_DAY
    while datetime.datetime.combine(day, datetime.time()) < end:
        night_from = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=night_start_minute)
        night_to = night_from + datetime.timedelta(minutes=span)
        total += max(0, minutes_between(max(start, night_from), min(end, night_to)))
        day += ONE_DAY
    return total


def validate_holiday(*, country_code: str, name: str) -> Result[None]:
    if not _COUNTRY.match(country_code):
        return Err("INVALID_HOLIDAY", "the country is a two-letter code such as ML", "le pays est un code à deux lettres comme ML")
    if not name.strip():
        return Err("INVALID_HOLIDAY", "the holiday name is required", "le nom du jour férié est obligatoire")
    return Ok(None)


def validate_presence_settings(
    *,
    night_start_minute: int | None,
    night_end_minute: int | None,
    punch_attach_minutes: int | None,
    punch_dedupe_seconds: int | None,
    late_grace_minutes: int | None,
) -> Result[None]:
    if (night_start_minute is None) != (night_end_minute is None):
        return Err("INVALID_SETTINGS", "give both ends of the night-work window, or neither", "indiquez les deux bornes de la plage de nuit, ou aucune")
    for value in (night_start_minute, night_end_minute):
        if value is not None and not 0 <= value < MINUTES_PER_DAY:
            return Err("INVALID_SETTINGS", "the night-work window uses times of day", "la plage de nuit se compose d'heures de la journée")
    if night_start_minute is not None and night_start_minute == night_end_minute:
        return Err("INVALID_SETTINGS", "the night-work window cannot start and end at the same time", "la plage de nuit ne peut pas commencer et finir à la même heure")
    for value in (punch_attach_minutes, punch_dedupe_seconds, late_grace_minutes):
        if value is not None and value < 0:
            return Err("INVALID_SETTINGS", "settings cannot be negative", "les paramètres ne peuvent pas être négatifs")
    return Ok(None)

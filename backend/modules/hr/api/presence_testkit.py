"""Shared set-up for the phase-2 integration tests (presence, clock, leave, month close).

A test module imports the fixture by name:
    from modules.hr.api.presence_testkit import presence_env  # noqa: F401
Every write goes through the `db` fixture's connection, which rolls back after each test.
The minute values below are test inputs, not the plant's settings (those are rows HR
confirms; the dev seed writes drafts).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.schedule_service import PresenceSettingsService, ScheduleService
from modules.hr.domain.presence import ManualEntry

TENANT = "integration-test-presence"
AUG_1 = datetime.date(2026, 8, 1)
AUG_3 = datetime.date(2026, 8, 3)  # a Monday
DAY_SHIFT = [{"weekday": w, "start_minute": 420, "end_minute": 900, "break_minutes": 0} for w in range(6)]
NIGHT_SHIFT = [{"weekday": w, "start_minute": 1380, "end_minute": 420, "break_minutes": 0} for w in range(6)]

_ROW_KEYS = (
    "status", "source", "scheduled_minutes", "worked_minutes", "late_minutes", "ot_minutes_day",
    "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "justified", "locked", "leave_request_id",
)


@dataclass(frozen=True)
class PresenceEnv:
    actor: str
    department: str
    day_schedule: str
    night_schedule: str
    day_worker: str
    night_worker: str


def add_employee(
    db,
    *,
    employee_no: str,
    department: str,
    hire_date: datetime.date = datetime.date(2026, 1, 1),
    termination_date: datetime.date | None = None,
    badge_no: str | None = None,
) -> str:
    employee_id = str(ULID())
    db.execute(
        """
        INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, department_id,
                                  hire_date, termination_date, badge_no)
        VALUES (%s, %s, %s, 'Test', %s, %s, %s, %s, %s)
        """,
        (employee_id, TENANT, employee_no, employee_no, department, hire_date, termination_date, badge_no),
    )
    return employee_id


def presence_row(db, employee_id: str, work_date: datetime.date) -> dict | None:
    row = db.execute(
        f"SELECT {', '.join(_ROW_KEYS)} FROM hr.presence_days WHERE tenant_id = %s AND employee_id = %s AND work_date = %s",
        (TENANT, employee_id, work_date),
    ).fetchone()
    return dict(zip(_ROW_KEYS, row)) if row else None


def insert_presence_row(
    db,
    *,
    employee_id: str,
    work_date: datetime.date,
    status: str,
    source: str,
    worked_minutes: int = 0,
    leave_request_id: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO hr.presence_days (id, tenant_id, employee_id, work_date, status, source, worked_minutes, leave_request_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (str(ULID()), TENANT, employee_id, work_date, status, source, worked_minutes, leave_request_id),
    )


def close_month_directly(db, period: datetime.date) -> None:
    db.execute(
        """
        INSERT INTO hr.presence_months (tenant_id, period, status) VALUES (%s, %s, 'closed')
        ON CONFLICT (tenant_id, period) DO UPDATE SET status = 'closed'
        """,
        (TENANT, period),
    )


@pytest.fixture
def presence_env(db) -> PresenceEnv:
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    department = str(ULID())
    db.execute(
        "INSERT INTO hr.departments (id, tenant_id, code, name) VALUES (%s, %s, 'PROD', 'Production')",
        (department, TENANT),
    )
    settings = PresenceSettingsService(db).update(
        tenant_id=TENANT, actor_id=actor, night_start_minute=1260, night_end_minute=300,
        punch_attach_minutes=240, punch_dedupe_seconds=60, late_grace_minutes=0,
    )
    assert isinstance(settings, Ok), settings
    schedules = ScheduleService(db)
    day = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="JOUR", name="Jour 07-15", is_night=False, days=DAY_SHIFT)
    night = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="NUIT", name="Nuit 23-07", is_night=True, days=NIGHT_SHIFT)
    assert isinstance(day, Ok) and isinstance(night, Ok)
    day_worker = add_employee(db, employee_no="P-001", department=department, badge_no="B001")
    night_worker = add_employee(db, employee_no="P-002", department=department, badge_no="B002")
    for employee_id, schedule_id in ((day_worker, day.value["id"]), (night_worker, night.value["id"])):
        assigned = schedules.create_assignment(
            tenant_id=TENANT, actor_id=actor, employee_id=employee_id,
            valid_from=datetime.date(2026, 1, 1), schedule_id=schedule_id,
        )
        assert isinstance(assigned, Ok), assigned
    return PresenceEnv(
        actor=actor, department=department, day_schedule=day.value["id"], night_schedule=night.value["id"],
        day_worker=day_worker, night_worker=night_worker,
    )


def fill_month(db, env: PresenceEnv, period: datetime.date) -> None:
    """Saves 'present' on every working day of both test workers that has no row yet (public holidays left alone)."""
    presence = PresenceService(db)
    entries: list[ManualEntry] = []
    for employee_id in (env.day_worker, env.night_worker):
        month = presence.employee_month(tenant_id=TENANT, employee_id=employee_id, period=period).value
        entries += [
            ManualEntry(employee_id=employee_id, work_date=datetime.date.fromisoformat(day["work_date"]), status="present")
            for day in month["days"]
            if day["default_status"] == "present" and day["record"] is None
        ]
    saved = presence.save_days(tenant_id=TENANT, actor_id=env.actor, entries=entries)
    assert isinstance(saved, Ok), saved

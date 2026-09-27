"""Schedules, rotations, assignments, holidays and presence settings against a real database."""
from __future__ import annotations

import datetime

from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.presence_testkit import AUG_3, DAY_SHIFT, TENANT, add_employee, presence_env  # noqa: F401
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService

EVENING_SHIFT = [{"weekday": w, "start_minute": 900, "end_minute": 1380, "break_minutes": 0} for w in range(6)]


def _audits(db, action: str) -> int:
    return db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = %s", (TENANT, action)).fetchone()[0]


def test_a_schedule_is_listed_with_its_days_and_edited_with_an_audit_trail(db, presence_env):
    service = ScheduleService(db)
    listed = {s["code"]: s for s in service.list_schedules(tenant_id=TENANT)}
    assert [d["weekday"] for d in listed["JOUR"]["days"]] == [0, 1, 2, 3, 4, 5]
    updated = service.update_schedule(
        tenant_id=TENANT, actor_id=presence_env.actor, schedule_id=presence_env.day_schedule, name="Jour",
        days=[{"weekday": 0, "start_minute": 480, "end_minute": 960, "break_minutes": 30}],
    )
    assert isinstance(updated, Ok)
    assert updated.value["name"] == "Jour"
    assert updated.value["days"] == [{"weekday": 0, "start_minute": 480, "end_minute": 960, "break_minutes": 30}]
    assert _audits(db, "work_schedule.created") == 2 and _audits(db, "work_schedule.updated") == 1


def test_a_schedule_code_is_unique_per_tenant(db, presence_env):
    result = ScheduleService(db).create_schedule(tenant_id=TENANT, actor_id=presence_env.actor, code="JOUR", name="Autre", is_night=False, days=DAY_SHIFT)
    assert isinstance(result, Err) and result.code == "DUPLICATE_CODE" and result.message_fr


def test_a_rotation_resolves_week_by_week_and_a_night_stays_on_its_start_day(db, presence_env):
    service = ScheduleService(db)
    evening = service.create_schedule(tenant_id=TENANT, actor_id=presence_env.actor, code="SOIR", name="Soir 15-23", is_night=False, days=EVENING_SHIFT)
    rotation = service.create_rotation(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ROT3", name="3x8", anchor_date=AUG_3,
        schedule_ids=[presence_env.day_schedule, evening.value["id"], presence_env.night_schedule],
    )
    assert isinstance(rotation, Ok) and rotation.value["schedule_ids"][1] == evening.value["id"]
    worker = add_employee(db, employee_no="P-010", department=presence_env.department)
    assigned = service.create_assignment(
        tenant_id=TENANT, actor_id=presence_env.actor, employee_id=worker, valid_from=AUG_3,
        rotation_pattern_id=rotation.value["id"], rotation_offset_weeks=1,
    )
    assert isinstance(assigned, Ok) and assigned.value["rotation_code"] == "ROT3"
    days = service.resolve(tenant_id=TENANT, employee_ids=[worker], date_from=AUG_3, date_to=AUG_3 + datetime.timedelta(days=20))[worker]
    mondays = [AUG_3 + datetime.timedelta(weeks=w) for w in range(3)]
    assert [days[monday].schedule_code for monday in mondays] == ["SOIR", "NUIT", "JOUR"]
    night = days[mondays[1]].window
    assert night.work_date == mondays[1] and night.end.date() == mondays[1] + datetime.timedelta(days=1)


def test_a_rotation_anchor_must_be_a_monday(db, presence_env):
    result = ScheduleService(db).create_rotation(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ROT", name="Rotation",
        anchor_date=AUG_3 + datetime.timedelta(days=1), schedule_ids=[presence_env.day_schedule],
    )
    assert isinstance(result, Err) and result.code == "INVALID_ROTATION"


def test_overlaps_are_refused_and_an_assignment_can_switch_to_a_rotation_and_back_to_open_ended(db, presence_env):
    service = ScheduleService(db)
    overlap = service.create_assignment(tenant_id=TENANT, actor_id=presence_env.actor, employee_id=presence_env.day_worker, valid_from=AUG_3, schedule_id=presence_env.night_schedule)
    assert isinstance(overlap, Err) and overlap.code == "ASSIGNMENT_OVERLAP"
    current = service.list_assignments(tenant_id=TENANT, employee_id=presence_env.day_worker)[0]
    rotation = service.create_rotation(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ROT2", name="2x8", anchor_date=AUG_3,
        schedule_ids=[presence_env.day_schedule, presence_env.night_schedule],
    ).value
    switched = service.update_assignment(tenant_id=TENANT, actor_id=presence_env.actor, assignment_id=current["id"], rotation_pattern_id=rotation["id"])
    assert isinstance(switched, Ok) and switched.value["schedule_id"] is None and switched.value["rotation_code"] == "ROT2"
    ended = service.update_assignment(tenant_id=TENANT, actor_id=presence_env.actor, assignment_id=current["id"], valid_to=datetime.date(2026, 8, 31))
    reopened = service.update_assignment(tenant_id=TENANT, actor_id=presence_env.actor, assignment_id=current["id"], clear_valid_to=True)
    assert ended.value["valid_to"] == "2026-08-31" and reopened.value["valid_to"] is None
    assert _audits(db, "schedule_assignment.updated") == 3


def test_public_holidays_are_listed_by_year_unique_per_date_and_confirmable(db, presence_env):
    holidays = HolidayService(db)
    created = holidays.create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ml", holiday_date=datetime.date(2026, 9, 22), name="Fête de l'Indépendance")
    assert isinstance(created, Ok) and created.value["country_code"] == "ML" and created.value["confirmed"] is False
    duplicate = holidays.create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=datetime.date(2026, 9, 22), name="Doublon")
    assert isinstance(duplicate, Err) and duplicate.code == "DUPLICATE_HOLIDAY" and duplicate.message_fr
    confirmed = holidays.update_holiday(tenant_id=TENANT, actor_id=presence_env.actor, holiday_id=created.value["id"], confirmed=True)
    assert isinstance(confirmed, Ok) and confirmed.value["confirmed"] is True
    assert [h["name"] for h in holidays.list_holidays(tenant_id=TENANT, year=2026)] == ["Fête de l'Indépendance"]
    assert holidays.list_holidays(tenant_id=TENANT, year=2025) == []
    september = holidays.holiday_map(tenant_id=TENANT, date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30))
    assert september == {datetime.date(2026, 9, 22): True}


def test_presence_settings_start_empty_and_a_change_clears_the_confirmation(db):
    tenant = "integration-test-settings"
    actor = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, tenant, f"{actor}@test.local"))
    settings = PresenceSettingsService(db)
    assert settings.get(tenant_id=tenant)["night_start_minute"] is None
    missing = settings.night_window(tenant_id=tenant)
    assert isinstance(missing, Err) and missing.code == "PRESENCE_SETTINGS_MISSING" and missing.message_fr
    confirmed = settings.update(tenant_id=tenant, actor_id=actor, night_start_minute=1260, night_end_minute=300, punch_attach_minutes=240, punch_dedupe_seconds=None, late_grace_minutes=None, confirm=True)
    assert isinstance(confirmed, Ok) and confirmed.value["confirmed"] is True
    changed = settings.update(tenant_id=tenant, actor_id=actor, night_start_minute=1260, night_end_minute=300, punch_attach_minutes=240, punch_dedupe_seconds=None, late_grace_minutes=5)
    assert changed.value["confirmed"] is False and changed.value["late_grace_minutes"] == 5
    assert settings.night_window(tenant_id=tenant).value == (1260, 300)


def test_half_a_night_window_is_refused(db, presence_env):
    result = PresenceSettingsService(db).update(tenant_id=TENANT, actor_id=presence_env.actor, night_start_minute=1260, night_end_minute=None, punch_attach_minutes=None, punch_dedupe_seconds=None, late_grace_minutes=None)
    assert isinstance(result, Err) and result.code == "INVALID_SETTINGS"

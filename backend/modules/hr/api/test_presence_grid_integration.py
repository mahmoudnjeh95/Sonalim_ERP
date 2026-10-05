"""The supervisor grid against a real database."""
from __future__ import annotations

import datetime

from core.domain.result import Err, Ok
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.presence_testkit import (  # noqa: F401
    AUG_1, AUG_3, TENANT, add_employee, close_month_directly, insert_presence_row, presence_env, presence_row,
)
from modules.hr.api.schedule_service import HolidayService
from modules.hr.domain.presence import ManualEntry

SUNDAY = datetime.date(2026, 8, 9)


def _day(rows: list[dict], employee_no: str) -> dict:
    return next(row["days"][0] for row in rows if row["employee_no"] == employee_no)


def _save(db, env, *entries: ManualEntry):
    return PresenceService(db).save_days(tenant_id=TENANT, actor_id=env.actor, entries=list(entries))


def test_the_day_grid_defaults_each_person_to_their_schedule(db, presence_env):
    rows = PresenceService(db).grid(tenant_id=TENANT, work_date=AUG_3)
    day = _day(rows, "P-001")
    assert (day["default_status"], day["planned_minutes"], day["record"], day["employed"]) == ("present", 480, None, True)
    assert _day(rows, "P-002")["schedule_code"] == "NUIT"


def test_sunday_is_rest_and_a_public_holiday_defaults_to_holiday(db, presence_env):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_3, name="Jour de test")
    presence = PresenceService(db)
    assert _day(presence.grid(tenant_id=TENANT, work_date=AUG_3), "P-001")["default_status"] == "holiday"
    assert _day(presence.grid(tenant_id=TENANT, work_date=SUNDAY), "P-001")["default_status"] == "rest"


def test_the_schedule_filter_keeps_that_team_only_and_a_week_has_seven_days(db, presence_env):
    presence = PresenceService(db)
    night_team = presence.grid(tenant_id=TENANT, work_date=AUG_3, schedule_id=presence_env.night_schedule)
    assert [row["employee_no"] for row in night_team] == ["P-002"]
    assert {len(row["days"]) for row in presence.week(tenant_id=TENANT, date_from=AUG_3)} == {7}


def test_saving_writes_manual_days_with_derived_minutes_and_one_audit_row_each(db, presence_env):
    saved = _save(
        db, presence_env,
        ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="late", late_minutes=30),
        ManualEntry(employee_id=presence_env.night_worker, work_date=AUG_3, status="present"),
    )
    assert isinstance(saved, Ok) and saved.value == {"saved": 2}
    day = presence_row(db, presence_env.day_worker, AUG_3)
    night = presence_row(db, presence_env.night_worker, AUG_3)
    assert (day["status"], day["worked_minutes"], day["late_minutes"], day["source"]) == ("late", 450, 30, "manual")
    assert (night["worked_minutes"], night["night_minutes"]) == (480, 360)
    audits = db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'presence_day.saved'", (TENANT,)).fetchone()[0]
    assert audits == 2


def test_a_rest_day_worked_by_hand_is_rest_holiday_overtime(db, presence_env):
    saved = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=SUNDAY, status="present", worked_minutes=240))
    assert isinstance(saved, Ok)
    row = presence_row(db, presence_env.day_worker, SUNDAY)
    assert (row["scheduled_minutes"], row["worked_minutes"], row["ot_minutes_rest_holiday"]) == (0, 240, 240)


def test_a_manual_entry_replaces_a_clock_day(db, presence_env):
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_3, status="absent", source="clock")
    assert isinstance(_save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present")), Ok)
    assert presence_row(db, presence_env.day_worker, AUG_3)["source"] == "manual"


def test_a_leave_day_cannot_be_overwritten_from_the_grid_nor_typed_there(db, presence_env):
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_3, status="leave", source="leave")
    over_leave = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present"))
    typed_leave = _save(db, presence_env, ManualEntry(employee_id=presence_env.night_worker, work_date=AUG_3, status="leave"))
    assert isinstance(over_leave, Err) and over_leave.code == "PRESENCE_DAY_FROM_LEAVE" and over_leave.message_fr
    assert isinstance(typed_leave, Err) and typed_leave.code == "INVALID_PRESENCE"


def test_a_closed_month_refuses_changes_and_reports_itself_closed(db, presence_env):
    close_month_directly(db, AUG_1)
    result = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present"))
    assert isinstance(result, Err) and result.code == "PRESENCE_MONTH_CLOSED" and "2026-08" in result.message_fr
    presence = PresenceService(db)
    assert presence.is_month_closed(tenant_id=TENANT, period=AUG_1) is True
    assert presence.is_month_closed(tenant_id=TENANT, period=datetime.date(2026, 9, 1)) is False


def test_saving_needs_the_night_window(db, presence_env):
    db.execute("UPDATE hr.presence_settings SET night_start_minute = NULL, night_end_minute = NULL WHERE tenant_id = %s", (TENANT,))
    result = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present"))
    assert isinstance(result, Err) and result.code == "PRESENCE_SETTINGS_MISSING"


def test_a_day_outside_employment_is_refused(db, presence_env):
    newcomer = add_employee(db, employee_no="P-003", department=presence_env.department, hire_date=datetime.date(2026, 8, 10))
    result = _save(db, presence_env, ManualEntry(employee_id=newcomer, work_date=AUG_3, status="present"))
    assert isinstance(result, Err) and result.code == "NOT_EMPLOYED" and result.message_fr


def test_the_employee_month_lists_every_day_and_says_whether_it_is_closed(db, presence_env):
    result = PresenceService(db).employee_month(tenant_id=TENANT, employee_id=presence_env.day_worker, period=AUG_1)
    assert isinstance(result, Ok)
    assert (len(result.value["days"]), result.value["closed"], result.value["period"]) == (31, False, "2026-08-01")

"""Closing and reopening a month, the summary payroll reads, and the payroll-lock consumers."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.leave_service import LeaveRequestService, LeaveTypeService
from modules.hr.api.presence_month_service import PresenceMonthService
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.presence_testkit import AUG_1, AUG_3, TENANT, add_employee, fill_month, presence_env, presence_row  # noqa: F401
from modules.hr.api.schedule_service import HolidayService, ScheduleService
from modules.hr.domain.presence import ManualEntry
from modules.hr.events.consumers import _handle_run_approved, _handle_run_reversed

AUG_5 = datetime.date(2026, 8, 5)
AUG_31 = datetime.date(2026, 8, 31)
CONTRACT_KEYS = {
    "employee_id", "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "rest_days_worked", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "late_minutes",
}


def _close(db, env):
    return PresenceMonthService(db).close(tenant_id=TENANT, actor_id=env.actor, period=AUG_1)


def _envelope(event_type: str, run_id: str) -> dict:
    return {
        "event_id": str(ULID()), "event_type": event_type, "tenant_id": TENANT,
        "payload": {"run_id": run_id, "period": "2026-08-01", "run_type": "regular"},
    }


def test_gaps_list_every_working_day_without_presence_and_block_the_close(db, presence_env):
    gaps = PresenceMonthService(db).gaps(tenant_id=TENANT, period=AUG_1)
    assert len([gap for gap in gaps if gap["reason"] == "missing"]) == 52  # 26 working days (Mon-Sat) x 2 people
    refused = _close(db, presence_env)
    assert isinstance(refused, Err) and refused.code == "PRESENCE_INCOMPLETE" and "52" in refused.message_fr


def test_gaps_stop_at_the_termination_date_and_a_person_without_schedule_is_a_gap(db, presence_env):
    leaver = add_employee(db, employee_no="P-004", department=presence_env.department, termination_date=datetime.date(2026, 8, 14))
    ScheduleService(db).create_assignment(
        tenant_id=TENANT, actor_id=presence_env.actor, employee_id=leaver, valid_from=datetime.date(2026, 1, 1),
        schedule_id=presence_env.day_schedule,
    )
    unscheduled = add_employee(db, employee_no="P-005", department=presence_env.department)
    gaps = PresenceMonthService(db).gaps(tenant_id=TENANT, period=AUG_1)
    leaver_days = [gap["work_date"] for gap in gaps if gap["employee_id"] == leaver]
    assert len(leaver_days) == 12 and leaver_days[-1] == "2026-08-14"
    assert {gap["reason"] for gap in gaps if gap["employee_id"] == unscheduled} == {"no_schedule"}


def test_closing_a_complete_month_writes_holidays_locks_rows_and_announces_it(db, presence_env):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_5, name="Jour de test")
    fill_month(db, presence_env, AUG_1)
    closed = _close(db, presence_env)
    assert isinstance(closed, Ok)
    assert (closed.value["status"], closed.value["holiday_rows"]) == ("closed", 2)
    assert presence_row(db, presence_env.day_worker, AUG_5)["status"] == "holiday"
    unlocked = db.execute(
        "SELECT count(*) FROM hr.presence_days WHERE tenant_id = %s AND work_date BETWEEN %s AND %s AND NOT locked", (TENANT, AUG_1, AUG_31)
    ).fetchone()[0]
    assert unlocked == 0
    envelope = db.execute("SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'hr.presence_month.closed'", (TENANT,)).fetchone()[0]
    assert envelope["payload"] == {"period": "2026-08-01"} and envelope["producer"] == "hr"
    assert PresenceService(db).is_month_closed(tenant_id=TENANT, period=AUG_1) is True
    august = next(m for m in PresenceMonthService(db).list_months(tenant_id=TENANT, year=2026) if m["period"] == "2026-08-01")
    assert (august["status"], august["payroll_locked"]) == ("closed", False)
    again = _close(db, presence_env)
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"
    refused = PresenceService(db).save_days(tenant_id=TENANT, actor_id=presence_env.actor, entries=[
        ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="absent"),
    ])
    assert refused.code == "PRESENCE_MONTH_CLOSED"


def test_a_pending_leave_request_touching_the_month_blocks_the_close(db, presence_env):
    fill_month(db, presence_env, AUG_1)
    unpaid = LeaveTypeService(db).create_type(
        tenant_id=TENANT, actor_id=presence_env.actor, code="SANS_SOLDE", name_en="Unpaid leave", name_fr="Congé sans solde",
        paid=False, accrual_days_per_month=Decimal("0"), max_carry_over=None, counts_days="calendar",
        requires_document=False, presence_status="leave",
    ).value
    LeaveRequestService(db).create_request(
        tenant_id=TENANT, actor_id=presence_env.actor, employee_id=presence_env.day_worker, leave_type_id=unpaid["id"],
        start_date=AUG_31, end_date=datetime.date(2026, 9, 2),
    )
    refused = _close(db, presence_env)
    assert isinstance(refused, Err) and refused.code == "LEAVE_PENDING" and refused.message_fr


def test_reopening_needs_a_reason_and_no_approved_payroll(db, presence_env):
    fill_month(db, presence_env, AUG_1)
    assert isinstance(_close(db, presence_env), Ok)
    months = PresenceMonthService(db)
    no_reason = months.reopen(tenant_id=TENANT, actor_id=presence_env.actor, period=AUG_1, reason=" ")
    assert isinstance(no_reason, Err) and no_reason.code == "INVALID_REOPEN"
    _handle_run_approved(db, _envelope("payroll.run.approved", "run-1"))
    _handle_run_approved(db, _envelope("payroll.run.approved", "run-1"))  # a redelivery changes nothing
    assert db.execute("SELECT count(*) FROM hr.presence_month_payroll_locks WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 1
    blocked = months.reopen(tenant_id=TENANT, actor_id=presence_env.actor, period=AUG_1, reason="correction d'un pointage")
    assert isinstance(blocked, Err) and blocked.code == "PRESENCE_PAYROLL_APPROVED" and blocked.message_fr
    _handle_run_reversed(db, _envelope("payroll.run.reversed", "run-1"))
    reopened = months.reopen(tenant_id=TENANT, actor_id=presence_env.actor, period=AUG_1, reason="correction d'un pointage")
    assert isinstance(reopened, Ok) and reopened.value["status"] == "open"
    assert presence_row(db, presence_env.day_worker, AUG_3)["locked"] is False
    assert PresenceService(db).is_month_closed(tenant_id=TENANT, period=AUG_1) is False
    audit = db.execute("SELECT payload FROM core.audit_log WHERE tenant_id = %s AND action = 'presence_month.reopened'", (TENANT,)).fetchone()[0]
    assert audit["reason"] == "correction d'un pointage"


def test_the_month_summary_is_exactly_what_payroll_is_promised(db, presence_env):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_5, name="Jour de test")
    fill_month(db, presence_env, AUG_1)
    PresenceService(db).save_days(tenant_id=TENANT, actor_id=presence_env.actor, entries=[
        ManualEntry(employee_id=presence_env.day_worker, work_date=datetime.date(2026, 8, 4), status="late", late_minutes=30),
        ManualEntry(employee_id=presence_env.day_worker, work_date=datetime.date(2026, 8, 6), status="absent"),
    ])
    assert isinstance(_close(db, presence_env), Ok)
    nobody = add_employee(db, employee_no="P-009", department=presence_env.department)
    summary = PresenceService(db).month_summary(
        tenant_id=TENANT, period=AUG_1, employee_ids=[presence_env.day_worker, presence_env.night_worker, nobody]
    )
    assert all(set(item) == CONTRACT_KEYS for item in summary)
    assert all(type(value) is int for item in summary for key, value in item.items() if key != "employee_id")
    day, night, empty = summary
    assert (day["scheduled_days"], day["worked_days"], day["unpaid_absence_days"], day["holiday_days"], day["late_minutes"]) == (25, 24, 1, 1, 30)
    assert (night["worked_days"], night["night_minutes"], night["holiday_days"]) == (25, 25 * 360, 1)
    assert empty == {"employee_id": nobody, **{key: 0 for key in CONTRACT_KEYS - {"employee_id"}}}


def test_the_payroll_consumers_are_registered():
    from core.events.consumers import _registry

    assert ("hr.payroll_run_approved", _handle_run_approved) in _registry["payroll.run.approved"]
    assert ("hr.payroll_run_reversed", _handle_run_reversed) in _registry["payroll.run.reversed"]

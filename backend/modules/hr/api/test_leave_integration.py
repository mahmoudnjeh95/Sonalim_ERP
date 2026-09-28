"""Leave types, requests, approval and balances against a real database.
The 2.5 days a month below is a test input, not the plant's (unconfirmed) seed value."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.leave_service import LeaveBalanceService, LeaveRequestService, LeaveTypeService
from modules.hr.api.presence_testkit import (  # noqa: F401
    AUG_1, AUG_3, TENANT, add_employee, close_month_directly, insert_presence_row, presence_env, presence_row,
)
from modules.hr.api.schedule_service import HolidayService
from modules.hr.api.service import LeaveService

AUG_4 = datetime.date(2026, 8, 4)
AUG_5 = datetime.date(2026, 8, 5)
AUG_6 = datetime.date(2026, 8, 6)
AUG_9 = datetime.date(2026, 8, 9)


@pytest.fixture
def leave(db, presence_env):
    types = LeaveTypeService(db)

    def create(code: str, **values) -> str:
        created = types.create_type(tenant_id=TENANT, actor_id=presence_env.actor, code=code, **values)
        assert isinstance(created, Ok), created
        return created.value["id"]

    return SimpleNamespace(
        annual=create("ANNUEL", name_en="Annual leave", name_fr="Congé annuel", paid=True, accrual_days_per_month=Decimal("2.5"),
                      max_carry_over=None, counts_days="working", requires_document=False, presence_status="leave"),
        sick=create("MALADIE", name_en="Sick leave", name_fr="Congé maladie", paid=True, accrual_days_per_month=Decimal("0"),
                    max_carry_over=None, counts_days="calendar", requires_document=True, presence_status="sick"),
        unpaid=create("SANS_SOLDE", name_en="Unpaid leave", name_fr="Congé sans solde", paid=False, accrual_days_per_month=Decimal("0"),
                      max_carry_over=None, counts_days="calendar", requires_document=False, presence_status="leave"),
    )


def _request(db, env, leave_type_id, start, end, *, half_day=False, document_ref=None):
    return LeaveRequestService(db).create_request(
        tenant_id=TENANT, actor_id=env.actor, employee_id=env.day_worker, leave_type_id=leave_type_id,
        start_date=start, end_date=end, half_day=half_day, document_ref=document_ref,
    )


def _approve(db, env, request_id):
    return LeaveRequestService(db).approve(tenant_id=TENANT, actor_id=env.actor, request_id=request_id)


def _give(db, env, leave_type_id, days: str, year: int = 2026):
    result = LeaveBalanceService(db).adjust(
        tenant_id=TENANT, actor_id=env.actor, employee_id=env.day_worker, leave_type_id=leave_type_id,
        year=year, delta=Decimal(days), reason="solde d'ouverture",
    )
    assert isinstance(result, Ok), result


def _balance(db, env, leave_type_id, year: int = 2026) -> dict:
    return next(b for b in LeaveBalanceService(db).balances(tenant_id=TENANT, year=year, employee_id=env.day_worker) if b["leave_type_id"] == leave_type_id)


def test_working_day_leave_skips_the_rest_day_and_the_public_holiday(db, presence_env, leave):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_5, name="Jour de test")
    created = _request(db, presence_env, leave.annual, AUG_3, AUG_9)
    assert isinstance(created, Ok)
    assert (created.value["days"], created.value["status"], created.value["leave_type_code"]) == (Decimal("5"), "pending", "ANNUEL")


def test_approval_needs_enough_balance_then_writes_leave_days(db, presence_env, leave):
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    refused = _approve(db, presence_env, request["id"])
    assert isinstance(refused, Err) and refused.code == "LEAVE_BALANCE_INSUFFICIENT" and refused.message_fr
    _give(db, presence_env, leave.annual, "5")
    approved = _approve(db, presence_env, request["id"])
    assert isinstance(approved, Ok) and approved.value["status"] == "approved"
    for day in (AUG_3, AUG_4):
        row = presence_row(db, presence_env.day_worker, day)
        assert (row["status"], row["source"], row["justified"], row["leave_request_id"]) == ("leave", "leave", True, request["id"])
    balance = _balance(db, presence_env, leave.annual)
    assert (balance["taken"], balance["available"]) == (Decimal("2"), Decimal("3"))


def test_a_half_day_takes_half_a_day_and_writes_no_presence(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "1")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_3, half_day=True).value
    assert request["days"] == Decimal("0.5")
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    assert presence_row(db, presence_env.day_worker, AUG_3) is None
    assert _balance(db, presence_env, leave.annual)["available"] == Decimal("0.5")


def test_leave_over_a_worked_day_is_refused(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_4, status="present", source="clock", worked_minutes=480)
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    refused = _approve(db, presence_env, request["id"])
    assert isinstance(refused, Err) and refused.code == "LEAVE_OVERLAPS_WORK" and "2026-08-04" in refused.message_fr


def test_overlapping_requests_are_refused(db, presence_env, leave):
    assert isinstance(_request(db, presence_env, leave.annual, AUG_3, AUG_4), Ok)
    overlap = _request(db, presence_env, leave.unpaid, AUG_4, AUG_5)
    assert isinstance(overlap, Err) and overlap.code == "LEAVE_OVERLAP" and overlap.message_fr


def test_legacy_review_refuses_a_typed_request_instead_of_corrupting_its_balance(db, presence_env, leave):
    """A request created on the new /hr/leave screen (has a leave_type_id) must not be decided through
    the legacy /hr/leave-requests/{id}/review route: that route takes nothing from the balance, but a
    later cancel on the new screen would still reverse a debit that was never made, inflating `available`."""
    _give(db, presence_env, leave.annual, "5")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    refused = LeaveService(db).review_request(
        tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"], status="approved",
    )
    assert isinstance(refused, Err) and refused.code == "LEAVE_TYPED_REQUEST" and refused.message_fr
    unchanged = next(r for r in LeaveRequestService(db).list_requests(tenant_id=TENANT) if r["id"] == request["id"])
    assert unchanged["status"] == "pending"
    assert _balance(db, presence_env, leave.annual)["available"] == Decimal("5")


def test_cancelling_approved_leave_gives_the_days_back_and_clears_the_leave_days(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    cancelled = LeaveRequestService(db).cancel(tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"])
    assert isinstance(cancelled, Ok) and cancelled.value["status"] == "cancelled"
    assert presence_row(db, presence_env.day_worker, AUG_3) is None
    assert _balance(db, presence_env, leave.annual)["taken"] == Decimal("0")


def test_a_closed_month_refuses_approval_and_cancellation(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    approved = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, approved["id"]), Ok)
    pending = _request(db, presence_env, leave.annual, datetime.date(2026, 8, 10), datetime.date(2026, 8, 11)).value
    close_month_directly(db, AUG_1)
    refused_approval = _approve(db, presence_env, pending["id"])
    refused_cancel = LeaveRequestService(db).cancel(tenant_id=TENANT, actor_id=presence_env.actor, request_id=approved["id"])
    assert (refused_approval.code, refused_cancel.code) == ("PRESENCE_MONTH_CLOSED", "PRESENCE_MONTH_CLOSED")


def test_sick_leave_needs_its_document_and_marks_sick_days_without_a_balance(db, presence_env, leave):
    request = _request(db, presence_env, leave.sick, AUG_3, AUG_4).value
    refused = _approve(db, presence_env, request["id"])
    assert isinstance(refused, Err) and refused.code == "LEAVE_DOCUMENT_REQUIRED" and refused.message_fr
    edited = LeaveRequestService(db).update_request(tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"], document_ref="certificat-2026-081.pdf")
    assert isinstance(edited, Ok)
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    assert presence_row(db, presence_env.day_worker, AUG_3)["status"] == "sick"


def test_editing_approved_leave_moves_its_days_and_its_balance(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    edited = LeaveRequestService(db).update_request(tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"], start_date=AUG_4, end_date=AUG_6)
    assert isinstance(edited, Ok) and edited.value["days"] == Decimal("3")
    assert presence_row(db, presence_env.day_worker, AUG_3) is None
    assert presence_row(db, presence_env.day_worker, AUG_6)["status"] == "leave"
    assert _balance(db, presence_env, leave.annual)["taken"] == Decimal("3")


def test_month_accrual_is_prorated_and_posting_it_twice_changes_nothing(db, presence_env, leave):
    add_employee(db, employee_no="P-003", department=presence_env.department, hire_date=datetime.date(2026, 8, 16))
    balances = LeaveBalanceService(db)
    assert balances.post_month_accruals(tenant_id=TENANT, period=AUG_1) == 3  # three people, one accruing type
    assert balances.post_month_accruals(tenant_id=TENANT, period=AUG_1) == 3
    accrued = {b["employee_no"]: b["accrued"] for b in balances.balances(tenant_id=TENANT, year=2026) if b["leave_type_id"] == leave.annual}
    assert accrued == {"P-001": Decimal("2.50"), "P-002": Decimal("2.50"), "P-003": Decimal("1.29")}


def test_the_carry_over_cap_of_the_leave_type_applies_and_can_be_cleared(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "10", year=2025)
    types = LeaveTypeService(db)
    capped = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.annual, max_carry_over=Decimal("2"))
    assert isinstance(capped, Ok)
    assert _balance(db, presence_env, leave.annual)["carried_over"] == Decimal("2")
    uncapped = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.annual, clear_max_carry_over=True)
    assert uncapped.value["max_carry_over"] is None
    assert _balance(db, presence_env, leave.annual)["carried_over"] == Decimal("10")


def test_an_old_request_without_a_type_is_listed_and_must_get_one_before_approval(db, presence_env, leave):
    old_id = str(ULID())
    db.execute(
        "INSERT INTO hr.leave_requests (id, tenant_id, employee_id, leave_type, start_date, end_date) VALUES (%s, %s, %s, 'annual', %s, %s)",
        (old_id, TENANT, presence_env.day_worker, AUG_3, AUG_3),
    )
    listed = next(r for r in LeaveRequestService(db).list_requests(tenant_id=TENANT) if r["id"] == old_id)
    assert (listed["leave_type_id"], listed["legacy_leave_type"], listed["days"]) == (None, "annual", None)
    refused = _approve(db, presence_env, old_id)
    assert isinstance(refused, Err) and refused.code == "INVALID_LEAVE"


def test_flipping_paid_is_refused_once_the_type_has_leave_days_in_a_closed_month(db, presence_env, leave):
    """month_summary reads the leave type's `paid` flag live (CATALOG.md promises the summary is
    final once a month is closed), so flipping `paid` after the month closes must be refused when
    the type already has leave days recorded in that closed month."""
    _give(db, presence_env, leave.annual, "5")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    close_month_directly(db, AUG_1)
    types = LeaveTypeService(db)
    refused = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.annual, paid=False)
    assert isinstance(refused, Err) and refused.code == "PRESENCE_MONTH_CLOSED" and refused.message_fr
    unaffected = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.annual, name_en="Annual leave (renamed)")
    assert isinstance(unaffected, Ok) and unaffected.value["name_en"] == "Annual leave (renamed)"


def test_flipping_paid_still_succeeds_when_the_type_has_no_leave_days_in_a_closed_month(db, presence_env, leave):
    close_month_directly(db, AUG_1)
    types = LeaveTypeService(db)
    allowed = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.unpaid, paid=True)
    assert isinstance(allowed, Ok) and allowed.value["paid"] is True

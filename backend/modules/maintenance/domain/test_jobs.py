import datetime

import pytest

from core.domain.result import Err, Ok
from modules.maintenance.domain.jobs import (
    CheckSnapshot,
    EntrySummary,
    apply_review,
    can_assign,
    can_cancel,
    can_close,
    can_delegate,
    can_record_entry,
    entry_timing,
    status_after_entry,
    validate_submit,
)


def _check(id, state="done", action="inspect", photo=False, entry=EntrySummary(1, "ok", False, None), requires_photo=False):
    return CheckSnapshot(id=id, state=state, attempt=1, action=action, requires_photo=requires_photo, latest_entry=entry if state != "pending" else None)


# -- can_assign -------------------------------------------------------------


def test_planned_job_can_be_assigned():
    assert isinstance(can_assign("planned"), Ok)


def test_assigned_job_can_be_reassigned():
    assert isinstance(can_assign("assigned"), Ok)


def test_closed_job_cannot_be_assigned():
    assert can_assign("closed").code == "INVALID_TRANSITION"


def test_in_progress_job_cannot_be_assigned():
    assert can_assign("in_progress").code == "INVALID_TRANSITION"


# -- can_delegate -------------------------------------------------------------


def test_checks_can_be_delegated_while_the_job_is_being_worked():
    for status in ("assigned", "in_progress", "rework"):
        assert isinstance(can_delegate(status), Ok)


def test_checks_cannot_be_delegated_before_assignment_or_after_submission():
    for status in ("planned", "submitted", "closed", "cancelled"):
        assert can_delegate(status).code == "INVALID_TRANSITION"


# -- can_record_entry ---------------------------------------------------------


def test_accepted_check_is_locked():
    assert can_record_entry("rework", "accepted").code == "CHECK_LOCKED"


def test_entry_refused_on_a_submitted_job():
    assert can_record_entry("submitted", "done").code == "INVALID_TRANSITION"


def test_entry_allowed_while_assigned_in_progress_or_rework():
    for status in ("assigned", "in_progress", "rework"):
        for state in ("pending", "done"):
            assert isinstance(can_record_entry(status, state), Ok)


def test_entry_refused_on_planned_job():
    assert can_record_entry("planned", "pending").code == "INVALID_TRANSITION"


# -- status_after_entry -------------------------------------------------------


def test_first_entry_starts_the_job():
    assert status_after_entry("assigned") == "in_progress" and status_after_entry("rework") == "rework"


def test_status_after_entry_leaves_in_progress_unchanged():
    assert status_after_entry("in_progress") == "in_progress"


# -- validate_submit -----------------------------------------------------------


def test_submit_refused_while_a_check_is_pending():
    assert validate_submit("in_progress", [_check("a"), _check("b", state="pending")]).code == "CHECKS_PENDING"


def test_submit_requires_photo_unless_not_done():
    no_photo = EntrySummary(1, "ok", False, None)
    assert validate_submit("in_progress", [_check("a", requires_photo=True, entry=no_photo)]).code == "PHOTO_REQUIRED"
    skipped = EntrySummary(1, "not_done", False, None)
    assert isinstance(validate_submit("in_progress", [_check("a", requires_photo=True, entry=skipped)]), Ok)


def test_submit_accepts_photo_when_required_and_present():
    with_photo = EntrySummary(1, "ok", True, None)
    assert isinstance(validate_submit("in_progress", [_check("a", requires_photo=True, entry=with_photo)]), Ok)


def test_measure_needs_a_value():
    assert validate_submit("rework", [_check("a", action="measure")]).code == "MEASURE_REQUIRED"


def test_measure_not_required_when_outcome_is_not_done():
    skipped = EntrySummary(1, "not_done", False, None)
    assert isinstance(validate_submit("in_progress", [_check("a", action="measure", entry=skipped)]), Ok)


def test_measure_with_a_value_passes():
    measured = EntrySummary(1, "ok", False, 12.5)
    assert isinstance(validate_submit("in_progress", [_check("a", action="measure", entry=measured)]), Ok)


def test_submit_refused_on_a_planned_job():
    assert validate_submit("assigned", [_check("a")]).code == "INVALID_TRANSITION"


def test_submit_refused_on_an_assigned_job():
    assert validate_submit("planned", [_check("a")]).code == "INVALID_TRANSITION"


# -- apply_review ---------------------------------------------------------------


def test_review_with_a_rejection_sends_the_job_to_rework():
    out = apply_review("submitted", [_check("a"), _check("b")], [("a", "accepted", None), ("b", "rejected", "graisse oubliée")]).value
    assert out.next_status == "rework" and out.rejected_ids == ("b",)


def test_review_with_all_accepted_keeps_submitted():
    out = apply_review("submitted", [_check("a"), _check("b")], [("a", "accepted", None), ("b", "accepted", None)]).value
    assert out.next_status == "submitted" and out.accepted_ids == ("a", "b")


def test_review_must_cover_every_done_check_and_only_them():
    assert apply_review("submitted", [_check("a"), _check("b")], [("a", "accepted", None)]).code == "REVIEW_INCOMPLETE"
    assert apply_review("submitted", [_check("a")], [("a", "accepted", None), ("z", "accepted", None)]).code == "UNKNOWN_CHECK"


def test_rejection_needs_a_reason():
    assert apply_review("submitted", [_check("a")], [("a", "rejected", "  ")]).code == "REASON_REQUIRED"
    assert apply_review("submitted", [_check("a")], [("a", "rejected", None)]).code == "REASON_REQUIRED"


def test_review_refused_outside_submitted():
    assert apply_review("rework", [_check("a")], [("a", "accepted", None)]).code == "INVALID_TRANSITION"


def test_review_ignores_checks_not_in_done_state():
    # an already-accepted check from an earlier partial review round is not
    # asked for again, and giving it one anyway is rejected as unknown.
    checks = [_check("a", state="accepted"), _check("b")]
    assert apply_review("submitted", checks, [("b", "accepted", None)]).value.next_status == "submitted"
    assert apply_review("submitted", checks, [("a", "accepted", None), ("b", "accepted", None)]).code == "UNKNOWN_CHECK"


# -- can_close ------------------------------------------------------------------


def test_close_needs_every_check_accepted():
    assert can_close("submitted", [_check("a", state="accepted"), _check("b")]).code == "NOT_ALL_ACCEPTED"


def test_close_succeeds_when_all_accepted():
    assert isinstance(can_close("submitted", [_check("a", state="accepted"), _check("b", state="accepted")]), Ok)


def test_close_refused_outside_submitted():
    assert can_close("rework", [_check("a", state="accepted")]).code == "INVALID_TRANSITION"


# -- can_cancel -------------------------------------------------------------------


def test_can_cancel_from_any_state_except_terminal_ones():
    for status in ("planned", "assigned", "in_progress", "submitted", "rework"):
        assert isinstance(can_cancel(status), Ok)


def test_cannot_cancel_a_closed_job():
    assert can_cancel("closed").code == "INVALID_TRANSITION"


def test_cannot_cancel_an_already_cancelled_job():
    assert can_cancel("cancelled").code == "INVALID_TRANSITION"


# -- entry_timing -----------------------------------------------------------------


def test_timing_modes():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    t = entry_timing(started_at=now - datetime.timedelta(minutes=7), finished_at=now, manual_minutes=None, now=now).value
    assert (t.seconds, t.source) == (420, "timer")
    m = entry_timing(started_at=None, finished_at=None, manual_minutes=15, now=now).value
    assert (m.seconds, m.source, m.finished_at) == (900, "manual", now)
    assert entry_timing(started_at=now, finished_at=now, manual_minutes=None, now=now).code == "INVALID_TIMING"
    assert entry_timing(started_at=now, finished_at=now, manual_minutes=5, now=now).code == "INVALID_TIMING"


def test_timing_requires_one_mode():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    assert entry_timing(started_at=None, finished_at=None, manual_minutes=None, now=now).code == "INVALID_TIMING"


def test_timing_rejects_finished_before_started():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    result = entry_timing(started_at=now, finished_at=now - datetime.timedelta(minutes=1), manual_minutes=None, now=now)
    assert result.code == "INVALID_TIMING"


def test_timing_allows_small_clock_skew_in_the_future():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    finished = now + datetime.timedelta(minutes=1)
    started = finished - datetime.timedelta(minutes=5)
    result = entry_timing(started_at=started, finished_at=finished, manual_minutes=None, now=now)
    assert isinstance(result, Ok)


def test_timing_rejects_finish_too_far_in_the_future():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    finished = now + datetime.timedelta(minutes=10)
    started = finished - datetime.timedelta(minutes=5)
    result = entry_timing(started_at=started, finished_at=finished, manual_minutes=None, now=now)
    assert result.code == "INVALID_TIMING"


def test_timing_rejects_non_positive_manual_minutes():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    assert entry_timing(started_at=None, finished_at=None, manual_minutes=0, now=now).code == "INVALID_TIMING"
    assert entry_timing(started_at=None, finished_at=None, manual_minutes=-5, now=now).code == "INVALID_TIMING"


def test_a_sub_second_timer_records_one_second():
    """check_entries.duration_seconds must be > 0: a Start/Finish tapped within a second
    is still a recorded check, not a database error."""
    now = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=datetime.timezone.utc)
    timing = entry_timing(started_at=now - datetime.timedelta(milliseconds=400), finished_at=now, manual_minutes=None, now=now)

    assert timing.value.seconds == 1


def test_a_tiny_manual_duration_records_one_second():
    now = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=datetime.timezone.utc)

    assert entry_timing(started_at=None, finished_at=None, manual_minutes=0.005, now=now).value.seconds == 1


@pytest.mark.parametrize("minutes", [float("nan"), float("inf")])
def test_a_manual_duration_that_is_not_a_number_is_refused(minutes):
    now = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=datetime.timezone.utc)

    assert entry_timing(started_at=None, finished_at=None, manual_minutes=minutes, now=now).code == "INVALID_TIMING"

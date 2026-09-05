import datetime

from core.domain.result import Err, Ok
from modules.qc.domain.quality import (
    DEFAULT_FOLLOW_UP_WINDOW_DAYS,
    FollowUp,
    QualityReport,
    QualityReportDetail,
    follow_up_window_end,
    is_conforming,
    transition_follow_up,
    transition_quality_report,
    validate_quality_detail,
    validate_window_days,
)


def _report(status: str) -> QualityReport:
    return QualityReport(
        id="q1", of_id="of1", report_date=datetime.date(2026, 9, 1), status=status, revision=1
    )


def _follow_up(status: str) -> FollowUp:
    return FollowUp(
        id="f1",
        quality_report_id="q1",
        of_id="of1",
        window_ends_on=datetime.date(2026, 10, 11),
        observed_on=datetime.date(2026, 9, 5),
        status=status,
    )


def test_quality_report_follows_the_same_vocabulary_as_a_production_report():
    assert isinstance(transition_quality_report(_report("draft"), "submitted"), Ok)
    assert isinstance(transition_quality_report(_report("submitted"), "validated"), Ok)
    assert isinstance(transition_quality_report(_report("submitted"), "rejected"), Ok)
    assert isinstance(transition_quality_report(_report("rejected"), "draft"), Ok)


def test_a_draft_quality_report_cannot_be_validated():
    result = transition_quality_report(_report("draft"), "validated")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_a_validated_quality_report_is_terminal():
    for target in ("draft", "submitted", "rejected", "validated"):
        assert isinstance(transition_quality_report(_report("validated"), target), Err)


def test_follow_up_can_skip_straight_to_completed():
    # An observation that needs no investigation is closed on the spot.
    assert isinstance(transition_follow_up(_follow_up("open"), "completed"), Ok)
    assert isinstance(transition_follow_up(_follow_up("open"), "in_progress"), Ok)


def test_a_completed_follow_up_cannot_reopen():
    for target in ("open", "in_progress"):
        assert isinstance(transition_follow_up(_follow_up("completed"), target), Err)


def test_an_empty_quality_report_is_valid():
    assert isinstance(validate_quality_detail(QualityReportDetail()), Ok)


def test_negative_carton_counts_are_rejected():
    result = validate_quality_detail(QualityReportDetail(conforming_cartons=-1))
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_humidity_outside_zero_to_one_hundred_is_rejected():
    assert isinstance(validate_quality_detail(QualityReportDetail(humidity_percentage=101)), Err)
    assert isinstance(validate_quality_detail(QualityReportDetail(humidity_percentage=-0.5)), Err)
    assert isinstance(validate_quality_detail(QualityReportDetail(humidity_percentage=12.5)), Ok)


def test_non_conforming_cartons_require_defect_details():
    result = validate_quality_detail(QualityReportDetail(non_conforming_cartons=10))
    assert isinstance(result, Err)
    assert result.code == "MISSING_DEFECT_DETAILS"

    with_details = validate_quality_detail(
        QualityReportDetail(non_conforming_cartons=10, defect_details="bad film seal")
    )
    assert isinstance(with_details, Ok)


def test_a_poor_reading_is_still_a_valid_report():
    # The indices are measurements, not targets — recording a bad shift honestly
    # is the point, so nothing here refuses a disappointing number.
    detail = QualityReportDetail(pre_dryer_index=0, cooling_index=0, pf_index=0, sumo_index=0)
    assert isinstance(validate_quality_detail(detail), Ok)


def test_conformity_is_decided_by_the_non_conforming_count():
    assert is_conforming(QualityReportDetail(conforming_cartons=100))
    assert not is_conforming(
        QualityReportDetail(conforming_cartons=100, non_conforming_cartons=2, defect_details="bad seal")
    )


def test_the_window_runs_from_the_report_date():
    end = follow_up_window_end(datetime.date(2026, 9, 1), DEFAULT_FOLLOW_UP_WINDOW_DAYS)
    assert end == datetime.date(2026, 10, 11)


def test_a_per_product_window_overrides_the_default():
    assert follow_up_window_end(datetime.date(2026, 9, 1), 10) == datetime.date(2026, 9, 11)


def test_a_nonsense_window_is_rejected():
    assert isinstance(validate_window_days(0), Err)
    assert isinstance(validate_window_days(-1), Err)
    assert isinstance(validate_window_days(99999), Err)
    assert isinstance(validate_window_days(40), Ok)

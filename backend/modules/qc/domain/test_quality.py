import datetime

from core.domain.result import Err, Ok
from modules.qc.domain.quality import (
    DEFAULT_FOLLOW_UP_WINDOW_DAYS,
    ConformityLine,
    FollowUp,
    QualityReport,
    follow_up_window_end,
    is_conforming,
    transition_follow_up,
    transition_quality_report,
    validate_conformity_line,
    validate_window_days,
)


def _report(status: str) -> QualityReport:
    return QualityReport(
        id="q1", shift_report_id="shift1", report_date=datetime.date(2026, 9, 1), status=status, revision=1
    )


def _follow_up(status: str) -> FollowUp:
    return FollowUp(
        id="f1",
        quality_report_id="q1",
        of_id="of1",
        conformity_line_id="line-1",
        window_ends_on=datetime.date(2026, 10, 11),
        observed_on=datetime.date(2026, 9, 5),
        status=status,
    )


def _line(**overrides) -> ConformityLine:
    base = dict(
        id="line-1", report_id="report-1", shift_packing_row_id="row-1",
        of_id="of-1", product_id="product-1", conforming_cartons=10, non_conforming_cartons=0,
        defect_details=None,
    )
    base.update(overrides)
    return ConformityLine(**base)


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


def test_negative_conforming_cartons_is_rejected():
    result = validate_conformity_line(_line(conforming_cartons=-1))
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_non_integer_cartons_is_rejected():
    result = validate_conformity_line(_line(conforming_cartons=10.5))
    assert isinstance(result, Err)
    assert result.code == "QUANTITY_MUST_BE_INTEGER"


def test_non_conforming_cartons_requires_defect_details():
    result = validate_conformity_line(_line(non_conforming_cartons=3, defect_details=""))
    assert isinstance(result, Err)
    assert result.code == "MISSING_DEFECT_DETAILS"


def test_non_conforming_cartons_with_defect_details_is_valid():
    result = validate_conformity_line(_line(non_conforming_cartons=3, defect_details="soudure défectueuse"))
    assert isinstance(result, Ok)


def test_is_conforming_true_when_every_line_has_zero_defects():
    lines = [_line(id="a"), _line(id="b")]
    assert is_conforming(lines) is True


def test_is_conforming_false_when_any_line_has_a_defect():
    lines = [_line(id="a"), _line(id="b", non_conforming_cartons=1, defect_details="x")]
    assert is_conforming(lines) is False


def test_is_conforming_true_for_empty_lines():
    assert is_conforming([]) is True


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

import datetime

from core.domain.result import Err, Ok
from modules.production.domain.production_report import (
    DailyReportDetail,
    DowntimeLine,
    ProductionReport,
    SemolinaLine,
    downtime_total_minutes,
    transition_report,
    validate_daily_detail,
    validate_downtime_lines,
    validate_report_header,
)


def _report(status: str, revision: int = 1) -> ProductionReport:
    return ProductionReport(
        id="r1",
        of_id="of1",
        report_type="daily",
        report_date=datetime.date(2026, 8, 28),
        status=status,
        revision=revision,
    )


def test_draft_submits():
    result = transition_report(_report("draft"), "submitted")
    assert isinstance(result, Ok)
    assert result.value.status == "submitted"


def test_draft_cannot_skip_straight_to_validated():
    result = transition_report(_report("draft"), "validated")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_submitted_validates_or_rejects():
    assert isinstance(transition_report(_report("submitted"), "validated"), Ok)
    assert isinstance(transition_report(_report("submitted"), "rejected"), Ok)


def test_rejected_reopens_as_draft():
    result = transition_report(_report("rejected"), "draft")
    assert isinstance(result, Ok)
    assert result.value.status == "draft"


def test_rejected_cannot_be_validated_without_resubmission():
    result = transition_report(_report("rejected"), "validated")
    assert isinstance(result, Err)


def test_validated_is_terminal():
    # The guard that makes a retried validate harmless once validation posts stock.
    for target in ("draft", "submitted", "rejected", "validated"):
        assert isinstance(transition_report(_report("validated"), target), Err)


def test_transition_keeps_the_revision():
    result = transition_report(_report("draft", revision=3), "submitted")
    assert isinstance(result, Ok)
    assert result.value.revision == 3


def test_empty_daily_report_is_valid():
    # A shift that produced nothing is still a legitimate report.
    assert isinstance(validate_daily_detail(DailyReportDetail()), Ok)


def test_negative_quantity_is_rejected():
    result = validate_daily_detail(DailyReportDetail(regrind_input_quantity=-1))
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_a_negative_semolina_line_is_rejected():
    detail = DailyReportDetail(semolina_lines=(SemolinaLine(product_id="semoule", quantity=-1),))
    result = validate_daily_detail(detail)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_end_time_before_start_time_is_rejected():
    result = validate_daily_detail(
        DailyReportDetail(start_time=datetime.time(14, 0), end_time=datetime.time(6, 0))
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_TIME_RANGE"


def test_downtime_requires_a_reason():
    result = validate_daily_detail(DailyReportDetail(downtime_lines=(DowntimeLine(minutes=45),)))
    assert isinstance(result, Err)
    assert result.code == "MISSING_DOWNTIME_REASON"

    with_reason = validate_daily_detail(
        DailyReportDetail(downtime_lines=(DowntimeLine(minutes=45, motif="press jam"),))
    )
    assert isinstance(with_reason, Ok)


def test_gasoil_quantity_cannot_be_negative():
    result = validate_daily_detail(DailyReportDetail(gasoil_quantity=-1))
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_multiple_downtime_lines_with_different_motifs_are_all_valid():
    """The whole point of the list: a shift that stopped for two different
    reasons records both, rather than folding one into the other."""
    lines = (
        DowntimeLine(motif="mixer jam", minutes=20),
        DowntimeLine(motif="power cut", minutes=15),
    )
    assert isinstance(validate_downtime_lines(lines), Ok)
    assert isinstance(validate_daily_detail(DailyReportDetail(downtime_lines=lines)), Ok)


def test_a_negative_downtime_line_is_rejected():
    result = validate_downtime_lines((DowntimeLine(motif="x", minutes=-5),))
    assert isinstance(result, Err)
    assert result.code == "INVALID_DURATION"


def test_a_downtime_line_at_zero_needs_no_motif():
    """An untouched row in a form recorded no stoppage, so there is nothing to name."""
    assert isinstance(validate_downtime_lines((DowntimeLine(minutes=0),)), Ok)


def test_downtime_total_minutes_sums_every_line():
    lines = (DowntimeLine(motif="a", minutes=20), DowntimeLine(motif="b", minutes=15))
    assert downtime_total_minutes(lines) == 35


def test_downtime_total_minutes_of_no_lines_is_zero():
    assert downtime_total_minutes(()) == 0


def test_a_shortfall_never_invalidates_a_report():
    # Semoule is always treated as available: the report records what physically
    # happened, so no combination of figures is refused for being implausible.
    detail = DailyReportDetail(
        semolina_lines=(SemolinaLine(product_id="semoule", quantity=500),),
        finished_product_quantity=9000,
        regrind_quantity=120,
    )
    assert isinstance(validate_daily_detail(detail), Ok)


def test_header_rejects_an_unknown_report_type():
    result = validate_report_header(report_type="quality", of_id="of1")
    assert isinstance(result, Err)
    assert result.code == "INVALID_REPORT_TYPE"


def test_header_requires_an_of():
    result = validate_report_header(report_type="daily", of_id="  ")
    assert isinstance(result, Err)
    assert result.code == "MISSING_OF"

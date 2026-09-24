"""What a plant-defined déchet kind needs, without a database."""
from __future__ import annotations

from core.domain.result import Err, Ok
from modules.production.domain.waste_type import validate_waste_type


def test_a_name_and_a_report_are_all_a_waste_type_needs():
    result = validate_waste_type(name="Déchet PF fab", report_type="daily")
    assert isinstance(result, Ok)
    assert result.value == "Déchet PF fab"


def test_the_name_is_trimmed():
    result = validate_waste_type(name="  Pâte non conforme  ", report_type="daily")
    assert isinstance(result, Ok)
    assert result.value == "Pâte non conforme"


def test_a_blank_name_is_refused():
    for blank in ("", "   "):
        result = validate_waste_type(name=blank, report_type="daily")
        assert isinstance(result, Err)
        assert result.code == "INVALID_NAME"


def test_only_the_two_reports_can_carry_a_waste_type():
    for report_type in ("daily", "conditionnement"):
        assert isinstance(validate_waste_type(name="x", report_type=report_type), Ok)
    result = validate_waste_type(name="x", report_type="quality")
    assert isinstance(result, Err)
    assert result.code == "INVALID_REPORT_TYPE"

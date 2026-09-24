from core.domain.result import Err, Ok
from modules.maintenance.domain.equipment import (
    PRODUCTION_STAGES,
    Equipment,
    transition_equipment,
    validate_equipment_code,
    validate_production_stage,
)


def _equipment(status: str = "operational", production_stage: str | None = None) -> Equipment:
    return Equipment(id="1", work_center_id="wc1", code="M-1", name="Mixer 1", status=status, production_stage=production_stage)


def test_operational_equipment_can_go_down():
    result = transition_equipment(_equipment(), "down")
    assert isinstance(result, Ok)
    assert result.value.status == "down"


def test_down_equipment_can_return_to_operational():
    result = transition_equipment(_equipment("down"), "operational")
    assert isinstance(result, Ok)
    assert result.value.status == "operational"


def test_maintenance_equipment_cannot_go_directly_down():
    result = transition_equipment(_equipment("maintenance"), "down")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_blank_code_is_invalid():
    result = validate_equipment_code("")
    assert isinstance(result, Err)
    assert result.code == "INVALID_CODE"


def test_production_stages_are_listed_in_the_order_a_line_runs_them():
    assert PRODUCTION_STAGES == ("versement", "extrusion", "conditionnement")


def test_a_machine_may_work_at_no_stage_or_at_one_of_the_three():
    assert isinstance(validate_production_stage(None), Ok)
    for stage in PRODUCTION_STAGES:
        assert isinstance(validate_production_stage(stage), Ok)


def test_a_stage_outside_the_three_is_invalid():
    result = validate_production_stage("drying")
    assert isinstance(result, Err)
    assert result.code == "INVALID_STAGE"


def test_a_machine_keeps_its_stage_through_a_status_change():
    result = transition_equipment(_equipment(production_stage="extrusion"), "maintenance")
    assert isinstance(result, Ok)
    assert result.value.status == "maintenance"
    assert result.value.production_stage == "extrusion"

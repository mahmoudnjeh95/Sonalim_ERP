from __future__ import annotations

from core.domain.result import Err, Ok
from modules.warehouse.domain.replenishment import (
    needs_replenishment,
    proposal_quantity,
    validate_proposal_decision,
    validate_rule,
)


def test_a_rule_needs_its_max_above_its_min():
    assert validate_rule(reorder_point=100, order_up_to=500, min_order_quantity=0) == Ok(None)
    result = validate_rule(reorder_point=100, order_up_to=100, min_order_quantity=0)
    assert isinstance(result, Err) and result.code == "INVALID_RULE"


def test_negative_levels_are_refused():
    assert isinstance(validate_rule(reorder_point=-1, order_up_to=10, min_order_quantity=0), Err)


def test_replenishment_triggers_at_the_reorder_point():
    assert needs_replenishment(available=100, reorder_point=100)
    assert not needs_replenishment(available=100.5, reorder_point=100)


def test_the_proposal_orders_back_up_to_the_max():
    assert proposal_quantity(available=80, order_up_to=500, min_order_quantity=0, integer_only=False) == 420


def test_the_supplier_minimum_wins_when_larger():
    assert proposal_quantity(available=480, order_up_to=500, min_order_quantity=100, integer_only=False) == 100


def test_negative_availability_is_topped_up_fully():
    assert proposal_quantity(available=-20, order_up_to=500, min_order_quantity=0, integer_only=False) == 520


def test_a_whole_count_unit_rounds_up():
    assert proposal_quantity(available=0.5, order_up_to=10, min_order_quantity=0, integer_only=True) == 10
    assert proposal_quantity(available=2.5, order_up_to=10, min_order_quantity=0, integer_only=True) == 8


def test_only_an_open_proposal_can_be_decided():
    assert validate_proposal_decision("open") == Ok(None)
    assert isinstance(validate_proposal_decision("approved"), Err)

from __future__ import annotations

import datetime

from core.domain.result import Err, Ok
from modules.warehouse.domain.fulfillment import (
    PickListLine,
    aggregate_order_lines,
    check_picking_complete,
    transition_pick_list,
    validate_packing,
    validate_picked_quantity,
)


def _line(requested: float, picked: float | None) -> PickListLine:
    return PickListLine(
        id="l", tenant_id="t", pick_list_id="p", product_id="x", quantity_requested=requested,
        quantity_picked=picked, picked_by=None, picked_at=datetime.datetime(2026, 1, 1),
    )


def test_the_lifecycle_runs_open_picking_picked_shipped():
    assert transition_pick_list("open", "picking") == Ok("picking")
    assert transition_pick_list("picking", "picked") == Ok("picked")
    assert transition_pick_list("picked", "shipped") == Ok("shipped")


def test_a_shipped_pick_list_cannot_be_cancelled():
    result = transition_pick_list("shipped", "cancelled")
    assert isinstance(result, Err) and result.code == "INVALID_TRANSITION"


def test_picking_cannot_be_skipped():
    assert isinstance(transition_pick_list("open", "shipped"), Err)


def test_duplicate_order_lines_for_one_product_add_up():
    totals = aggregate_order_lines(
        [{"product_id": "a", "quantity": 10}, {"product_id": "b", "quantity": 2}, {"product_id": "a", "quantity": 5}]
    )
    assert totals == {"a": 15.0, "b": 2.0}


def test_zero_quantity_order_lines_are_dropped():
    assert aggregate_order_lines([{"product_id": "a", "quantity": 0}]) == {}


def test_a_short_pick_is_allowed():
    assert validate_picked_quantity(quantity_picked=3, quantity_requested=5) == Ok(None)


def test_over_picking_is_refused():
    result = validate_picked_quantity(quantity_picked=6, quantity_requested=5)
    assert isinstance(result, Err) and result.code == "OVER_PICK"


def test_a_negative_pick_is_refused():
    assert isinstance(validate_picked_quantity(quantity_picked=-1, quantity_requested=5), Err)


def test_picking_is_incomplete_while_a_line_is_unpicked():
    result = check_picking_complete([_line(5, 5), _line(3, None)])
    assert isinstance(result, Err) and result.code == "LINES_UNPICKED"


def test_picking_nothing_at_all_is_refused():
    result = check_picking_complete([_line(5, 0), _line(3, 0)])
    assert isinstance(result, Err) and result.code == "NOTHING_PICKED"


def test_a_partial_pick_completes():
    assert check_picking_complete([_line(5, 5), _line(3, 0)]) == Ok(None)


def test_packing_needs_at_least_one_package():
    assert isinstance(validate_packing(package_count=0, total_weight_kg=None), Err)
    assert validate_packing(package_count=2, total_weight_kg=12.5) == Ok(None)


def test_packing_weight_cannot_be_negative():
    assert isinstance(validate_packing(package_count=1, total_weight_kg=-1), Err)

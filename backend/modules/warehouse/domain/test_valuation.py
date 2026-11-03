from __future__ import annotations

import datetime

from modules.warehouse.domain.valuation import (
    Allocation,
    CostLayer,
    allocate_fifo,
    allocation_cost,
    value_layers,
)


def test_consumption_draws_the_oldest_layer_first():
    allocations = allocate_fifo([("old", 10, 100.0), ("new", 10, 150.0)], 15)
    assert allocations == [Allocation("old", 10, 100.0), Allocation("new", 5, 150.0)]
    assert allocation_cost(allocations) == (1750.0, 0)


def test_exhausted_layers_are_skipped():
    assert allocate_fifo([("empty", 0, 90.0), ("next", 4, 100.0)], 3) == [Allocation("next", 3, 100.0)]


def test_a_shortfall_is_recorded_not_dropped():
    allocations = allocate_fifo([("only", 4, 100.0)], 6)
    assert allocations == [Allocation("only", 4, 100.0), Allocation(None, 2, None)]
    assert allocation_cost(allocations) == (400.0, 2)


def test_an_uncosted_layer_is_counted_but_not_valued():
    allocations = allocate_fifo([("uncosted", 5, None), ("costed", 5, 200.0)], 7)
    assert allocation_cost(allocations) == (400.0, 5)


def _layer(remaining, unit_cost):
    return CostLayer(
        id="l", tenant_id="t", product_id="p", reference="r", move_type="receipt", quantity_in=remaining,
        quantity_remaining=remaining, unit_cost=unit_cost, received_at=datetime.datetime(2026, 1, 1),
    )


def test_valuation_sums_remaining_quantity_at_layer_cost():
    valuation = value_layers("p", [_layer(10, 100.0), _layer(5, 160.0), _layer(3, None)])
    assert (valuation.quantity, valuation.value, valuation.unvalued_quantity) == (18, 1800.0, 3)
    assert valuation.average_unit_cost == 120.0


def test_an_all_unvalued_product_has_no_average_cost():
    assert value_layers("p", [_layer(3, None)]).average_unit_cost is None

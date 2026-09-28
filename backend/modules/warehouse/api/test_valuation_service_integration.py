"""Integration tests for FIFO cost layers, driven through StockService the way
every real movement is -- the layers must follow the stock without any
caller having to remember them."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.warehouse.api.service import StockService
from modules.warehouse.api.valuation_service import ValuationService

TENANT = "integration-test-valuation"


@pytest.fixture
def env(db):
    actor, uom, product, uncosted, loc_a, loc_b = (str(ULID()) for _ in range(6))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, purchase_price) VALUES (%s, %s, 'VAL-SEMO', 'Semolina', %s, 90)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'VAL-NOCOST', 'No cost', %s)",
        (uncosted, TENANT, uom),
    )
    for location in (loc_a, loc_b):
        db.execute(
            "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Loc')", (location, TENANT, str(ULID()))
        )
    return {"actor": actor, "product": product, "uncosted": uncosted, "a": loc_a, "b": loc_b}


def _receive(db, env, quantity, unit_cost=None, product=None, location=None):
    result = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product or env["product"], location_id=location or env["a"], quantity=quantity,
        correlation_id=str(ULID()), reference=f"test_receipt:{ULID()}", actor_id=env["actor"], unit_cost=unit_cost,
    )
    assert isinstance(result, Ok), getattr(result, "message", "")


def _valuation(db, product):
    [valuation] = [v for v in ValuationService(db).get_valuation(tenant_id=TENANT) if v.product_id == product]
    return valuation


def test_a_receipt_opens_a_layer_at_its_landed_cost(db, env):
    _receive(db, env, 100, unit_cost=120)
    valuation = _valuation(db, env["product"])
    assert (valuation.quantity, valuation.value, valuation.average_unit_cost) == (100, 12000, 120)


def test_without_a_landed_cost_the_catalog_price_stands_in(db, env):
    _receive(db, env, 10)
    assert _valuation(db, env["product"]).value == 900


def test_without_any_cost_stock_is_counted_but_unvalued(db, env):
    _receive(db, env, 10, product=env["uncosted"])
    valuation = _valuation(db, env["uncosted"])
    assert (valuation.quantity, valuation.value, valuation.unvalued_quantity) == (10, 0, 10)


def test_an_issue_draws_the_oldest_layer_first_and_its_cost_is_recorded(db, env):
    _receive(db, env, 10, unit_cost=100)
    _receive(db, env, 10, unit_cost=150)
    StockService(db).issue_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["a"], quantity=15, reference="shipment:TEST1",
        actor_id=env["actor"], move_type="shipment",
    )
    assert _valuation(db, env["product"]).value == 5 * 150
    cost = ValuationService(db).cost_of_reference(tenant_id=TENANT, reference="shipment:TEST1")
    assert (cost["quantity"], cost["cost"], cost["unvalued_quantity"]) == (15, 10 * 100 + 5 * 150, 0)


def test_a_transfer_between_bins_leaves_valuation_untouched(db, env):
    _receive(db, env, 10, unit_cost=100)
    StockService(db).transfer_stock(
        tenant_id=TENANT, product_id=env["product"], from_location_id=env["a"], to_location_id=env["b"], quantity=4,
        correlation_id=str(ULID()), reference="move", actor_id=env["actor"],
    )
    layers = ValuationService(db).list_layers(tenant_id=TENANT, product_id=env["product"])
    assert [(layer.quantity_remaining, layer.unit_cost) for layer in layers] == [(10, 100)]


def test_sending_to_production_is_neutral_and_consumption_draws_down(db, env):
    _receive(db, env, 10, unit_cost=100)
    stock = StockService(db)
    stock.send_to_production_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["a"], quantity=6, reference="of:1", actor_id=env["actor"]
    )
    assert _valuation(db, env["product"]).quantity == 10
    stock.consume_in_production_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["a"], quantity=6, reference="of:1", actor_id=env["actor"]
    )
    assert _valuation(db, env["product"]).quantity == 4


def test_a_negative_adjustment_consumes_and_a_positive_one_opens_a_layer(db, env):
    _receive(db, env, 10, unit_cost=100)
    stock = StockService(db)
    stock.adjust_stock(tenant_id=TENANT, product_id=env["product"], location_id=env["a"], delta=-3, reason="breakage", actor_id=env["actor"])
    stock.adjust_stock(tenant_id=TENANT, product_id=env["product"], location_id=env["a"], delta=2, reason="found", actor_id=env["actor"])
    valuation = _valuation(db, env["product"])
    # 7 left at 100, plus 2 found valued at the catalog price (90).
    assert (valuation.quantity, valuation.value) == (9, 7 * 100 + 2 * 90)


def test_a_production_withdrawal_beyond_the_books_records_an_unvalued_shortfall(db, env):
    _receive(db, env, 4, unit_cost=100)
    result = StockService(db).post_production_movement(
        tenant_id=TENANT, product_id=env["product"], location_id=env["a"], quantity=6, direction="out",
        correlation_id=str(ULID()), reference="production_report:X", move_type="production_consumption",
    )
    assert isinstance(result, Ok)
    cost = ValuationService(db).cost_of_reference(tenant_id=TENANT, reference="production_report:X")
    assert (cost["cost"], cost["unvalued_quantity"]) == (400, 2)
    assert not [v for v in ValuationService(db).get_valuation(tenant_id=TENANT) if v.product_id == env["product"]]

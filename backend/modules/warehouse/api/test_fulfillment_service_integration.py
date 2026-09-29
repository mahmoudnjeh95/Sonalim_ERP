"""Integration tests for outbound fulfillment against a real database.

The pick list is opened by the sales.order.confirmed consumer; sales has
already reserved the stock by then, so the fixture reserves it the same way
(StockService.reserve_stock under the order's reference) instead of going
through sales -- this module's tests stay inside this module.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.events.consumers import _process, _registry
from modules.warehouse.api.fulfillment_service import FulfillmentService
from modules.warehouse.api.service import StockService
from modules.warehouse.events.consumers import SALES_ORDER_CONFIRMED_CONSUMER_NAME, _handle_sales_order_confirmed

TENANT = "integration-test-fulfillment"


@pytest.fixture
def env(db):
    actor, uom, pasta, flour, partner, location = (str(ULID()) for _ in range(6))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'FF-PASTA', 'Pasta', %s)", (pasta, TENANT, uom))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'FF-FLOUR', 'Flour', %s)", (flour, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Acme', 'customer')", (partner, TENANT))
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Finished goods')",
        (location, TENANT, str(ULID())),
    )
    stock = StockService(db)
    for product in (pasta, flour):
        stock.receive_stock(
            tenant_id=TENANT, product_id=product, location_id=location, quantity=100, correlation_id=str(ULID()),
            reference="setup", actor_id=actor,
        )
    order_id = str(ULID())
    reference = f"sales_order:{order_id}"
    # The order lists pasta twice -- sales reserves per line.
    for product, quantity in ((pasta, 20), (pasta, 10), (flour, 5)):
        stock.reserve_stock(
            tenant_id=TENANT, product_id=product, location_id=location, quantity=quantity, correlation_id=str(ULID()),
            reference=reference, actor_id=actor,
        )
    return {"actor": actor, "pasta": pasta, "flour": flour, "partner": partner, "location": location, "order_id": order_id}


def _envelope(env, *, event_id: str | None = None, version: str = "1.1") -> dict:
    payload = {"order_id": env["order_id"], "partner_id": env["partner"], "total_amount": 0, "currency": "XOF"}
    if version == "1.1":
        payload |= {
            "location_id": env["location"],
            "reservation_reference": f"sales_order:{env['order_id']}",
            "lines": [
                {"product_id": env["pasta"], "quantity": 20},
                {"product_id": env["pasta"], "quantity": 10},
                {"product_id": env["flour"], "quantity": 5},
            ],
        }
    return {
        "event_id": event_id or str(ULID()),
        "event_type": "sales.order.confirmed",
        "event_version": version,
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "payload": payload,
    }


def _open_pick_list(db, env):
    _handle_sales_order_confirmed(db, _envelope(env))
    [pick_list] = [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == env["order_id"]]
    return pick_list


def _level(db, env, product):
    [level] = [s for s in StockService(db).list_stock_items(TENANT, location_id=env["location"]) if s.product_id == product]
    return level


def _pick_everything(db, env, pick_list, quantities: dict[str, float]):
    service = FulfillmentService(db)
    for line in service.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id):
        result = service.submit_pick(
            tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=line.id,
            quantity_picked=quantities[line.product_id],
        )
        assert isinstance(result, Ok), getattr(result, "message", "")


def test_a_confirmed_order_opens_a_pick_list_with_one_line_per_product(db, env):
    pick_list = _open_pick_list(db, env)
    assert pick_list.status == "open"
    assert pick_list.number.startswith("PK-")
    lines = {line.product_id: line.quantity_requested for line in FulfillmentService(db).list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id)}
    assert lines == {env["pasta"]: 30.0, env["flour"]: 5.0}


def test_a_redelivered_confirmation_does_not_open_a_second_pick_list(db, env):
    _handle_sales_order_confirmed(db, _envelope(env))
    _handle_sales_order_confirmed(db, _envelope(env))
    matching = [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == env["order_id"]]
    assert len(matching) == 1


def test_an_already_processed_event_is_skipped(db, env):
    """Asserted through the skip path: `_process` commits after a handler
    that runs, which would defeat the rollback fixture. Every consumer of the
    event is marked processed (finance listens too), so none of them runs."""
    event_id = str(ULID())
    consumer_names = [name for name, _ in _registry.get("sales.order.confirmed", [])]
    assert SALES_ORDER_CONFIRMED_CONSUMER_NAME in consumer_names
    for name in consumer_names:
        db.execute("INSERT INTO events.processed_events (event_id, consumer) VALUES (%s, %s)", (event_id, name))

    assert _process(db, _envelope(env, event_id=event_id))
    assert not [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == env["order_id"]]


def test_a_version_1_0_event_without_lines_is_skipped(db, env):
    _handle_sales_order_confirmed(db, _envelope(env, version="1.0"))
    assert not [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == env["order_id"]]


def test_the_first_pick_moves_the_list_to_picking(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    line = service.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id)[0]
    service.submit_pick(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=line.id, quantity_picked=1)
    assert service.get_pick_list(tenant_id=TENANT, pick_list_id=pick_list.id).value.status == "picking"


def test_over_picking_is_refused(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    [pasta_line] = [l for l in service.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id) if l.product_id == env["pasta"]]
    result = service.submit_pick(
        tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=pasta_line.id, quantity_picked=31
    )
    assert isinstance(result, Err) and result.code == "OVER_PICK"


def test_picking_cannot_close_with_an_unpicked_line(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    [pasta_line] = [l for l in service.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id) if l.product_id == env["pasta"]]
    service.submit_pick(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=pasta_line.id, quantity_picked=30)
    result = service.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id)
    assert isinstance(result, Err) and result.code == "LINES_UNPICKED"


def test_only_a_picked_list_can_be_packed(db, env):
    pick_list = _open_pick_list(db, env)
    result = FulfillmentService(db).pack(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=1)
    assert isinstance(result, Err) and result.code == "INVALID_STATE"


def test_shipping_issues_what_was_picked_and_releases_the_whole_reservation(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    # A short pick on pasta: 25 of 30.
    _pick_everything(db, env, pick_list, {env["pasta"]: 25, env["flour"]: 5})
    assert isinstance(service.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id), Ok)

    # Picking alone moves nothing on the books.
    assert _level(db, env, env["pasta"]).quantity_on_hand == 100
    assert _level(db, env, env["pasta"]).quantity_reserved == 30

    shipment = service.pack(
        tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=3, total_weight_kg=31.5,
        carrier="Transports Diallo",
    )
    assert isinstance(shipment, Ok), getattr(shipment, "message", "")
    assert shipment.value.number.startswith("SH-")

    shipped = service.ship(tenant_id=TENANT, actor_id=env["actor"], shipment_id=shipment.value.id, correlation_id=str(ULID()))
    assert isinstance(shipped, Ok), getattr(shipped, "message", "")
    assert shipped.value.status == "shipped"

    pasta = _level(db, env, env["pasta"])
    assert (pasta.quantity_on_hand, pasta.quantity_reserved) == (75, 0)
    flour = _level(db, env, env["flour"])
    assert (flour.quantity_on_hand, flour.quantity_reserved) == (95, 0)
    assert service.get_pick_list(tenant_id=TENANT, pick_list_id=pick_list.id).value.status == "shipped"

    event = db.execute(
        "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'warehouse.shipment.shipped' ORDER BY event_id DESC LIMIT 1",
        (TENANT,),
    ).fetchone()[0]
    assert event["payload"]["source_id"] == env["order_id"]
    shipped_by_product = {line["product_id"]: line["quantity_shipped"] for line in event["payload"]["lines"]}
    assert shipped_by_product == {env["pasta"]: 25, env["flour"]: 5}


def test_a_shipment_cannot_ship_twice(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    _pick_everything(db, env, pick_list, {env["pasta"]: 30, env["flour"]: 5})
    service.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id)
    shipment = service.pack(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=1).value
    service.ship(tenant_id=TENANT, actor_id=env["actor"], shipment_id=shipment.id, correlation_id=str(ULID()))
    again = service.ship(tenant_id=TENANT, actor_id=env["actor"], shipment_id=shipment.id, correlation_id=str(ULID()))
    assert isinstance(again, Err) and again.code == "INVALID_STATE"
    assert _level(db, env, env["pasta"]).quantity_on_hand == 70


def test_cancelling_a_pick_list_releases_its_reservation(db, env):
    pick_list = _open_pick_list(db, env)
    result = FulfillmentService(db).cancel_pick_list(
        tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, correlation_id=str(ULID())
    )
    assert isinstance(result, Ok) and result.value.status == "cancelled"
    assert _level(db, env, env["pasta"]).quantity_reserved == 0
    assert _level(db, env, env["pasta"]).quantity_on_hand == 100


def test_a_packed_pick_list_cannot_be_cancelled(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    _pick_everything(db, env, pick_list, {env["pasta"]: 30, env["flour"]: 5})
    service.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id)
    service.pack(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=1)
    result = service.cancel_pick_list(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, correlation_id=str(ULID()))
    assert isinstance(result, Err) and result.code == "ALREADY_PACKED"


def test_admin_update_edits_only_the_given_fields_and_is_audited(db, env):
    pick_list = _open_pick_list(db, env)
    service = FulfillmentService(db)
    _pick_everything(db, env, pick_list, {env["pasta"]: 30, env["flour"]: 5})
    service.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id)
    shipment = service.pack(
        tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=2, carrier="A"
    ).value

    updated = service.admin_update_shipment(
        tenant_id=TENANT, actor_id=env["actor"], shipment_id=shipment.id, tracking_reference="TRK-1"
    )
    assert isinstance(updated, Ok)
    assert (updated.value.package_count, updated.value.carrier, updated.value.tracking_reference) == (2, "A", "TRK-1")
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'shipment.updated'",
        (TENANT, shipment.id),
    ).fetchone()
    assert audit[0] == {"tracking_reference": "TRK-1"}

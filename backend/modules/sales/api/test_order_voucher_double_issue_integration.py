"""Integration test: a confirmed sales order can leave the warehouse by two routes that don't know
about each other. The fulfillment flow (pick list, pack, ship) issues the stock; an issue voucher
drafted from the same order would issue it again. The voucher's order cap only counts other vouchers,
and its availability check only looks at stock not reserved, so surplus stock would let it through.
voucher_service refuses such an order with ORDER_IN_FULFILLMENT."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.sales.events.consumers import _handle_shipment_shipped
from modules.warehouse.api.fulfillment_service import FulfillmentService
from modules.warehouse.api.reservation_service import ReservationService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.voucher_service import VoucherService
from modules.warehouse.events.consumers import _handle_sales_order_confirmed

TENANT = "integration-test-order-voucher"
ORDERED = 30


@pytest.fixture
def env(db):
    actor, uom, product, partner, location = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'OV-PASTA', 'Pasta', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Acme', 'customer')", (partner, TENANT))
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Finished goods')",
        (location, TENANT, str(ULID())),
    )
    return {"actor": actor, "product": product, "partner": partner, "location": location}


def _confirmed_order(db, env, *, stock: float) -> str:
    received = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=stock,
        correlation_id=str(ULID()), reference="setup", actor_id=env["actor"],
    )
    assert isinstance(received, Ok)
    sales = SalesOrderService(db)
    order = sales.create_order(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=ORDERED, unit_price=100.0)],
    )
    confirmed = sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id=str(ULID()))
    assert isinstance(confirmed, Ok)
    _handle_sales_order_confirmed(db, _outbox_envelope(db, "sales.order.confirmed", "order_id", order.id))
    return order.id


def _outbox_envelope(db, event_type: str, key: str, value: str) -> dict:
    row = db.execute(
        "SELECT payload FROM events.outbox WHERE payload->>'event_type' = %s AND payload->'payload'->>%s = %s",
        (event_type, key, value),
    ).fetchone()
    return row[0]


def _ship(db, env, order_id: str) -> None:
    """The remote fulfillment flow, end to end, through the same consumers the worker runs."""
    fulfillment = FulfillmentService(db)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    for line in fulfillment.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id):
        picked = fulfillment.submit_pick(
            tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=line.id,
            quantity_picked=line.quantity_requested,
        )
        assert isinstance(picked, Ok)
    assert isinstance(fulfillment.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id), Ok)
    shipment = fulfillment.pack(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=1)
    assert isinstance(shipment, Ok)
    shipped = fulfillment.ship(tenant_id=TENANT, actor_id=env["actor"], shipment_id=shipment.value.id, correlation_id=str(ULID()))
    assert isinstance(shipped, Ok)
    _handle_shipment_shipped(db, _outbox_envelope(db, "warehouse.shipment.shipped", "shipment_id", shipment.value.id))


def _post_voucher_from_order(db, env, order_id: str) -> Ok | Err:
    vouchers = VoucherService(db)
    draft = vouchers.create_issue_from_order(
        tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["location"]
    )
    if isinstance(draft, Err):
        return draft
    return vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id=str(ULID()))


def _levels(db, env) -> tuple[float, float]:
    on_hand, reserved = db.execute(
        "SELECT quantity_on_hand, quantity_reserved FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, env["product"], env["location"]),
    ).fetchone()
    return float(on_hand), float(reserved)


def test_shipping_alone_issues_the_order_once(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    assert _levels(db, env) == (100, ORDERED)

    _ship(db, env, order_id)

    assert _levels(db, env) == (100 - ORDERED, 0)
    assert db.execute("SELECT status FROM sales.orders WHERE id = %s", (order_id,)).fetchone()[0] == "shipped"


def test_a_voucher_after_the_shipment_does_not_issue_the_goods_again(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    _ship(db, env, order_id)

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Err) and posted.code == "ORDER_IN_FULFILLMENT"
    assert _levels(db, env) == (100 - ORDERED, 0)


def test_a_voucher_before_the_shipment_does_not_issue_the_goods_twice(db, env):
    order_id = _confirmed_order(db, env, stock=100)

    posted = _post_voucher_from_order(db, env, order_id)
    assert isinstance(posted, Err) and posted.code == "ORDER_IN_FULFILLMENT"
    fulfillment_can_ship = [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    assert fulfillment_can_ship
    _ship(db, env, order_id)

    assert _levels(db, env) == (100 - ORDERED, 0)


def test_without_surplus_stock_the_voucher_is_refused_the_same_way(db, env):
    order_id = _confirmed_order(db, env, stock=ORDERED)

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Err) and posted.code == "ORDER_IN_FULFILLMENT"
    assert _levels(db, env) == (ORDERED, ORDERED)


def test_restarting_fulfilment_after_a_voucher_cannot_issue_the_goods_again(db, env):
    """Cancelled pick list, voucher posted: the cancelled list is final, and an order can't be re-confirmed."""
    order_id = _confirmed_order(db, env, stock=100)
    fulfillment = FulfillmentService(db)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    assert isinstance(fulfillment.cancel_pick_list(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, correlation_id=str(ULID())), Ok)
    assert isinstance(_post_voucher_from_order(db, env, order_id), Ok)
    assert _levels(db, env) == (100 - ORDERED, 0)

    _handle_sales_order_confirmed(db, _outbox_envelope(db, "sales.order.confirmed", "order_id", order_id))  # redelivered
    reconfirmed = SalesOrderService(db).confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, correlation_id=str(ULID()))

    assert isinstance(reconfirmed, Err)
    assert [p.status for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id] == ["cancelled"]
    assert _levels(db, env) == (100 - ORDERED, 0)


def test_a_late_confirmation_event_opens_no_pick_list_on_an_order_a_voucher_already_issued(db, env):
    """Regression: reservation released by hand before the worker ran, voucher posted, then the event.
    The pick list opened and shipping issued the order again: 100 received, 30 + 30 ordered, on hand
    40 and the other order's hold gone, where 70 on hand and 30 reserved is right."""
    received = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=100,
        correlation_id=str(ULID()), reference="setup", actor_id=env["actor"],
    )
    assert isinstance(received, Ok)
    sales = SalesOrderService(db)
    orders = [
        sales.create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
                           lines=[OrderLine(product_id=env["product"], quantity=ORDERED, unit_price=100.0)])
        for _ in range(2)
    ]
    for order in orders:
        assert isinstance(sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id=str(ULID())), Ok)
    issued_order = orders[0].id
    reservations = ReservationService(db)
    [held] = [r for r in reservations.list_reservations(tenant_id=TENANT) if r.reference == f"sales_order:{issued_order}"]
    assert isinstance(reservations.release_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=held.id), Ok)
    assert isinstance(_post_voucher_from_order(db, env, issued_order), Ok)

    _handle_sales_order_confirmed(db, _outbox_envelope(db, "sales.order.confirmed", "order_id", issued_order))  # acknowledged, no raise

    assert not [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == issued_order]
    assert _levels(db, env) == (100 - ORDERED, ORDERED)


def test_a_reservation_alone_is_enough_to_refuse_the_voucher(db, env):
    """The window between confirming the order and the worker creating its pick list."""
    received = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=100,
        correlation_id=str(ULID()), reference="setup", actor_id=env["actor"],
    )
    assert isinstance(received, Ok)
    sales = SalesOrderService(db)
    order = sales.create_order(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=ORDERED, unit_price=100.0)],
    )
    assert isinstance(sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id=str(ULID())), Ok)

    assert not [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == order.id]
    posted = _post_voucher_from_order(db, env, order.id)

    assert isinstance(posted, Err) and posted.code == "ORDER_IN_FULFILLMENT"


def test_a_cancelled_pick_list_with_no_reservation_left_lets_the_voucher_through(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    db.execute("UPDATE warehouse.pick_lists SET status = 'cancelled' WHERE tenant_id = %s AND source_id = %s", (TENANT, order_id))
    db.execute(
        "UPDATE warehouse.stock_reservations SET status = 'released', quantity_open = 0 WHERE tenant_id = %s AND reference = %s",
        (TENANT, f"sales_order:{order_id}"),
    )
    db.execute(
        "UPDATE warehouse.stock_items SET quantity_reserved = 0 WHERE tenant_id = %s AND product_id = %s",
        (TENANT, env["product"]),
    )

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Ok), posted
    assert _levels(db, env) == (100 - ORDERED, 0)

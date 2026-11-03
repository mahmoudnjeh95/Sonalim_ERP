"""Integration test: a confirmed sales order can leave the warehouse by two routes that don't know
about each other. The fulfillment flow (pick list, pack, ship) issues the stock; an issue voucher
drafted from the same order issues it again. The voucher's order cap only counts other vouchers,
and its availability check only looks at stock not reserved, so surplus stock lets it through.

The two xfail tests state the correct outcome. They are strict, so the refusal in voucher_service
turns them into failures until the marker comes off."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.sales.events.consumers import _handle_shipment_shipped
from modules.warehouse.api.fulfillment_service import FulfillmentService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.voucher_service import VoucherService
from modules.warehouse.events.consumers import _handle_sales_order_confirmed

TENANT = "integration-test-order-voucher"
ORDERED = 30

double_issue = pytest.mark.xfail(
    strict=True,
    reason="voucher_service does not refuse an order that fulfillment holds or has shipped",
)


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


@double_issue
def test_a_voucher_after_the_shipment_does_not_issue_the_goods_again(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    _ship(db, env, order_id)

    _post_voucher_from_order(db, env, order_id)

    assert _levels(db, env) == (100 - ORDERED, 0)


@double_issue
def test_a_voucher_before_the_shipment_does_not_issue_the_goods_twice(db, env):
    order_id = _confirmed_order(db, env, stock=100)

    _post_voucher_from_order(db, env, order_id)
    fulfillment_can_ship = [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    assert fulfillment_can_ship
    _ship(db, env, order_id)

    assert _levels(db, env) == (100 - ORDERED, 0)


def test_without_surplus_stock_the_voucher_is_already_refused(db, env):
    """Why this stays unnoticed in a small test: the reservation hides the order's own stock from
    the voucher, so only stock beyond the order lets the second issue through."""
    order_id = _confirmed_order(db, env, stock=ORDERED)

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Err)
    assert _levels(db, env) == (ORDERED, ORDERED)

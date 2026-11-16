"""Integration test: a confirmed sales order can leave the warehouse by two routes that don't know
about each other. The fulfillment flow (pick list, pack, ship) issues the stock; an issue voucher
drafted from the same order would issue it again. The voucher's order cap only counts other vouchers,
and its availability check only looks at stock not reserved, so surplus stock would let it through.
voucher_service refuses such an order with ORDER_IN_FULFILLMENT."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.sales.events.consumers import _handle_shipment_shipped, _handle_voucher_posted
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


def test_a_voucher_takes_over_from_a_pick_list_nobody_started_and_issues_the_goods_once(db, env):
    order_id = _confirmed_order(db, env, stock=100)

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Ok), posted
    assert [p.status for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == order_id] == ["cancelled"]
    assert _levels(db, env) == (100 - ORDERED, 0)


def test_a_voucher_is_refused_once_someone_has_started_picking(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    fulfillment = FulfillmentService(db)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    [line] = fulfillment.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id)
    assert isinstance(fulfillment.submit_pick(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=line.id,
                                              quantity_picked=1), Ok)

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Err) and posted.code == "ORDER_IN_FULFILLMENT"
    assert _levels(db, env) == (100, ORDERED)


def test_without_surplus_stock_the_voucher_issues_what_was_reserved_for_the_order(db, env):
    order_id = _confirmed_order(db, env, stock=ORDERED)

    posted = _post_voucher_from_order(db, env, order_id)

    assert isinstance(posted, Ok), posted
    assert _levels(db, env) == (0, 0)


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


def _order_status(db, order_id):
    return db.execute("SELECT status FROM sales.orders WHERE id = %s", (order_id,)).fetchone()[0]


def _ledger_row(db, order_id):
    return db.execute(
        "SELECT id, status, quantity_open FROM warehouse.stock_reservations WHERE tenant_id = %s AND reference = %s",
        (TENANT, f"sales_order:{order_id}"),
    ).fetchone()


def _second_order_holding(db, env, *, stock):
    """Another order reserved at the same location, its pick list not yet opened."""
    assert isinstance(StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=stock,
        correlation_id=str(ULID()), reference="more", actor_id=env["actor"],
    ), Ok)
    sales = SalesOrderService(db)
    order = sales.create_order(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=ORDERED, unit_price=100.0)],
    )
    assert isinstance(sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id=str(ULID())), Ok)
    return order.id


def _break_hold_as_an_older_release_did(db, order_id):
    """The state a manual release could leave before it was refused: ledger closed, counter given back."""
    reservation_id, _, open_quantity = _ledger_row(db, order_id)
    db.execute("UPDATE warehouse.stock_reservations SET status = 'released', quantity_open = 0, closed_at = NOW() WHERE id = %s", (reservation_id,))
    db.execute(
        "UPDATE warehouse.stock_items SET quantity_reserved = quantity_reserved - %s WHERE tenant_id = %s",
        (open_quantity, TENANT),
    )


def test_a_reservation_under_a_pick_list_cannot_be_released_by_hand_until_the_list_lets_go(db, env):
    """Regression: the release left the voucher refused and the pick list unable to cancel or ship."""
    order_id = _confirmed_order(db, env, stock=100)
    reservations, fulfillment = ReservationService(db), FulfillmentService(db)
    reservation_id = _ledger_row(db, order_id)[0]

    refused = reservations.release_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=reservation_id)

    assert isinstance(refused, Err) and refused.code == "RESERVATION_IN_FULFILLMENT"
    assert _levels(db, env) == (100, ORDERED)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    assert pick_list.number in refused.message and pick_list.number in refused.message_fr
    assert isinstance(fulfillment.cancel_pick_list(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, correlation_id=str(ULID())), Ok)
    assert _levels(db, env) == (100, 0)


def test_the_expiry_sweep_leaves_a_hold_its_pick_list_still_owns(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    reservation_id = _ledger_row(db, order_id)[0]
    past = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    db.execute("UPDATE warehouse.stock_reservations SET expires_at = %s WHERE id = %s", (past, reservation_id))
    now = datetime.datetime.now(datetime.timezone.utc)

    assert ReservationService(db).expire_due_reservations(now=now, tenant_id=TENANT) == []

    assert _ledger_row(db, order_id)[1] == "active" and _levels(db, env) == (100, ORDERED)
    _ship(db, env, order_id)
    assert _levels(db, env) == (100 - ORDERED, 0)


def test_cancelling_a_pick_list_whose_hold_is_gone_leaves_another_orders_hold_alone(db, env):
    """Regression: with the first order's hold already closed, its cancel took reserved 30 to 0 while
    the second order's reservation still said active."""
    order_id = _confirmed_order(db, env, stock=100)
    _break_hold_as_an_older_release_did(db, order_id)
    other = _second_order_holding(db, env, stock=1)
    assert _levels(db, env) == (101, ORDERED)
    fulfillment = FulfillmentService(db)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]

    cancelled = fulfillment.cancel_pick_list(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, correlation_id=str(ULID()))

    assert isinstance(cancelled, Ok), cancelled
    assert _levels(db, env) == (101, ORDERED)
    assert _ledger_row(db, other)[1:] == ("active", ORDERED)


def test_shipping_a_pick_list_whose_hold_is_gone_leaves_another_orders_hold_alone(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    _break_hold_as_an_older_release_did(db, order_id)
    other = _second_order_holding(db, env, stock=1)

    _ship(db, env, order_id)

    assert _levels(db, env) == (101 - ORDERED, ORDERED)
    assert _ledger_row(db, other)[1:] == ("active", ORDERED)


def test_a_pick_list_whose_hold_is_gone_can_still_be_cancelled_alone(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    _break_hold_as_an_older_release_did(db, order_id)
    fulfillment = FulfillmentService(db)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]

    assert isinstance(fulfillment.cancel_pick_list(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, correlation_id=str(ULID())), Ok)
    assert _levels(db, env) == (100, 0)


def _order_free_for_vouchers(db, env):
    """Confirmed, its hold released before any pick list opened: the route a voucher can take."""
    assert isinstance(StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=100,
        correlation_id=str(ULID()), reference="setup", actor_id=env["actor"],
    ), Ok)
    sales = SalesOrderService(db)
    order = sales.create_order(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=ORDERED, unit_price=100.0)],
    )
    assert isinstance(sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id=str(ULID())), Ok)
    assert isinstance(ReservationService(db).release_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=_ledger_row(db, order.id)[0]), Ok)
    return order.id


def _issue_and_deliver(db, env, order_id, quantity):
    vouchers = VoucherService(db)
    draft = vouchers.create_issue_from_order(
        tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["location"],
        quantities={env["product"]: Decimal(quantity)},
    )
    assert isinstance(draft, Ok), draft
    posted = vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id=str(ULID()))
    assert isinstance(posted, Ok), posted
    envelope = _outbox_envelope(db, "warehouse.voucher.posted", "voucher_id", draft.value["id"])
    _handle_voucher_posted(db, envelope)
    return envelope


def test_vouchers_covering_every_line_mark_the_order_shipped_and_a_part_issue_does_not(db, env):
    """Regression: an order fully issued by voucher stayed confirmed for good."""
    order_id = _order_free_for_vouchers(db, env)

    first = _issue_and_deliver(db, env, order_id, 20)
    assert first["payload"]["issued_to_date"] == {env["product"]: 20}
    assert _order_status(db, order_id) == "confirmed"
    _handle_voucher_posted(db, first)  # a replay changes nothing
    assert _order_status(db, order_id) == "confirmed"

    last = _issue_and_deliver(db, env, order_id, 10)
    assert last["payload"]["issued_to_date"] == {env["product"]: ORDERED}
    assert _order_status(db, order_id) == "shipped"
    _handle_voucher_posted(db, last)
    assert _order_status(db, order_id) == "shipped"
    audited = db.execute(
        "SELECT payload->>'voucher_id' FROM core.audit_log WHERE tenant_id = %s AND action = 'sales_order.status_changed' AND entity_id = %s",
        (TENANT, order_id),
    ).fetchall()
    assert audited == [(last["payload"]["voucher_id"],)]


def test_issued_to_date_is_net_of_returns(db, env):
    order_id = _order_free_for_vouchers(db, env)
    vouchers = VoucherService(db)
    first = _issue_and_deliver(db, env, order_id, 20)
    returned = vouchers.create_draft(
        tenant_id=TENANT, actor_id=env["actor"], type="return", dest_location_id=env["location"],
        return_of_voucher_id=first["payload"]["voucher_id"], lines=[{"product_id": env["product"], "quantity": 5}],
    )
    assert isinstance(vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=returned.value["id"], correlation_id=str(ULID())), Ok)

    second = _issue_and_deliver(db, env, order_id, 10)

    assert second["payload"]["issued_to_date"] == {env["product"]: 25}
    assert _order_status(db, order_id) == "confirmed"


def test_the_consumer_ignores_vouchers_that_are_not_issues_from_an_order(db, env):
    order_id = _confirmed_order(db, env, stock=100)
    for payload in (
        {"voucher_id": "v", "type": "receipt", "ref_type": None, "ref_id": None},
        {"voucher_id": "v", "type": "issue", "ref_type": None, "ref_id": None},
        {"voucher_id": "v", "type": "issue", "number": "ISS"},  # a 1.0 event
    ):
        _handle_voucher_posted(db, {"tenant_id": TENANT, "payload": payload})
    assert _order_status(db, order_id) == "confirmed"


def test_a_voucher_in_the_window_before_the_pick_list_releases_the_reservation(db, env):
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

    assert isinstance(posted, Ok), posted
    assert _levels(db, env) == (100 - ORDERED, 0)
    # The late event then finds the order already issued and opens nothing.
    _handle_sales_order_confirmed(db, _outbox_envelope(db, "sales.order.confirmed", "order_id", order.id))
    assert not [p for p in FulfillmentService(db).list_pick_lists(tenant_id=TENANT) if p.source_id == order.id]


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

"""Sales' half of fulfillment: confirm publishes what warehouse needs to open
a pick list, and a shipped shipment marks the order shipped."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.sales.events.consumers import _handle_shipment_shipped
from modules.warehouse.api.service import StockService

TENANT = "integration-test-sales-shipment"


@pytest.fixture
def env(db):
    actor, uom, product, partner, location = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'SS-PASTA', 'Pasta', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Acme', 'customer')", (partner, TENANT))
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Main')", (location, TENANT, str(ULID()))
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=50, correlation_id=str(ULID()), reference="setup"
    )
    service = SalesOrderService(db)
    order = service.create_order(
        tenant_id=TENANT, actor_id=actor, partner_id=partner, location_id=location,
        lines=[OrderLine(product_id=product, quantity=12, unit_price=500.0)],
    )
    confirmed = service.confirm_order(tenant_id=TENANT, actor_id=actor, order_id=order.id, correlation_id=str(ULID()))
    assert isinstance(confirmed, Ok), getattr(confirmed, "message", "")
    return {"actor": actor, "product": product, "location": location, "order": order}


def _status(db, order_id):
    return db.execute("SELECT status FROM sales.orders WHERE id = %s", (order_id,)).fetchone()[0]


def test_confirmation_publishes_the_lines_and_location_warehouse_picks_against(db, env):
    envelope = db.execute(
        "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'sales.order.confirmed' ORDER BY event_id DESC LIMIT 1",
        (TENANT,),
    ).fetchone()[0]
    assert envelope["event_version"] == "1.1"
    payload = envelope["payload"]
    assert payload["location_id"] == env["location"]
    assert payload["reservation_reference"] == f"sales_order:{env['order'].id}"
    assert payload["lines"] == [{"product_id": env["product"], "quantity": 12.0}]


def _shipped(env, *, source_type="sales_order") -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": "warehouse.shipment.shipped",
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "payload": {"shipment_id": str(ULID()), "pick_list_id": str(ULID()), "source_type": source_type, "source_id": env["order"].id},
    }


def test_a_shipped_shipment_marks_the_order_shipped(db, env):
    _handle_shipment_shipped(db, _shipped(env))
    assert _status(db, env["order"].id) == "shipped"


def test_a_redelivered_shipment_event_is_harmless(db, env):
    _handle_shipment_shipped(db, _shipped(env))
    _handle_shipment_shipped(db, _shipped(env))
    assert _status(db, env["order"].id) == "shipped"
    audits = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'sales_order.status_changed'",
        (TENANT, env["order"].id),
    ).fetchone()[0]
    assert audits == 1


def test_a_shipment_from_another_source_is_ignored(db, env):
    _handle_shipment_shipped(db, _shipped(env, source_type="transfer_order"))
    assert _status(db, env["order"].id) == "confirmed"

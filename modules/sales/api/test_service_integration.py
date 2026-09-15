"""Integration test: requested_ship_date and opportunity_id round-trip through
create_order/list_orders exactly like every other order field."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine

TENANT = "integration-test-sales-orders"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, partner, location = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'SO-PASTA', 'Pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Acme Corp', 'customer')",
        (partner, TENANT),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'MAIN', 'Main warehouse')",
        (location, TENANT),
    )
    return {"actor": actor, "product": product, "partner": partner, "location": location}


def test_create_order_round_trips_ship_date_and_opportunity_id(db, env):
    service = SalesOrderService(db)
    ship_date = datetime.date(2026, 11, 15)
    order = service.create_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        partner_id=env["partner"],
        location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=100, unit_price=0.0)],
        requested_ship_date=ship_date,
        opportunity_id="opp-123",
    )
    assert order.requested_ship_date == ship_date
    assert order.opportunity_id == "opp-123"

    [listed] = [o for o in service.list_orders(TENANT) if o.id == order.id]
    assert listed.requested_ship_date == ship_date
    assert listed.opportunity_id == "opp-123"


def test_create_order_without_ship_date_or_opportunity_defaults_to_none(db, env):
    service = SalesOrderService(db)
    order = service.create_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        partner_id=env["partner"],
        location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=10, unit_price=5.0)],
    )
    assert order.requested_ship_date is None
    assert order.opportunity_id is None

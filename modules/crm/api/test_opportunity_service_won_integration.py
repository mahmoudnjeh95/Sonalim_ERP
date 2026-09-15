"""Integration tests for winning an opportunity.

Winning is the one transition with a real side effect: it must create a draft
Sales Order carrying what the rep says was sold, atomically with the stage
change, and link the two records together. These tests exercise the real
`SalesOrderService` composition, not a mock, because that composition (and its
transactional atomicity) is the behavior under test.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.crm.api.opportunity_service import OpportunityService
from modules.crm.domain.opportunity import WonLine
from modules.sales.api.service import SalesOrderService

TENANT = "integration-test-crm-won"


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
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'WON-PASTA', 'Pasta', %s)",
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
    opportunity_id = str(ULID())
    db.execute(
        """
        INSERT INTO crm.opportunities (id, tenant_id, partner_id, name, stage, amount)
        VALUES (%s, %s, %s, 'Acme Q4 restock', 'negotiation', 5000)
        """,
        (opportunity_id, TENANT, partner),
    )
    return {
        "actor": actor,
        "product": product,
        "partner": partner,
        "location": location,
        "opportunity_id": opportunity_id,
    }


def test_winning_without_lines_is_rejected(db, env):
    service = OpportunityService(db)
    result = service.transition_stage(
        tenant_id=TENANT,
        actor_id=env["actor"],
        opportunity_id=env["opportunity_id"],
        new_stage="won",
        won_lines=None,
        won_location_id=env["location"],
    )
    assert isinstance(result, Err)
    assert result.code == "EMPTY_LINES"


def test_winning_without_location_is_rejected(db, env):
    service = OpportunityService(db)
    result = service.transition_stage(
        tenant_id=TENANT,
        actor_id=env["actor"],
        opportunity_id=env["opportunity_id"],
        new_stage="won",
        won_lines=[WonLine(product_id=env["product"], quantity=10)],
        won_location_id=None,
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_LOCATION"


def test_winning_with_valid_lines_creates_a_draft_sales_order(db, env):
    service = OpportunityService(db)
    ship_date = datetime.date(2026, 10, 1)
    result = service.transition_stage(
        tenant_id=TENANT,
        actor_id=env["actor"],
        opportunity_id=env["opportunity_id"],
        new_stage="won",
        won_lines=[WonLine(product_id=env["product"], quantity=250)],
        won_location_id=env["location"],
        requested_ship_date=ship_date,
        correlation_id=str(ULID()),
    )
    assert isinstance(result, Ok)
    opportunity = result.value
    assert opportunity.stage == "won"
    assert opportunity.sales_order_id is not None

    orders = SalesOrderService(db).list_orders(TENANT)
    matching = [o for o in orders if o.id == opportunity.sales_order_id]
    assert len(matching) == 1
    order = matching[0]
    assert order.status == "draft"
    assert order.partner_id == env["partner"]
    assert order.location_id == env["location"]
    assert order.requested_ship_date == ship_date
    assert order.opportunity_id == env["opportunity_id"]
    assert len(order.lines) == 1
    assert order.lines[0].product_id == env["product"]
    assert order.lines[0].quantity == 250

    row = db.execute(
        "SELECT sales_order_id FROM crm.opportunities WHERE id = %s", (env["opportunity_id"],)
    ).fetchone()
    assert row[0] == opportunity.sales_order_id

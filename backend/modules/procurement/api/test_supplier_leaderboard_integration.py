"""Integration test for PurchaseOrderService.list_supplier_leaderboard: the
aggregate ranking of suppliers by how often they held the lowest recorded CFA
price across products -- the cross-product view behind list_price_history's
per-product best-supplier highlight.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.service import PurchaseOrderService

TENANT = "integration-test-supplier-leaderboard"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product_a, product_b, supplier_a, supplier_b = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-FILM', 'Test film', %s)",
        (product_a, TENANT, uom),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-BOX', 'Test box', %s)",
        (product_b, TENANT, uom),
    )
    for supplier_id, name in ((supplier_a, "Supplier A"), (supplier_b, "Supplier B")):
        db.execute(
            "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, 'supplier', 'active')",
            (supplier_id, TENANT, name),
        )
    db.execute(
        "INSERT INTO core.exchange_rates (id, tenant_id, currency_code, rate_to_base, effective_date, source) "
        "VALUES (%s, %s, 'EUR', 655.957, '2024-01-01', 'test')",
        (str(ULID()), TENANT),
    )
    return {
        "actor": actor, "uom": uom, "product_a": product_a, "product_b": product_b,
        "supplier_a": supplier_a, "supplier_b": supplier_b,
    }


def test_leaderboard_ranks_supplier_with_more_best_prices_first(db, env):
    service = PurchaseOrderService(db)

    # Product A: supplier A is cheaper (10 < 12).
    order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_a"],
        order_date=datetime.date(2024, 6, 1), currency_code="EUR",
        lines=[{"product_id": env["product_a"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 10, "unit_price_currency": "EUR"}],
    )
    assert isinstance(order, Ok), getattr(order, "message", "")
    order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_b"],
        order_date=datetime.date(2024, 6, 2), currency_code="EUR",
        lines=[{"product_id": env["product_a"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 12, "unit_price_currency": "EUR"}],
    )
    assert isinstance(order, Ok), getattr(order, "message", "")

    # Product B: supplier A is cheaper again (5 < 8) -- A wins both products.
    order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_a"],
        order_date=datetime.date(2024, 6, 3), currency_code="EUR",
        lines=[{"product_id": env["product_b"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 5, "unit_price_currency": "EUR"}],
    )
    assert isinstance(order, Ok), getattr(order, "message", "")
    order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_b"],
        order_date=datetime.date(2024, 6, 4), currency_code="EUR",
        lines=[{"product_id": env["product_b"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 8, "unit_price_currency": "EUR"}],
    )
    assert isinstance(order, Ok), getattr(order, "message", "")

    leaderboard = service.list_supplier_leaderboard(tenant_id=TENANT)

    assert [row["supplier_id"] for row in leaderboard] == [env["supplier_a"], env["supplier_b"]]
    assert leaderboard[0]["best_price_count"] == 2
    assert leaderboard[0]["products_supplied"] == 2
    assert leaderboard[0]["total_orders"] == 2
    assert leaderboard[1]["best_price_count"] == 0
    assert leaderboard[1]["products_supplied"] == 2
    assert leaderboard[1]["total_orders"] == 2


def test_leaderboard_ties_keep_the_earlier_order(db, env):
    service = PurchaseOrderService(db)
    order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_a"],
        order_date=datetime.date(2024, 6, 1), currency_code="EUR",
        lines=[{"product_id": env["product_a"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 10, "unit_price_currency": "EUR"}],
    )
    assert isinstance(order, Ok), getattr(order, "message", "")
    order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_b"],
        order_date=datetime.date(2024, 6, 2), currency_code="EUR",
        lines=[{"product_id": env["product_a"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 10, "unit_price_currency": "EUR"}],
    )
    assert isinstance(order, Ok), getattr(order, "message", "")

    leaderboard = service.list_supplier_leaderboard(tenant_id=TENANT)
    by_supplier = {row["supplier_id"]: row for row in leaderboard}
    assert by_supplier[env["supplier_a"]]["best_price_count"] == 1
    assert by_supplier[env["supplier_b"]]["best_price_count"] == 0

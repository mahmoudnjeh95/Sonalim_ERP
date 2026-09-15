"""Integration test for PurchaseOrderService.list_price_history: the price
*trend* across every recorded order for a product, unlike list_last_prices'
single latest figure -- and that each price converts to CFA using the rate in
effect on its own order date, not today's.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.service import PurchaseOrderService

TENANT = "integration-test-price-history"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, supplier_a, supplier_b = (str(ULID()) for _ in range(4))
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
        (product, TENANT, uom),
    )
    for supplier_id, name in ((supplier_a, "Supplier A"), (supplier_b, "Supplier B")):
        db.execute(
            "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, 'supplier', 'active')",
            (supplier_id, TENANT, name),
        )
    # Two EUR rates on file, before either test order, so the older order uses
    # the older rate and the newer order uses the newer one.
    db.execute(
        "INSERT INTO core.exchange_rates (id, tenant_id, currency_code, rate_to_base, effective_date, source) "
        "VALUES (%s, %s, 'EUR', 655.957, '2024-01-01', 'test')",
        (str(ULID()), TENANT),
    )
    db.execute(
        "INSERT INTO core.exchange_rates (id, tenant_id, currency_code, rate_to_base, effective_date, source) "
        "VALUES (%s, %s, 'EUR', 658.33, '2026-01-01', 'test')",
        (str(ULID()), TENANT),
    )
    return {"actor": actor, "uom": uom, "product": product, "supplier_a": supplier_a, "supplier_b": supplier_b}


def test_history_is_chronological_and_converted_per_order_date(db, env):
    service = PurchaseOrderService(db)
    old_order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_a"],
        order_date=datetime.date(2024, 6, 1), currency_code="EUR",
        lines=[{"product_id": env["product"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 10, "unit_price_currency": "EUR"}],
    )
    assert isinstance(old_order, Ok), getattr(old_order, "message", "")
    new_order = service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_b"],
        order_date=datetime.date(2026, 6, 1), currency_code="EUR",
        lines=[{"product_id": env["product"], "uom_id": env["uom"], "quantity_ordered": 5, "unit_price": 12, "unit_price_currency": "EUR"}],
    )
    assert isinstance(new_order, Ok), getattr(new_order, "message", "")

    history = service.list_price_history(tenant_id=TENANT, product_id=env["product"])

    assert [row["order_date"] for row in history] == ["2024-06-01", "2026-06-01"]
    assert history[0]["supplier_id"] == env["supplier_a"]
    assert history[0]["unit_price"] == 10
    assert history[0]["unit_price_cfa"] == pytest.approx(10 * 655.957)
    assert history[1]["supplier_id"] == env["supplier_b"]
    assert history[1]["unit_price_cfa"] == pytest.approx(12 * 658.33)


def test_history_can_be_narrowed_to_one_supplier(db, env):
    service = PurchaseOrderService(db)
    service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_a"],
        order_date=datetime.date(2024, 6, 1), currency_code="EUR",
        lines=[{"product_id": env["product"], "uom_id": env["uom"], "quantity_ordered": 10, "unit_price": 10, "unit_price_currency": "EUR"}],
    )
    service.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier_b"],
        order_date=datetime.date(2026, 6, 1), currency_code="EUR",
        lines=[{"product_id": env["product"], "uom_id": env["uom"], "quantity_ordered": 5, "unit_price": 12, "unit_price_currency": "EUR"}],
    )

    history = service.list_price_history(tenant_id=TENANT, product_id=env["product"], supplier_id=env["supplier_b"])
    assert len(history) == 1
    assert history[0]["supplier_id"] == env["supplier_b"]

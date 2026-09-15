"""Integration tests for the disposition summary, against a real database.

The property under test: only the `product` component is summed — film, carton
and tape lines are counted in their own units, and mixing them into the same
total would be the exact cross-unit mistake the waste ratio elsewhere in this
codebase was built to avoid.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.service import WorkOrderService
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.domain.non_conformity import DispositionLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-disposition-summary"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, quarantine, work_center = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'DS-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'DS-FG', 'Finished goods')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked, blocked_reason) "
        "VALUES (%s, %s, 'DS-QUAR', 'Quarantine', TRUE, 'awaiting QC disposition')",
        (quarantine, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'DS-WC', 'Test line')",
        (work_center, TENANT),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=1_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    return {"actor": actor, "product": product, "location": location, "quarantine": quarantine, "work_center": work_center}


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _raise_and_disposition(db, env, of, *, quantity, disposition):
    service = NonConformityService(db)
    raised = service.raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"],
        quantity=quantity, source_location_id=env["location"], quarantine_location_id=env["quarantine"],
        defect_type="test defect", correlation_id=str(ULID()),
    )
    assert isinstance(raised, Ok), getattr(raised, "message", "")
    dispositioned = service.disposition(
        tenant_id=TENANT, actor_id=env["actor"], non_conformity_id=raised.value.id, correlation_id=str(ULID()),
        lines=(DispositionLine(component="product", disposition=disposition, quantity=quantity),),
    )
    assert isinstance(dispositioned, Ok), getattr(dispositioned, "message", "")


def test_summary_groups_by_disposition_and_sums_quantity(db, env, of):
    _raise_and_disposition(db, env, of, quantity=8, disposition="regrind")
    _raise_and_disposition(db, env, of, quantity=2, disposition="dechet")
    _raise_and_disposition(db, env, of, quantity=5, disposition="dechet")

    rows = {r["disposition"]: r for r in NonConformityService(db).disposition_summary(tenant_id=TENANT)}
    assert rows["regrind"]["quantity"] == 8
    assert rows["regrind"]["count"] == 1
    assert rows["dechet"]["quantity"] == 7
    assert rows["dechet"]["count"] == 2


def test_summary_reports_weight_kg_when_product_net_weight_is_known(db, env, of):
    db.execute("UPDATE core.products SET net_weight_grams = 500 WHERE id = %s", (env["product"],))
    _raise_and_disposition(db, env, of, quantity=20, disposition="dechet")

    rows = {r["disposition"]: r for r in NonConformityService(db).disposition_summary(tenant_id=TENANT)}
    assert rows["dechet"]["weight_kg"] == pytest.approx(10.0)


def test_summary_omits_weight_kg_when_product_net_weight_is_unknown(db, env, of):
    _raise_and_disposition(db, env, of, quantity=20, disposition="dechet")

    rows = {r["disposition"]: r for r in NonConformityService(db).disposition_summary(tenant_id=TENANT)}
    assert rows["dechet"]["weight_kg"] is None


def test_packaging_components_are_excluded(db, env, of):
    service = NonConformityService(db)
    raised = service.raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"],
        quantity=10, source_location_id=env["location"], quarantine_location_id=env["quarantine"],
        defect_type="test defect", correlation_id=str(ULID()),
    )
    service.disposition(
        tenant_id=TENANT, actor_id=env["actor"], non_conformity_id=raised.value.id, correlation_id=str(ULID()),
        lines=(
            DispositionLine(component="product", disposition="regrind", quantity=9),
            DispositionLine(component="film", disposition="dechet", quantity=999),
        ),
    )
    rows = {r["disposition"]: r for r in NonConformityService(db).disposition_summary(tenant_id=TENANT)}
    # Film's 999 must not leak into dechet's total via the product-only quantity.
    assert "dechet" not in rows or rows["dechet"]["quantity"] < 999
    assert rows["regrind"]["quantity"] == 9

"""Integration tests for reorder rules and replenishment proposals."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.replenishment_service import ReplenishmentService
from modules.warehouse.api.service import StockService

TENANT = "integration-test-replenishment"


@pytest.fixture
def env(db):
    actor, uom, product, supplier, location, quarantine = (str(ULID()) for _ in range(6))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, 'ctn', 'Carton', 'unit', TRUE)",
        (uom, TENANT),
    )
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'RP-FILM', 'Film', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Supplier', 'supplier')", (supplier, TENANT))
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Main')", (location, TENANT, str(ULID()))
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked) VALUES (%s, %s, %s, 'Quarantine', TRUE)",
        (quarantine, TENANT, str(ULID())),
    )
    stock = StockService(db)
    stock.receive_stock(tenant_id=TENANT, product_id=product, location_id=location, quantity=40, correlation_id=str(ULID()), reference="setup")
    # Blocked stock must not count as available.
    stock.receive_stock(tenant_id=TENANT, product_id=product, location_id=quarantine, quantity=500, correlation_id=str(ULID()), reference="setup")
    rule = ReplenishmentService(db).create_rule(
        tenant_id=TENANT, actor_id=actor, product_id=product, reorder_point=50, order_up_to=200, preferred_supplier_id=supplier
    )
    assert isinstance(rule, Ok), getattr(rule, "message", "")
    return {"actor": actor, "product": product, "supplier": supplier, "location": location, "rule": rule.value}


def _receive(db, env, quantity):
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=quantity, correlation_id=str(ULID()),
        reference="po",
    )


def test_a_breached_rule_raises_a_proposal_back_up_to_the_max(db, env):
    outcome = ReplenishmentService(db).evaluate(tenant_id=TENANT)
    [proposal] = outcome["created"]
    assert (proposal.available_at_proposal, proposal.quantity, proposal.supplier_id) == (40, 160, env["supplier"])


def test_reserved_stock_is_not_available(db, env):
    _receive(db, env, 30)  # 70 on hand: above the reorder point...
    StockService(db).reserve_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=25, correlation_id=str(ULID()), reference="so"
    )
    # ...but only 45 can still be promised.
    [proposal] = ReplenishmentService(db).evaluate(tenant_id=TENANT)["created"]
    assert proposal.available_at_proposal == 45


def test_a_pending_proposal_blocks_a_second_one(db, env):
    service = ReplenishmentService(db)
    service.evaluate(tenant_id=TENANT)
    assert service.evaluate(tenant_id=TENANT)["created"] == []


def test_approval_publishes_the_order_request_with_any_adjustment(db, env):
    service = ReplenishmentService(db)
    [proposal] = service.evaluate(tenant_id=TENANT)["created"]
    approved = service.approve_proposal(
        tenant_id=TENANT, actor_id=env["actor"], proposal_id=proposal.id, correlation_id=str(ULID()), quantity=180
    )
    assert isinstance(approved, Ok) and approved.value.status == "approved"
    event = db.execute(
        "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'warehouse.replenishment.approved'", (TENANT,)
    ).fetchone()[0]
    assert (event["payload"]["quantity"], event["payload"]["supplier_id"]) == (180, env["supplier"])
    again = service.approve_proposal(tenant_id=TENANT, actor_id=env["actor"], proposal_id=proposal.id, correlation_id=str(ULID()))
    assert isinstance(again, Err) and again.code == "INVALID_STATE"


def test_an_approved_proposal_is_fulfilled_once_stock_recovers(db, env):
    service = ReplenishmentService(db)
    [proposal] = service.evaluate(tenant_id=TENANT)["created"]
    service.approve_proposal(tenant_id=TENANT, actor_id=env["actor"], proposal_id=proposal.id, correlation_id=str(ULID()))
    _receive(db, env, 160)
    outcome = service.evaluate(tenant_id=TENANT)
    assert [p.id for p in outcome["fulfilled"]] == [proposal.id]
    assert outcome["created"] == []


def test_dismissing_frees_the_rule_for_the_next_evaluation(db, env):
    service = ReplenishmentService(db)
    [proposal] = service.evaluate(tenant_id=TENANT)["created"]
    dismissed = service.dismiss_proposal(tenant_id=TENANT, actor_id=env["actor"], proposal_id=proposal.id)
    assert isinstance(dismissed, Ok) and dismissed.value.status == "dismissed"
    assert len(service.evaluate(tenant_id=TENANT)["created"]) == 1


def test_an_inactive_rule_raises_nothing(db, env):
    service = ReplenishmentService(db)
    service.update_rule(tenant_id=TENANT, actor_id=env["actor"], rule_id=env["rule"].id, is_active=False)
    assert service.evaluate(tenant_id=TENANT)["created"] == []


def test_one_rule_per_product_and_scope(db, env):
    result = ReplenishmentService(db).create_rule(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], reorder_point=10, order_up_to=20
    )
    assert isinstance(result, Err) and result.code == "DUPLICATE_RULE"


def test_update_validates_the_merged_rule_and_is_audited(db, env):
    service = ReplenishmentService(db)
    bad = service.update_rule(tenant_id=TENANT, actor_id=env["actor"], rule_id=env["rule"].id, order_up_to=30)
    assert isinstance(bad, Err) and bad.code == "INVALID_RULE"
    good = service.update_rule(tenant_id=TENANT, actor_id=env["actor"], rule_id=env["rule"].id, reorder_point=20)
    assert isinstance(good, Ok) and (good.value.reorder_point, good.value.order_up_to) == (20, 200)
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'reorder_rule.updated'",
        (TENANT, env["rule"].id),
    ).fetchone()
    assert audit[0] == {"reorder_point": 20}


def test_a_rule_with_history_cannot_be_deleted(db, env):
    service = ReplenishmentService(db)
    service.evaluate(tenant_id=TENANT)
    result = service.delete_rule(tenant_id=TENANT, actor_id=env["actor"], rule_id=env["rule"].id)
    assert isinstance(result, Err) and result.code == "RULE_HAS_HISTORY"

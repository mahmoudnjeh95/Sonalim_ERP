"""Integration tests for guided put-away against a real database.

Suggestions rank three signals in order -- an explicit rule, a bin already
holding the same product, any empty bin -- and confirming a put-away is an
ordinary transfer_stock plus a record of whether the top suggestion was
actually followed.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.putaway_service import PutAwayService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.site_service import SiteService

TENANT = "integration-test-putaway"


@pytest.fixture
def env(db):
    actor, uom, product = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'PA-P', 'Pasta', %s)", (product, TENANT, uom))

    site = SiteService(db).create_site(tenant_id=TENANT, actor_id=actor, code="main", name="Main").value
    dock = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=actor, site_id=site.id, code=str(ULID()), name="Dock", location_type="bin"
    ).value
    empty_bin = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=actor, site_id=site.id, code=str(ULID()), name="Empty bin", location_type="bin"
    ).value
    occupied_bin = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=actor, site_id=site.id, code=str(ULID()), name="Occupied bin", location_type="bin"
    ).value

    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=dock.id, quantity=50, correlation_id=str(ULID()),
        reference="setup", actor_id=actor,
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=occupied_bin.id, quantity=10, correlation_id=str(ULID()),
        reference="setup", actor_id=actor,
    )
    return {"actor": actor, "product": product, "site": site, "dock": dock, "empty_bin": empty_bin, "occupied_bin": occupied_bin}


def test_with_no_rule_a_bin_already_holding_the_product_ranks_first(db, env):
    service = PutAwayService(db)
    suggestions = service.suggest_locations(
        tenant_id=TENANT, site_id=env["site"].id, product_id=env["product"], exclude_location_id=env["dock"].id
    )
    assert [loc.id for loc in suggestions] == [env["occupied_bin"].id, env["empty_bin"].id]


def test_an_explicit_rule_outranks_the_same_product_signal(db, env):
    service = PutAwayService(db)
    rule_result = service.create_rule(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"],
        target_location_id=env["empty_bin"].id,
    )
    assert isinstance(rule_result, Ok)

    suggestions = service.suggest_locations(
        tenant_id=TENANT, site_id=env["site"].id, product_id=env["product"], exclude_location_id=env["dock"].id
    )
    assert [loc.id for loc in suggestions] == [env["empty_bin"].id, env["occupied_bin"].id]


def test_the_current_location_is_excluded_from_its_own_suggestions(db, env):
    service = PutAwayService(db)
    suggestions = service.suggest_locations(
        tenant_id=TENANT, site_id=env["site"].id, product_id=env["product"], exclude_location_id=env["occupied_bin"].id
    )
    assert env["occupied_bin"].id not in [loc.id for loc in suggestions]


def test_creating_a_rule_twice_for_the_same_product_updates_it_in_place(db, env):
    service = PutAwayService(db)
    first = service.create_rule(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"],
        target_location_id=env["empty_bin"].id,
    ).value
    second = service.create_rule(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"],
        target_location_id=env["occupied_bin"].id,
    ).value
    assert second.id == first.id
    assert second.target_location_id == env["occupied_bin"].id
    assert len(service.list_rules(tenant_id=TENANT, site_id=env["site"].id)) == 1


def test_a_rule_target_from_another_site_is_refused(db, env):
    other_site = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code="other", name="Other").value
    other_bin = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=other_site.id, code=str(ULID()), name="Other bin"
    ).value
    result = PutAwayService(db).create_rule(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"], target_location_id=other_bin.id
    )
    assert isinstance(result, Err)
    assert result.code == "CROSS_SITE_TARGET"


def test_a_rule_target_that_is_not_a_bin_is_refused(db, env):
    zone = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, code=str(ULID()), name="Zone", location_type="zone"
    ).value
    result = PutAwayService(db).create_rule(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"], target_location_id=zone.id
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_TARGET"


def test_delete_rule_removes_it(db, env):
    service = PutAwayService(db)
    rule = service.create_rule(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"],
        target_location_id=env["empty_bin"].id,
    ).value
    assert isinstance(service.delete_rule(tenant_id=TENANT, actor_id=env["actor"], rule_id=rule.id), Ok)
    assert service.list_rules(tenant_id=TENANT, site_id=env["site"].id) == []


def test_confirming_a_putaway_moves_stock_and_records_whether_the_suggestion_was_followed(db, env):
    service = PutAwayService(db)

    # Following the top suggestion (occupied_bin, since it already holds the product).
    followed = service.confirm_putaway(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"],
        from_location_id=env["dock"].id, to_location_id=env["occupied_bin"].id, quantity=20, correlation_id=str(ULID()),
    )
    assert isinstance(followed, Ok)
    on_hand = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s AND product_id = %s",
        (TENANT, env["occupied_bin"].id, env["product"]),
    ).fetchone()[0]
    assert on_hand == 30

    # Looked up by entity_id (to_location_id:product_id), not by "most recent" --
    # record_audit uses NOW(), which Postgres freezes at transaction start, so
    # both calls in this test get an identical occurred_at and an ORDER BY on
    # it would be an arbitrary tie-break, not a real ordering.
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND action = 'putaway.confirmed' AND entity_id = %s",
        (TENANT, f"{env['occupied_bin'].id}:{env['product']}"),
    ).fetchone()[0]
    assert audit["followed_suggestion"] is True

    # Overriding the suggestion by choosing the empty bin instead.
    overridden = service.confirm_putaway(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, product_id=env["product"],
        from_location_id=env["dock"].id, to_location_id=env["empty_bin"].id, quantity=10, correlation_id=str(ULID()),
    )
    assert isinstance(overridden, Ok)
    audit2 = db.execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND action = 'putaway.confirmed' AND entity_id = %s",
        (TENANT, f"{env['empty_bin'].id}:{env['product']}"),
    ).fetchone()[0]
    assert audit2["followed_suggestion"] is False

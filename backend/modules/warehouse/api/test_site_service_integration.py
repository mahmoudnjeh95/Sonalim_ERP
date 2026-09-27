"""Integration tests for the site + zone/aisle/rack/bin location hierarchy against a
real database. Every existing location was flat before this; the hierarchy is layered
on as additive columns on warehouse.locations, so a location created with no site
information at all should still behave exactly as it did before (see
test_a_location_with_no_hierarchy_fields_defaults_to_a_bin_with_no_parent).
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.site_service import SiteService

TENANT = "integration-test-sites"


@pytest.fixture
def env(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    return {"actor": actor}


def _create_site(db, env, code="main", name="Site principal"):
    result = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code=code, name=name)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _create_location(db, env, site_id, **kwargs):
    result = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=site_id, code=str(ULID()), name="loc", **kwargs
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def test_create_site_then_list_it(db, env):
    site = _create_site(db, env)
    assert site.code == "main"
    assert site.is_active is True

    sites = SiteService(db).list_sites(tenant_id=TENANT)
    assert [s.id for s in sites] == [site.id]


def test_duplicate_site_code_is_refused(db, env):
    _create_site(db, env, code="dup")
    result = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code="dup", name="Second")
    assert isinstance(result, Err)
    assert result.code == "DUPLICATE_CODE"


def test_site_creation_is_audited(db, env):
    site = _create_site(db, env)
    row = db.execute(
        "SELECT actor_id, action FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s",
        (TENANT, site.id),
    ).fetchone()
    assert row == (env["actor"], "site.created")


def test_update_site_leaves_unspecified_fields_unchanged(db, env):
    site = _create_site(db, env)
    result = SiteService(db).update_site(tenant_id=TENANT, actor_id=env["actor"], site_id=site.id, name="Renamed")
    assert isinstance(result, Ok)
    assert result.value.name == "Renamed"
    assert result.value.code == site.code
    assert result.value.is_active is True


def test_deactivate_site_is_soft_only(db, env):
    site = _create_site(db, env)
    result = SiteService(db).deactivate_site(tenant_id=TENANT, actor_id=env["actor"], site_id=site.id)
    assert isinstance(result, Ok)
    assert result.value.is_active is False
    # The row still exists -- nothing was deleted.
    assert db.execute("SELECT 1 FROM warehouse.sites WHERE id = %s", (site.id,)).fetchone() is not None


def test_a_location_cannot_be_created_under_a_different_sites_parent(db, env):
    site_a = _create_site(db, env, code="a")
    site_b = _create_site(db, env, code="b")
    zone_b = _create_location(db, env, site_b.id, location_type="zone")

    result = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=site_a.id, code=str(ULID()), name="loc",
        location_type="bin", parent_location_id=zone_b.id,
    )
    assert isinstance(result, Err)
    assert result.code == "CROSS_SITE_PARENT"


def test_a_location_with_no_hierarchy_fields_defaults_to_a_bin_with_no_parent(db, env):
    site = _create_site(db, env)
    location = _create_location(db, env, site.id)
    assert location.location_type == "bin"
    assert location.parent_location_id is None
    assert location.site_id == site.id


def test_get_location_tree_returns_every_location_for_a_site_parents_before_children(db, env):
    site = _create_site(db, env)
    zone = _create_location(db, env, site.id, location_type="zone")
    aisle = _create_location(db, env, site.id, location_type="aisle", parent_location_id=zone.id)
    bin_ = _create_location(db, env, site.id, location_type="bin", parent_location_id=aisle.id)

    tree = LocationService(db).get_location_tree(tenant_id=TENANT, site_id=site.id)
    ids_in_order = [loc.id for loc in tree]
    assert ids_in_order.index(zone.id) < ids_in_order.index(aisle.id) < ids_in_order.index(bin_.id)


def test_get_location_tree_does_not_leak_another_sites_locations(db, env):
    site_a = _create_site(db, env, code="a")
    site_b = _create_site(db, env, code="b")
    loc_a = _create_location(db, env, site_a.id)
    _create_location(db, env, site_b.id)

    tree = LocationService(db).get_location_tree(tenant_id=TENANT, site_id=site_a.id)
    assert [loc.id for loc in tree] == [loc_a.id]


def test_reparent_moves_a_location_under_a_new_parent(db, env):
    site = _create_site(db, env)
    zone_a = _create_location(db, env, site.id, location_type="zone")
    zone_b = _create_location(db, env, site.id, location_type="zone")
    bin_ = _create_location(db, env, site.id, location_type="bin", parent_location_id=zone_a.id)

    result = LocationService(db).reparent_location(
        tenant_id=TENANT, actor_id=env["actor"], location_id=bin_.id, parent_location_id=zone_b.id
    )
    assert isinstance(result, Ok)
    assert result.value.parent_location_id == zone_b.id


def test_reparent_refuses_a_cross_site_parent(db, env):
    site_a = _create_site(db, env, code="a")
    site_b = _create_site(db, env, code="b")
    bin_a = _create_location(db, env, site_a.id)
    zone_b = _create_location(db, env, site_b.id, location_type="zone")

    result = LocationService(db).reparent_location(
        tenant_id=TENANT, actor_id=env["actor"], location_id=bin_a.id, parent_location_id=zone_b.id
    )
    assert isinstance(result, Err)
    assert result.code == "CROSS_SITE_PARENT"


def test_reparent_refuses_a_cycle(db, env):
    site = _create_site(db, env)
    zone = _create_location(db, env, site.id, location_type="zone")
    aisle = _create_location(db, env, site.id, location_type="aisle", parent_location_id=zone.id)

    result = LocationService(db).reparent_location(
        tenant_id=TENANT, actor_id=env["actor"], location_id=zone.id, parent_location_id=aisle.id
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_PARENT"


def test_reparent_refuses_a_location_that_still_holds_stock(db, env):
    site = _create_site(db, env)
    zone_a = _create_location(db, env, site.id, location_type="zone")
    zone_b = _create_location(db, env, site.id, location_type="zone")
    bin_ = _create_location(db, env, site.id, location_type="bin", parent_location_id=zone_a.id)

    uom, product = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'SITE-P', 'Pasta', %s)", (product, TENANT, uom))
    receive_result = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=bin_.id, quantity=10,
        correlation_id=str(ULID()), reference="test", actor_id=env["actor"],
    )
    assert isinstance(receive_result, Ok)

    result = LocationService(db).reparent_location(
        tenant_id=TENANT, actor_id=env["actor"], location_id=bin_.id, parent_location_id=zone_b.id
    )
    assert isinstance(result, Err)
    assert result.code == "LOCATION_NOT_EMPTY"


def test_list_stock_items_can_be_scoped_to_one_site(db, env):
    site_a = _create_site(db, env, code="a")
    site_b = _create_site(db, env, code="b")
    bin_a = _create_location(db, env, site_a.id)
    bin_b = _create_location(db, env, site_b.id)

    uom, product = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'SITE-Q', 'Pasta', %s)", (product, TENANT, uom))
    stock = StockService(db)
    assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=product, location_id=bin_a.id, quantity=5, correlation_id=str(ULID()), reference="a", actor_id=env["actor"]), Ok)
    assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=product, location_id=bin_b.id, quantity=7, correlation_id=str(ULID()), reference="b", actor_id=env["actor"]), Ok)

    items_a = stock.list_stock_items(TENANT, site_id=site_a.id)
    assert [item.location_id for item in items_a] == [bin_a.id]
    assert items_a[0].quantity_on_hand == 5

    items_all = stock.list_stock_items(TENANT)
    assert {item.location_id for item in items_all} == {bin_a.id, bin_b.id}

"""Integration tests for the cycle-count workflow against a real database.

Today's only counting mechanisms are an ad hoc single-delta adjust_stock or a
privileged full stock_items overwrite; this is the structured count -> variance
-> approval flow that actually reconciles the books the way a physical
inventory does, scoped to a site's bins (or one subtree of them).
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.cycle_count_service import CycleCountService
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.site_service import SiteService

TENANT = "integration-test-cycle-counts"


@pytest.fixture
def env(db):
    actor, uom, product = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'CC-P', 'Pasta', %s)", (product, TENANT, uom))

    site_result = SiteService(db).create_site(tenant_id=TENANT, actor_id=actor, code="main", name="Main")
    assert isinstance(site_result, Ok)
    site = site_result.value

    zone_result = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=actor, site_id=site.id, code=str(ULID()), name="Zone A", location_type="zone"
    )
    assert isinstance(zone_result, Ok)
    zone = zone_result.value

    bin_result = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=actor, site_id=site.id, code=str(ULID()), name="Bin A1", location_type="bin",
        parent_location_id=zone.id,
    )
    assert isinstance(bin_result, Ok)
    bin_ = bin_result.value

    stock_result = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=bin_.id, quantity=100, correlation_id=str(ULID()),
        reference="setup", actor_id=actor,
    )
    assert isinstance(stock_result, Ok)

    return {"actor": actor, "product": product, "site": site, "zone": zone, "bin": bin_}


def _create_count(db, env, **kwargs):
    result = CycleCountService(db).create_count(tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, **kwargs)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def test_create_count_snapshots_current_on_hand(db, env):
    count = _create_count(db, env)
    lines_result = CycleCountService(db).list_lines(tenant_id=TENANT, cycle_count_id=count.id)
    assert isinstance(lines_result, Ok)
    lines = lines_result.value
    assert len(lines) == 1
    assert lines[0].product_id == env["product"]
    assert lines[0].expected_quantity == 100
    assert lines[0].status == "pending"


def test_create_count_with_no_stock_in_scope_is_refused(db, env):
    empty_bin_result = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, code=str(ULID()), name="Empty bin", location_type="bin",
    )
    assert isinstance(empty_bin_result, Ok)
    result = CycleCountService(db).create_count(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, scope_location_id=empty_bin_result.value.id
    )
    assert isinstance(result, Err)
    assert result.code == "EMPTY_SCOPE"


def test_create_count_refuses_a_scope_location_from_another_site(db, env):
    other_site = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code="other", name="Other").value
    other_bin = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=other_site.id, code=str(ULID()), name="Other bin"
    ).value
    result = CycleCountService(db).create_count(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, scope_location_id=other_bin.id
    )
    assert isinstance(result, Err)
    assert result.code == "CROSS_SITE_SCOPE"


def test_a_matching_count_needs_no_decision_and_leaves_stock_untouched(db, env):
    count = _create_count(db, env)
    service = CycleCountService(db)
    assert isinstance(service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id), Ok)

    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]
    result = service.submit_line_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=100
    )
    assert isinstance(result, Ok)
    assert result.value.resolution == "matched"

    complete = service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id=str(ULID()))
    assert isinstance(complete, Ok)
    assert complete.value.status == "completed"

    on_hand = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s AND product_id = %s",
        (TENANT, env["bin"].id, env["product"]),
    ).fetchone()[0]
    assert on_hand == 100


def test_an_approved_variance_adjusts_stock_and_a_rejected_one_does_not(db, env):
    count = _create_count(db, env)
    service = CycleCountService(db)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]

    counted = service.submit_line_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=95
    )
    assert isinstance(counted, Ok)
    assert counted.value.resolution is None  # a real variance awaits a decision

    approved = service.resolve_line_variance(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve"
    )
    assert isinstance(approved, Ok)
    assert approved.value.resolution == "approved"

    on_hand = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s AND product_id = %s",
        (TENANT, env["bin"].id, env["product"]),
    ).fetchone()[0]
    assert on_hand == 95

    move = db.execute(
        "SELECT move_type, quantity, reason FROM warehouse.stock_moves WHERE tenant_id = %s AND reference = %s",
        (TENANT, f"cycle_count:{count.id}"),
    ).fetchone()
    assert move[0] == "adjustment"
    assert move[1] == -5


def test_rejecting_a_variance_leaves_stock_unchanged(db, env):
    count = _create_count(db, env)
    service = CycleCountService(db)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]
    service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=50)

    rejected = service.resolve_line_variance(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="reject"
    )
    assert isinstance(rejected, Ok)
    assert rejected.value.resolution == "rejected"

    on_hand = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s AND product_id = %s",
        (TENANT, env["bin"].id, env["product"]),
    ).fetchone()[0]
    assert on_hand == 100


def test_complete_is_blocked_until_every_line_is_resolved(db, env):
    count = _create_count(db, env)
    service = CycleCountService(db)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]
    service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=42)

    result = service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id=str(ULID()))
    assert isinstance(result, Err)
    assert result.code == "LINES_UNRESOLVED"


def test_a_blind_count_hides_expected_quantity_until_the_line_is_counted(db, env):
    count = _create_count(db, env, count_type="blind")
    service = CycleCountService(db)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)

    lines_before = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert lines_before[0].expected_quantity is None

    line = lines_before[0]
    service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=100)

    lines_after = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert lines_after[0].expected_quantity == 100


def test_cancel_is_allowed_from_draft_and_in_progress_but_not_after(db, env):
    service = CycleCountService(db)

    draft_count = _create_count(db, env)
    assert isinstance(service.cancel_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=draft_count.id), Ok)

    in_progress_count = _create_count(db, env)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=in_progress_count.id).value[0]
    service.submit_line_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id, line_id=line.id, counted_quantity=100
    )
    completed = service.complete_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id, correlation_id=str(ULID())
    )
    assert isinstance(completed, Ok)

    cancel_after_complete = service.cancel_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id)
    assert isinstance(cancel_after_complete, Err)
    assert cancel_after_complete.code == "INVALID_TRANSITION"


def test_scope_location_only_counts_bins_under_it(db, env):
    # A second zone with its own bin and stock, as a sibling of env's zone/bin.
    zone_b = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, code=str(ULID()), name="Zone B", location_type="zone"
    ).value
    bin_b = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, code=str(ULID()), name="Bin B1", location_type="bin",
        parent_location_id=zone_b.id,
    ).value
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=bin_b.id, quantity=7, correlation_id=str(ULID()),
        reference="setup-b", actor_id=env["actor"],
    )

    count = _create_count(db, env, scope_location_id=env["zone"].id)
    lines = CycleCountService(db).list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert [line.location_id for line in lines] == [env["bin"].id]


def test_cycle_count_creation_is_audited(db, env):
    count = _create_count(db, env)
    row = db.execute(
        "SELECT actor_id, action FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s",
        (TENANT, count.id),
    ).fetchone()
    assert row == (env["actor"], "cycle_count.created")

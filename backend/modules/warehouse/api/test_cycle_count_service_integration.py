"""Integration tests for the cycle-count workflow against a real database.

Today's only counting mechanisms are an ad hoc single-delta adjust_stock or a
privileged full stock_items overwrite; this is the structured count -> variance
-> approval flow that actually reconciles the books the way a physical
inventory does, scoped to a site's bins (or one subtree of them).
"""
from __future__ import annotations

import datetime

import psycopg
import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.cycle_count_service import CycleCountService
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService, count_start_lock_key
from modules.warehouse.api.site_service import SiteService
from modules.warehouse.api.valuation_service import ValuationService

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

    # Empty, so the count's lines stay as they are unless a test stocks it.
    second_bin = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=actor, site_id=site.id, code=str(ULID()), name="Bin A2", location_type="bin",
        parent_location_id=zone.id,
    ).value

    return {"actor": actor, "product": product, "site": site, "zone": zone, "bin": bin_, "second_bin": second_bin}


def _create_count(db, env, **kwargs):
    result = CycleCountService(db).create_count(tenant_id=TENANT, actor_id=env["actor"], site_id=env["site"].id, **kwargs)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _started(db, env, **kwargs):
    count = _create_count(db, env, **kwargs)
    result = CycleCountService(db).start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return count


def _submit(db, env, count, line, quantity):
    return CycleCountService(db).submit_line_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=quantity
    )


def _first_line(db, count):
    return CycleCountService(db).list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]


def _on_hand(db, env, location=None):
    return db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s AND product_id = %s",
        (TENANT, location or env["bin"].id, env["product"]),
    ).fetchone()[0]


def test_starting_a_count_snapshots_current_on_hand(db, env):
    count = _started(db, env)
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
    first = service.submit_line_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=100
    )
    assert isinstance(first, Ok)
    assert first.value.status == "pending" and first.value.resolution is None  # one count settles nothing
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

    service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=95)  # a differing count needs a confirming second one
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
    for _ in range(2):
        service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=100)

    lines_after = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert lines_after[0].expected_quantity == 100


@pytest.mark.parametrize("count_type", ["blind", "scheduled"])
def test_a_first_count_gives_no_sign_whether_it_matched_the_books(db, env, count_type):
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["second_bin"].id, quantity=100, correlation_id=str(ULID()),
        reference="setup", actor_id=env["actor"],
    )
    count = _started(db, env, count_type=count_type)
    matching, differing = CycleCountService(db).list_lines(tenant_id=TENANT, cycle_count_id=count.id).value

    def signal(line):
        return (line.status, line.resolution, line.counted_quantity, line.expected_quantity, line.count_1, line.counts_recorded)

    assert signal(_submit(db, env, count, matching, 100).value) == signal(_submit(db, env, count, differing, 90).value)
    assert _submit(db, env, count, matching, 100).value.resolution == "matched"  # the books speak only once settled


def test_a_blind_count_response_hides_the_books_until_the_line_settles(db, env):
    """Regression: the answer to POST .../count used to carry the expected quantity."""
    count = _started(db, env, count_type="blind")
    line = _first_line(db, count)

    first = _submit(db, env, count, line, 90).value
    assert first.status == "pending" and first.expected_quantity is None
    assert _first_line(db, count).expected_quantity is None

    second = _submit(db, env, count, line, 90).value
    assert second.status == "counted" and second.counted_quantity == 90 and second.expected_quantity == 100


@pytest.mark.parametrize("count_type", ["blind", "scheduled"])
def test_earlier_counts_stay_hidden_from_whoever_enters_the_next(db, env, count_type):
    """Regression: count_1 reached the person entering count_2, who could simply copy it."""
    count = _started(db, env, count_type=count_type)
    line = _first_line(db, count)

    for answer, recorded in ((_submit(db, env, count, line, 90).value, 1), (_submit(db, env, count, line, 80).value, 2)):
        assert (answer.count_1, answer.count_2, answer.counts_recorded) == (None, None, recorded)
        listed = _first_line(db, count)
        assert (listed.count_1, listed.count_2) == (None, None)

    settled = _submit(db, env, count, line, 85).value
    assert (settled.count_1, settled.count_2, settled.count_3, settled.counted_quantity) == (90, 80, 85, 85)
    assert _first_line(db, count).count_1 == 90


def test_a_count_cannot_start_over_part_of_a_scope_already_being_counted(db, env):
    """Regression: a site count and a zone count each adjusted the same shelf: books 100, shelf 90, books 80."""
    service = CycleCountService(db)
    site_count = _started(db, env)
    zone_count = _create_count(db, env, scope_location_id=env["zone"].id)

    refused = service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=zone_count.id)
    assert isinstance(refused, Err) and refused.code == "COUNT_SCOPE_OVERLAP" and site_count.number in refused.message
    assert service.get_count(tenant_id=TENANT, cycle_count_id=zone_count.id).value.status == "draft"

    assert isinstance(service.cancel_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=site_count.id), Ok)
    assert isinstance(service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=zone_count.id), Ok)


def test_counts_over_separate_scopes_can_run_together(db, env):
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["second_bin"].id, quantity=5, correlation_id=str(ULID()),
        reference="setup", actor_id=env["actor"],
    )
    _started(db, env, scope_location_id=env["bin"].id)
    _started(db, env, scope_location_id=env["second_bin"].id)


def test_a_count_adjustment_cannot_pass_another_counts_freeze(db, env):
    count = _started(db, env, scope_location_id=env["bin"].id)
    line = _first_line(db, count)
    _submit(db, env, count, line, 90)
    _submit(db, env, count, line, 90)
    other = _create_count(db, env, scope_location_id=env["zone"].id)
    db.execute("UPDATE warehouse.cycle_counts SET status = 'in_progress' WHERE id = %s", (other.id,))  # as an older overlap would be

    refused = CycleCountService(db).resolve_line_variance(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve"
    )

    assert isinstance(refused, Err) and refused.code == "LOCATION_FROZEN" and other.number in refused.message
    assert _on_hand(db, env) == 100


def test_the_books_are_read_when_the_count_starts_not_when_it_is_created(db, env):
    """Regression: created at 100, 10 received before the start, true 110 counted twice, approved: 120."""
    service = CycleCountService(db)
    count = _create_count(db, env)
    stock = StockService(db)
    other_product = str(ULID())
    uom = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["product"],)).fetchone()[0]
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'CC-O', 'Other', %s)", (other_product, TENANT, uom))
    for product, location, quantity in ((env["product"], env["bin"].id, 10), (other_product, env["second_bin"].id, 7)):
        assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=product, location_id=location, quantity=quantity,
                                              correlation_id=str(ULID()), reference="gap", actor_id=env["actor"]), Ok)
    assert service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value == []

    assert isinstance(service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id), Ok)

    lines = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert {(line.product_id, line.expected_quantity) for line in lines} == {(env["product"], 110), (other_product, 7)}
    line = next(line for line in lines if line.product_id == env["product"])
    _submit(db, env, count, line, 110)
    assert _submit(db, env, count, line, 110).value.resolution == "matched"
    assert _on_hand(db, env) == 110


def test_stock_on_a_non_bin_location_is_counted_like_any_other(db, env):
    """Regression: stock on a zone was frozen by a count over it but got no line."""
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["zone"].id, quantity=40, correlation_id=str(ULID()),
        reference="setup", actor_id=env["actor"],
    )
    count = _started(db, env)
    lines = CycleCountService(db).list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert {line.location_id: line.expected_quantity for line in lines} == {env["zone"].id: 40, env["bin"].id: 100}


def test_admin_stock_overrides_are_refused_during_a_count(db, env):
    """Regression: admin_set_stock to 5 succeeded mid-count and stranded it."""
    stock = StockService(db)
    count = _started(db, env)

    overwrite = stock.admin_set_stock(tenant_id=TENANT, product_id=env["product"], location_id=env["bin"].id, quantity_on_hand=5,
                                      quantity_reserved=0, quantity_in_production=0, actor_id=env["actor"])
    delete = stock.delete_stock_item(tenant_id=TENANT, product_id=env["product"], location_id=env["bin"].id, actor_id=env["actor"])

    assert isinstance(overwrite, Err) and overwrite.code == "LOCATION_FROZEN" and count.number in overwrite.message and count.number in overwrite.message_fr
    assert isinstance(delete, Err) and delete.code == "LOCATION_FROZEN"
    assert _on_hand(db, env) == 100


def _found_product(db, env, *, purchase_price=0):
    product = str(ULID())
    uom = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["product"],)).fetchone()[0]
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, purchase_price) VALUES (%s, %s, %s, 'Found', %s, %s)",
        (product, TENANT, str(ULID()), uom, purchase_price),
    )
    return product


def _add_found(db, env, count, location, product):
    return CycleCountService(db).add_found_line(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, location_id=location, product_id=product
    )


def test_a_found_product_follows_the_two_count_rule_and_approval_creates_valued_stock(db, env):
    """Same valuation as any positive variance: no cost is known, so the catalog purchase price."""
    count = _started(db, env)
    product = _found_product(db, env, purchase_price=250)

    added = _add_found(db, env, count, env["bin"].id, product)
    assert isinstance(added, Ok), added
    line = added.value
    assert (line.expected_quantity, line.status, line.resolution) == (0, "pending", None)
    service = CycleCountService(db)
    assert service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id="c").code == "LINES_UNRESOLVED"

    assert _submit(db, env, count, line, 12).value.status == "pending"
    settled = _submit(db, env, count, line, 12).value
    assert (settled.status, settled.counted_quantity, settled.resolution) == ("counted", 12, None)

    approved = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve")
    assert isinstance(approved, Ok), approved
    on_hand = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s AND product_id = %s",
        (TENANT, env["bin"].id, product),
    ).fetchone()[0]
    assert on_hand == 12
    [layer] = ValuationService(db).list_layers(tenant_id=TENANT, product_id=product)
    assert (layer.quantity_remaining, layer.unit_cost, layer.reference) == (12, 250, f"cycle_count:{count.id}")


def test_a_rejected_found_product_creates_nothing(db, env):
    count = _started(db, env)
    product = _found_product(db, env)
    line = _add_found(db, env, count, env["bin"].id, product).value
    _submit(db, env, count, line, 3)
    _submit(db, env, count, line, 3)

    assert isinstance(CycleCountService(db).resolve_line_variance(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="reject"
    ), Ok)

    assert db.execute("SELECT 1 FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s", (TENANT, product)).fetchone() is None
    assert ValuationService(db).list_layers(tenant_id=TENANT, product_id=product) == []


def test_a_found_line_refuses_a_duplicate_and_a_location_the_count_does_not_cover(db, env):
    count = _started(db, env, scope_location_id=env["bin"].id)
    product = _found_product(db, env)

    assert isinstance(_add_found(db, env, count, env["bin"].id, product), Ok)
    duplicate = _add_found(db, env, count, env["bin"].id, product)
    assert isinstance(duplicate, Err) and duplicate.code == "LINE_ALREADY_EXISTS"
    already_counted = _add_found(db, env, count, env["bin"].id, env["product"])  # a line the count started with
    assert isinstance(already_counted, Err) and already_counted.code == "LINE_ALREADY_EXISTS"

    outside = _add_found(db, env, count, env["second_bin"].id, product)
    assert isinstance(outside, Err) and outside.code == "LOCATION_OUT_OF_SCOPE"
    unknown = _add_found(db, env, count, env["bin"].id, str(ULID()))
    assert isinstance(unknown, Err) and unknown.code == "NOT_FOUND"


def test_a_found_line_needs_a_count_in_progress(db, env):
    draft = _create_count(db, env)
    refused = _add_found(db, env, draft, env["bin"].id, _found_product(db, env))
    assert isinstance(refused, Err) and refused.code == "INVALID_STATE"


def test_a_found_line_on_a_blind_count_reveals_no_books(db, env):
    """The duplicate refusal is the only signal; its message carries no quantity, and the new line none."""
    count = _started(db, env, count_type="blind")

    added = _add_found(db, env, count, env["bin"].id, _found_product(db, env)).value
    assert (added.expected_quantity, added.status) == (None, "pending")
    existing = _first_line(db, count)
    refused = _add_found(db, env, count, existing.location_id, existing.product_id)
    assert refused.code == "LINE_ALREADY_EXISTS"
    assert "100" not in refused.message and "100" not in refused.message_fr


def _second_connection(db):
    return psycopg.connect(db.info.dsn, password=db.info.password, autocommit=True)


def _try_lock(connection, key, *, shared):
    function = "pg_try_advisory_xact_lock_shared" if shared else "pg_try_advisory_xact_lock"
    return connection.execute(f"SELECT {function}(hashtextextended(%s, 0))", (key,)).fetchone()[0]


def test_a_stock_write_in_flight_keeps_a_count_from_starting_on_its_site_only(db, env):
    """Regression: a move past the freeze check wrote after the start committed: expected 100, books
    99, the true 99 counted twice and approved, books 98. The two-connection race itself needs
    committed rows, so here a second connection asks for the lock a start would take."""
    other_site = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code="elsewhere", name="Elsewhere").value
    assert isinstance(StockService(db).issue_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["bin"].id, quantity=1, reference="in-flight", actor_id=env["actor"]
    ), Ok)

    with _second_connection(db) as other:
        assert _try_lock(other, count_start_lock_key(TENANT, env["site"].id), shared=False) is False
        assert _try_lock(other, count_start_lock_key(TENANT, env["site"].id), shared=True) is True  # writers don't block writers
        assert _try_lock(other, count_start_lock_key(TENANT, other_site.id), shared=False) is True


def test_a_count_starting_keeps_stock_writers_out_of_its_site(db, env):
    other_key = count_start_lock_key(TENANT, env["site"].id)
    _started(db, env)
    with _second_connection(db) as other:
        assert _try_lock(other, other_key, shared=True) is False


@pytest.mark.parametrize("write", ["issue", "adjust", "reserve", "release"])
def test_writers_take_the_site_lock_before_any_stock_row_and_before_reading_the_freeze(db, env, write):
    recording = _RecordingConnection(db)
    stock = StockService(recording)
    common = {"tenant_id": TENANT, "product_id": env["product"], "location_id": env["bin"].id}
    if write == "release":  # needs something held, read outside the recording
        assert isinstance(StockService(db).reserve_stock(**common, actor_id=env["actor"], quantity=1, correlation_id="c", reference="r"), Ok)
    {
        "issue": lambda: stock.issue_stock(**common, quantity=1, reference="r", actor_id=env["actor"]),
        "adjust": lambda: stock.adjust_stock(**common, delta=1, reason="r", actor_id=env["actor"]),
        "reserve": lambda: stock.reserve_stock(**common, actor_id=env["actor"], quantity=1, correlation_id="c", reference="r"),
        "release": lambda: stock.release_reserved_quantity(**common, quantity=1, reference="r", actor_id=env["actor"]),
    }[write]()

    position = lambda fragment: next(i for i, q in enumerate(recording.statements) if fragment in q)
    lock = position("pg_advisory_xact_lock_shared")
    assert lock < next(i for i, q in enumerate(recording.statements) if "stock_items" in q and "FOR UPDATE" in q)
    if write in ("issue", "adjust"):
        assert lock < position("warehouse.cycle_counts")


def test_a_count_type_change_is_refused_once_started(db, env):
    """Regression: turning a blind count scheduled mid-way showed the books to whoever was still counting."""
    service = CycleCountService(db)
    count = _create_count(db, env, count_type="blind")
    assert service.admin_update_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, count_type="scheduled").value.count_type == "scheduled"
    assert service.admin_update_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, count_type="blind").value.count_type == "blind"
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)

    refused = service.admin_update_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, count_type="scheduled")

    assert isinstance(refused, Err) and refused.code == "INVALID_STATE"
    assert _first_line(db, count).expected_quantity is None
    same_type = service.admin_update_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, scheduled_for=datetime.date(2030, 1, 2))
    assert isinstance(same_type, Ok) and same_type.value.scheduled_for == datetime.date(2030, 1, 2)


class _RecordingConnection:
    def __init__(self, connection) -> None:
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, query, *args, **kwargs):
        self.statements.append(str(query))
        return self._connection.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def test_counting_and_deciding_lock_the_line_so_two_approvals_cannot_both_adjust(db, env):
    """Regression. The test's rows are uncommitted, so a second connection can't race on them: this
    pins the lock itself, then the second approval's outcome once the first has gone through."""
    count = _started(db, env)
    line = _first_line(db, count)
    recording = _RecordingConnection(db)
    service = CycleCountService(recording)

    def locked_line_reads():
        return [q for q in recording.statements if "FROM warehouse.cycle_count_lines WHERE id" in q and q.rstrip().endswith("FOR UPDATE")]

    service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=90)
    assert locked_line_reads()
    service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=90)

    recording.statements.clear()
    approved = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve")
    assert isinstance(approved, Ok) and locked_line_reads()

    again = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve")
    assert isinstance(again, Err) and again.code == "INVALID_STATE"
    assert _on_hand(db, env) == 90


def test_a_scheduled_second_count_that_disagrees_with_a_matching_first_needs_a_third(db, env):
    count = _create_count(db, env)
    service = CycleCountService(db)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]

    def submit(quantity):
        return service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=quantity).value

    assert submit(100).status == "pending"
    assert submit(97).status == "pending"
    third = submit(97)
    assert third.status == "counted" and third.counted_quantity == 97 and third.resolution is None


def test_cancel_is_allowed_from_draft_and_in_progress_but_not_after(db, env):
    service = CycleCountService(db)

    draft_count = _create_count(db, env)
    assert isinstance(service.cancel_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=draft_count.id), Ok)

    in_progress_count = _create_count(db, env)
    service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=in_progress_count.id).value[0]
    for _ in range(2):  # a scheduled count settles on two equal counts
        service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id, line_id=line.id, counted_quantity=100)
    completed = service.complete_count(
        tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id, correlation_id=str(ULID())
    )
    assert isinstance(completed, Ok)

    cancel_after_complete = service.cancel_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=in_progress_count.id)
    assert isinstance(cancel_after_complete, Err)
    assert cancel_after_complete.code == "INVALID_TRANSITION"


def test_scope_location_only_counts_what_is_under_it(db, env):
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

    count = _started(db, env, scope_location_id=env["zone"].id)
    lines = CycleCountService(db).list_lines(tenant_id=TENANT, cycle_count_id=count.id).value
    assert [line.location_id for line in lines] == [env["bin"].id]


def test_cycle_count_creation_is_audited(db, env):
    count = _create_count(db, env)
    row = db.execute(
        "SELECT actor_id, action FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s",
        (TENANT, count.id),
    ).fetchone()
    assert row == (env["actor"], "cycle_count.created")

"""Integration tests for stock vouchers, the cycle-count freeze, and FIFO valuation."""
from __future__ import annotations

from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.warehouse.api.cycle_count_service import CycleCountService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.site_service import SiteService
from modules.warehouse.api.movements_report_service import MovementsReportService
from modules.warehouse.api.reservation_service import ReservationService
from modules.warehouse.api.valuation_service import ValuationService
from modules.warehouse.api.voucher_service import VoucherService

TENANT = "integration-test-stock-vouchers"
D = Decimal


@pytest.fixture
def env(db):
    actor, uom, film, pasta, customer = (str(ULID()) for _ in range(5))
    main, annex = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    for pid, sku in ((film, "FILM"), (pasta, "PASTA")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (pid, TENANT, sku, sku, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Client', 'customer', 'active')", (customer, TENANT))
    for lid, code in ((main, "MAIN"), (annex, "ANNEX")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (lid, TENANT, code, code))
    return {"actor": actor, "film": film, "pasta": pasta, "customer": customer, "main": main, "annex": annex}


def _on_hand(db, env, product, location):
    row = db.execute("SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
                     (TENANT, product, location)).fetchone()
    return row[0] if row else D("0")


def _voucher(db, env, **kwargs):
    return VoucherService(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], **kwargs)


def _post(db, env, voucher):
    return VoucherService(db).post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=voucher.value["id"], correlation_id="c")


def _receive(db, env, product, qty, cost, location=None):
    voucher = _voucher(db, env, type="receipt", dest_location_id=location or env["main"],
                       lines=[{"product_id": product, "quantity": qty, "unit_cost": cost}])
    result = _post(db, env, voucher)
    assert isinstance(result, Ok), result
    return result.value


# ---- vouchers ----------------------------------------------------------------------------------

def test_receipt_posts_stock_number_and_stamps_moves(db, env):
    posted = _receive(db, env, env["film"], 100, 10)
    assert posted["number"].startswith("BE-") and posted["status"] == "posted"
    assert _on_hand(db, env, env["film"], env["main"]) == D("100")
    move = db.execute("SELECT source_type, source_id, unit_cost FROM warehouse.stock_moves WHERE tenant_id = %s AND reference = %s",
                      (TENANT, posted["number"])).fetchone()
    assert move == ("voucher", posted["id"], D("10.0000"))
    again = _post(db, env, Ok(posted))
    assert isinstance(again, Err) and again.code == "VOUCHER_NOT_DRAFT"


def test_receipt_requires_cost_and_location(db, env):
    assert _voucher(db, env, type="receipt", dest_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 1}]).code == "COST_REQUIRED"
    assert _voucher(db, env, type="receipt", lines=[{"product_id": env["film"], "quantity": 1, "unit_cost": 1}]).code == "LOCATION_REQUIRED"


def test_draft_edit_and_cancel_rules(db, env):
    draft = _voucher(db, env, type="receipt", dest_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 5, "unit_cost": 2}])
    edited = VoucherService(db).update_draft(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"],
                                              changes={"lines": [{"product_id": env["film"], "quantity": 7, "unit_cost": 2}]})
    assert edited.value["lines"][0]["quantity"] == D("7")
    cancelled = VoucherService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"])
    assert cancelled.value["status"] == "cancelled"
    posted = _receive(db, env, env["film"], 1, 1)
    refused = VoucherService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], voucher_id=posted["id"])
    assert isinstance(refused, Err) and refused.code == "VOUCHER_NOT_DRAFT"


def test_issue_refused_without_stock_and_leaves_no_partial_moves(db, env):
    _receive(db, env, env["film"], 10, 5)
    _receive(db, env, env["pasta"], 1, 5)
    voucher = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[
        {"product_id": env["film"], "quantity": 4}, {"product_id": env["pasta"], "quantity": 1}])
    # The stock leaves while the draft waits: posting checks again.
    assert isinstance(StockService(db).issue_stock(tenant_id=TENANT, product_id=env["pasta"], location_id=env["main"], quantity=1, reference="other"), Ok)
    result = _post(db, env, voucher)
    assert isinstance(result, Err) and result.code == "STOCK_INSUFFICIENT"
    assert _on_hand(db, env, env["film"], env["main"]) == D("10")


def test_issue_posts_and_warns_below_minimum(db, env):
    db.execute("UPDATE core.products SET stock_alert_threshold = 8 WHERE id = %s", (env["film"],))
    _receive(db, env, env["film"], 10, 5)
    voucher = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 4}])
    result = _post(db, env, voucher)
    assert isinstance(result, Ok) and result.value["number"].startswith("BS-")
    assert _on_hand(db, env, env["film"], env["main"]) == D("6")
    assert [w["code"] for w in result.value["warnings"]] == ["BELOW_MINIMUM"]
    assert result.value["lines"][0]["unit_cost"] == D("5.0000")  # cost recorded at issue


def test_transfer_moves_between_locations_and_rejects_same_location(db, env):
    _receive(db, env, env["film"], 10, 5)
    same = _voucher(db, env, type="transfer", source_location_id=env["main"], dest_location_id=env["main"],
                    lines=[{"product_id": env["film"], "quantity": 1}])
    assert isinstance(same, Err) and same.code == "INVALID_TRANSFER"
    ok = _voucher(db, env, type="transfer", source_location_id=env["main"], dest_location_id=env["annex"],
                  lines=[{"product_id": env["film"], "quantity": 3}])
    assert isinstance(_post(db, env, ok), Ok)
    assert _on_hand(db, env, env["film"], env["main"]) == D("7") and _on_hand(db, env, env["film"], env["annex"]) == D("3")


def test_return_is_capped_by_the_issue_and_restocks(db, env):
    _receive(db, env, env["film"], 10, 5)
    issue = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 6}])
    issued = _post(db, env, issue).value
    # Refused when entered, like a shortage, not only when posted.
    too_many = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                        lines=[{"product_id": env["film"], "quantity": 7}])
    assert isinstance(too_many, Err) and too_many.code == "RETURN_QTY_EXCEEDED"
    ok = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                  lines=[{"product_id": env["film"], "quantity": 4}])
    waiting = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                       lines=[{"product_id": env["film"], "quantity": 4}])
    assert isinstance(waiting, Ok)  # fits on its own while the first is still a draft
    assert isinstance(_post(db, env, ok), Ok) and _on_hand(db, env, env["film"], env["annex"]) == D("4")
    assert _post(db, env, waiting).code == "RETURN_QTY_EXCEEDED"  # posting checks again
    rest = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                    lines=[{"product_id": env["film"], "quantity": 3}])
    assert rest.code == "RETURN_QTY_EXCEEDED"
    no_source = _voucher(db, env, type="return", dest_location_id=env["annex"], lines=[{"product_id": env["film"], "quantity": 1}])
    assert no_source.code == "RETURN_SOURCE_INVALID"


def test_issue_from_a_sales_order_is_capped_across_vouchers(db, env):
    order = SalesOrderService(db).create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"],
                                               location_id=env["main"], lines=[OrderLine(product_id=env["film"], quantity=10, unit_price=1)])
    order_id = order.id
    _receive(db, env, env["film"], 50, 5)
    assert isinstance(SalesOrderService(db).confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, correlation_id="c"), Ok)
    service = VoucherService(db)
    first = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id,
                                            source_location_id=env["main"], quantities={env["film"]: D("6")})
    assert first.value["partner_id"] == env["customer"] and first.value["ref_type"] == "sales_order"
    assert isinstance(_post(db, env, first), Ok)
    capped = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id,
                                             source_location_id=env["main"], quantities={env["film"]: D("5")})
    assert isinstance(capped, Err) and capped.code == "ORDER_QTY_EXCEEDED"
    # Without quantities the draft carries only what is left to ship.
    rest = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["main"])
    assert [D(str(line["quantity"])) for line in rest.value["lines"]] == [D("4")]
    assert isinstance(_post(db, env, rest), Ok)
    done = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["main"])
    assert isinstance(done, Err) and done.code == "ORDER_FULLY_ISSUED"


def test_an_order_not_yet_confirmed_cannot_be_issued(db, env):
    order = SalesOrderService(db).create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"],
                                               location_id=env["main"], lines=[OrderLine(product_id=env["film"], quantity=10, unit_price=1)])
    _receive(db, env, env["film"], 50, 5)

    refused = VoucherService(db).create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, source_location_id=env["main"])
    assert isinstance(refused, Err) and refused.code == "ORDER_NOT_CONFIRMED"

    # A voucher drafted by hand with the order as its reference is stopped at posting.
    draft = _voucher(db, env, type="issue", source_location_id=env["main"], ref_type="sales_order", ref_id=order.id,
                     lines=[{"product_id": env["film"], "quantity": 10}])
    posted = _post(db, env, draft)
    assert isinstance(posted, Err) and posted.code == "ORDER_NOT_CONFIRMED"
    assert _on_hand(db, env, env["film"], env["main"]) == D("50")


def test_a_draft_made_before_the_order_was_confirmed_posts_after_and_takes_its_reservation_over(db, env):
    order = SalesOrderService(db).create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"],
                                               location_id=env["main"], lines=[OrderLine(product_id=env["film"], quantity=10, unit_price=1)])
    _receive(db, env, env["film"], 50, 5)
    draft = _voucher(db, env, type="issue", source_location_id=env["main"], ref_type="sales_order", ref_id=order.id,
                     lines=[{"product_id": env["film"], "quantity": 10}])
    assert isinstance(draft, Ok)
    assert isinstance(SalesOrderService(db).confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id="c"), Ok)

    posted = _post(db, env, draft)

    assert isinstance(posted, Ok), posted
    assert _on_hand(db, env, env["film"], env["main"]) == D("40")


# ---- valuation ---------------------------------------------------------------------------------

def _film_value(db, env):
    return next(v for v in ValuationService(db).get_valuation(tenant_id=TENANT) if v.product_id == env["film"])


def test_fifo_valuation_spans_locations_and_issue_draws_the_oldest_layer(db, env):
    _receive(db, env, env["film"], 100, 10)
    _receive(db, env, env["film"], 100, 20, location=env["annex"])  # valuation is plant-wide
    before = _film_value(db, env)
    assert before.quantity == 200 and before.value == 3000 and before.average_unit_cost == 15
    issue = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 50}])
    posted = _post(db, env, issue)
    assert isinstance(posted, Ok)
    after = _film_value(db, env)
    assert after.value == 2500  # 50 @ 10 + 100 @ 20
    line = posted.value["lines"][0]
    assert float(line["unit_cost"]) == 10  # recorded so a return restocks at the same figure


def test_stock_received_without_cost_is_counted_but_not_valued(db, env):
    StockService(db).receive_stock(tenant_id=TENANT, product_id=env["pasta"], location_id=env["main"], quantity=5,
                                   correlation_id="c", reference="manual")
    pasta = next(v for v in ValuationService(db).get_valuation(tenant_id=TENANT) if v.product_id == env["pasta"])
    assert pasta.unvalued_quantity == 5


def test_movements_report_links_the_voucher(db, env):
    posted = _receive(db, env, env["film"], 5, 2)
    rows = MovementsReportService(db).movements_report(tenant_id=TENANT, product_id=env["film"])
    assert rows[0]["voucher_number"] == posted["number"] and rows[0]["unit_cost"] == D("2.0000")


# ---- cycle-count freeze ------------------------------------------------------------------------

def _site_for(db, env):
    """Put the fixture's two locations in one site as bins, so a cycle count can cover them."""
    site = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code="main", name="Main").value
    db.execute("UPDATE warehouse.locations SET site_id = %s, location_type = 'bin' WHERE tenant_id = %s", (site.id, TENANT))
    return site


def _started_count(db, env, scope=None):
    site = _site_for(db, env)
    service = CycleCountService(db)
    count = service.create_count(tenant_id=TENANT, actor_id=env["actor"], site_id=site.id, scope_location_id=scope)
    assert isinstance(count, Ok), count
    started = service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.value.id)
    assert isinstance(started, Ok)
    return count.value


def test_a_started_cycle_count_freezes_its_scope_until_completed(db, env):
    _receive(db, env, env["film"], 10, 5)
    count = _started_count(db, env, scope=env["main"])

    stock = StockService(db)
    blocked = [
        stock.receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1, correlation_id="c", reference="x"),
        stock.issue_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1, reference="x"),
        stock.adjust_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], delta=1, reason="x"),
        stock.transfer_stock(tenant_id=TENANT, product_id=env["film"], from_location_id=env["main"], to_location_id=env["annex"],
                             quantity=1, correlation_id="c", reference="x"),
    ]
    assert all(isinstance(r, Err) and r.code == "LOCATION_FROZEN" for r in blocked)
    voucher = _voucher(db, env, type="receipt", dest_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 1, "unit_cost": 1}])
    assert _post(db, env, voucher).code == "LOCATION_FROZEN"
    # Outside the count's scope stock still moves.
    assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["annex"], quantity=1,
                                          correlation_id="c", reference="x"), Ok)

    service = CycleCountService(db)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]
    for _ in range(2):
        assert isinstance(service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id,
                                                    line_id=line.id, counted_quantity=10), Ok)
    assert isinstance(service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id="c"), Ok)
    assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1,
                                          correlation_id="c", reference="x"), Ok)


def test_the_count_rule_two_equal_counts_else_a_third_and_approval_adjusts_stock(db, env):
    _receive(db, env, env["film"], 10, 5)
    count = _started_count(db, env, scope=env["main"])
    service = CycleCountService(db)
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]

    def submit(qty):
        result = service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id,
                                           counted_quantity=qty)
        assert isinstance(result, Ok), result
        return result.value

    first = submit(8)  # one count never settles
    assert first.status == "pending" and first.counted_quantity is None and first.counts_recorded == 1
    second = submit(9)  # two different counts: a third decides
    assert second.status == "pending" and second.counted_quantity is None
    third = submit(8)
    assert third.status == "counted" and third.counted_quantity == 8 and third.resolution is None  # variance -2 awaits a decision
    assert service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id,
                                     counted_quantity=8).code == "INVALID_STATE"

    refused = service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id="c")
    assert isinstance(refused, Err) and refused.code == "LINES_UNRESOLVED"
    resolved = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id,
                                             decision="approve", observation="counted again")
    assert isinstance(resolved, Ok)  # the count's own adjustment passes its own freeze
    assert _on_hand(db, env, env["film"], env["main"]) == D("8")
    assert isinstance(service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id="c"), Ok)


def test_cancelling_a_cycle_count_unfreezes_its_scope(db, env):
    _receive(db, env, env["film"], 10, 5)
    count = _started_count(db, env, scope=env["main"])
    stock = StockService(db)
    assert stock.issue_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1, reference="x").code == "LOCATION_FROZEN"
    assert isinstance(CycleCountService(db).cancel_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id), Ok)
    assert isinstance(stock.issue_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1, reference="x"), Ok)

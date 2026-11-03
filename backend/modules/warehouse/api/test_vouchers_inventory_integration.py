"""Integration tests for stock vouchers, the inventory freeze, and weighted-average valuation."""
from __future__ import annotations

from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.warehouse.api.inventory_service import InventoryService
from modules.warehouse.api.service import StockService
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
    assert posted["number"].startswith("RCP-") and posted["status"] == "posted"
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
    voucher = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[
        {"product_id": env["film"], "quantity": 4}, {"product_id": env["pasta"], "quantity": 1}])
    result = _post(db, env, voucher)
    assert isinstance(result, Err) and result.code == "STOCK_INSUFFICIENT"
    assert _on_hand(db, env, env["film"], env["main"]) == D("10")


def test_issue_posts_and_warns_below_minimum(db, env):
    db.execute("UPDATE core.products SET stock_alert_threshold = 8 WHERE id = %s", (env["film"],))
    _receive(db, env, env["film"], 10, 5)
    voucher = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 4}])
    result = _post(db, env, voucher)
    assert isinstance(result, Ok) and result.value["number"].startswith("ISS-")
    assert _on_hand(db, env, env["film"], env["main"]) == D("6")
    assert [w["code"] for w in result.value["warnings"]] == ["BELOW_MINIMUM"]
    assert result.value["lines"][0]["unit_cost"] == D("5.0000")  # cost recorded at issue


def test_transfer_moves_between_locations_and_rejects_same_location(db, env):
    _receive(db, env, env["film"], 10, 5)
    same = _voucher(db, env, type="transfer", source_location_id=env["main"], dest_location_id=env["main"],
                    lines=[{"product_id": env["film"], "quantity": 1}])
    assert isinstance(_post(db, env, same), Err)
    ok = _voucher(db, env, type="transfer", source_location_id=env["main"], dest_location_id=env["annex"],
                  lines=[{"product_id": env["film"], "quantity": 3}])
    assert isinstance(_post(db, env, ok), Ok)
    assert _on_hand(db, env, env["film"], env["main"]) == D("7") and _on_hand(db, env, env["film"], env["annex"]) == D("3")


def test_return_is_capped_by_the_issue_and_restocks(db, env):
    _receive(db, env, env["film"], 10, 5)
    issue = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 6}])
    issued = _post(db, env, issue).value
    too_many = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                        lines=[{"product_id": env["film"], "quantity": 7}])
    refused = _post(db, env, too_many)
    assert isinstance(refused, Err) and refused.code == "RETURN_QTY_EXCEEDED"
    ok = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                  lines=[{"product_id": env["film"], "quantity": 4}])
    assert isinstance(_post(db, env, ok), Ok) and _on_hand(db, env, env["film"], env["annex"]) == D("4")
    rest = _voucher(db, env, type="return", dest_location_id=env["annex"], return_of_voucher_id=issued["id"],
                    lines=[{"product_id": env["film"], "quantity": 3}])
    assert _post(db, env, rest).code == "RETURN_QTY_EXCEEDED"
    no_source = _voucher(db, env, type="return", dest_location_id=env["annex"], lines=[{"product_id": env["film"], "quantity": 1}])
    assert no_source.code == "RETURN_SOURCE_INVALID"


def test_issue_from_a_sales_order_is_capped_across_vouchers(db, env):
    order = SalesOrderService(db).create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"],
                                               location_id=env["main"], lines=[OrderLine(product_id=env["film"], quantity=10, unit_price=1)])
    order_id = order.id
    _receive(db, env, env["film"], 50, 5)
    service = VoucherService(db)
    first = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id,
                                            source_location_id=env["main"], quantities={env["film"]: D("6")})
    assert first.value["partner_id"] == env["customer"] and first.value["ref_type"] == "sales_order"
    assert isinstance(_post(db, env, first), Ok)
    second = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id,
                                             source_location_id=env["main"], quantities={env["film"]: D("5")})
    capped = _post(db, env, second)
    assert isinstance(capped, Err) and capped.code == "ORDER_QTY_EXCEEDED"
    rest = service.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id,
                                           source_location_id=env["main"], quantities={env["film"]: D("4")})
    assert isinstance(_post(db, env, rest), Ok)


# ---- valuation ---------------------------------------------------------------------------------

def test_weighted_average_follows_receipts_only(db, env):
    _receive(db, env, env["film"], 100, 10)
    _receive(db, env, env["film"], 100, 20, location=env["annex"])  # average spans locations
    valuation = ValuationService(db).valued_stock(tenant_id=TENANT)
    row = next(i for i in valuation["items"] if i["product_id"] == env["film"])
    assert row["avg_cost"] == D("15.0000") and row["quantity"] == D("200") and row["value"] == D("3000.00")
    issue = _voucher(db, env, type="issue", source_location_id=env["main"], lines=[{"product_id": env["film"], "quantity": 50}])
    _post(db, env, issue)
    after = next(i for i in ValuationService(db).valued_stock(tenant_id=TENANT)["items"] if i["product_id"] == env["film"])
    assert after["avg_cost"] == D("15.0000") and after["value"] == D("2250.00")


def test_valued_stock_flags_products_without_cost_and_filters_by_location(db, env):
    StockService(db).receive_stock(tenant_id=TENANT, product_id=env["pasta"], location_id=env["main"], quantity=5,
                                   correlation_id="c", reference="manual")
    report = ValuationService(db).valued_stock(tenant_id=TENANT, location_id=env["main"])
    assert report["missing_cost_count"] == 1 and report["items"][0]["missing_cost"]
    assert ValuationService(db).valued_stock(tenant_id=TENANT, location_id=env["annex"])["items"] == []


def test_movements_report_links_the_voucher(db, env):
    posted = _receive(db, env, env["film"], 5, 2)
    rows = ValuationService(db).movements_report(tenant_id=TENANT, product_id=env["film"])
    assert rows[0]["voucher_number"] == posted["number"] and rows[0]["unit_cost"] == D("2.0000")


# ---- inventory ---------------------------------------------------------------------------------

def _inventory(db, env, kind="full", location=None):
    result = InventoryService(db).open(tenant_id=TENANT, actor_id=env["actor"], location_id=location or env["main"], type=kind)
    assert isinstance(result, Ok), result
    return result.value


def _count(db, env, inventory, line, which, qty, observation=None):
    return InventoryService(db).record_count(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"],
                                             line_id=line["id"], which=which, quantity=D(str(qty)), observation=observation)


def test_full_inventory_freezes_the_location_until_closed(db, env):
    _receive(db, env, env["film"], 10, 5)
    inventory = _inventory(db, env)
    assert len(inventory["lines"]) == 1 and inventory["lines"][0]["theoretical_qty"] == D("10")
    again = InventoryService(db).open(tenant_id=TENANT, actor_id=env["actor"], location_id=env["main"], type="full")
    assert isinstance(again, Err) and again.code == "INVENTORY_ALREADY_OPEN"

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
    assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["annex"], quantity=1,
                                          correlation_id="c", reference="x"), Ok)

    line = inventory["lines"][0]
    _count(db, env, inventory, line, 1, 10)
    _count(db, env, inventory, line, 2, 10)
    closed = InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c")
    assert isinstance(closed, Ok) and closed.value["status"] == "closed"
    assert isinstance(stock.receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1,
                                          correlation_id="c", reference="x"), Ok)


def test_close_adjusts_stock_by_the_variance_and_demands_observations(db, env):
    _receive(db, env, env["film"], 10, 5)
    inventory = _inventory(db, env)
    line = inventory["lines"][0]
    _count(db, env, inventory, line, 1, 8)
    unsettled = InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c")
    assert isinstance(unsettled, Err) and unsettled.code == "COUNT_REQUIRED"
    _count(db, env, inventory, line, 2, 9)
    assert InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c").code == "COUNT_REQUIRED"
    updated = _count(db, env, inventory, line, 3, 9, observation="two cartons damaged")
    assert updated.value["lines"][0]["final_qty"] == D("9") and updated.value["lines"][0]["variance"] == D("-1")

    cleared = _count(db, env, inventory, line, 3, 8)
    assert cleared.value["lines"][0]["final_qty"] == D("8")
    closed = InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c")
    assert isinstance(closed, Ok)
    assert _on_hand(db, env, env["film"], env["main"]) == D("8")
    move = db.execute("SELECT move_type, source_type, quantity FROM warehouse.stock_moves WHERE tenant_id = %s AND reference = %s",
                      (TENANT, inventory["number"])).fetchone()
    assert move == ("adjustment", "inventory", D("-2"))


def test_variance_without_observation_cannot_close(db, env):
    _receive(db, env, env["film"], 10, 5)
    inventory = _inventory(db, env)
    line = inventory["lines"][0]
    _count(db, env, inventory, line, 1, 7)
    _count(db, env, inventory, line, 2, 7)
    refused = InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c")
    assert isinstance(refused, Err) and refused.code == "OBSERVATION_REQUIRED"
    _count(db, env, inventory, line, 2, 7, observation="shrinkage")
    assert isinstance(InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c"), Ok)


def test_interim_inventory_neither_freezes_nor_adjusts(db, env):
    _receive(db, env, env["film"], 10, 5)
    inventory = _inventory(db, env, kind="interim")
    assert isinstance(StockService(db).issue_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1, reference="x"), Ok)
    line = inventory["lines"][0]
    _count(db, env, inventory, line, 1, 3)
    _count(db, env, inventory, line, 2, 3, observation="count only")
    assert isinstance(InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c"), Ok)
    assert _on_hand(db, env, env["film"], env["main"]) == D("9")  # untouched by the interim count


def test_cancel_unfreezes_and_extra_lines_start_at_zero(db, env):
    _receive(db, env, env["film"], 10, 5)
    inventory = _inventory(db, env)
    extra = InventoryService(db).add_line(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], product_id=env["pasta"])
    assert {l["sku"]: l["theoretical_qty"] for l in extra.value["lines"]} == {"FILM": D("10"), "PASTA": D("0")}
    cancelled = InventoryService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"])
    assert cancelled.value["status"] == "cancelled"
    assert isinstance(StockService(db).issue_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=1, reference="x"), Ok)
    closed_again = InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=inventory["id"], correlation_id="c")
    assert isinstance(closed_again, Err) and closed_again.code == "INVENTORY_NOT_OPEN"


def test_blank_sheet_hides_counts(db, env):
    _receive(db, env, env["film"], 10, 5)
    inventory = _inventory(db, env)
    _count(db, env, inventory, inventory["lines"][0], 1, 4)
    sheet = InventoryService(db).blank_sheet(tenant_id=TENANT, inventory_id=inventory["id"]).value
    assert sheet["lines"][0]["theoretical_qty"] == D("10") and sheet["lines"][0]["count_1"] is None

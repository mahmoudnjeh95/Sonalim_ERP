"""The stock requirements of the vendor manual: interim inventory, observations, delivery notes, returns,
checks at entry, the valuation method, goods-receipt vouchers, and attached files."""
from __future__ import annotations

import datetime

from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.procurement.api.service import PurchaseOrderService
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.warehouse.api.attachment_service import MAX_ATTACHMENT_BYTES, AttachmentService
from modules.warehouse.api.cycle_count_service import CycleCountService
from modules.warehouse.api.movements_report_service import MovementsReportService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.site_service import SiteService
from modules.warehouse.api.valuation_service import ValuationService
from modules.warehouse.api.voucher_service import VoucherService

TENANT = "integration-test-stock-manual"
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


def _service(db):
    return VoucherService(db)


def _posted(db, env, **kwargs):
    draft = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], **kwargs)
    assert isinstance(draft, Ok), draft
    posted = _service(db).post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert isinstance(posted, Ok), posted
    return posted.value


def _receive(db, env, quantity, cost, product="film", location="main"):
    return _posted(db, env, type="receipt", dest_location_id=env[location],
                   lines=[{"product_id": env[product], "quantity": D(quantity), "unit_cost": D(cost)}])


def _issue(db, env, quantity, product="film", location="main", **kwargs):
    return _posted(db, env, type="issue", source_location_id=env[location], partner_id=env["customer"],
                   lines=[{"product_id": env[product], "quantity": D(quantity)}], **kwargs)


def _site_count(db, env, **kwargs):
    site = SiteService(db).create_site(tenant_id=TENANT, actor_id=env["actor"], code=f"S{ULID()}"[:12], name="Site")
    db.execute("UPDATE warehouse.locations SET site_id = %s WHERE tenant_id = %s AND id = %s", (site.value.id, TENANT, env["main"]))
    service = CycleCountService(db)
    created = service.create_count(tenant_id=TENANT, actor_id=env["actor"], site_id=site.value.id, scope_location_id=env["main"], **kwargs)
    assert isinstance(created, Ok), created
    started = service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=created.value.id)
    assert isinstance(started, Ok), started
    return service, started.value


def _count_line(service, env, count, *counts):
    line = service.list_lines(tenant_id=TENANT, cycle_count_id=count.id).value[0]
    for counted in counts:
        result = service.submit_line_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, counted_quantity=counted)
        assert isinstance(result, Ok), result
    return result.value


# ---- interim inventory and observations --------------------------------------------------------
def test_an_interim_inventory_blocks_nothing_and_changes_no_stock(db, env):
    _receive(db, env, 100, 5)
    service, count = _site_count(db, env, mode="interim")
    assert count.mode == "interim"
    assert service.frozen_scopes(tenant_id=TENANT) == []
    _issue(db, env, 10)  # moves go on; the expected quantity stays the one read at the start

    line = _count_line(service, env, count, 80, 80)
    assert line.counted_quantity == 80 and line.resolution is None

    refused = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve", observation="x")
    assert isinstance(refused, Err) and refused.code == "INVALID_DECISION"
    noted = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="note", observation="casse")
    assert isinstance(noted, Ok) and noted.value.resolution == "noted" and noted.value.observation == "casse"
    done = service.complete_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, correlation_id="c")
    assert isinstance(done, Ok)
    assert _on_hand(db, env, env["film"], env["main"]) == 90


def test_an_interim_inventory_does_not_count_as_an_overlap(db, env):
    _receive(db, env, 100, 5)
    service, interim = _site_count(db, env, mode="interim")
    full = service.create_count(tenant_id=TENANT, actor_id=env["actor"], site_id=interim.site_id, scope_location_id=env["main"])
    assert isinstance(service.start_count(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=full.value.id), Ok)


def test_a_variance_needs_an_observation_and_a_full_inventory_cannot_only_note_it(db, env):
    _receive(db, env, 100, 5)
    service, count = _site_count(db, env, note="fin d'année")
    assert count.note == "fin d'année"
    line = _count_line(service, env, count, 90, 90)
    for decision, observation, code in (("approve", None, "OBSERVATION_REQUIRED"), ("reject", "   ", "OBSERVATION_REQUIRED"), ("note", "x", "INVALID_DECISION")):
        refused = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision=decision, observation=observation)
        assert isinstance(refused, Err) and refused.code == code
    assert _on_hand(db, env, env["film"], env["main"]) == 100
    approved = service.resolve_line_variance(tenant_id=TENANT, actor_id=env["actor"], cycle_count_id=count.id, line_id=line.id, decision="approve", observation="manquant")
    assert isinstance(approved, Ok) and approved.value.observation == "manquant"
    assert _on_hand(db, env, env["film"], env["main"]) == 90


def test_a_matching_line_needs_no_observation(db, env):
    _receive(db, env, 100, 5)
    service, count = _site_count(db, env)
    line = _count_line(service, env, count, 100, 100)
    assert line.resolution == "matched" and line.observation is None


# ---- checks at entry ----------------------------------------------------------------------------
def test_an_issue_or_transfer_beyond_stock_is_refused_when_entered_not_only_when_posted(db, env):
    _receive(db, env, 10, 5)
    for kind, extra in (("issue", {}), ("transfer", {"dest_location_id": env["annex"]})):
        refused = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type=kind, source_location_id=env["main"],
                                            lines=[{"product_id": env["film"], "quantity": D(11)}], **extra)
        assert isinstance(refused, Err) and refused.code == "STOCK_INSUFFICIENT"
    draft = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type="issue", source_location_id=env["main"],
                                      lines=[{"product_id": env["film"], "quantity": D(5)}])
    edited = _service(db).update_draft(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"],
                                       changes={"lines": [{"product_id": env["film"], "quantity": D(11)}]})
    assert isinstance(edited, Err) and edited.code == "STOCK_INSUFFICIENT"


def test_the_safety_quantity_alerts_when_the_quantity_is_entered(db, env):
    db.execute("UPDATE core.products SET stock_alert_threshold = 8 WHERE id = %s", (env["film"],))
    _receive(db, env, 10, 5)
    fine = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type="issue", source_location_id=env["main"],
                                     lines=[{"product_id": env["film"], "quantity": D(2)}])
    assert fine.value["warnings"] == []
    below = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type="issue", source_location_id=env["main"],
                                      lines=[{"product_id": env["film"], "quantity": D(3)}])
    assert [w["code"] for w in below.value["warnings"]] == ["BELOW_MINIMUM"]


def test_document_date_defaults_to_today_and_can_be_set(db, env):
    voucher = _receive(db, env, 1, 5)
    assert voucher["document_date"] is not None
    dated = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type="receipt", dest_location_id=env["main"],
                                      document_date="2026-05-21", lines=[{"product_id": env["film"], "quantity": D(1), "unit_cost": D(5)}])
    assert str(dated.value["document_date"]) == "2026-05-21"


def test_voucher_numbers_use_the_manuals_codes(db, env):
    assert _receive(db, env, 10, 5)["number"].startswith("BE-")
    assert _issue(db, env, 1)["number"].startswith("BS-")


# ---- delivery notes and returns -----------------------------------------------------------------
def test_a_delivery_note_from_an_issue_moves_no_stock_and_cannot_exceed_it(db, env):
    _receive(db, env, 100, 5)
    issue = _issue(db, env, 30)
    service = _service(db)
    first = service.generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c", quantities={env["film"]: D(20)})
    assert isinstance(first, Ok) and first.value["number"].startswith("BL-") and first.value["billable"] is True
    assert first.value["partner_id"] == env["customer"]
    assert _on_hand(db, env, env["film"], env["main"]) == 70

    over = service.generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c", quantities={env["film"]: D(11)})
    assert isinstance(over, Err) and over.code == "DELIVERY_QTY_EXCEEDED"
    rest = service.generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c")
    assert [D(str(line["quantity"])) for line in rest.value["lines"]] == [D(10)]
    done = service.generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c")
    assert isinstance(done, Err) and done.code == "NOTHING_TO_DELIVER"
    assert _on_hand(db, env, env["film"], env["main"]) == 70


def test_a_delivery_note_after_a_return_redelivers_and_is_not_billable(db, env):
    _receive(db, env, 100, 5)
    issue = _issue(db, env, 30)
    returned = _posted(db, env, type="return", dest_location_id=env["main"], return_of_voucher_id=issue["id"], note="abîmé",
                       lines=[{"product_id": env["film"], "quantity": D(10)}])
    assert _on_hand(db, env, env["film"], env["main"]) == 80
    assert returned["partner_id"] == env["customer"]
    note = _service(db).generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=returned["id"], correlation_id="c")
    assert isinstance(note, Ok) and note.value["billable"] is False
    assert _on_hand(db, env, env["film"], env["main"]) == 70
    types = [(row["move_type"], row["voucher_type"]) for row in MovementsReportService(db).movements_report(tenant_id=TENANT, product_id=env["film"])]
    assert ("issue", "delivery") in types  # the real move of the re-delivery, once


def test_a_draft_or_cancelled_voucher_gives_no_delivery_note(db, env):
    _receive(db, env, 100, 5)
    draft = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type="issue", source_location_id=env["main"],
                                      lines=[{"product_id": env["film"], "quantity": D(1)}])
    refused = _service(db).generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert isinstance(refused, Err) and refused.code == "DELIVERY_SOURCE_INVALID"


def test_a_return_against_a_delivery_note_counts_against_the_issue(db, env):
    _receive(db, env, 100, 5)
    issue = _issue(db, env, 30)
    note = _service(db).generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c")
    returned = _posted(db, env, type="return", dest_location_id=env["main"], return_of_voucher_id=note.value["id"],
                       lines=[{"product_id": env["film"], "quantity": D(30)}])
    assert returned["return_of_voucher_id"] == issue["id"]
    over = _service(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], type="return", dest_location_id=env["main"],
                                     return_of_voucher_id=note.value["id"], lines=[{"product_id": env["film"], "quantity": D(1)}])
    assert isinstance(over, Err) and over.code == "RETURN_QTY_EXCEEDED"


def test_a_return_can_add_a_product_and_restocks_at_the_cost_it_left_at(db, env):
    _receive(db, env, 10, 100)
    _receive(db, env, 10, 200)
    issue = _issue(db, env, 10)  # FIFO: the 100 layer
    _posted(db, env, type="return", dest_location_id=env["main"], return_of_voucher_id=issue["id"],
            lines=[{"product_id": env["film"], "quantity": D(4)}, {"product_id": env["pasta"], "quantity": D(2)}])
    assert _on_hand(db, env, env["pasta"], env["main"]) == 2
    layers = ValuationService(db).list_layers(tenant_id=TENANT, product_id=env["film"])
    assert [(l.quantity_remaining, l.unit_cost) for l in layers if l.move_type == "return"] == [(4.0, 100.0)]


def test_the_movements_report_traces_a_delivery_note_with_no_move(db, env):
    _receive(db, env, 100, 5)
    issue = _issue(db, env, 30)
    note = _service(db).generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c")
    rows = MovementsReportService(db).movements_report(tenant_id=TENANT, product_id=env["film"])
    deliveries = [r for r in rows if r["move_type"] == "delivery"]
    assert [(r["voucher_number"], r["quantity"]) for r in deliveries] == [(note.value["number"], D(30))]
    only = MovementsReportService(db).movements_report(tenant_id=TENANT, move_type="delivery")
    assert len(only) == 1
    assert MovementsReportService(db).movements_report(tenant_id=TENANT, move_type="receipt")[0]["move_type"] == "receipt"


# ---- from a sales order --------------------------------------------------------------------------
def _confirmed_order(db, env, quantity):
    sales = SalesOrderService(db)
    order = sales.create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], location_id=env["main"],
                               lines=[OrderLine(product_id=env["film"], quantity=float(quantity), unit_price=10.0)])
    confirmed = sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id="c")
    assert isinstance(confirmed, Ok), confirmed
    return order.id


def test_with_only_the_reserved_stock_the_order_can_still_be_issued_by_voucher(db, env):
    _receive(db, env, 30, 5)
    order_id = _confirmed_order(db, env, 30)
    draft = _service(db).create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["main"])
    assert isinstance(draft, Ok), draft
    posted = _service(db).post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert isinstance(posted, Ok), posted
    assert _on_hand(db, env, env["film"], env["main"]) == 0


def test_the_order_cap_is_checked_when_the_quantity_is_entered(db, env):
    _receive(db, env, 100, 5)
    order_id = _confirmed_order(db, env, 30)
    refused = _service(db).create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["main"],
                                                   quantities={env["film"]: D(31)})
    assert isinstance(refused, Err) and refused.code == "ORDER_QTY_EXCEEDED"


# ---- valuation method ----------------------------------------------------------------------------
def test_fifo_is_the_default_and_the_average_follows_the_manuals_formula(db, env):
    valuation = ValuationService(db)
    assert valuation.valuation_method(tenant_id=TENANT) == "fifo"
    _receive(db, env, 10, 100)
    assert isinstance(valuation.set_valuation_method(tenant_id=TENANT, actor_id=env["actor"], method="average"), Ok)
    _receive(db, env, 30, 200)  # (10*100 + 30*200) / 40 = 175
    assert valuation.get_valuation(tenant_id=TENANT)[0].average_unit_cost == 175

    issue = _issue(db, env, 10)  # leaves at the average, not at the oldest layer's 100
    assert float(issue["lines"][0]["unit_cost"]) == 175
    _receive(db, env, 30, 100)  # (30*175 + 30*100) / 60 = 137.5
    assert valuation.get_valuation(tenant_id=TENANT)[0].average_unit_cost == 137.5


def test_choosing_the_average_levels_the_open_layers_at_once_and_refuses_an_unknown_method(db, env):
    valuation = ValuationService(db)
    _receive(db, env, 10, 100)
    _receive(db, env, 10, 200)
    before = valuation.get_valuation(tenant_id=TENANT)[0].value
    valuation.set_valuation_method(tenant_id=TENANT, actor_id=env["actor"], method="average")
    layers = valuation.list_layers(tenant_id=TENANT, product_id=env["film"])
    assert {l.unit_cost for l in layers} == {150.0}
    assert valuation.get_valuation(tenant_id=TENANT)[0].value == before
    refused = valuation.set_valuation_method(tenant_id=TENANT, actor_id=env["actor"], method="lifo")
    assert isinstance(refused, Err) and refused.code == "INVALID_VALUATION_METHOD"


def test_under_the_average_an_inflow_without_a_cost_takes_the_average(db, env):
    valuation = ValuationService(db)
    valuation.set_valuation_method(tenant_id=TENANT, actor_id=env["actor"], method="average")
    _receive(db, env, 10, 100)
    StockService(db).receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=10, correlation_id="c", reference="manual")
    product = valuation.get_valuation(tenant_id=TENANT)[0]
    assert product.unvalued_quantity == 0 and product.average_unit_cost == 100


def test_the_valuation_tells_when_stock_last_came_in(db, env):
    _receive(db, env, 10, 100)
    assert ValuationService(db).get_valuation(tenant_id=TENANT)[0].last_received_at is not None


# ---- goods-receipt vouchers ----------------------------------------------------------------------
def test_a_goods_receipt_gets_one_entry_voucher_and_no_second_stock_move(db, env):
    receipt_id = str(ULID())
    StockService(db).receive_stock(tenant_id=TENANT, product_id=env["film"], location_id=env["main"], quantity=12, correlation_id="c",
                                   reference=f"purchase_order_receipt:{receipt_id}", unit_cost=250.0)
    service = _service(db)
    assert [r["receipt_id"] for r in service.list_unvouchered_purchase_receipts(tenant_id=TENANT)] == [receipt_id]
    voucher = service.create_receipt_from_purchase_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=receipt_id, correlation_id="c")
    assert isinstance(voucher, Ok), voucher
    assert voucher.value["status"] == "posted" and voucher.value["number"].startswith("BE-")
    assert float(voucher.value["lines"][0]["unit_cost"]) == 250 and float(voucher.value["lines"][0]["quantity"]) == 12
    assert _on_hand(db, env, env["film"], env["main"]) == 12
    again = service.create_receipt_from_purchase_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=receipt_id, correlation_id="c")
    assert again.value["id"] == voucher.value["id"]
    assert service.list_unvouchered_purchase_receipts(tenant_id=TENANT) == []


def test_the_receipts_waiting_for_a_voucher_say_who_delivered_what(db, env):
    supplier = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Moulins du Sahel', 'supplier', 'active')",
               (supplier, TENANT))
    uom = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["film"],)).fetchone()[0]
    procurement = PurchaseOrderService(db)
    order = procurement.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=supplier, order_date=datetime.date(2026, 10, 1), currency_code="XOF",
        lines=[{"product_id": env["film"], "uom_id": uom, "quantity_ordered": 5, "unit_price": 100, "unit_price_currency": "XOF"}],
    ).value
    for method in ("validate_order", "approve_order", "place_order"):
        assert isinstance(getattr(procurement, method)(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id), Ok)
    line = procurement.list_lines(tenant_id=TENANT, purchase_order_id=order.id)[0]
    receipt = procurement.create_receipt(
        tenant_id=TENANT, actor_id=env["actor"], purchase_order_id=order.id, location_id=env["main"], currency_code="XOF",
        invoice_number="FAC-778", invoice_date=datetime.date(2026, 10, 2), lines=[{"purchase_order_line_id": line.id, "quantity": 5}],
        base_cost=500,
    ).value
    assert isinstance(procurement.confirm_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=receipt.id, correlation_id="c"), Ok)
    [waiting] = _service(db).list_unvouchered_purchase_receipts(tenant_id=TENANT)
    assert waiting["receipt_id"] == receipt.id and waiting["purchase_order_id"] == order.id
    assert waiting["supplier_name"] == "Moulins du Sahel" and waiting["invoice_number"] == "FAC-778" and waiting["lines"] == 1


def test_a_goods_receipt_that_moved_no_stock_gets_no_voucher(db, env):
    refused = _service(db).create_receipt_from_purchase_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=str(ULID()), correlation_id="c")
    assert isinstance(refused, Err) and refused.code == "RECEIPT_NOT_CONFIRMED"


# ---- attached files ------------------------------------------------------------------------------
def test_files_attach_to_a_document_and_are_scoped_to_it(db, env):
    voucher = _receive(db, env, 1, 5)
    files = AttachmentService(db)
    added = files.add(tenant_id=TENANT, actor_id=env["actor"], entity_type="voucher", entity_id=voucher["id"],
                      filename="bl.pdf", content_type="application/pdf", content=b"%PDF")
    assert isinstance(added, Ok), added
    assert [f["filename"] for f in files.list(tenant_id=TENANT, entity_type="voucher", entity_id=voucher["id"])] == ["bl.pdf"]
    got = files.get(tenant_id=TENANT, entity_type="voucher", entity_id=voucher["id"], attachment_id=added.value["id"])
    assert got.value["content"] == b"%PDF"
    elsewhere = files.get(tenant_id="another-tenant", entity_type="voucher", entity_id=voucher["id"], attachment_id=added.value["id"])
    assert isinstance(elsewhere, Err) and elsewhere.code == "NOT_FOUND"
    assert isinstance(files.delete(tenant_id=TENANT, actor_id=env["actor"], entity_type="voucher", entity_id=voucher["id"], attachment_id=added.value["id"]), Ok)
    assert files.list(tenant_id=TENANT, entity_type="voucher", entity_id=voucher["id"]) == []


def test_a_file_is_refused_when_empty_too_large_or_on_a_missing_document(db, env):
    voucher = _receive(db, env, 1, 5)
    files = AttachmentService(db)
    for entity_id, content, code in ((voucher["id"], b"", "INVALID_FILE"), (voucher["id"], b"x" * (MAX_ATTACHMENT_BYTES + 1), "FILE_TOO_LARGE"), ("nope", b"x", "NOT_FOUND")):
        refused = files.add(tenant_id=TENANT, actor_id=env["actor"], entity_type="voucher", entity_id=entity_id, filename="a", content_type="text/plain", content=content)
        assert isinstance(refused, Err) and refused.code == code

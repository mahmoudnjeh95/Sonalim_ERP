"""Integration test: sales invoices follow the delivery, and returns become credit notes.

Deliveries go through the real warehouse services (an issue voucher and its delivery notes, or the
fulfilment flow) and the outbox events they publish are handed to finance's consumers, as the worker does."""
from __future__ import annotations

from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.events.consumers import _process
from modules.finance.api.billing_service import DeliveryBillingService
from modules.finance.api.service import InvoiceService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the ledger handlers)
from modules.finance.events.consumers import _handle_shipment_shipped, _handle_voucher_posted
from modules.finance.testing_support import NoCommitConnection
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.warehouse.api.fulfillment_service import FulfillmentService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.voucher_service import VoucherService
from modules.warehouse.events.consumers import _handle_sales_order_confirmed

TENANT = "integration-test-delivery-billing"
D = Decimal


@pytest.fixture
def env(db):
    actor, uom, product, partner, location = (str(ULID()) for _ in range(5))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'DB-PASTA', 'Pasta', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Acme', 'customer')", (partner, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'FG')", (location, TENANT, str(ULID())))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=product, location_id=location, quantity=200, correlation_id="c",
                                   reference="setup", actor_id=actor)
    return {"actor": actor, "product": product, "partner": partner, "location": location}


def _envelope(db, event_type: str, key: str, value: str) -> dict:
    return db.execute(
        "SELECT payload FROM events.outbox WHERE payload->>'event_type' = %s AND payload->'payload'->>%s = %s",
        (event_type, key, value),
    ).fetchone()[0]


def _confirmed_order(db, env, quantity=30, price=100.0) -> str:
    sales = SalesOrderService(db)
    order = sales.create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
                               lines=[OrderLine(product_id=env["product"], quantity=quantity, unit_price=price)])
    assert isinstance(sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id="c"), Ok)
    _handle_sales_order_confirmed(db, _envelope(db, "sales.order.confirmed", "order_id", order.id))
    return order.id


def _issue(db, env, order_id, quantity=None) -> dict:
    """Posts an exit voucher from the order; its delivery note comes with it."""
    vouchers = VoucherService(db)
    draft = vouchers.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["location"],
                                             quantities={env["product"]: D(quantity)} if quantity is not None else None)
    posted = vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert isinstance(posted, Ok), posted
    return posted.value


def _delivery_note(db, env, voucher_id, quantity=None) -> dict:
    note = VoucherService(db).generate_delivery_note(
        tenant_id=TENANT, actor_id=env["actor"], voucher_id=voucher_id, correlation_id="c",
        quantities={env["product"]: D(quantity)} if quantity is not None else None,
    )
    assert isinstance(note, Ok), note
    return note.value


def _bill(db, voucher_id) -> None:
    _handle_voucher_posted(db, _envelope(db, "warehouse.voucher.posted", "voucher_id", voucher_id))


def _order_invoices(db, order_id) -> list[dict]:
    return sorted(InvoiceService(db).list_invoice_rows(tenant_id=TENANT, source_order_id=order_id), key=lambda i: i["number"])


def _return(db, env, against_id, quantity) -> str:
    vouchers = VoucherService(db)
    draft = vouchers.create_draft(tenant_id=TENANT, actor_id=env["actor"], type="return", dest_location_id=env["location"],
                                  return_of_voucher_id=against_id, note="abîmé", lines=[{"product_id": env["product"], "quantity": quantity}])
    assert isinstance(draft, Ok), draft
    posted = vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert isinstance(posted, Ok), posted
    return posted.value["id"]


def test_an_exit_from_an_order_brings_its_delivery_note_and_each_is_billed_once(db, env):
    order_id = _confirmed_order(db, env)
    first = _issue(db, env, order_id, 10)["delivery_note"]
    _bill(db, first["id"])
    _bill(db, first["id"])  # a replayed event
    rest = _issue(db, env, order_id, 20)["delivery_note"]  # the 20 still on the order
    _bill(db, rest["id"])
    invoices = _order_invoices(db, order_id)
    assert [(i["source_type"], i["source_number"], i["total"], i["status"]) for i in invoices] == [
        ("delivery_note", first["number"], D(1000), "draft"), ("delivery_note", rest["number"], D(2000), "draft"),
    ]
    assert all(i["number"].startswith("FV-") for i in invoices)
    detail = InvoiceService(db).get_invoice_detail(tenant_id=TENANT, invoice_id=invoices[1]["id"]).value
    assert [(l["product_id"], l["quantity"], l["unit_price"]) for l in detail["lines"]] == [(env["product"], D(20), D(100))]


def test_a_second_delivery_note_for_an_order_exit_is_refused_and_bills_nothing(db, env):
    order_id = _confirmed_order(db, env)
    issue = _issue(db, env, order_id)
    _bill(db, issue["delivery_note"]["id"])
    again = VoucherService(db).generate_delivery_note(tenant_id=TENANT, actor_id=env["actor"], voucher_id=issue["id"], correlation_id="c")
    assert isinstance(again, Err) and again.code == "NOTHING_TO_DELIVER"
    _bill(db, issue["id"])  # the exit voucher's own event bills nothing either
    assert [i["total"] for i in _order_invoices(db, order_id)] == [D(3000)]


def test_an_exit_without_an_order_gets_no_delivery_note_by_itself(db, env):
    vouchers = VoucherService(db)
    draft = vouchers.create_draft(tenant_id=TENANT, actor_id=env["actor"], type="issue", source_location_id=env["location"],
                                  partner_id=env["partner"], lines=[{"product_id": env["product"], "quantity": 3}])
    posted = vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert "delivery_note" not in posted.value
    manual = _delivery_note(db, env, posted.value["id"])
    assert manual["billable"] is True
    _bill(db, manual["id"])  # no order, so no price: nothing to invoice
    assert InvoiceService(db).list_invoice_rows(tenant_id=TENANT) == []


def test_a_re_delivery_after_a_return_is_not_billed(db, env):
    order_id = _confirmed_order(db, env)
    note = _issue(db, env, order_id)["delivery_note"]
    _bill(db, note["id"])
    returned = _return(db, env, note["id"], 4)
    redelivery = _delivery_note(db, env, returned)
    assert redelivery["billable"] is False
    _bill(db, redelivery["id"])
    assert [i["total"] for i in _order_invoices(db, order_id)] == [D(3000)]


def _ship(db, env, order_id, picked=None) -> str:
    fulfillment = FulfillmentService(db)
    [pick_list] = [p for p in fulfillment.list_pick_lists(tenant_id=TENANT) if p.source_id == order_id]
    for line in fulfillment.list_pick_lines(tenant_id=TENANT, pick_list_id=pick_list.id):
        fulfillment.submit_pick(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, line_id=line.id,
                                quantity_picked=picked if picked is not None else line.quantity_requested)
    fulfillment.complete_picking(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id)
    shipment = fulfillment.pack(tenant_id=TENANT, actor_id=env["actor"], pick_list_id=pick_list.id, package_count=1).value
    assert isinstance(fulfillment.ship(tenant_id=TENANT, actor_id=env["actor"], shipment_id=shipment.id, correlation_id="c"), Ok)
    envelope = _envelope(db, "warehouse.shipment.shipped", "shipment_id", shipment.id)
    _handle_shipment_shipped(db, envelope)
    _handle_shipment_shipped(db, envelope)  # replayed
    return shipment.number


def test_a_shipped_pick_list_is_billed_once(db, env):
    order_id = _confirmed_order(db, env, quantity=12, price=250.0)
    number = _ship(db, env, order_id)
    assert [(i["source_type"], i["source_number"], i["total"]) for i in _order_invoices(db, order_id)] == [("shipment", number, D(3000))]


def test_a_short_shipment_is_billed_at_the_shipped_quantity_not_the_ordered_one(db, env):
    order_id = _confirmed_order(db, env, quantity=12, price=250.0)
    number = _ship(db, env, order_id, picked=5)
    [invoice] = _order_invoices(db, order_id)
    assert (invoice["source_number"], invoice["total"]) == (number, D(1250))
    assert [(l["quantity"], l["unit_price"]) for l in InvoiceService(db).get_invoice_detail(tenant_id=TENANT, invoice_id=invoice["id"]).value["lines"]] == [(D(5), D(250))]


def test_an_order_invoiced_when_it_was_confirmed_is_never_invoiced_again_at_delivery(db, env):
    order_id = _confirmed_order(db, env, quantity=12, price=250.0)
    # What the old rule did when the order was confirmed.
    old = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["partner"], amount=3000, source_order_id=order_id)
    _ship(db, env, order_id)
    invoices = _order_invoices(db, order_id)
    assert [(i["id"], i["source_type"]) for i in invoices] == [(old.id, "order")]


def test_orders_are_no_longer_invoiced_when_confirmed(db, env):
    order_id = _confirmed_order(db, env)
    assert _order_invoices(db, order_id) == []


def test_a_return_credits_the_invoice_and_a_payment_above_what_is_due_becomes_a_customer_credit(db, env):
    order_id = _confirmed_order(db, env)
    note = _issue(db, env, order_id, 10)["delivery_note"]
    _bill(db, note["id"])
    [invoice] = _order_invoices(db, order_id)
    invoices = InvoiceService(db)
    assert isinstance(invoices.issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], correlation_id="c"), Ok)
    paid = invoices.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D(800),
                                        event_type="treasury.receipt.posted", document_id="R1")
    assert paid.value["status"] == "partially_paid"

    returned = _return(db, env, note["id"], 5)
    _bill(db, returned)
    _bill(db, returned)  # replayed: still one credit note
    [credit_note] = DeliveryBillingService(db).list_credit_notes(tenant_id=TENANT, invoice_id=invoice["id"])
    assert credit_note["number"].startswith("AVC-") and credit_note["amount"] == D(500) and credit_note["return_id"] == returned
    after = invoices.get_invoice(tenant_id=TENANT, invoice_id=invoice["id"]).value
    assert (after["total"], after["amount"], after["amount_paid"], after["status"]) == (D(1000), D(500), D(800), "paid")
    assert after["remaining"] == 0 and after["customer_credit"] == D(300)
    # Taking more than is due is refused; giving back a payment works.
    over = invoices.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D(1),
                                        event_type="treasury.receipt.posted", document_id="R2")
    assert isinstance(over, Err) and over.code == "OVER_ALLOCATION"


def test_a_return_on_an_order_billed_at_confirmation_credits_that_invoice_at_the_order_price(db, env):
    order_id = _confirmed_order(db, env)
    old = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["partner"], amount=3000, source_order_id=order_id)
    issue = _issue(db, env, order_id)
    _bill(db, issue["delivery_note"]["id"])  # already billed whole at confirmation: no second invoice
    returned = _return(db, env, issue["id"], 4)
    _bill(db, returned)
    assert [i["id"] for i in _order_invoices(db, order_id)] == [old.id]
    [credit_note] = DeliveryBillingService(db).list_credit_notes(tenant_id=TENANT, invoice_id=old.id)
    assert credit_note["amount"] == D(400) and credit_note["lines"][0]["quantity"] == D(4)
    assert InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=old.id).value["amount"] == D(2600)


def test_a_credit_note_posts_the_mirror_of_the_sales_entry_once_the_invoice_is_posted(ledger):
    db, tenant = ledger["db"], ledger["tenant"]
    partner = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Client CN', 'customer')", (partner, tenant))
    invoice_id, credit_note_id = str(ULID()), str(ULID())

    def envelope(event_type, payload):
        return {"event_id": str(ULID()), "event_type": event_type, "event_version": "1.0", "occurred_at": f"{ledger['year']}-03-04T10:00:00+00:00",
                "producer": "finance", "tenant_id": tenant, "correlation_id": str(ULID()), "causation_id": None, "payload": payload}

    credit = envelope("finance.credit_note.issued", {"credit_note_id": credit_note_id, "invoice_id": invoice_id, "number": "AVC-T-1",
                                                       "partner_id": partner, "amount": "400", "currency": "XOF"})
    # Before the invoice's own entry, the credit note is refused and kept for a retry.
    assert _process(NoCommitConnection(db), credit) is False
    assert db.execute("SELECT error_code FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s",
                      (tenant, credit_note_id)).fetchone()[0] == "INVOICE_NOT_POSTED"
    issued = envelope("finance.invoice.issued", {"invoice_id": invoice_id, "partner_id": partner, "amount": 1000, "currency": "XOF"})
    assert _process(NoCommitConnection(db), issued) is True
    again = {**credit, "event_id": str(ULID())}
    assert _process(NoCommitConnection(db), again) is True
    assert _process(NoCommitConnection(db), {**credit, "event_id": str(ULID())}) is True  # replayed: posts nothing more
    lines = db.execute(
        """
        SELECT e.journal_code, l.account_code, l.debit, l.credit, l.partner_id FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_id = %s AND e.source_kind = 'invoice_credit_note' ORDER BY l.line_no
        """,
        (tenant, credit_note_id),
    ).fetchall()
    assert lines == [("VTE", "411", D(0), D(400), partner), ("VTE", "702", D(400), D(0), None)]


def test_the_movements_report_reads_issued_invoice_lines_and_credit_notes(db, env):
    from modules.finance.api import report_queries

    order_id = _confirmed_order(db, env)
    note = _issue(db, env, order_id, 10)["delivery_note"]
    _bill(db, note["id"])
    [invoice] = _order_invoices(db, order_id)
    assert report_queries.list_invoice_lines_for_report(db, tenant_id=TENANT) == []  # a draft doesn't count yet
    InvoiceService(db).issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], correlation_id="c")
    returned = _return(db, env, note["id"], 3)
    _bill(db, returned)
    [line] = report_queries.list_invoice_lines_for_report(db, tenant_id=TENANT, product_id=env["product"])
    assert (line["number"], line["quantity"], line["partner_id"]) == (invoice["number"], D(10), env["partner"])
    [credit] = report_queries.list_credit_notes_for_report(db, tenant_id=TENANT)
    assert credit["number"].startswith("AVC-") and credit["quantity"] == D(3)

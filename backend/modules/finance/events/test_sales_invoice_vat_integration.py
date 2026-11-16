"""Sales invoices carry the order's discounts and VAT: billed at the net price, owed VAT included, and posted
with the collected VAT on its own account. Credit notes take the same back."""
from __future__ import annotations

from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Ok
from core.events.consumers import _process
from modules.finance.api.billing_service import DeliveryBillingService
from modules.finance.api.service import InvoiceService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the ledger handlers)
from modules.finance.events.consumers import _handle_voucher_posted
from modules.finance.testing_support import NoCommitConnection
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from modules.warehouse.api.service import StockService
from modules.warehouse.api.voucher_service import VoucherService
from modules.warehouse.events.consumers import _handle_sales_order_confirmed

TENANT = "integration-test-sales-invoice-vat"
D = Decimal


@pytest.fixture
def env(db):
    actor, uom, product, partner, location = (str(ULID()) for _ in range(5))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'VAT-PASTA', 'Pasta', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Client TVA', 'customer')", (partner, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'FG')", (location, TENANT, str(ULID())))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=product, location_id=location, quantity=200, correlation_id="c",
                                   reference="setup", actor_id=actor)
    return {"actor": actor, "product": product, "partner": partner, "location": location}


def _envelope(db, event_type: str, key: str, value: str) -> dict:
    return db.execute(
        "SELECT payload FROM events.outbox WHERE payload->>'event_type' = %s AND payload->'payload'->>%s = %s",
        (event_type, key, value),
    ).fetchone()[0]


def _discounted_order(db, env) -> str:
    """10 at 1 000, 10 % off the line, 5 % off the order, 18 % VAT: 855 a unit excl. tax."""
    sales = SalesOrderService(db)
    order = sales.create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
                               discount_rate=5, lines=[OrderLine(product_id=env["product"], quantity=10, unit_price=1000,
                                                                 discount_rate=10, vat_rate=18)])
    assert isinstance(sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id="c"), Ok)
    _handle_sales_order_confirmed(db, _envelope(db, "sales.order.confirmed", "order_id", order.id))
    return order.id


def _deliver(db, env, order_id, quantity) -> dict:
    vouchers = VoucherService(db)
    draft = vouchers.create_issue_from_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order_id, source_location_id=env["location"],
                                             quantities={env["product"]: D(quantity)})
    posted = vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    assert isinstance(posted, Ok), posted
    note = posted.value["delivery_note"]
    _handle_voucher_posted(db, _envelope(db, "warehouse.voucher.posted", "voucher_id", note["id"]))
    return note


def test_the_invoice_bills_the_net_price_and_owes_the_vat(db, env):
    order_id = _discounted_order(db, env)
    _deliver(db, env, order_id, 4)
    [invoice] = InvoiceService(db).list_invoice_rows(tenant_id=TENANT, source_order_id=order_id)
    detail = InvoiceService(db).get_invoice_detail(tenant_id=TENANT, invoice_id=invoice["id"]).value
    [line] = detail["lines"]
    assert (line["quantity"], line["unit_price"], line["vat_rate"], line["list_price"]) == (D(4), D(855), D(18), D(1000))
    assert line["discount_rate"] == D("14.5")
    # 4 x 855 = 3 420 excl.; 18 % = 615.6 -> 616; 4 036 owed
    assert (detail["amount_excl_tax"], detail["vat_amount"], invoice["total"]) == (D(3420), D(616), D(4036))


def test_an_order_from_before_discounts_and_vat_bills_exactly_as_before(db, env):
    sales = SalesOrderService(db)
    order = sales.create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["partner"], location_id=env["location"],
                               lines=[OrderLine(product_id=env["product"], quantity=10, unit_price=100)])
    sales.confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id="c")
    _handle_sales_order_confirmed(db, _envelope(db, "sales.order.confirmed", "order_id", order.id))
    _deliver(db, env, order.id, 10)
    [invoice] = InvoiceService(db).list_invoice_rows(tenant_id=TENANT, source_order_id=order.id)
    detail = InvoiceService(db).get_invoice_detail(tenant_id=TENANT, invoice_id=invoice["id"]).value
    assert (invoice["total"], detail["vat_amount"], detail["lines"][0]["vat_rate"]) == (D(1000), D(0), D(0))


def test_a_return_credits_the_net_price_with_its_vat(db, env):
    order_id = _discounted_order(db, env)
    note = _deliver(db, env, order_id, 10)
    vouchers = VoucherService(db)
    draft = vouchers.create_draft(tenant_id=TENANT, actor_id=env["actor"], type="return", dest_location_id=env["location"],
                                  return_of_voucher_id=note["id"], note="abîmé", lines=[{"product_id": env["product"], "quantity": 2}])
    posted = vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c")
    _handle_voucher_posted(db, _envelope(db, "warehouse.voucher.posted", "voucher_id", posted.value["id"]))
    [credit] = DeliveryBillingService(db).list_credit_notes(tenant_id=TENANT)
    # 2 x 855 = 1 710 excl.; VAT 307.8 -> 308; 2 018
    assert (credit["amount_excl_tax"], credit["vat_amount"], credit["amount"]) == (D(1710), D(308), D(2018))
    assert credit["lines"][0]["vat_rate"] == D(18)
    payload = _envelope(db, "finance.credit_note.issued", "credit_note_id", credit["id"])["payload"]
    assert D(payload["vat"]) == D(308)


def test_the_sales_entry_puts_the_collected_vat_on_its_own_account(ledger):
    db, tenant = ledger["db"], ledger["tenant"]
    partner = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Client TVA L', 'customer')", (partner, tenant))
    invoice_id, credit_note_id = str(ULID()), str(ULID())

    def envelope(event_type, payload):
        return {"event_id": str(ULID()), "event_type": event_type, "event_version": "1.1", "occurred_at": f"{ledger['year']}-03-04T10:00:00+00:00",
                "producer": "finance", "tenant_id": tenant, "correlation_id": str(ULID()), "causation_id": None, "payload": payload}

    def lines(source_id, kind):
        return db.execute(
            """
            SELECT l.account_code, l.debit, l.credit FROM finance.journal_lines l JOIN finance.journal_entries e ON e.id = l.entry_id
            WHERE e.tenant_id = %s AND e.source_id = %s AND e.source_kind = %s ORDER BY l.line_no
            """,
            (tenant, source_id, kind),
        ).fetchall()

    issued = envelope("finance.invoice.issued", {"invoice_id": invoice_id, "partner_id": partner, "amount": 4036, "currency": "XOF",
                                                 "vat": 616})
    assert _process(NoCommitConnection(db), issued) is True
    assert lines(invoice_id, "invoice_issued") == [("411", D(4036), D(0)), ("702", D(0), D(3420)), ("443", D(0), D(616))]
    credit = envelope("finance.credit_note.issued", {"credit_note_id": credit_note_id, "invoice_id": invoice_id, "number": "AVC-T",
                                                     "partner_id": partner, "amount": "2018", "currency": "XOF", "vat": "308"})
    assert _process(NoCommitConnection(db), credit) is True
    assert lines(credit_note_id, "invoice_credit_note") == [("411", D(0), D(2018)), ("702", D(1710), D(0)), ("443", D(308), D(0))]
    # A 1.0 event (no VAT) posts as it always did.
    old_id = str(ULID())
    old = envelope("finance.invoice.issued", {"invoice_id": old_id, "partner_id": partner, "amount": 1000, "currency": "XOF"})
    assert _process(NoCommitConnection(db), old) is True
    assert lines(old_id, "invoice_issued") == [("411", D(1000), D(0)), ("702", D(0), D(1000))]

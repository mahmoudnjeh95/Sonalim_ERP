"""The tax engine end to end: a tax code on each line, the VAT split per code in the event, each code's share
posted to its own account, the VAT register and the VAT return read from it."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.events.consumers import _process
from core.tax_codes import TaxCodeService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.api.service import InvoiceService
from modules.finance.api.tax_register_service import TaxRegisterService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the ledger handlers)
from modules.finance.events.consumers import _handle_voucher_posted
from modules.finance.testing_support import NoCommitConnection
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.sales.api.router import OrderLineRequest, _lines
from modules.sales.api.service import SalesOrderService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.voucher_service import VoucherService
from modules.warehouse.events.consumers import _handle_sales_order_confirmed

D = Decimal


def _envelope(db, event_type: str, key: str, value: str) -> dict:
    return db.execute(
        "SELECT payload FROM events.outbox WHERE payload->>'event_type' = %s AND payload->'payload'->>%s = %s",
        (event_type, key, value),
    ).fetchone()[0]


def _entry_lines(db, tenant, source_id, kind):
    return db.execute(
        """
        SELECT l.account_code, l.debit, l.credit FROM finance.journal_lines l JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_id = %s AND e.source_kind = %s ORDER BY l.line_no
        """,
        (tenant, source_id, kind),
    ).fetchall()


@pytest.fixture
def taxed(ledger):
    """The ledger tenant with a 5 % code whose VAT goes to 446, and a customer and a supplier."""
    db, tenant, actor = ledger["db"], ledger["tenant"], ledger["actor"]
    tva5 = TaxCodeService(db).create_code(tenant_id=tenant, actor_id=actor, code="TVA5", name_fr="TVA 5 %", name_en=None, rate=5)
    assert isinstance(tva5, Ok), tva5
    for source, debit, credit in (("invoice", None, "446"), ("purchase_invoice", "446", None)):
        rule = PostingRuleService(db).create_rule(tenant_id=tenant, actor_id=actor, source=source, source_kind="vat", code="tva5",
                                                  debit_account_code=debit, credit_account_code=credit)
        assert isinstance(rule, Ok), rule
    customer, supplier = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Client', 'customer')", (customer, tenant))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Fourn', 'supplier', 'active')", (supplier, tenant))
    return {**ledger, "customer": customer, "supplier": supplier}


def _event(taxed, event_type, payload, day="03-04"):
    return {"event_id": str(ULID()), "event_type": event_type, "event_version": "1.2", "occurred_at": f"{taxed['year']}-{day}T10:00:00+00:00",
            "producer": "finance", "tenant_id": taxed["tenant"], "correlation_id": str(ULID()), "causation_id": None, "payload": payload}


def test_a_vat_rule_names_an_existing_tax_code(ledger):
    refused = PostingRuleService(ledger["db"]).create_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="invoice",
                                                          source_kind="vat", code="NOPE", credit_account_code="443")
    assert isinstance(refused, Err) and refused.code == "TAX_CODE_NOT_FOUND"
    refused = PostingRuleService(ledger["db"]).create_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="invoice",
                                                          source_kind="issued", code="TVA18", debit_account_code="411",
                                                          credit_account_code="702", journal_code="VTE")
    assert isinstance(refused, Err) and refused.code == "INVALID_POSTING_RULE"


def test_each_code_posts_to_its_account_and_lands_in_the_register(taxed):
    db, tenant = taxed["db"], taxed["tenant"]
    invoice_id, credit_id, bill_id = str(ULID()), str(ULID()), str(ULID())
    # 1 000 at 18 % (180) + 2 000 at 5 % (100) + 500 exempt: 3 500 excl., 280 VAT, 3 780 owed
    breakdown = [{"tax_code": "TVA18", "rate": "18", "base": "1000.00", "vat": "180.00"},
                 {"tax_code": "TVA5", "rate": "5", "base": "2000.00", "vat": "100.00"},
                 {"tax_code": "EXO", "rate": "0", "base": "500.00", "vat": "0.00"}]
    issued = _event(taxed, "finance.invoice.issued", {"invoice_id": invoice_id, "partner_id": taxed["customer"], "amount": 3780,
                                                      "currency": "XOF", "vat": 280, "vat_breakdown": breakdown})
    assert _process(NoCommitConnection(db), issued) is True
    assert _entry_lines(db, tenant, invoice_id, "invoice_issued") == [
        ("411", D(3780), D(0)), ("702", D(0), D(3500)), ("443", D(0), D(180)), ("446", D(0), D(100))]

    credit = _event(taxed, "finance.credit_note.issued", {
        "credit_note_id": credit_id, "invoice_id": invoice_id, "number": "AV-1", "partner_id": taxed["customer"], "amount": "105",
        "currency": "XOF", "vat": "5", "vat_breakdown": [{"tax_code": "TVA5", "rate": "5", "base": "100", "vat": "5"}]})
    assert _process(NoCommitConnection(db), credit) is True
    assert _entry_lines(db, tenant, credit_id, "invoice_credit_note") == [("411", D(0), D(105)), ("702", D(100), D(0)), ("446", D(5), D(0))]

    bill = _event(taxed, "procurement.purchase_invoice.validated", {
        "invoice_id": bill_id, "number": "FA-1", "partner_id": taxed["supplier"], "amount": "1180", "total_excl_tax": "1000",
        "total_vat": "180", "lines": [{"product_id": None, "net": "1000"}], "currency": "XOF",
        "vat_breakdown": [{"tax_code": "TVA18", "rate": "18", "base": "1000", "vat": "180"}]}, day="03-10")
    assert _process(NoCommitConnection(db), bill) is True

    report = TaxRegisterService(db).vat_return(tenant_id=tenant, date_from=datetime.date(taxed["year"], 3, 1),
                                               date_to=datetime.date(taxed["year"], 3, 31)).value
    collected = {(r["tax_code"], r["rate"]): (r["base"], r["vat"]) for r in report["collected"]}
    assert collected == {("TVA18", D(18)): (D(1000), D(180)), ("TVA5", D(5)): (D(1900), D(95)), ("EXO", D(0)): (D(500), D(0))}
    assert [r["exempt"] for r in report["collected"] if r["tax_code"] == "EXO"] == [True]
    assert report["totals"]["collected"] == {"base": D(3400), "vat": D(275)}
    assert report["totals"]["deductible"] == {"base": D(1000), "vat": D(180)}
    assert report["net_vat_due"] == D(95)
    # the ledger's VAT accounts moved exactly what the register says (446 is both sides here, so check the totals)
    assert report["ledger"]["collected"]["accounts"] == ["443", "446"]

    # cancelling the purchase invoice takes its VAT back out of the return, on the day of the cancellation
    cancelled = _event(taxed, "procurement.purchase_invoice.cancelled", {"invoice_id": bill_id}, day="03-20")
    assert _process(NoCommitConnection(db), cancelled) is True
    report = TaxRegisterService(db).vat_return(tenant_id=tenant, date_from=datetime.date(taxed["year"], 3, 1),
                                               date_to=datetime.date(taxed["year"], 3, 31)).value
    assert report["totals"]["deductible"] == {"base": D(0), "vat": D(0)}
    assert report["net_vat_due"] == D(275)
    early = TaxRegisterService(db).vat_return(tenant_id=tenant, date_from=datetime.date(taxed["year"], 3, 1),
                                              date_to=datetime.date(taxed["year"], 3, 15)).value
    assert early["totals"]["deductible"]["vat"] == D(180)


def test_an_event_without_a_breakdown_posts_as_before_and_is_unclassified(taxed):
    db, tenant = taxed["db"], taxed["tenant"]
    invoice_id = str(ULID())
    issued = _event(taxed, "finance.invoice.issued", {"invoice_id": invoice_id, "partner_id": taxed["customer"], "amount": 1180,
                                                      "currency": "XOF", "vat": 180})
    assert _process(NoCommitConnection(db), issued) is True
    assert _entry_lines(db, tenant, invoice_id, "invoice_issued") == [("411", D(1180), D(0)), ("702", D(0), D(1000)), ("443", D(0), D(180))]
    report = TaxRegisterService(db).vat_return(tenant_id=tenant, date_from=datetime.date(taxed["year"], 1, 1),
                                               date_to=datetime.date(taxed["year"], 12, 31)).value
    assert [(r["tax_code"], r["rate"], r["base"], r["vat"]) for r in report["collected"]] == [(None, None, D(1000), D(180))]
    assert report["ledger"]["collected"]["difference"] == D(0)


def test_rounding_across_codes_matches_the_document_vat(taxed):
    db, tenant = taxed["db"], taxed["tenant"]
    invoice_id = str(ULID())
    # 333.33 at 18 % = 60.00 and 333.33 at 5 % = 16.67 -> 76.67, the document says 77
    breakdown = [{"tax_code": "TVA18", "rate": "18", "base": "333.33", "vat": "60.00"},
                 {"tax_code": "TVA5", "rate": "5", "base": "333.33", "vat": "16.67"}]
    issued = _event(taxed, "finance.invoice.issued", {"invoice_id": invoice_id, "partner_id": taxed["customer"], "amount": 744,
                                                      "currency": "XOF", "vat": 77, "vat_breakdown": breakdown})
    assert _process(NoCommitConnection(db), issued) is True
    lines = _entry_lines(db, tenant, invoice_id, "invoice_issued")
    assert sum(credit for _, _, credit in lines) == D(744)
    report = TaxRegisterService(db).vat_return(tenant_id=tenant, date_from=datetime.date(taxed["year"], 1, 1),
                                               date_to=datetime.date(taxed["year"], 12, 31)).value
    assert report["totals"]["collected"] == {"base": D(667), "vat": D(77)}


# ---- from the documents -----------------------------------------------------------------------------------

def test_an_exempt_customer_is_invoiced_without_vat_under_its_code(taxed):
    db, tenant, actor = taxed["db"], taxed["tenant"], taxed["actor"]
    codes = {c["code"]: c for c in TaxCodeService(db).list_codes(tenant_id=tenant)}
    TaxCodeService(db).set_partner_codes(tenant_id=tenant, actor_id=actor, partner_id=taxed["customer"], values={"sales": codes["EXO"]["id"]})
    uom, product, location = str(ULID()), str(ULID()), str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, tenant))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'EXO-P', 'Exported', %s)", (product, tenant, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'FG')", (location, tenant, str(ULID())))
    StockService(db).receive_stock(tenant_id=tenant, product_id=product, location_id=location, quantity=50, correlation_id="c",
                                   reference="setup", actor_id=actor)

    lines = _lines(db, tenant, taxed["customer"], [OrderLineRequest(product_id=product, quantity=D(10), unit_price=D(100))])
    assert [(line.tax_code, line.vat_rate) for line in lines] == [("EXO", D(0))]
    sales = SalesOrderService(db)
    order = sales.create_order(tenant_id=tenant, actor_id=actor, partner_id=taxed["customer"], location_id=location, lines=lines)
    assert sales.get_order(tenant_id=tenant, order_id=order.id).value.lines[0].tax_code == "EXO"
    sales.confirm_order(tenant_id=tenant, actor_id=actor, order_id=order.id, correlation_id="c")
    _handle_sales_order_confirmed(db, _envelope(db, "sales.order.confirmed", "order_id", order.id))
    vouchers = VoucherService(db)
    draft = vouchers.create_issue_from_order(tenant_id=tenant, actor_id=actor, order_id=order.id, source_location_id=location,
                                             quantities={product: D(10)})
    posted = vouchers.post(tenant_id=tenant, actor_id=actor, voucher_id=draft.value["id"], correlation_id="c")
    _handle_voucher_posted(db, _envelope(db, "warehouse.voucher.posted", "voucher_id", posted.value["delivery_note"]["id"]))
    [invoice] = InvoiceService(db).list_invoice_rows(tenant_id=tenant, source_order_id=order.id)
    detail = InvoiceService(db).get_invoice_detail(tenant_id=tenant, invoice_id=invoice["id"]).value
    assert [(l["tax_code"], l["vat_rate"]) for l in detail["lines"]] == [("EXO", D(0))]
    issued = InvoiceService(db).issue_invoice(tenant_id=tenant, actor_id=actor, invoice_id=invoice["id"], correlation_id="c")
    assert isinstance(issued, Ok), issued
    payload = _envelope(db, "finance.invoice.issued", "invoice_id", invoice["id"])["payload"]
    assert payload["vat_breakdown"] == [{"tax_code": "EXO", "rate": "0.00", "base": "1000.00", "vat": "0.00"}]


def test_a_purchase_invoice_line_takes_the_product_code_and_the_event_splits_it(taxed):
    db, tenant, actor = taxed["db"], taxed["tenant"], taxed["actor"]
    codes = {c["code"]: c for c in TaxCodeService(db).list_codes(tenant_id=tenant)}
    uom, product = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilo', 'mass')", (uom, tenant))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'FLOUR', 'Flour', %s)", (product, tenant, uom))
    TaxCodeService(db).set_product_codes(tenant_id=tenant, actor_id=actor, product_id=product, values={"purchases": codes["TVA5"]["id"]})
    service = PurchaseInvoiceService(db)
    draft = service.create_draft(tenant_id=tenant, actor_id=actor, partner_id=taxed["supplier"], supplier_invoice_number="S-1",
                                 invoice_date=datetime.date(taxed["year"], 3, 5),
                                 lines=[{"product_id": product, "quantity": 10, "unit_price": 200},
                                        {"description": "Transport", "quantity": 1, "unit_price": 1000}])
    assert isinstance(draft, Ok), draft
    lines = service.list_lines(tenant_id=tenant, invoice_id=draft.value["id"])
    assert [(l["tax_code"], l["vat_rate"]) for l in lines] == [("TVA5", D(5)), ("TVA18", D(18))]
    validated = service.validate(tenant_id=tenant, actor_id=actor, invoice_id=draft.value["id"], correlation_id="c")
    assert isinstance(validated, Ok), validated
    envelope = _envelope(db, "procurement.purchase_invoice.validated", "invoice_id", draft.value["id"])
    assert envelope["event_version"] == "1.2"
    assert envelope["payload"]["vat_breakdown"] == [
        {"tax_code": "TVA18", "rate": "18.00", "base": "1000.00", "vat": "180.00"},
        {"tax_code": "TVA5", "rate": "5.00", "base": "2000.00", "vat": "100.00"}]
    # the ledger's open year is the fixture's, not today's
    envelope = {**envelope, "occurred_at": f"{taxed['year']}-03-05T10:00:00+00:00"}
    assert _process(NoCommitConnection(db), envelope) is True
    assert _entry_lines(db, tenant, draft.value["id"], "purchase_invoice_validated")[-3:] == [
        ("445", D(180), D(0)), ("446", D(100), D(0)), ("401", D(0), D(3280))]

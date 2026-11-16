"""The complete purchase invoice: priced lines with discount and VAT, invoicing from goods receipts with a
three-way match, supplier credit notes, attachments and the default VAT rate."""
from __future__ import annotations

import base64
import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.procurement.api.credit_note_service import PurchaseCreditNoteService
from modules.procurement.api.invoice_attachment_service import PurchaseInvoiceAttachmentService
from modules.procurement.api.invoice_service import PurchaseInvoiceService, apply_document_delta
from modules.procurement.api.service import PurchaseOrderService

TENANT = "integration-test-full-purchase-invoice"
D = Decimal
DAY = datetime.date(2026, 10, 1)


@pytest.fixture
def env(db):
    actor, supplier, other, uom, film, pasta, location = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    for pid, name in ((supplier, "Moulins du Sahel"), (other, "Autre fournisseur")):
        db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, 'supplier', 'active')", (pid, TENANT, name))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    for pid, sku in ((film, "FILM"), (pasta, "PASTA")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (pid, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'PI-MAIN', 'Main')", (location, TENANT))
    return {"actor": actor, "supplier": supplier, "other": other, "uom": uom, "film": film, "pasta": pasta, "location": location}


def _service(db):
    return PurchaseInvoiceService(db)


def _draft(db, env, number="F-1", lines=None, **extra):
    return _service(db).create_draft(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=extra.pop("partner_id", env["supplier"]),
        supplier_invoice_number=number, invoice_date=DAY, lines=lines, **extra)


def _validate(db, env, invoice_id, **extra):
    return _service(db).validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, correlation_id="c", **extra)


def _received(db, env, quantities: dict[str, float], price=100, supplier=None):
    """A placed purchase order for these products, fully received on one confirmed goods receipt whose goods
    value is `price` per unit (procurement prices orders from their receipts)."""
    procurement = PurchaseOrderService(db)
    order = procurement.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=supplier or env["supplier"], order_date=DAY, currency_code="XOF",
        lines=[{"product_id": env[p], "uom_id": env["uom"], "quantity_ordered": q, "unit_price": price, "unit_price_currency": "XOF"}
               for p, q in quantities.items()],
    ).value
    for method in ("validate_order", "approve_order", "place_order"):
        assert isinstance(getattr(procurement, method)(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id), Ok)
    lines = procurement.list_lines(tenant_id=TENANT, purchase_order_id=order.id)
    receipt = procurement.create_receipt(
        tenant_id=TENANT, actor_id=env["actor"], purchase_order_id=order.id, location_id=env["location"], currency_code="XOF",
        lines=[{"purchase_order_line_id": l.id, "quantity": l.quantity_ordered} for l in lines],
        base_cost=price * sum(quantities.values()), transport_fee=500,
    ).value
    assert isinstance(procurement.confirm_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=receipt.id, correlation_id="c"), Ok)
    return order, receipt, lines


# ---- lines and totals ----------------------------------------------------------------------------------

def test_lines_carry_discount_and_vat_and_the_amount_due_is_the_total_including_tax(db, env):
    created = _draft(db, env, lines=[
        {"product_id": env["film"], "quantity": 3, "unit_price": 1000, "discount_rate": 10},  # VAT from the tenant default, 18 %
        {"description": "Transport", "quantity": 1, "unit_price": 5000, "vat_rate": 0},
    ])
    assert isinstance(created, Ok), created
    invoice = created.value
    assert (invoice["total_gross"], invoice["total_discount"], invoice["total_excl_tax"], invoice["total_vat"], invoice["total_incl_tax"]) == \
        (D("8000"), D("300"), D("7700"), D("486"), D("8186"))
    assert invoice["amount"] == D("8186") and invoice["remaining"] == D("8186")
    lines = _service(db).list_lines(tenant_id=TENANT, invoice_id=invoice["id"])
    assert [(l["description"], l["vat_rate"], l["total_excl_tax"], l["total_vat"]) for l in lines] == [
        ("FILM", D("18.00"), D("2700.00"), D("486.00")), ("Transport", D("0.00"), D("5000.00"), D("0.00"))]


def test_the_default_vat_rate_is_a_tenant_setting(db, env):
    service = _service(db)
    assert service.default_vat_rate(tenant_id=TENANT) == D("18")
    assert service.set_default_vat_rate(tenant_id=TENANT, actor_id=env["actor"], rate=D("101")).code == "INVALID_VAT_RATE"
    assert isinstance(service.set_default_vat_rate(tenant_id=TENANT, actor_id=env["actor"], rate=D("5")), Ok)
    invoice = _draft(db, env, lines=[{"description": "Film", "quantity": 1, "unit_price": 1000}]).value
    assert invoice["total_vat"] == D("50")


def test_header_only_invoices_keep_working_as_one_line_without_vat(db, env):
    invoice = _draft(db, env, amount=D("1500"), note="Électricité").value
    lines = _service(db).list_lines(tenant_id=TENANT, invoice_id=invoice["id"])
    assert invoice["amount"] == D("1500") and [(l["description"], l["vat_rate"]) for l in lines] == [("Électricité", D("0.00"))]
    updated = _service(db).update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], changes={"amount": D("1700")})
    assert updated.value["amount"] == D("1700")


def test_draft_editing_and_its_refusals(db, env):
    service = _service(db)
    invoice = _draft(db, env, lines=[{"description": "Film", "quantity": 1, "unit_price": 100, "vat_rate": 0}]).value
    _draft(db, env, number="F-2", lines=[{"description": "Film", "quantity": 1, "unit_price": 1, "vat_rate": 0}])
    changed = service.update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], changes={
        "lines": [{"description": "Film", "quantity": 2, "unit_price": 100, "vat_rate": 18}], "due_date": DAY + datetime.timedelta(days=30)})
    assert changed.value["amount"] == D("236") and changed.value["due_date"] == DAY + datetime.timedelta(days=30)
    assert service.update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"],
                                changes={"supplier_invoice_number": "F-2"}).code == "DUPLICATE_SUPPLIER_INVOICE"
    assert service.update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"],
                                changes={"due_date": DAY - datetime.timedelta(days=1)}).code == "INVALID_DUE_DATE"
    assert service.update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], changes={"lines": []}).code == "LINES_REQUIRED"
    free = _draft(db, env, number="F-3", lines=[{"description": "Gift", "quantity": 1, "unit_price": 0}])
    assert isinstance(free, Ok)  # a draft may wait for its prices, but it can't be validated at zero
    assert _validate(db, env, free.value["id"]).code == "INVOICE_AMOUNT_ZERO"
    assert _draft(db, env, number=" ", amount=D("5")).code == "SUPPLIER_NUMBER_REQUIRED"


def test_list_filters_by_supplier_period_and_status(db, env):
    _draft(db, env, number="A", amount=D("10"))
    service = _service(db)
    service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["other"], supplier_invoice_number="B",
                         invoice_date=DAY + datetime.timedelta(days=40), amount=D("10"))
    assert [i["supplier_invoice_number"] for i in service.list_invoices(tenant_id=TENANT, partner_id=env["other"])] == ["B"]
    assert [i["supplier_invoice_number"] for i in service.list_invoices(tenant_id=TENANT, date_to=DAY)] == ["A"]
    assert [i["supplier_invoice_number"] for i in service.list_invoices(tenant_id=TENANT, date_from=DAY + datetime.timedelta(days=1))] == ["B"]
    assert service.list_invoices(tenant_id=TENANT, status="validated") == []


# ---- from goods receipts and three-way match --------------------------------------------------------

def test_an_invoice_from_receipts_bills_what_was_received_at_the_order_price(db, env):
    order, receipt, lines = _received(db, env, {"film": 10, "pasta": 4}, price=250)
    waiting = _service(db).invoiceable_receipts(tenant_id=TENANT, partner_id=env["supplier"])
    assert [r["receipt_id"] for r in waiting] == [receipt.id] and sorted(l["to_invoice"] for l in waiting[0]["lines"]) == [D("4"), D("10")]

    created = _service(db).create_from_receipts(tenant_id=TENANT, actor_id=env["actor"], receipt_ids=[receipt.id],
                                                supplier_invoice_number="SAHEL-77", invoice_date=DAY)
    assert isinstance(created, Ok), created
    detail = _service(db).get_detail(tenant_id=TENANT, invoice_id=created.value["id"]).value
    assert detail["purchase_order_id"] == order.id and detail["receipt_ids"] == [receipt.id] and detail["warnings"] == []
    assert sorted((l["quantity"], l["unit_price"], l["vat_rate"]) for l in detail["lines"]) == [(D("4"), D("250"), D("18.00")), (D("10"), D("250"), D("18.00"))]
    assert detail["total_excl_tax"] == D("3500") and detail["total_incl_tax"] == D("4130")
    # Fully invoiced: the receipt leaves the list, and asking again is refused.
    assert _service(db).invoiceable_receipts(tenant_id=TENANT) == []
    again = _service(db).create_from_receipts(tenant_id=TENANT, actor_id=env["actor"], receipt_ids=[receipt.id],
                                              supplier_invoice_number="SAHEL-78", invoice_date=DAY)
    assert isinstance(again, Err) and again.code == "RECEIPT_NOT_INVOICEABLE"


def test_receipts_of_two_suppliers_cannot_share_an_invoice(db, env):
    _, mine, _ = _received(db, env, {"film": 1})
    _, theirs, _ = _received(db, env, {"film": 1}, supplier=env["other"])
    mixed = _service(db).create_from_receipts(tenant_id=TENANT, actor_id=env["actor"], receipt_ids=[mine.id, theirs.id],
                                              supplier_invoice_number="X", invoice_date=DAY)
    assert isinstance(mixed, Err) and mixed.code == "RECEIPTS_OTHER_SUPPLIERS"


def test_billing_more_than_received_warns_and_needs_the_dedicated_permission_to_validate(db, env):
    _, receipt, lines = _received(db, env, {"film": 10}, price=100)
    invoice = _draft(db, env, lines=[{"product_id": env["film"], "quantity": 12, "unit_price": 110, "vat_rate": 0,
                                      "purchase_order_line_id": lines[0].id, "receipt_id": receipt.id}]).value
    warnings = _service(db).get_detail(tenant_id=TENANT, invoice_id=invoice["id"]).value["warnings"]
    assert {w["code"] for w in warnings} == {"QUANTITY_OVER_RECEIVED", "PRICE_DIFFERS_FROM_ORDER"}
    refused = _validate(db, env, invoice["id"])
    assert isinstance(refused, Err) and refused.code == "INVOICED_MORE_THAN_RECEIVED"
    assert isinstance(_validate(db, env, invoice["id"], may_exceed_receipts=True), Ok)
    # A second invoice on the same order line now finds nothing left to bill.
    second = _draft(db, env, number="F-2", lines=[{"product_id": env["film"], "quantity": 1, "unit_price": 100, "vat_rate": 0,
                                                   "purchase_order_line_id": lines[0].id}]).value
    assert [w["code"] for w in _service(db).get_detail(tenant_id=TENANT, invoice_id=second["id"]).value["warnings"]] == ["QUANTITY_OVER_RECEIVED"]


def test_an_order_line_of_another_supplier_is_refused(db, env):
    _, _, lines = _received(db, env, {"film": 1}, supplier=env["other"])
    refused = _draft(db, env, lines=[{"product_id": env["film"], "quantity": 1, "unit_price": 1, "purchase_order_line_id": lines[0].id}])
    assert isinstance(refused, Err) and refused.code == "ORDER_OF_ANOTHER_SUPPLIER"


# ---- credit notes -----------------------------------------------------------------------------------

def _validated(db, env, lines):
    invoice = _draft(db, env, lines=lines).value
    assert isinstance(_validate(db, env, invoice["id"]), Ok)
    return invoice["id"], _service(db).list_lines(tenant_id=TENANT, invoice_id=invoice["id"])


def _note(db, env, invoice_id, lines, reason="Retour de 2 rouleaux"):
    return PurchaseCreditNoteService(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, note_date=DAY,
                                                      reason=reason, lines=lines)


def _validate_note(db, env, note_id):
    return PurchaseCreditNoteService(db).validate(tenant_id=TENANT, actor_id=env["actor"], note_id=note_id, correlation_id="c")


def test_a_credit_note_takes_its_total_off_what_is_due(db, env):
    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 10, "unit_price": 1000, "vat_rate": 18}])
    note = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 2}])
    assert isinstance(note, Ok), note
    assert note.value["status"] == "draft" and note.value["total_incl_tax"] == D("2360") and note.value["number"] is None
    validated = _validate_note(db, env, note.value["id"])
    assert isinstance(validated, Ok) and validated.value["number"].startswith("AV-2026-")
    invoice = _service(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["credited_amount"], invoice["amount"], invoice["remaining"], invoice["status"]) == (D("2360"), D("9440"), D("9440"), "validated")
    event = db.execute("SELECT payload FROM events.outbox WHERE event_type = 'procurement.purchase_credit_note.validated' "
                       "AND payload -> 'payload' ->> 'credit_note_id' = %s", (note.value["id"],)).fetchone()[0]
    assert event["payload"]["amount"] == "2360.00" and event["payload"]["total_vat"] == "360.00"
    # A validated credit note is final, and a draft one can be dropped.
    assert PurchaseCreditNoteService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], note_id=note.value["id"]).code == "CREDIT_NOTE_NOT_DRAFT"
    draft = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 1}]).value
    assert PurchaseCreditNoteService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], note_id=draft["id"]).value["status"] == "cancelled"


def test_credit_notes_cannot_credit_a_line_beyond_what_it_was_invoiced(db, env):
    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 10, "unit_price": 1000, "vat_rate": 0}])
    first = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 8}]).value
    second = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 3}]).value  # fits while the first is a draft
    assert isinstance(_validate_note(db, env, first["id"]), Ok)
    refused = _validate_note(db, env, second["id"])
    assert isinstance(refused, Err) and refused.code == "CREDIT_EXCEEDS_INVOICE"
    assert _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 3}]).code == "CREDIT_EXCEEDS_INVOICE"
    assert _note(db, env, invoice_id, [{"invoice_line_id": "other", "quantity": 1}]).code == "CREDIT_LINE_NOT_ON_INVOICE"
    assert _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 1}], reason=" ").code == "CREDIT_REASON_REQUIRED"


def test_a_price_correction_credits_part_of_a_line(db, env):
    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 10, "unit_price": 1000, "vat_rate": 0}])
    note = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 10, "unit_price": 50}], reason="Remise oubliée").value
    assert note["total_incl_tax"] == D("500") and isinstance(_validate_note(db, env, note["id"]), Ok)
    assert _service(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["amount"] == D("9500")


def test_a_credit_note_after_payment_leaves_a_supplier_credit_rather_than_a_negative_balance(db, env):
    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 10, "unit_price": 100, "vat_rate": 0}])
    assert isinstance(apply_document_delta(db, tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, delta=D("1000"),
                                           event_type="treasury.disbursement.posted", document_id="d1"), Ok)
    note = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 2}]).value
    assert isinstance(_validate_note(db, env, note["id"]), Ok)
    invoice = _service(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["amount"], invoice["amount_paid"], invoice["remaining"], invoice["supplier_credit"], invoice["status"]) == \
        (D("800"), D("1000"), D("0"), D("200"), "paid")
    # The disbursement can still be cancelled: its whole payment comes back off the invoice.
    assert isinstance(apply_document_delta(db, tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, delta=D("-1000"),
                                           event_type="treasury.disbursement.cancelled", document_id="d1"), Ok)
    assert _service(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["status"] == "validated"


def test_an_invoice_credited_in_full_is_settled(db, env):
    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 1, "unit_price": 100, "vat_rate": 18}])
    note = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 1}]).value
    assert isinstance(_validate_note(db, env, note["id"]), Ok)
    invoice = _service(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["amount"], invoice["remaining"], invoice["status"]) == (D("0"), D("0"), "paid")


def test_cancelling_is_refused_once_payments_or_credit_notes_exist(db, env):
    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 2, "unit_price": 100, "vat_rate": 0}])
    _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 1}])
    refused = _service(db).cancel(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id)
    assert isinstance(refused, Err) and refused.code == "INVOICE_HAS_CREDIT_NOTES"
    draft = _draft(db, env, number="F-9", amount=D("10")).value
    assert _note(db, env, draft["id"], [{"invoice_line_id": "x", "quantity": 1}]).code == "INVOICE_NOT_VALIDATED"


def test_treasury_sees_the_amount_due_after_credit_notes(db, env):
    from modules.treasury.api.document_service import DocumentService

    invoice_id, lines = _validated(db, env, [{"description": "Film", "quantity": 10, "unit_price": 100, "vat_rate": 0}])
    note = _note(db, env, invoice_id, [{"invoice_line_id": lines[0]["id"], "quantity": 4}]).value
    _validate_note(db, env, note["id"])
    assert DocumentService(db).open_invoice(TENANT, "out", invoice_id).value["remaining"] == D("600")


# ---- attachments ------------------------------------------------------------------------------------

def test_attachments_on_an_invoice(db, env):
    invoice = _draft(db, env, amount=D("10")).value
    files = PurchaseInvoiceAttachmentService(db)
    added = files.add(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], filename="scan.pdf",
                      content_type="application/pdf", content_base64=base64.b64encode(b"%PDF-1").decode())
    assert isinstance(added, Ok) and added.value["size_bytes"] == 6
    assert [a["filename"] for a in files.list(tenant_id=TENANT, invoice_id=invoice["id"]).value] == ["scan.pdf"]
    assert files.read(tenant_id=TENANT, invoice_id=invoice["id"], attachment_id=added.value["id"]).value["content"] == b"%PDF-1"
    assert files.add(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], filename="x", content_type=None,
                     content_base64="***").code == "ATTACHMENT_UNREADABLE"
    assert isinstance(files.delete(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], attachment_id=added.value["id"]), Ok)
    assert files.list(tenant_id=TENANT, invoice_id=invoice["id"]).value == []
    assert files.list(tenant_id=TENANT, invoice_id="missing").code == "NOT_FOUND"

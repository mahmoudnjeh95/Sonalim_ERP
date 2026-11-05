"""Integration tests for PurchaseInvoiceService: the supplier invoice that treasury
disbursements allocate to. Payment progress only moves through apply_payment_delta."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.procurement.api.invoice_service import PurchaseInvoiceService

TENANT = "integration-test-purchase-invoice"
D = Decimal


@pytest.fixture
def env(db):
    actor = str(ULID())
    supplier = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Supplier', 'supplier', 'active')",
        (supplier, TENANT),
    )
    return {"actor": actor, "supplier": supplier}


def _draft(service, env, number="F-001", amount=D("1000"), **extra):
    return service.create_draft(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"],
        supplier_invoice_number=number, invoice_date=datetime.date(2026, 3, 1), amount=amount, **extra,
    )


def _validated(service, env, **kwargs):
    created = _draft(service, env, **kwargs)
    assert isinstance(created, Ok)
    result = service.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=created.value["id"], correlation_id="c")
    assert isinstance(result, Ok)
    return result.value


def test_draft_with_and_without_lines(db, env):
    service = PurchaseInvoiceService(db)
    plain = _draft(service, env, "F-001")
    assert isinstance(plain, Ok) and plain.value["status"] == "draft" and plain.value["number"] is None
    with_lines = _draft(
        service, env, "F-002", lines=[{"description": "Film", "quantity": 2, "unit_price": 500, "vat_rate": 0}],
    )
    assert isinstance(with_lines, Ok)
    assert len(service.list_lines(tenant_id=TENANT, invoice_id=with_lines.value["id"])) == 1


def test_lines_must_match_total(db, env):
    result = _draft(PurchaseInvoiceService(db), env, lines=[{"description": "Film", "quantity": 1, "unit_price": 10}])
    assert isinstance(result, Err) and result.code == "TOTAL_MISMATCH"


def test_duplicate_supplier_number_refused(db, env):
    service = PurchaseInvoiceService(db)
    assert isinstance(_draft(service, env, "F-001"), Ok)
    again = _draft(service, env, "F-001")
    assert isinstance(again, Err) and again.code == "DUPLICATE_SUPPLIER_INVOICE"


def test_edit_only_while_draft(db, env):
    service = PurchaseInvoiceService(db)
    invoice = _validated(service, env)
    result = service.update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], changes={"note": "x"})
    assert isinstance(result, Err) and result.code == "INVOICE_NOT_DRAFT"


def test_validate_numbers_the_invoice_and_publishes_event(db, env):
    service = PurchaseInvoiceService(db)
    first = _validated(service, env, number="F-001")
    second = _validated(service, env, number="F-002")
    assert first["number"] == "FA-2026-000001" and second["number"] == "FA-2026-000002"
    assert first["status"] == "validated"
    row = db.execute(
        "SELECT count(*) FROM events.outbox WHERE tenant_id = %s AND event_type = 'procurement.purchase_invoice.validated'",
        (TENANT,),
    ).fetchone()
    assert row[0] == 2


def test_payment_deltas_drive_status_and_bounds(db, env):
    service = PurchaseInvoiceService(db)
    invoice = _validated(service, env, amount=D("1000"))
    partial = service.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D("400"))
    assert partial.value["status"] == "partially_paid" and partial.value["remaining"] == D("600")
    over = service.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D("601"))
    assert isinstance(over, Err) and over.code == "OVER_ALLOCATION"
    paid = service.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D("600"))
    assert paid.value["status"] == "paid"
    back = service.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D("-1000"))
    assert back.value["status"] == "validated" and back.value["amount_paid"] == D("0")


def test_draft_cannot_be_paid(db, env):
    service = PurchaseInvoiceService(db)
    created = _draft(service, env)
    result = service.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=created.value["id"], delta=D("10"))
    assert isinstance(result, Err) and result.code == "INVOICE_NOT_VALIDATED"


def test_cancel_refused_with_payments(db, env):
    service = PurchaseInvoiceService(db)
    invoice = _validated(service, env)
    service.apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], delta=D("10"))
    result = service.cancel(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"])
    assert isinstance(result, Err)  # partially_paid has no manual transition


def test_cancel_unpaid_validated(db, env):
    service = PurchaseInvoiceService(db)
    invoice = _validated(service, env)
    result = service.cancel(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"])
    assert isinstance(result, Ok) and result.value["status"] == "cancelled"


def test_list_filters_and_overdue(db, env):
    service = PurchaseInvoiceService(db)
    _validated(service, env, number="F-001", due_date=datetime.date(2026, 3, 10))
    _validated(service, env, number="F-002", due_date=datetime.date(2026, 4, 30))
    overdue = service.list_invoices(tenant_id=TENANT, overdue=True, today=datetime.date(2026, 4, 1))
    assert [i["supplier_invoice_number"] for i in overdue] == ["F-001"]
    assert len(service.list_invoices(tenant_id=TENANT, status="validated")) == 2
    assert len(service.list_invoices(tenant_id=TENANT, partner_id=env["supplier"])) == 2


def test_get_invoice_not_found(db, env):
    result = PurchaseInvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id="nope")
    assert isinstance(result, Err) and result.code == "NOT_FOUND"

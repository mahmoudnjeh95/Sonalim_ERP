"""Sales invoices over HTTP: the order filter, the detail with lines and credit notes, the credit-note list.

A throwaway FastAPI app carries just the invoices router; its connection is the fixture's rolled-back one
wrapped in NoCommitConnection."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.finance.api import router as router_module  # noqa: E402
from modules.finance.api.billing_service import DeliveryBillingService  # noqa: E402
from modules.finance.api.service import InvoiceService  # noqa: E402
from modules.finance.testing_support import NoCommitConnection  # noqa: E402
from modules.sales.api.service import SalesOrderService  # noqa: E402
from modules.sales.domain.entities import OrderLine  # noqa: E402

TENANT = "integration-test-invoices-router"


@pytest.fixture
def api(db, monkeypatch) -> dict:
    actor, partner, product, uom = (str(ULID()) for _ in range(4))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Acme', 'customer')", (partner, TENANT))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'IR', 'IR', %s)", (product, TENANT, uom))
    wrapped = NoCommitConnection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=actor, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (actor, permission))

    return {"client": TestClient(app), "grant": grant, "db": db, "actor": actor, "partner": partner, "product": product}


def test_an_order_lists_its_delivery_invoices_with_lines_and_credit_notes(api):
    db = api["db"]
    order = SalesOrderService(db).create_order(tenant_id=TENANT, actor_id=api["actor"], partner_id=api["partner"], location_id="L",
                                               lines=[OrderLine(product_id=api["product"], quantity=10, unit_price=150)])
    billing = DeliveryBillingService(db)
    invoice = billing.invoice_delivery(tenant_id=TENANT, source_type="delivery_note", source_id="BL-ID", source_number="BL-2026-000009",
                                       order_id=order.id, delivered={api["product"]: Decimal(4)}, delivered_on=datetime.date(2026, 11, 6))
    invoice_id = invoice.value["id"]
    InvoiceService(db).issue_invoice(tenant_id=TENANT, actor_id=api["actor"], invoice_id=invoice_id, correlation_id="c")
    billing.credit_return(tenant_id=TENANT, return_id="BR-ID", return_number="BR-2026-000001", delivery_note_ids=["BL-ID"], order_id=order.id,
                          returned={api["product"]: Decimal(1)}, returned_on=datetime.date(2026, 11, 6), correlation_id="c")

    client = api["client"]
    assert client.get(f"/finance/invoices?order_id={order.id}").status_code == 403
    api["grant"]("finance.view_invoices")
    [listed] = client.get(f"/finance/invoices?order_id={order.id}").json()
    assert (listed["source_type"], listed["source_number"], float(listed["total"]), float(listed["amount"])) == ("delivery_note", "BL-2026-000009", 600, 450)
    detail = client.get(f"/finance/invoices/{invoice_id}").json()
    assert [float(l["quantity"]) for l in detail["lines"]] == [4]
    assert [c["return_number"] for c in detail["credit_notes"]] == ["BR-2026-000001"]
    [note] = client.get("/finance/credit-notes").json()
    assert note["invoice_number"] == listed["number"] and float(note["amount"]) == 150
    assert client.get("/finance/invoices/missing").status_code == 404


def test_an_invoice_amount_is_stored_exactly_as_sent(api):
    api["grant"]("finance.manage_invoices", "finance.admin_invoices")
    client, db = api["client"], api["db"]
    created = client.post("/finance/invoices", json={"partner_id": api["partner"], "amount": 1234.56})
    assert created.status_code == 201
    invoice_id = created.json()["id"]
    stored = lambda: db.execute("SELECT amount FROM finance.invoices WHERE id = %s", (invoice_id,)).fetchone()[0]  # noqa: E731
    assert stored() == Decimal("1234.56")
    # a decimal string is an amount too
    assert client.patch(f"/finance/invoices/{invoice_id}", json={"amount": "0.30"}).status_code == 200
    assert stored() == Decimal("0.30")
    assert client.post("/finance/invoices", json={"partner_id": api["partner"], "amount": "lots"}).status_code == 422


def test_a_manual_invoice_with_lines_is_created_edited_and_refused_once_issued(api):
    api["grant"]("finance.manage_invoices", "finance.view_invoices")
    client = api["client"]
    body = {"partner_id": api["partner"], "invoice_date": "2026-06-15",
            "lines": [{"description": "Transport", "quantity": 2, "unit_price": 1000, "tax_code": "TVA18"}]}
    created = client.post("/finance/invoices", json=body)
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert float(invoice["total"]) == 2360 and float(invoice["vat_amount"]) == 360 and invoice["lines"][0]["description"] == "Transport"

    edited = client.put(f"/finance/invoices/{invoice['id']}/lines",
                        json={"lines": [{"description": "Transport", "quantity": 1, "unit_price": 500, "tax_code": "EXO"}]})
    assert edited.status_code == 200 and float(edited.json()["total"]) == 500

    assert client.post("/finance/invoices", json={"partner_id": api["partner"]}).status_code == 400
    assert client.post("/finance/invoices", json={**body, "lines": []}).json()["detail"]["code"] == "INVOICE_EMPTY"
    assert client.post(f"/finance/invoices/{invoice['id']}/issue", json={"correlation_id": "c"}).status_code == 200
    again = client.put(f"/finance/invoices/{invoice['id']}/lines", json={"lines": [{"description": "x", "unit_price": 1}]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "INVOICE_NOT_DRAFT"
    legacy = client.post("/finance/invoices", json={"partner_id": api["partner"], "amount": 750})
    assert legacy.status_code == 201

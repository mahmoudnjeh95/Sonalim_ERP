"""The complete purchase invoice through HTTP: request models, permissions, status codes, the export and
attachment downloads, credit notes, and treasury's read of one invoice. The services have their own tests.

Routers commit on their own connection, so the factory is replaced by the test's rolled-back connection
with commit and rollback made no-ops."""
from __future__ import annotations

import base64
import datetime
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from ulid import ULID

TENANT = "integration-test-purchase-invoice-http"
TODAY = datetime.date.today().isoformat()
PERMISSIONS = ["procurement.view_purchase_invoices", "procurement.manage_purchase_invoices", "procurement.admin_purchase_invoices",
               "treasury.view"]


class _SharedConnection:
    def __init__(self, connection) -> None:
        self._connection = connection

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _session(db, *permissions) -> dict[str, str]:
    user, token = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (user, TENANT, f"{user}@test.local"))
    db.execute("INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, NOW() + interval '1 hour')",
               (token, user, TENANT))
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api(db, monkeypatch):
    @contextmanager
    def shared():
        yield _SharedConnection(db)

    import core.tenancy
    import modules.procurement.api.invoice_router
    import modules.treasury.api.router

    for module in (core.tenancy, modules.procurement.api.invoice_router, modules.treasury.api.router):
        monkeypatch.setattr(module, "get_connection", shared)
    from app.main import app

    client = TestClient(app)
    client.headers.update(_session(db, *PERMISSIONS))
    return client


@pytest.fixture
def supplier(db):
    partner = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Fournisseur HTTP', 'supplier', 'active')",
               (partner, TENANT))
    return partner


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def test_an_invoice_with_lines_credit_note_and_attachment_over_http(api, supplier):
    invoice = _ok(api.post("/procurement/purchase-invoices", json={
        "partner_id": supplier, "supplier_invoice_number": "HTTP-1", "invoice_date": TODAY,
        "lines": [{"description": "Film", "quantity": "10", "unit_price": "1000", "discount_rate": "5"},
                  {"description": "Port", "quantity": "1", "unit_price": "2000", "vat_rate": "0"}]}), 201)
    assert (invoice["total_excl_tax"], invoice["total_vat"], invoice["total_incl_tax"]) == ("11500.00", "1710.00", "13210.00")
    assert [line["vat_rate"] for line in invoice["lines"]] == ["18.00", "0.00"] and invoice["warnings"] == []

    edited = _ok(api.patch(f"/procurement/purchase-invoices/{invoice['id']}", json={"due_date": TODAY, "note": "Scan reçu"}))
    assert edited["note"] == "Scan reçu" and edited["amount"] == "13210.00"
    validated = _ok(api.post(f"/procurement/purchase-invoices/{invoice['id']}/validate"))
    assert validated["number"].startswith("FA-") and validated["status"] == "validated"

    note = _ok(api.post("/procurement/purchase-credit-notes", json={
        "invoice_id": invoice["id"], "note_date": TODAY, "reason": "Retour", "lines": [{"invoice_line_id": invoice["lines"][0]["id"], "quantity": "2"}]}), 201)
    assert note["total_incl_tax"] == "2242.00"
    too_much = api.post("/procurement/purchase-credit-notes", json={
        "invoice_id": invoice["id"], "note_date": TODAY, "reason": "x", "lines": [{"invoice_line_id": invoice["lines"][0]["id"], "quantity": "11"}]})
    assert too_much.status_code == 409 and too_much.json()["detail"]["code"] == "CREDIT_EXCEEDS_INVOICE"
    assert _ok(api.post(f"/procurement/purchase-credit-notes/{note['id']}/validate"))["number"].startswith("AV-")
    detail = _ok(api.get(f"/procurement/purchase-invoices/{invoice['id']}"))
    assert detail["amount"] == "10968.00" and [n["status"] for n in detail["credit_notes"]] == ["validated"]
    cancel = api.post(f"/procurement/purchase-invoices/{invoice['id']}/cancel")
    assert cancel.status_code == 409 and cancel.json()["detail"]["code"] == "INVOICE_HAS_CREDIT_NOTES"

    attachment = _ok(api.post(f"/procurement/purchase-invoices/{invoice['id']}/attachments", json={
        "filename": "facture.pdf", "content_type": "application/pdf", "content_base64": base64.b64encode(b"%PDF").decode()}), 201)
    download = api.get(f"/procurement/purchase-invoices/{invoice['id']}/attachments/{attachment['id']}")
    assert download.status_code == 200 and download.content == b"%PDF"
    assert api.delete(f"/procurement/purchase-invoices/{invoice['id']}/attachments/{attachment['id']}").status_code == 204

    activity = _ok(api.get(f"/treasury/invoice-activity?direction=out&invoice_id={invoice['id']}"))
    assert activity == {"documents": [], "payment_orders": []}


def test_list_filters_export_and_settings_over_http(api, db, supplier):
    _ok(api.post("/procurement/purchase-invoices", json={
        "partner_id": supplier, "supplier_invoice_number": "HTTP-2", "invoice_date": TODAY, "amount": "500"}), 201)
    assert [i["supplier_invoice_number"] for i in _ok(api.get(f"/procurement/purchase-invoices?partner_id={supplier}&date_from={TODAY}"))] == ["HTTP-2"]
    assert _ok(api.get("/procurement/purchase-invoices?date_to=2000-01-01")) == []
    csv = api.get(f"/procurement/purchase-invoices/export?fmt=csv&lang=fr&partner_id={supplier}")
    text = csv.content.decode("utf-8-sig")
    assert csv.status_code == 200 and "Net à payer" in text and "HTTP-2" in text and "Fournisseur HTTP" in text
    assert api.get("/procurement/purchase-invoices/export?fmt=xlsx").content[:2] == b"PK"

    assert _ok(api.get("/procurement/purchase-invoices/settings")) == {"default_vat_rate": "18.00"}
    assert _ok(api.put("/procurement/purchase-invoices/settings", json={"default_vat_rate": "10"}))["default_vat_rate"] == "10"
    viewer = _session(db, "procurement.view_purchase_invoices")
    assert api.put("/procurement/purchase-invoices/settings", json={"default_vat_rate": "5"}, headers=viewer).status_code == 403
    assert api.post("/procurement/purchase-invoices", json={"partner_id": supplier, "supplier_invoice_number": "HTTP-3",
                                                            "invoice_date": TODAY, "amount": "5"}, headers=viewer).status_code == 403


def test_from_receipts_route_refuses_an_unknown_receipt(api):
    refused = api.post("/procurement/purchase-invoices/from-receipts", json={
        "receipt_ids": [str(ULID())], "supplier_invoice_number": "R-1", "invoice_date": TODAY})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "RECEIPT_NOT_INVOICEABLE"
    assert _ok(api.get("/procurement/purchase-invoices/invoiceable-receipts")) == []

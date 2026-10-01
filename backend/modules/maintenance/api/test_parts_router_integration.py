"""The parts-request endpoints over HTTP: rights, shapes, error codes, and a refused
approval that leaves the stock as it was.

The session is overridden and every connection the routers or the permission check open
is the `db` fixture's rolled-back one (commit and rollback made no-ops), so nothing
reaches the development data.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.domain.result import Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.maintenance.api import jobs_router, parts_router  # noqa: E402
from modules.maintenance.api import router as router_module  # noqa: E402
from modules.maintenance.api.equipment_service import EquipmentService  # noqa: E402
from modules.maintenance.api.job_service import JobService  # noqa: E402
from modules.warehouse.api.location_service import LocationService  # noqa: E402
from modules.warehouse.api.service import StockService  # noqa: E402

TENANT = "integration-test-parts-router"
TODAY = datetime.date.today()


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _user(db, full_name, *permissions):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, TENANT, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


@pytest.fixture
def api(db, monkeypatch):
    sup = _user(db, "Sara Superviseur", "maintenance.view_jobs", "maintenance.plan_jobs", "maintenance.execute_jobs")
    chef = _user(db, "Chef Keita", "maintenance.view_jobs", "maintenance.execute_jobs")
    other = _user(db, "Autre Chef", "maintenance.view_jobs", "maintenance.execute_jobs")

    machine = EquipmentService(db).create_equipment(
        tenant_id=TENANT, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    job = JobService(db).create_job(
        tenant_id=TENANT, actor_id=sup, equipment_id=machine, title="Roulement", description=None, kind="corrective",
        priority="normal", due_date=TODAY, stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Changer le roulement", "action": "replace"}], chef_user_id=chef,
    ).value

    piece = str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, 'pc', 'Pièce', 'unit', TRUE)",
        (piece, TENANT),
    )
    bearing = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'PRT-ROUL', 'Roulement 6204', %s)",
        (bearing, TENANT, piece),
    )
    store = LocationService(db).create_location(tenant_id=TENANT, actor_id=sup, code="MAG-PDR", name="Magasin pièces").value.id
    received = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=bearing, location_id=store, quantity=3, correlation_id=str(ULID()), reference="setup"
    )
    assert isinstance(received, Ok), received

    wrapped = _Connection(db)
    monkeypatch.setattr(parts_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr(jobs_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)

    current = {"user": sup}
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(
        tenant_id=TENANT, user_id=current["user"], session_token="t"
    )

    def acting_as(user_id: str) -> None:
        current["user"] = user_id

    return SimpleNamespace(
        client=TestClient(app), acting_as=acting_as, sup=sup, chef=chef, other=other, job=job,
        piece=piece, bearing=bearing, store=store, db=db,
    )


def _ask(api, quantity=5, **extra):
    api.acting_as(api.chef)
    return api.client.post(
        f"/maintenance/jobs/{api.job}/part-requests",
        json={"lines": [{"product_id": api.bearing, "uom_id": api.piece, "quantity": quantity}], **extra},
    )


def _stock_moves(api):
    return api.db.execute(
        "SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s AND move_type = 'maintenance'", (TENANT,)
    ).fetchone()[0]


def test_request_availability_and_approve_over_http(api):
    created = _ask(api, note="urgent")
    assert created.status_code == 201, created.text
    request = created.json()
    assert request["status"] == "pending" and request["requested_by_name"] == "Chef Keita"
    assert request["equipment_name"] == "Presse 1" and request["note"] == "urgent"
    [line] = request["lines"]
    assert (line["product_name"], line["uom_code"], line["quantity"]) == ("Roulement 6204", "pc", 5)

    api.acting_as(api.sup)
    listed = api.client.get("/maintenance/part-requests", params={"status": "pending"})
    assert listed.status_code == 200 and [r["id"] for r in listed.json()] == [request["id"]]
    assert api.client.get("/maintenance/part-requests", params={"status": "approved"}).json() == []

    availability = api.client.get(f"/maintenance/part-requests/{request['id']}/availability")
    assert availability.status_code == 200
    assert availability.json() == {
        "lines": [
            {
                "line_id": line["id"],
                "product_id": api.bearing,
                "locations": [{"location_id": api.store, "location_name": "Magasin pièces", "available": 3.0, "in_spare_parts": False}],
            }
        ]
    }

    approved = api.client.post(
        f"/maintenance/part-requests/{request['id']}/approve",
        json={"lines": [{"line_id": line["id"], "location_id": api.store, "issue_quantity": 3}], "note": "2 à commander"},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved" and body["decided_by_name"] == "Sara Superviseur"
    assert (body["lines"][0]["issued_quantity"], body["lines"][0]["purchase_quantity"]) == (3, 2)
    assert _stock_moves(api) == 1

    job = api.client.get(f"/maintenance/jobs/{api.job}").json()
    assert [r["id"] for r in job["part_requests"]] == [request["id"]]


def test_refusals_over_http(api):
    request = _ask(api).json()
    [line] = request["lines"]

    # another chef's job
    api.acting_as(api.other)
    refused = api.client.post(
        f"/maintenance/jobs/{api.job}/part-requests",
        json={"lines": [{"product_id": api.bearing, "uom_id": api.piece, "quantity": 1}]},
    )
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "NOT_JOB_CHEF"
    # deciding is a supervisor's right
    assert api.client.get(f"/maintenance/part-requests/{request['id']}/availability").status_code == 403
    assert api.client.post(f"/maintenance/part-requests/{request['id']}/reject", json={"note": "non"}).status_code == 403

    api.acting_as(api.sup)
    too_much = api.client.post(
        f"/maintenance/part-requests/{request['id']}/approve",
        json={"lines": [{"line_id": line["id"], "location_id": api.store, "issue_quantity": 4}]},
    )
    assert too_much.status_code == 422
    detail = too_much.json()["detail"]
    assert detail["code"] == "INSUFFICIENT_STOCK" and detail["message"] and detail["message_fr"]
    assert _stock_moves(api) == 0

    no_note = api.client.post(f"/maintenance/part-requests/{request['id']}/reject", json={})
    assert no_note.status_code == 422 and no_note.json()["detail"]["code"] == "NOTE_REQUIRED"

    missing = api.client.get("/maintenance/part-requests/nope/availability")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "NOT_FOUND"
    assert api.client.post("/maintenance/part-requests/nope/reject", json={"note": "x"}).status_code == 404
    assert api.client.post("/maintenance/jobs/nope/part-requests", json={"lines": []}).status_code == 404

    rejected = api.client.post(f"/maintenance/part-requests/{request['id']}/reject", json={"note": "déjà en atelier"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected" and rejected.json()["decision_note"] == "déjà en atelier"

"""The spare-parts endpoints over HTTP: the location setting, the catalog the map
editor picks from, and parts on a checkpoint -- rights, shapes and error codes.

The session is overridden and every connection the routers or the permission check
open is the `db` fixture's rolled-back one (commit and rollback made no-ops), so
nothing reaches the development data.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.domain.result import Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.maintenance.api import maps_router, spare_parts_router  # noqa: E402
from modules.maintenance.api import router as router_module  # noqa: E402
from modules.maintenance.api.equipment_service import EquipmentService  # noqa: E402
from modules.maintenance.api.map_service import MapService  # noqa: E402
from modules.warehouse.api.location_service import LocationService  # noqa: E402
from modules.warehouse.api.service import StockService  # noqa: E402

TENANT = "integration-test-spare-parts-router"
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50


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
    sup = _user(
        db, "Sara Superviseur", "maintenance.view_jobs", "maintenance.plan_jobs", "maintenance.manage_checkpoints",
        "maintenance.view_equipment",
    )
    chef = _user(db, "Chef Keita", "maintenance.view_jobs", "maintenance.execute_jobs")

    piece = str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, 'pc', 'Pièce', 'unit', TRUE)",
        (piece, TENANT),
    )
    store = LocationService(db).create_location(
        tenant_id=TENANT, actor_id=sup, code="PDR", name="Pièces de rechange", location_type="zone"
    ).value.id
    bearing = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) "
        "VALUES (%s, %s, 'PDR-ROUL', 'Roulement 6204', %s, %s)",
        (bearing, TENANT, piece, store),
    )
    received = StockService(db).receive_stock(
        tenant_id=TENANT, product_id=bearing, location_id=store, quantity=3, correlation_id=str(ULID()), reference="setup"
    )
    assert isinstance(received, Ok), received
    machine = EquipmentService(db).create_equipment(
        tenant_id=TENANT, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    view = MapService(db).create_view(
        tenant_id=TENANT, actor_id=sup, equipment_id=machine, label="Vue avant", image=JPEG_BYTES, mime="image/jpeg"
    ).value["id"]

    wrapped = _Connection(db)
    monkeypatch.setattr(spare_parts_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr(maps_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
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
        client=TestClient(app), acting_as=acting_as, sup=sup, chef=chef, piece=piece, store=store,
        bearing=bearing, view=view,
    )


def test_the_location_setting_round_trips_over_http(api):
    assert api.client.get("/maintenance/settings").json() == {
        "spare_parts_location_id": None, "spare_parts_location_name": None,
    }

    saved = api.client.put("/maintenance/settings", json={"spare_parts_location_id": api.store})

    assert saved.status_code == 200, saved.text
    assert saved.json() == {"spare_parts_location_id": api.store, "spare_parts_location_name": "Pièces de rechange"}
    assert api.client.get("/maintenance/settings").json() == saved.json()


def test_an_unknown_location_is_a_422_with_its_code(api):
    refused = api.client.put("/maintenance/settings", json={"spare_parts_location_id": str(ULID())})

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "UNKNOWN_LOCATION"


def test_only_a_planner_changes_the_location(api):
    api.acting_as(api.chef)

    assert api.client.put("/maintenance/settings", json={"spare_parts_location_id": api.store}).status_code == 403
    assert api.client.get("/maintenance/settings/locations").status_code == 403
    # Anyone who sees jobs may read which location it is.
    assert api.client.get("/maintenance/settings").status_code == 200


def test_location_options_list_the_warehouse_locations(api):
    options = api.client.get("/maintenance/settings/locations").json()

    assert {"id": api.store, "code": "PDR", "name": "Pièces de rechange", "label": "Pièces de rechange"} in options


def test_the_catalog_needs_the_map_editor_right(api):
    api.client.put("/maintenance/settings", json={"spare_parts_location_id": api.store})

    catalog = api.client.get("/maintenance/spare-parts")

    assert catalog.status_code == 200, catalog.text
    assert [(product["name"], product["available"]) for product in catalog.json()["products"]] == [("Roulement 6204", 3)]
    api.acting_as(api.chef)
    assert api.client.get("/maintenance/spare-parts").status_code == 403


def test_checkpoint_parts_over_http(api):
    created = api.client.post(
        f"/maintenance/views/{api.view}/checkpoints",
        json={"x_pct": 10, "y_pct": 20, "label": "Roulement moteur", "action": "replace",
              "parts": [{"product_id": api.bearing, "quantity": 2}]},
    )
    assert created.status_code == 201, created.text
    point = created.json()
    assert [(part["product_name"], part["uom_code"], part["quantity"]) for part in point["parts"]] == [("Roulement 6204", "pc", 2)]

    renamed = api.client.patch(f"/maintenance/checkpoints/{point['id']}", json={"label": "Roulement côté réducteur"})
    assert [part["quantity"] for part in renamed.json()["parts"]] == [2]

    cleared = api.client.patch(f"/maintenance/checkpoints/{point['id']}", json={"parts": []})
    assert cleared.json()["parts"] == []


def test_a_fractional_count_of_parts_is_a_422(api):
    refused = api.client.post(
        f"/maintenance/views/{api.view}/checkpoints",
        json={"x_pct": 10, "y_pct": 20, "label": "Roulement moteur", "action": "replace",
              "parts": [{"product_id": api.bearing, "quantity": 1.5}]},
    )

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "QUANTITY_MUST_BE_INTEGER"


def test_a_technician_lists_the_products_a_parts_request_can_name(api):
    """The request form must not depend on core.view_products, which a technician lacks."""
    api.client.put("/maintenance/settings", json={"spare_parts_location_id": api.store})
    api.acting_as(api.chef)

    listed = api.client.get("/maintenance/part-products")

    assert listed.status_code == 200, listed.text
    bearing = next(product for product in listed.json() if product["product_id"] == api.bearing)
    assert bearing == {
        "product_id": api.bearing, "name": "Roulement 6204", "sku": "PDR-ROUL",
        "uom_id": api.piece, "uom_code": "pc", "uom_integer_only": True, "in_spare_parts": True,
    }


def test_a_view_photo_is_added_and_replaced_over_http(api):
    machine = api.client.get("/maintenance/equipment").json()[0]["id"]

    created = api.client.post(
        f"/maintenance/equipment/{machine}/views",
        data={"label": "Vue arrière"},
        files={"image": ("arriere.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]

    replaced = api.client.patch(
        f"/maintenance/views/{view_id}", files={"image": ("arriere2.jpg", JPEG_BYTES + b"1", "image/jpeg")}
    )
    assert replaced.status_code == 200, replaced.text
    assert api.client.get(f"/maintenance/views/{view_id}/image").content == JPEG_BYTES + b"1"

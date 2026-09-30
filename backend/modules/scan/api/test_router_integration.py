"""The scan endpoints over HTTP: rights, error shapes, and the image round trip."""
from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.scan.api import router as router_module  # noqa: E402
from modules.scan.api.scan_world import make_world  # noqa: E402

TENANT = "scan-router-test"
IMAGE = b"\xff\xd8\xff router jpeg"


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


@pytest.fixture
def api(db, monkeypatch):
    world = make_world(db, TENANT)
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=world["actor"], session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (world["actor"], permission))

    return {"client": TestClient(app), "grant": grant, "world": world}


def _create(api) -> str:
    world = api["world"]
    response = api["client"].post("/scan/sessions", json={
        "work_center_id": world["work_center"], "report_date": world["day"].isoformat(), "shift": "Matin", "default_of_id": world["of"],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_no_scan_right_no_access(api):
    assert api["client"].get("/scan/sessions").status_code == 403


def test_upload_and_fetch_the_image(api):
    api["grant"]("scan.use_scanner")
    session_id = _create(api)
    uploaded = api["client"].post(f"/scan/sessions/{session_id}/pages", json={"files": [
        {"filename": "p.jpg", "content_type": "image/jpeg", "width": 10, "height": 20, "data_base64": base64.b64encode(IMAGE).decode()},
    ]})
    assert uploaded.status_code == 201, uploaded.text
    page_id = uploaded.json()[0]["id"]
    image = api["client"].get(f"/scan/pages/{page_id}/image")
    assert image.status_code == 200 and image.content == IMAGE and image.headers["content-type"] == "image/jpeg"
    detail = api["client"].get(f"/scan/sessions/{session_id}").json()
    assert [p["status"] for p in detail["pages"]] == ["queued"]


def test_errors_carry_code_and_french_message(api):
    api["grant"]("scan.use_scanner")
    response = api["client"].post("/scan/sessions", json={
        "work_center_id": api["world"]["work_center"], "report_date": "2030-03-04", "shift": "Brunch",
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNKNOWN_SHIFT" and response.json()["detail"]["message_fr"]


def test_apply_without_the_section_right_is_forbidden(api):
    api["grant"]("scan.use_scanner", "production.shift.edit.stops")
    session_id = _create(api)
    response = api["client"].post(f"/scan/sessions/{session_id}/apply", json={"header": {}, "sections": {"runs": {"runs": []}}, "fingerprints": {}})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "FORBIDDEN_SECTION"


def test_viewers_see_a_shifts_photos_but_cannot_scan(api):
    api["grant"]("scan.view_scans")
    assert api["client"].get("/scan/shifts/nothing/pages").json() == []
    assert api["client"].get("/scan/sessions").status_code == 403


def test_alias_edits_need_the_admin_right(api):
    api["grant"]("scan.use_scanner")
    assert api["client"].get("/scan/aliases").json() == []
    assert api["client"].delete("/scan/aliases/unknown").status_code == 403
    api["grant"]("scan.admin_aliases")
    assert api["client"].delete("/scan/aliases/unknown").status_code == 404


def test_vocabulary_lists_the_kinds(api):
    api["grant"]("scan.use_scanner")
    body = api["client"].get("/scan/vocabulary", params={"work_center_id": api["world"]["work_center"]}).json()
    assert {"raw_material", "finished_product", "waste_production", "line_state"} <= set(body)

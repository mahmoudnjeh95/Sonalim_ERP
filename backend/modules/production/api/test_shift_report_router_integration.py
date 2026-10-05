"""The shift report endpoints over HTTP: who may do what, and how errors map to statuses.

A throwaway FastAPI app carries just this router. The session is overridden, and the
router's connection is the `db` fixture's rolled-back one (with commit and rollback
made no-ops, so nothing reaches the development data).
"""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI
pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402
from ulid import ULID

from core.tenancy import TenantContext, require_session
from modules.production.api import router as router_module

TENANT = "shift-router-test"
DAY = "2030-05-06"


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
def world(db, monkeypatch):
    user, work_center = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user, TENANT, f"{user}@test.local"),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'RT-WC', 'Router line')",
        (work_center, TENANT),
    )
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))

    return {"client": TestClient(app), "grant": grant, "work_center": work_center, "db": db}


def _open(world) -> str:
    response = world["client"].post(
        "/production/shift-reports",
        json={"work_center_id": world["work_center"], "report_date": DAY, "shift": "morning"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_user_with_no_shift_permission_is_refused_everywhere(world):
    client = world["client"]
    assert client.get("/production/shift-reports").status_code == 403
    assert (
        client.post(
            "/production/shift-reports",
            json={"work_center_id": world["work_center"], "report_date": DAY, "shift": "morning"},
        ).status_code
        == 403
    )


def test_a_viewer_can_read_but_not_open_or_edit(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)  # needs some edit right, which this user has
    world["db"].execute("DELETE FROM core.user_permissions WHERE permission = 'production.shift.edit.energy'")
    client = world["client"]
    assert client.get(f"/production/shift-reports/{shift_id}").status_code == 200
    assert client.put(f"/production/shift-reports/{shift_id}/sections/energy", json={"payload": {}}).status_code == 403


def test_a_section_right_covers_that_section_only(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    client = world["client"]
    saved = client.put(
        f"/production/shift-reports/{shift_id}/sections/energy",
        json={"payload": {"energy": {"fuel_quantity": 600}}},
    )
    assert saved.status_code == 200 and saved.json()["status"] == "draft"
    refused = client.put(
        f"/production/shift-reports/{shift_id}/sections/packing", json={"payload": {"rows": []}}
    )
    assert refused.status_code == 403
    assert "production.shift.edit.packing" in refused.text


def test_an_unknown_section_is_a_404(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    response = world["client"].put(f"/production/shift-reports/{shift_id}/sections/reels", json={"payload": {}})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "INVALID_SECTION"


def test_domain_errors_map_to_400_and_409(world):
    world["grant"]("production.shift.view", "production.shift.edit.silo", "production.shift.edit.packet_checks")
    shift_id = _open(world)
    client = world["client"]
    bad = client.put(
        f"/production/shift-reports/{shift_id}/sections/silo",
        json={"payload": {"states": [{"side": "production", "phase": "start", "level_percent": 130}]}},
    )
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "INVALID_VALUE"
    empty = client.post(f"/production/shift-reports/{shift_id}/sections/packet_checks/submit")
    assert empty.status_code == 409 and empty.json()["detail"]["code"] == "INVALID_TRANSITION"
    world["db"].execute("UPDATE production.shift_reports SET status = 'validated' WHERE id = %s", (shift_id,))
    locked = client.post(f"/production/shift-reports/{shift_id}/sections/silo/nothing-to-report")
    assert locked.status_code == 409 and locked.json()["detail"]["code"] == "NOT_EDITABLE"


def test_submit_nothing_to_report_and_revisions_round_trip(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy", "production.shift.edit.silo")
    shift_id = _open(world)
    client = world["client"]
    client.put(f"/production/shift-reports/{shift_id}/sections/energy", json={"payload": {"energy": {"fuel_quantity": 5}}})
    assert client.post(f"/production/shift-reports/{shift_id}/sections/energy/submit").json()["status"] == "submitted"
    assert client.post(f"/production/shift-reports/{shift_id}/sections/silo/nothing-to-report").json()["status"] == "nothing_to_report"
    revisions = client.get(f"/production/shift-reports/{shift_id}/sections/energy/revisions").json()
    assert [r["revision"] for r in revisions] == [1]
    listed = client.get("/production/shift-reports", params={"report_date": DAY}).json()
    assert [s["id"] for s in listed] == [shift_id]
    assert {s["key"]: s["status"] for s in listed[0]["sections"]}["energy"] == "submitted"


def test_the_header_is_editable_with_any_section_right(world):
    world["grant"]("production.shift.edit.stops")
    shift_id = _open(world)
    response = world["client"].patch(
        f"/production/shift-reports/{shift_id}/header", json={"team": "B", "machiniste": "D. Samaké"}
    )
    assert response.status_code == 200
    assert (response.json()["team"], response.json()["machiniste"]) == ("B", "D. Samaké")


# ---- validating, rejecting, reversing --------------------------------------


def test_validating_and_rejecting_need_the_validate_right(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    client = world["client"]
    assert client.post(f"/production/shift-reports/{shift_id}/validate", json={}).status_code == 403
    assert client.post(f"/production/shift-reports/{shift_id}/reject", json={"sections": ["energy"], "reason": "x"}).status_code == 403

    world["grant"]("production.shift.validate")
    # Now allowed in, the shift is simply not submitted yet: a 409, not a 403.
    early = client.post(f"/production/shift-reports/{shift_id}/validate", json={})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "INVALID_TRANSITION"
    no_reason = client.post(f"/production/shift-reports/{shift_id}/reject", json={"sections": ["energy"], "reason": " "})
    assert no_reason.status_code == 400 and no_reason.json()["detail"]["code"] == "MISSING_REASON"


def test_reversing_needs_the_admin_right_not_just_the_validate_right(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy", "production.shift.validate")
    shift_id = _open(world)
    client = world["client"]
    assert client.post(f"/production/shift-reports/{shift_id}/reverse", json={"reason": "x"}).status_code == 403
    world["grant"]("production.admin_reports")
    response = client.post(f"/production/shift-reports/{shift_id}/reverse", json={"reason": "x"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "INVALID_TRANSITION"


def test_an_unknown_shift_is_a_404_for_every_validation_action(world):
    world["grant"]("production.shift.validate", "production.admin_reports")
    client = world["client"]
    for path, body in (("validate", {}), ("reject", {"sections": ["energy"], "reason": "x"}), ("reverse", {"reason": "x"})):
        response = client.post(f"/production/shift-reports/nope/{path}", json=body)
        assert response.status_code == 404, (path, response.text)


def test_a_validator_edit_needs_the_validate_right_and_a_reason(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    client = world["client"]
    client.put(f"/production/shift-reports/{shift_id}/sections/energy", json={"payload": {"energy": {"fuel_quantity": 5}}})
    client.post(f"/production/shift-reports/{shift_id}/sections/energy/submit")
    url = f"/production/shift-reports/{shift_id}/sections/energy/validator-edit"
    fix = {"payload": {"energy": {"fuel_quantity": 50}}, "reason": "decimal slipped"}

    # A section right is not enough: the edit is a reviewer's act.
    assert client.put(url, json=fix).status_code == 403

    world["grant"]("production.shift.validate")
    early = client.put(url, json=fix)  # the shift is still being filled in
    assert early.status_code == 409 and early.json()["detail"]["code"] == "INVALID_TRANSITION"

    world["db"].execute("UPDATE production.shift_reports SET status = 'submitted' WHERE id = %s", (shift_id,))
    no_reason = client.put(url, json={**fix, "reason": "  "})
    assert no_reason.status_code == 400 and no_reason.json()["detail"]["code"] == "MISSING_REASON"
    unknown = client.put(f"/production/shift-reports/{shift_id}/sections/reels/validator-edit", json=fix)
    assert unknown.status_code == 400 and unknown.json()["detail"]["code"] == "INVALID_SECTION"  # as reject_sections

    edited = client.put(url, json=fix)
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "submitted"
    revisions = client.get(f"/production/shift-reports/{shift_id}/sections/energy/revisions").json()
    assert revisions[0]["edited_by_validator"] is True and revisions[0]["reason"] == "decimal slipped"
    assert revisions[1]["edited_by_validator"] is False


# ---- deleting ----------------------------------------------------------


def test_delete_needs_its_own_permission_and_only_works_before_submission(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    client = world["client"]

    forbidden = client.delete(f"/production/shift-reports/{shift_id}")
    assert forbidden.status_code == 403

    world["grant"]("production.shift.delete")
    world["db"].execute("UPDATE production.shift_reports SET status = 'submitted' WHERE id = %s", (shift_id,))
    blocked = client.delete(f"/production/shift-reports/{shift_id}")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "DELETE_NOT_ALLOWED"

    world["db"].execute("UPDATE production.shift_reports SET status = 'open' WHERE id = %s", (shift_id,))
    ok = client.delete(f"/production/shift-reports/{shift_id}")
    assert ok.status_code == 200 and ok.json()["deleted"] is True
    assert client.get(f"/production/shift-reports/{shift_id}").status_code == 404


def test_deleting_an_unknown_shift_is_a_404(world):
    world["grant"]("production.shift.delete")
    response = world["client"].delete("/production/shift-reports/nope")
    assert response.status_code == 404

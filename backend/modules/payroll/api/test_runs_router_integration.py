"""Runs, payslips and inputs over HTTP: who may do what, four-eyes, statuses of refusals."""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.payroll.api import http  # noqa: E402
from modules.payroll.api.router import router  # noqa: E402
from modules.payroll.api.testing_support import (  # noqa: E402
    FakePresence, FakeSnapshots, WrappedConnection, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-runs-router-test"
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré")]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db, monkeypatch):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    wrapped = WrappedConnection(db)
    monkeypatch.setattr(http, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    for module in ("modules.payroll.api.run_service", "modules.payroll.api.input_service"):
        monkeypatch.setattr(f"{module}.PayrollSnapshotService", lambda connection: snapshots)
    monkeypatch.setattr("modules.payroll.api.run_service.PresenceService", lambda connection: presence)
    current = {"user": a}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=current["user"], session_token="t")

    def grant(user: str, *permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))

    return {"client": TestClient(app), "grant": grant, "a": a, "b": b, "current": current}


def _calculated_run(world) -> str:
    client = world["client"]
    created = client.post("/payroll/runs", json={"period": "2031-09-01", "run_type": "regular"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    calculated = client.post(f"/payroll/runs/{run_id}/calculate")
    assert calculated.status_code == 200 and calculated.json()["status"] == "calculated", calculated.text
    return run_id


def test_the_run_lifecycle_follows_rights_and_four_eyes(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    run_id = _calculated_run(world)
    client = world["client"]
    assert client.post(f"/payroll/runs/{run_id}/approve").status_code == 403
    world["grant"](world["a"], "payroll.approve_runs")
    same_user = client.post(f"/payroll/runs/{run_id}/approve")
    assert same_user.status_code == 409 and same_user.json()["detail"]["code"] == "SAME_USER_APPROVAL"
    world["grant"](world["b"], "payroll.view_runs", "payroll.approve_runs")
    world["current"]["user"] = world["b"]
    approved = client.post(f"/payroll/runs/{run_id}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert client.post(f"/payroll/runs/{run_id}/reverse", json={"reason": "x"}).status_code == 403


def test_reading_payslips_and_variance_needs_view_runs(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    run_id = _calculated_run(world)
    client = world["client"]
    payslips = client.get(f"/payroll/runs/{run_id}/payslips")
    assert payslips.status_code == 200 and payslips.json()[0]["employee_no"] == "M-001"
    payslip = client.get(f"/payroll/payslips/{payslips.json()[0]['id']}")
    assert payslip.status_code == 200 and payslip.json()["lines"]
    assert client.get(f"/payroll/runs/{run_id}/variance").json()["rows"][0]["change"] == "new"
    world["current"]["user"] = world["b"]
    assert client.get(f"/payroll/runs/{run_id}/payslips").status_code == 403


def test_editing_a_payslip_needs_admin_payslips(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    run_id = _calculated_run(world)
    client = world["client"]
    payslip_id = client.get(f"/payroll/runs/{run_id}/payslips").json()[0]["id"]
    assert client.patch(f"/payroll/payslips/{payslip_id}", json={"note": "checked"}).status_code == 403
    world["grant"](world["a"], "payroll.admin_payslips")
    edited = client.patch(f"/payroll/payslips/{payslip_id}", json={"note": "checked"})
    assert edited.status_code == 200 and edited.json()["note"] == "checked"


def test_the_employee_list_carries_no_salary(world):
    world["grant"](world["a"], "payroll.view_runs")
    rows = world["client"].get("/payroll/employees", params={"period": "2031-09-01"}).json()
    assert rows == [{"employee_id": "E1", "employee_no": "M-001", "full_name": "Awa Traoré", "department_id": "dept-a", "termination_date": None}]


def test_inputs_need_manage_inputs_and_a_bad_input_is_422(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    client = world["client"]
    run_id = client.post("/payroll/runs", json={"period": "2031-09-01", "run_type": "regular"}).json()["id"]
    body = {"employee_id": "E1", "component_code": "BONUS", "amount": 25000}
    assert client.post(f"/payroll/runs/{run_id}/inputs", json=body).status_code == 403
    world["grant"](world["a"], "payroll.manage_inputs")
    assert client.post(f"/payroll/runs/{run_id}/inputs", json=body).status_code == 201
    refused = client.post(f"/payroll/runs/{run_id}/inputs", json={**body, "component_code": "BASE"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "INPUT_INVALID"
    assert [item["code"] for item in client.get(f"/payroll/runs/{run_id}/input-components").json()] == ["HOUSING", "TRANSPORT", "MEAL", "BONUS", "CANTEEN"]

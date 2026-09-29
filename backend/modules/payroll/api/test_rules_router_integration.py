"""The rules endpoints over HTTP: rights per action, and refusal codes mapped to statuses.

A throwaway FastAPI app carries the payroll router; the session is overridden and every
connection is the `db` fixture's rolled-back one (commit/rollback are no-ops).
"""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.payroll.api import http  # noqa: E402
from modules.payroll.api.router import router  # noqa: E402
from modules.payroll.api.testing_support import make_user, store_rule_set  # noqa: E402

TENANT = "payroll-rules-router-test"
BODY = {"country": "ZZ", "name": "Router test", "valid_from": "2031-01-01",
        "working_days_per_month": 20, "working_hours_per_month": 160}


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
    user = make_user(db, TENANT)
    wrapped = _Connection(db)
    monkeypatch.setattr(http, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))

    return {"client": TestClient(app), "grant": grant, "db": db, "user": user}


def test_reading_the_rules_needs_view_rules(world):
    assert world["client"].get("/payroll/rule-sets").status_code == 403
    world["grant"]("payroll.view_rules")
    assert world["client"].get("/payroll/rule-sets").status_code == 200


def test_creating_and_confirming_need_their_own_rights(world):
    client = world["client"]
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    created = client.post("/payroll/rule-sets", json=BODY)
    assert created.status_code == 201, created.text
    rule_set_id = created.json()["id"]
    row = client.post(f"/payroll/rule-sets/{rule_set_id}/overtime_rates", json={"band_code": "day", "multiplier": 1.5})
    assert row.status_code == 201, row.text
    assert client.post(f"/payroll/rule-sets/{rule_set_id}/confirm").status_code == 403
    world["grant"]("payroll.confirm_rules")
    refused = client.post(f"/payroll/rule-sets/{rule_set_id}/confirm")
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "RULESET_INCOMPLETE" and refused.json()["detail"]["message_fr"]


def test_a_confirmed_rule_set_answers_409(world):
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    rule_set_id = store_rule_set(world["db"], tenant_id=TENANT, actor_id=world["user"], valid_from=datetime.date(2031, 1, 1))
    response = world["client"].patch(f"/payroll/rule-sets/{rule_set_id}", json={"name": "x"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "RULESET_LOCKED"


def test_a_duplicate_start_answers_409_and_an_unknown_table_404(world):
    client = world["client"]
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    first = client.post("/payroll/rule-sets", json=BODY)
    assert client.post("/payroll/rule-sets", json=BODY).status_code == 409
    assert client.get(f"/payroll/rule-sets/{first.json()['id']}/nonsense").status_code == 404


def test_settings_round_trip(world):
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    saved = world["client"].put("/payroll/settings", json={"country": "zz", "employer_inps_no": "123"})
    assert saved.status_code == 200 and saved.json()["country"] == "ZZ"
    assert world["client"].get("/payroll/settings").json()["employer_inps_no"] == "123"

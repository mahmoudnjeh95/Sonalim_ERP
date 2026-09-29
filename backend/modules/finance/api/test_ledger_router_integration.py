"""The ledger over HTTP: who may do what, status codes, and JSON shapes (money as integers).

A throwaway FastAPI app carries just the ledger router; its connection is the fixture's
rolled-back one wrapped in NoCommitConnection."""
from __future__ import annotations

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.finance.api import ledger_router as router_module  # noqa: E402
from modules.finance.testing_support import NoCommitConnection  # noqa: E402

PATENTE = {
    "entry_date": "2030-02-14",
    "label": "Patente 2030",
    "lines": [{"account_code": "641", "debit": 150000}, {"account_code": "521", "credit": 150000}],
}


@pytest.fixture
def api(ledger, monkeypatch) -> dict:
    wrapped = NoCommitConnection(ledger["db"])
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(
        tenant_id=ledger["tenant"], user_id=ledger["actor"], session_token="t"
    )

    def grant(*permissions: str) -> None:
        for permission in permissions:
            ledger["db"].execute(
                "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (ledger["actor"], permission)
            )

    return {"client": TestClient(app), "grant": grant}


def test_reading_the_ledger_needs_view_ledger(api):
    assert api["client"].get("/finance/accounts").status_code == 403
    api["grant"]("finance.view_ledger")
    response = api["client"].get("/finance/accounts")
    assert response.status_code == 200
    assert {
        "code": "422", "name": "Personnel, rémunérations dues", "class_no": 4,
        "account_type": "liability", "is_postable": True, "parent_code": "42",
    } in response.json()


def test_editing_an_account_needs_admin_accounts(api):
    api["grant"]("finance.manage_accounts")
    created = api["client"].post(
        "/finance/accounts", json={"code": "5211", "name": "BDM-SA", "account_type": "asset", "parent_code": "52"}
    )
    assert created.status_code == 201, created.text
    assert api["client"].patch("/finance/accounts/5211", json={"name": "BDM"}).status_code == 403
    api["grant"]("finance.admin_accounts")
    assert api["client"].patch("/finance/accounts/5211", json={"name": "BDM"}).json()["name"] == "BDM"


def test_a_manual_entry_goes_from_draft_to_posted_and_then_stays_frozen(api):
    api["grant"]("finance.view_ledger", "finance.manage_entries")
    created = api["client"].post("/finance/entries", json=PATENTE)
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["journal_code"] == "OD" and entry["status"] == "draft"
    assert entry["total_debit"] == 150000 and entry["lines"][0]["account_name"] == "Impôts et taxes directs"
    posted = api["client"].post(f"/finance/entries/{entry['id']}/post", json={})
    assert posted.status_code == 200, posted.text
    assert posted.json()["number"] == "OD-2030-000001"
    api["grant"]("finance.admin_entries")
    refused = api["client"].patch(f"/finance/entries/{entry['id']}", json={"label": "x"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "ENTRY_POSTED" and refused.json()["detail"]["message_fr"]
    listed = api["client"].get(
        "/finance/entries", params={"date_from": "2030-02-01", "date_to": "2030-02-28", "journal_code": "OD"}
    )
    assert [row["number"] for row in listed.json()] == ["OD-2030-000001"]


def test_posting_into_a_closed_period_is_a_409_in_both_languages(api):
    api["grant"]("finance.manage_entries", "finance.admin_periods")
    closed = api["client"].post("/finance/periods/2030-02-01/close")
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    refused = api["client"].post("/finance/entries", json=PATENTE)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "PERIOD_CLOSED" and "clôturée" in detail["message_fr"]


def test_the_run_page_reads_postings_with_payroll_view_runs_alone(api):
    assert api["client"].get("/finance/ledger/sources/payroll/RUN-X").status_code == 403
    api["grant"]("payroll.view_runs")
    response = api["client"].get("/finance/ledger/sources/payroll/RUN-X")
    assert response.status_code == 200
    assert response.json() == {"entries": [], "failures": []}


def test_reports_return_whole_francs_and_refuse_a_backwards_range(api):
    api["grant"]("finance.view_ledger", "finance.manage_entries")
    entry = api["client"].post("/finance/entries", json=PATENTE).json()
    api["client"].post(f"/finance/entries/{entry['id']}/post", json={})
    trial = api["client"].get("/finance/reports/trial-balance", params={"date_from": "2030-02-01", "date_to": "2030-02-28"})
    totals = trial.json()["totals"]
    assert totals["period_debit"] == 150000 and isinstance(totals["period_debit"], int)
    general = api["client"].get(
        "/finance/reports/general-ledger", params={"account_code": "521", "date_from": "2030-02-01", "date_to": "2030-02-28"}
    )
    assert general.json()["closing_balance"] == -150000
    balances = api["client"].get("/finance/reports/balances", params={"as_of": "2030-02-28"}).json()
    assert {row["account_code"] for row in balances} >= {"421", "422", "431", "433", "447"}
    backwards = api["client"].get("/finance/reports/trial-balance", params={"date_from": "2030-03-01", "date_to": "2030-02-01"})
    assert backwards.status_code == 400 and backwards.json()["detail"]["message_fr"]

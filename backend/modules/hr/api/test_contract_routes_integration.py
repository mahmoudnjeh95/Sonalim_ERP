"""Contracts over HTTP: pay and allowances are hidden without hr.view_sensitive and never written blind."""
from __future__ import annotations


def _employee(hr_api) -> str:
    hr_api.grant("hr.manage_employees")
    body = {"employee_no": "C-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": "2024-01-01"}
    return hr_api.client.post("/hr/employees", json=body).json()["id"]


def _contract_body(employee_id: str, **extra) -> dict:
    return {
        "employee_id": employee_id,
        "contract_type": "cdi",
        "start_date": "2024-01-01",
        "base_salary": 150000,
        "components": [{"component_code": "TRANSPORT", "amount": 15000}],
        **extra,
    }


def _revoke_sensitive(hr_api) -> None:
    hr_api.db.execute("DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,))


def test_creating_a_contract_needs_hr_view_sensitive(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts")
    assert hr_api.client.post("/hr/contracts", json=_contract_body(employee_id)).status_code == 403
    hr_api.grant("hr.view_sensitive")
    created = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id))
    assert created.status_code == 201
    assert (created.json()["base_salary"], created.json()["currency"], created.json()["sensitive_hidden"]) == (150000, "XOF", False)


def test_pay_and_allowances_are_hidden_from_a_reader_without_the_right(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive", "hr.view_contracts")
    hr_api.client.post("/hr/contracts", json=_contract_body(employee_id))
    _revoke_sensitive(hr_api)
    [contract] = hr_api.client.get(f"/hr/contracts?employee_id={employee_id}").json()
    assert contract["base_salary"] is None
    assert contract["components"] == [{"component_code": "TRANSPORT", "amount": None, "rate": None}]
    assert contract["sensitive_hidden"] is True


def test_an_overlapping_contract_is_a_409(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive")
    hr_api.client.post("/hr/contracts", json=_contract_body(employee_id))
    refused = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id, start_date="2026-01-01"))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "CONTRACT_OVERLAP"


def test_an_admin_without_the_right_can_fix_hours_but_not_pay(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive", "hr.admin_contracts")
    contract_id = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id)).json()["id"]
    _revoke_sensitive(hr_api)
    assert hr_api.client.patch(f"/hr/contracts/{contract_id}", json={"base_salary": 1}).status_code == 403
    assert hr_api.client.patch(f"/hr/contracts/{contract_id}", json={"components": []}).status_code == 403
    edited = hr_api.client.patch(f"/hr/contracts/{contract_id}", json={"weekly_hours": 48})
    assert edited.status_code == 200 and edited.json()["weekly_hours"] == 48 and edited.json()["base_salary"] is None
    assert hr_api.db.execute("SELECT base_salary FROM hr.contracts WHERE id = %s", (contract_id,)).fetchone()[0] == 150000


def test_amending_and_ending_go_through_manage_contracts(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive")
    contract_id = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id)).json()["id"]
    amended = hr_api.client.post(f"/hr/contracts/{contract_id}/amend", json={"effective_date": "2025-01-01", "base_salary": 175000})
    assert amended.status_code == 201 and amended.json()["amends_contract_id"] == contract_id
    ended = hr_api.client.post(f"/hr/contracts/{amended.json()['id']}/end", json={"end_date": "2025-12-31", "end_reason": "resignation"})
    assert ended.status_code == 200 and ended.json()["status"] == "terminated"

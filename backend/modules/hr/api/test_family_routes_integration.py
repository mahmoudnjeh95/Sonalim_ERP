"""Dependants and payment arrangements over HTTP."""
from __future__ import annotations

BANK = {"method": "bank", "share_percent": 100, "is_primary": True, "bank_name": "BDM-SA", "account_no": "ML-1"}
CASH = {"method": "cash", "share_percent": 100, "is_primary": True}


def _employee(hr_api) -> str:
    hr_api.grant("hr.manage_employees", "hr.view_employees")
    body = {"employee_no": "R-001", "first_name": "Moussa", "last_name": "Keïta", "hire_date": "2015-01-05"}
    return hr_api.client.post("/hr/employees", json=body).json()["id"]


def test_bank_details_need_hr_view_sensitive_to_write_and_to_read(hr_api):
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    body = {"valid_from": "2025-01-01", "methods": [BANK]}
    assert hr_api.client.put(url, json=body).status_code == 403
    hr_api.grant("hr.view_sensitive")
    saved = hr_api.client.put(url, json=body)
    assert saved.status_code == 200 and saved.json()[0]["methods"][0]["account_no"] == "ML-1"
    hr_api.db.execute("DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,))
    method = hr_api.client.get(url).json()[0]["methods"][0]
    assert (method["account_no"], method["bank_name"], method["sensitive_hidden"]) == (None, "BDM-SA", True)


def test_a_cash_arrangement_needs_no_sensitive_right_but_replacing_one_needs_admin(hr_api):
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    body = {"valid_from": "2025-01-01", "methods": [CASH]}
    assert hr_api.client.put(url, json=body).status_code == 200
    assert hr_api.client.put(url, json=body).status_code == 403
    hr_api.grant("hr.admin_employees")
    assert hr_api.client.put(url, json=body).status_code == 200


def test_a_bad_split_is_a_422_in_french_too(hr_api):
    employee_id = _employee(hr_api)
    body = {"valid_from": "2025-01-01", "methods": [{**CASH, "share_percent": 90}]}
    refused = hr_api.client.put(f"/hr/employees/{employee_id}/payment-methods", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "PAYOUT_SPLIT_INVALID"
    assert refused.json()["detail"]["message_fr"] == "les parts totalisent 90 %, pas 100 %"


def test_replacing_a_set_that_holds_numbers_needs_view_sensitive_even_with_no_number_in_the_new_body(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_sensitive")
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    assert hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": [BANK]}).status_code == 200
    hr_api.db.execute("DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,))
    hr_api.grant("hr.admin_employees")
    refused = hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": [CASH]})
    assert refused.status_code == 403
    assert refused.json()["detail"]["message_fr"]
    stored = hr_api.db.execute("SELECT method, account_no FROM hr.payment_methods WHERE employee_id = %s", (employee_id,)).fetchone()
    assert stored == ("bank", "ML-1")
    hr_api.grant("hr.view_sensitive")
    assert hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": [CASH]}).status_code == 200


def test_removing_a_set_that_holds_numbers_needs_view_sensitive(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_sensitive")
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    assert hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": [BANK]}).status_code == 200
    hr_api.db.execute("DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,))
    hr_api.grant("hr.admin_employees")
    refused = hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": []})
    assert refused.status_code == 403
    stored = hr_api.db.execute("SELECT 1 FROM hr.payment_methods WHERE employee_id = %s", (employee_id,)).fetchone()
    assert stored is not None
    hr_api.grant("hr.view_sensitive")
    assert hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": []}).status_code == 200


def test_replacing_a_cash_only_set_needs_no_view_sensitive(hr_api):
    hr_api.grant("hr.manage_employees", "hr.admin_employees")
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    assert hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": [CASH]}).status_code == 200
    assert hr_api.client.put(url, json={"valid_from": "2025-01-01", "methods": [CASH]}).status_code == 200


def test_dependants_are_added_with_manage_and_corrected_with_admin(hr_api):
    employee_id = _employee(hr_api)
    created = hr_api.client.post(
        f"/hr/employees/{employee_id}/dependants",
        json={"kind": "child", "name": "Issa", "valid_from": "2019-02-01", "dependent_for_tax": True},
    )
    assert created.status_code == 201
    assert hr_api.client.patch(f"/hr/dependants/{created.json()['id']}", json={"name": "Issa K."}).status_code == 403
    hr_api.grant("hr.admin_employees")
    assert hr_api.client.patch(f"/hr/dependants/{created.json()['id']}", json={"name": "Issa K."}).json()["name"] == "Issa K."

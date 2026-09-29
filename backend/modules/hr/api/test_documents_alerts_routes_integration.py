"""Documents, settings and alerts over HTTP."""
from __future__ import annotations


def test_settings_are_read_with_view_employees_and_saved_with_admin_employees(hr_api):
    hr_api.grant("hr.view_employees")
    assert hr_api.client.get("/hr/settings").json() == {
        "contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None,
    }
    body = {"contract_expiry_horizon_days": 30, "trial_end_horizon_days": 15, "document_expiry_horizon_days": None}
    assert hr_api.client.put("/hr/settings", json=body).status_code == 403
    hr_api.grant("hr.admin_employees")
    assert hr_api.client.put("/hr/settings", json=body).json()["trial_end_horizon_days"] == 15
    assert hr_api.client.get("/hr/alerts/expiries").json()["contracts_ending"] == []


def test_documents_are_added_with_manage_and_corrected_with_admin(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees")
    body = {"employee_no": "D-1", "first_name": "Rokia", "last_name": "Touré", "hire_date": "2024-01-01"}
    employee_id = hr_api.client.post("/hr/employees", json=body).json()["id"]
    created = hr_api.client.post(f"/hr/employees/{employee_id}/documents", json={"kind": "passport", "expires_on": "2030-01-01"})
    assert created.status_code == 201
    assert [d["kind"] for d in hr_api.client.get(f"/hr/employees/{employee_id}/documents").json()] == ["passport"]
    assert hr_api.client.patch(f"/hr/documents/{created.json()['id']}", json={"title": "Passeport"}).status_code == 403

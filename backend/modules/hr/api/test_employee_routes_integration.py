"""The employee file over HTTP: hr.view_sensitive hides NINA / INPS / AMO and guards writing them."""
from __future__ import annotations


def _create(hr_api, **extra):
    body = {"employee_no": "R-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": "2024-03-01", **extra}
    return hr_api.client.post("/hr/employees", json=body)


def _revoke_sensitive(hr_api) -> None:
    hr_api.db.execute(
        "DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,)
    )


def test_the_social_numbers_are_hidden_from_a_reader_without_hr_view_sensitive(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees", "hr.view_sensitive")
    employee_id = _create(hr_api, national_id="NINA-123", inps_no="INPS-9").json()["id"]
    _revoke_sensitive(hr_api)
    shown = hr_api.client.get(f"/hr/employees/{employee_id}").json()
    assert (shown["national_id"], shown["inps_no"], shown["sensitive_hidden"]) == (None, None, True)
    assert shown["first_name"] == "Awa"


def test_a_reader_with_hr_view_sensitive_sees_them(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees", "hr.view_sensitive")
    employee_id = _create(hr_api, national_id="NINA-123").json()["id"]
    shown = hr_api.client.get(f"/hr/employees/{employee_id}").json()
    assert (shown["national_id"], shown["sensitive_hidden"]) == ("NINA-123", False)


def test_the_list_never_carries_the_sensitive_fields(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees", "hr.view_sensitive")
    _create(hr_api, national_id="NINA-123")
    [row] = hr_api.client.get("/hr/employees").json()
    assert "national_id" not in row and "inps_no" not in row and "amo_no" not in row


def test_setting_a_social_number_without_the_right_is_refused(hr_api):
    hr_api.grant("hr.manage_employees")
    refused = _create(hr_api, national_id="NINA-123")
    assert refused.status_code == 403 and "hr.view_sensitive" in refused.json()["detail"]["message"]
    assert _create(hr_api).status_code == 201  # the same file without it goes through


def test_an_edit_without_the_right_cannot_touch_hidden_fields_but_edits_the_rest(hr_api):
    hr_api.grant("hr.manage_employees", "hr.admin_employees", "hr.view_sensitive")
    employee_id = _create(hr_api, national_id="NINA-123").json()["id"]
    _revoke_sensitive(hr_api)
    assert hr_api.client.patch(f"/hr/employees/{employee_id}", json={"national_id": None}).status_code == 403
    edited = hr_api.client.patch(f"/hr/employees/{employee_id}", json={"phone": "76 00 00 00"})
    assert edited.status_code == 200
    assert (edited.json()["phone"], edited.json()["national_id"]) == ("76 00 00 00", None)
    stored = hr_api.db.execute("SELECT national_id FROM hr.employees WHERE id = %s", (employee_id,)).fetchone()[0]
    assert stored == "NINA-123"


def test_an_edit_needs_admin_employees(hr_api):
    hr_api.grant("hr.manage_employees")
    employee_id = _create(hr_api).json()["id"]
    assert hr_api.client.patch(f"/hr/employees/{employee_id}", json={"phone": "1"}).status_code == 403


def test_a_taken_badge_is_a_409_and_an_unknown_file_a_404(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees")
    assert _create(hr_api, badge_no="B-7").status_code == 201
    refused = _create(hr_api, employee_no="R-002", badge_no="B-7")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BADGE_TAKEN"
    assert hr_api.client.get("/hr/employees/nobody").status_code == 404

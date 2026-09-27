"""Organisation routes: reading, creating and editing need three different rights."""
from __future__ import annotations


def test_a_position_edit_needs_admin_positions(hr_api):
    hr_api.grant("hr.view_positions", "hr.manage_positions")
    created = hr_api.client.post("/hr/positions", json={"code": "OP", "title": "Opérateur"})
    assert created.status_code == 201
    position_id = created.json()["id"]
    assert hr_api.client.patch(f"/hr/positions/{position_id}", json={"title": "Opératrice"}).status_code == 403
    hr_api.grant("hr.admin_positions")
    edited = hr_api.client.patch(f"/hr/positions/{position_id}", json={"title": "Opératrice"})
    assert edited.status_code == 200 and edited.json()["title"] == "Opératrice"


def test_grades_share_the_position_rights(hr_api):
    hr_api.grant("hr.view_positions")
    assert hr_api.client.get("/hr/grades").status_code == 200
    body = {"code": "OS1", "category": "3", "echelon": "A", "base_salary": 75000, "valid_from": "2026-01-01"}
    assert hr_api.client.post("/hr/grades", json=body).status_code == 403
    hr_api.grant("hr.manage_positions")
    created = hr_api.client.post("/hr/grades", json=body)
    assert created.status_code == 201 and created.json()["base_salary"] == 75000


def test_a_duplicate_department_code_is_a_409_in_french_too(hr_api):
    hr_api.grant("hr.manage_departments")
    assert hr_api.client.post("/hr/departments", json={"code": "PROD", "name": "Production"}).status_code == 201
    refused = hr_api.client.post("/hr/departments", json={"code": "PROD", "name": "Production"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["message_fr"] == "ce code de département existe déjà"


def test_a_department_edit_needs_admin_departments(hr_api):
    hr_api.grant("hr.manage_departments")
    department_id = hr_api.client.post("/hr/departments", json={"code": "PROD", "name": "Production"}).json()["id"]
    assert hr_api.client.patch(f"/hr/departments/{department_id}", json={"name": "Prod"}).status_code == 403
    hr_api.grant("hr.admin_departments")
    assert hr_api.client.patch(f"/hr/departments/{department_id}", json={"name": "Prod"}).json()["name"] == "Prod"

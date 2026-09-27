"""The hr router over HTTP, inside the test transaction (see conftest.hr_api)."""
from __future__ import annotations

from ulid import ULID


def test_a_caller_without_the_route_permission_is_refused(hr_api):
    response = hr_api.client.get("/hr/departments")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


def test_a_caller_with_it_reads_through_the_test_transaction(hr_api):
    hr_api.grant("hr.view_departments")
    hr_api.db.execute(
        "INSERT INTO hr.departments (id, tenant_id, code, name) VALUES (%s, %s, 'PROD', 'Production')",
        (str(ULID()), hr_api.tenant_id),
    )
    assert [row["code"] for row in hr_api.client.get("/hr/departments").json()] == ["PROD"]

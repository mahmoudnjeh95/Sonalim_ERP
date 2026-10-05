"""`/hr/me/profile`: the file of whoever is signed in, with no HR permission needed.

Reading your own file is not privileged the way reading a colleague's is, so the route is
gated by require_session alone -- and because it is yours, it is unmasked: the national,
INPS and AMO numbers on it are the caller's own, already on their payslip.
"""
from __future__ import annotations

from ulid import ULID


def _employee(hr_api, *, user_id: str | None, employee_no: str = "R-001", **extra) -> str:
    employee_id = str(ULID())
    hr_api.db.execute(
        """
        INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, user_id,
                                  job_title, national_id, address)
        VALUES (%s, %s, %s, %s, %s, DATE '2024-03-01', %s, %s, %s, %s)
        """,
        (
            employee_id,
            hr_api.tenant_id,
            employee_no,
            extra.get("first_name", "Awa"),
            extra.get("last_name", "Traoré"),
            user_id,
            extra.get("job_title", "Opératrice"),
            extra.get("national_id", "NINA-123"),
            extra.get("address", "Bamako"),
        ),
    )
    return employee_id


def test_a_user_reads_their_own_file_without_any_hr_permission(hr_api):
    _employee(hr_api, user_id=hr_api.user_id)
    profile = hr_api.client.get("/hr/me/profile")
    assert profile.status_code == 200
    body = profile.json()
    assert (body["first_name"], body["last_name"], body["job_title"]) == ("Awa", "Traoré", "Opératrice")
    assert body["full_name"] == "Awa Traoré"


def test_your_own_social_numbers_are_not_masked(hr_api):
    """They are already on the caller's own payslip -- hiding them from themself helps nobody."""
    _employee(hr_api, user_id=hr_api.user_id)
    assert hr_api.client.get("/hr/me/profile").json()["national_id"] == "NINA-123"


def test_a_user_with_no_employee_file_gets_404(hr_api):
    assert hr_api.client.get("/hr/me/profile").status_code == 404


def test_another_persons_file_is_never_returned(hr_api):
    other_user = str(ULID())
    hr_api.db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (other_user, hr_api.tenant_id, f"{other_user}@test.local"),
    )
    _employee(hr_api, user_id=other_user, employee_no="R-002", first_name="Moussa")
    assert hr_api.client.get("/hr/me/profile").status_code == 404

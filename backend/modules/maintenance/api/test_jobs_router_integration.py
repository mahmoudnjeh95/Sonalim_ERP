"""The job endpoints over HTTP: rights, error codes and shapes, and the multipart check entry.

The session is overridden and every connection the router or the permission check opens is
the `db` fixture's rolled-back one (commit and rollback made no-ops), so nothing reaches the
development data.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.domain.result import Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.hr.api.employee_service import EmployeeService  # noqa: E402
from modules.hr.domain.employee import EmployeeFile  # noqa: E402
from modules.maintenance.api import jobs_router  # noqa: E402
from modules.maintenance.api import router as router_module  # noqa: E402
from modules.maintenance.api.equipment_service import EquipmentService  # noqa: E402
from modules.maintenance.api.map_service import MapService  # noqa: E402

TENANT = "integration-test-jobs-router"
TODAY = datetime.date.today()
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50


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


def _user(db, full_name, *permissions):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, TENANT, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


@pytest.fixture
def api(db, monkeypatch):
    sup = _user(db, "Sara Superviseur", "maintenance.view_jobs", "maintenance.plan_jobs", "maintenance.execute_jobs")
    chef = _user(db, "Chef Keita", "maintenance.view_jobs", "maintenance.execute_jobs")
    other = _user(db, "Autre Chef", "maintenance.view_jobs", "maintenance.execute_jobs")
    nobody = _user(db, "Sans Droit")

    machine = EquipmentService(db).create_equipment(
        tenant_id=TENANT, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    maps = MapService(db)
    view = maps.create_view(
        tenant_id=TENANT, actor_id=sup, equipment_id=machine, label="Face", image=JPEG_BYTES, mime="image/jpeg"
    ).value
    point = maps.add_checkpoint(
        tenant_id=TENANT, actor_id=sup, view_id=view["id"], x_pct=10, y_pct=20, label="Joint", action="inspect", requires_photo=True
    ).value
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT,
        actor_id=sup,
        employee=EmployeeFile(employee_no=f"E-{ULID()}", first_name="Awa", last_name="Diarra", hire_date=datetime.date(2024, 1, 1)),
    )
    assert isinstance(employee, Ok), employee

    wrapped = _Connection(db)
    monkeypatch.setattr(jobs_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)

    current = {"user": sup}
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(
        tenant_id=TENANT, user_id=current["user"], session_token="t"
    )

    def acting_as(user_id: str) -> None:
        current["user"] = user_id

    return SimpleNamespace(
        client=TestClient(app), acting_as=acting_as, sup=sup, chef=chef, other=other, nobody=nobody,
        machine=machine, point=point["id"], employee=employee.value["id"],
    )


def _new_job(api, **overrides) -> dict:
    api.acting_as(api.sup)
    body = {
        "equipment_id": api.machine,
        "title": "Contrôle du joint",
        "description": "Fuite signalée",
        "priority": "urgent",
        "due_date": TODAY.isoformat(),
        "stops_machine": True,
        "checkpoint_ids": [api.point],
        "tasks": [{"label": "Nettoyer la trémie", "action": "clean"}],
        "chef_user_id": api.chef,
    }
    body.update(overrides)
    response = api.client.post("/maintenance/jobs", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_job_routes_need_their_permission(api):
    job = _new_job(api)

    api.acting_as(api.nobody)
    assert api.client.get("/maintenance/jobs").status_code == 403
    assert api.client.get(f"/maintenance/jobs/{job['id']}").status_code == 403

    # an executor can read and run jobs, but not plan, review, close or cancel them
    api.acting_as(api.chef)
    assert api.client.get(f"/maintenance/jobs/{job['id']}").status_code == 200
    refused = [
        api.client.post("/maintenance/jobs", json={}),
        api.client.post(f"/maintenance/jobs/{job['id']}/assign", json={"chef_user_id": api.chef}),
        api.client.post(f"/maintenance/jobs/{job['id']}/review", json={"verdicts": []}),
        api.client.post(f"/maintenance/jobs/{job['id']}/close"),
        api.client.post(f"/maintenance/jobs/{job['id']}/cancel", json={"reason": "non"}),
    ]
    assert [r.status_code for r in refused] == [403] * 5
    assert refused[0].json()["detail"]["code"] == "FORBIDDEN"


def test_a_job_runs_from_creation_to_closure_over_http(api):
    job = _new_job(api)
    assert (job["number"], job["status"], job["kind"], job["priority"]) == (f"MT-{TODAY.year}-0001", "assigned", "corrective", "urgent")
    assert (job["equipment_code"], job["equipment_name"], job["chef_name"]) == ("PRESSE-1", "Presse 1", "Chef Keita")
    assert (job["description"], job["created_by_name"], job["part_requests"]) == ("Fuite signalée", "Sara Superviseur", [])
    point, task = job["checks"]
    base = f"/maintenance/jobs/{job['id']}"

    api.acting_as(api.chef)
    delegated = api.client.post(f"{base}/delegate", json={"assignments": [{"check_id": point["id"], "employee_id": api.employee}]})
    assert delegated.status_code == 200, delegated.text
    assert delegated.json()["checks"][0]["assignee_name"] == "Awa Diarra"

    # the timer's stamps, as the browser sends them, with the photo the point asks for
    finished = datetime.datetime.now(datetime.timezone.utc)
    started = finished - datetime.timedelta(seconds=90)
    timed = api.client.post(
        f"{base}/checks/{point['id']}/entries",
        data={
            "performer_employee_id": api.employee,
            "outcome": "issue",
            "note": "joint fissuré",
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "finished_at": finished.isoformat().replace("+00:00", "Z"),
        },
        files={"photo": ("joint.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert timed.status_code == 201, timed.text
    assert timed.json()["status"] == "in_progress"
    entry = timed.json()["checks"][0]["entries"][0]
    assert (entry["duration_seconds"], entry["duration_source"], entry["outcome"], entry["note"], entry["has_photo"]) == (
        90, "timer", "issue", "joint fissuré", True,
    )

    photo = api.client.get(f"/maintenance/check-entries/{entry['id']}/photo")
    assert (photo.status_code, photo.content, photo.headers["content-type"]) == (200, JPEG_BYTES, "image/jpeg")

    # a duration typed afterwards, with no photo part at all
    manual = api.client.post(
        f"{base}/checks/{task['id']}/entries",
        data={"performer_employee_id": api.employee, "outcome": "ok", "manual_minutes": "7.5", "measured_value": "1.25"},
    )
    assert manual.status_code == 201, manual.text
    typed = manual.json()["checks"][1]["entries"][0]
    assert (typed["duration_seconds"], typed["duration_source"], typed["measured_value"]) == (450, "manual", 1.25)
    assert api.client.get(f"/maintenance/check-entries/{typed['id']}/photo").status_code == 404

    submitted = api.client.post(f"{base}/submit")
    assert (submitted.status_code, submitted.json()["status"]) == (200, "submitted")

    api.acting_as(api.sup)
    reviewed = api.client.post(
        f"{base}/review",
        json={"verdicts": [{"check_id": point["id"], "verdict": "accepted"}, {"check_id": task["id"], "verdict": "accepted", "reason": None}]},
    )
    assert (reviewed.status_code, reviewed.json()["status"]) == (200, "submitted")
    closed = api.client.post(f"{base}/close")
    assert (closed.status_code, closed.json()["status"]) == (200, "closed")
    assert closed.json()["minutes_spent"] == 9  # 90 s + 450 s

    listed = api.client.get("/maintenance/jobs", params={"status": "closed,cancelled", "equipment_id": api.machine})
    assert [j["id"] for j in listed.json()] == [job["id"]]
    assert api.client.get("/maintenance/jobs", params={"status": "planned"}).json() == []
    window = {"from": TODAY.isoformat(), "to": TODAY.isoformat()}
    assert [j["id"] for j in api.client.get("/maintenance/jobs", params=window).json()] == [job["id"]]
    assert api.client.get("/maintenance/jobs", params={"mine": "true"}).json() == []
    api.acting_as(api.chef)
    assert [j["id"] for j in api.client.get("/maintenance/jobs", params={"mine": "true"}).json()] == [job["id"]]


def test_refusals_carry_their_code_and_status(api):
    job = _new_job(api)
    base = f"/maintenance/jobs/{job['id']}"
    check_id = job["checks"][0]["id"]
    entry = {"performer_employee_id": api.employee, "outcome": "ok", "manual_minutes": "5"}

    # another executor is not this job's chef
    api.acting_as(api.other)
    for response in (
        api.client.post(f"{base}/checks/{check_id}/entries", data=entry),
        api.client.post(f"{base}/delegate", json={"assignments": [{"check_id": check_id, "employee_id": api.employee}]}),
        api.client.post(f"{base}/submit"),
    ):
        assert (response.status_code, response.json()["detail"]["code"]) == (403, "NOT_JOB_CHEF")
        assert response.json()["detail"]["message_fr"]

    # a supervisor may step in on any job
    api.acting_as(api.sup)
    assert api.client.post(f"{base}/checks/{check_id}/entries", data=entry).status_code == 201

    missing = [
        api.client.get("/maintenance/jobs/missing"),
        api.client.post("/maintenance/jobs/missing/submit"),
        api.client.post("/maintenance/jobs/missing/checks/x/entries", data=entry),
        api.client.post(f"{base}/checks/missing/entries", data=entry),
        api.client.post("/maintenance/jobs/missing/cancel", json={"reason": "x"}),
    ]
    assert [(r.status_code, r.json()["detail"]["code"]) for r in missing] == [(404, "NOT_FOUND")] * 5

    unprocessable = {
        "CHECKS_PENDING": api.client.post(f"{base}/submit"),
        "INVALID_TRANSITION": api.client.post(f"{base}/close"),
        "REASON_REQUIRED": api.client.post(f"{base}/cancel", json={"reason": " "}),
        "INVALID_TIMING": api.client.post(
            f"{base}/checks/{check_id}/entries", data={"performer_employee_id": api.employee, "outcome": "ok"}
        ),
        "UNKNOWN_EMPLOYEE": api.client.post(f"{base}/checks/{check_id}/entries", data={**entry, "performer_employee_id": "x"}),
        "NO_CHECKS": api.client.post(
            "/maintenance/jobs",
            json={"equipment_id": api.machine, "title": "Vide", "priority": "normal", "due_date": TODAY.isoformat(),
                  "stops_machine": False, "checkpoint_ids": [], "tasks": []},
        ),
    }
    assert {code: (r.status_code, r.json()["detail"]["code"]) for code, r in unprocessable.items()} == {
        code: (422, code) for code in unprocessable
    }

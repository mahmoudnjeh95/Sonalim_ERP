"""The history endpoints over HTTP: rights, cost visibility, error codes, the Excel journal."""
from __future__ import annotations

import datetime
import io
from types import SimpleNamespace

import pytest
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.domain.result import Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.hr.api.employee_service import EmployeeService  # noqa: E402
from modules.hr.domain.employee import EmployeeFile  # noqa: E402
from modules.maintenance.api import history_router  # noqa: E402
from modules.maintenance.api import router as router_module  # noqa: E402
from modules.maintenance.api.equipment_service import EquipmentService  # noqa: E402
from modules.maintenance.api.job_service import JobService  # noqa: E402

TENANT = "integration-test-history-router"
TODAY = datetime.date.today()


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
    valuer = _user(db, "Valérie Valorisation", "maintenance.view_jobs", "warehouse.view_valuation")
    nobody = _user(db, "Sans Droit")
    machine = EquipmentService(db).create_equipment(
        tenant_id=TENANT, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=sup,
        employee=EmployeeFile(employee_no=f"E-{ULID()}", first_name="Awa", last_name="Diarra", hire_date=datetime.date(2024, 1, 1)),
    ).value["id"]

    jobs = JobService(db)
    job_id = jobs.create_job(
        tenant_id=TENANT, actor_id=sup, equipment_id=machine, title="Graissage", description=None, kind="corrective",
        priority="normal", due_date=TODAY, stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Graisser", "action": "lubricate"}], chef_user_id=sup,
    ).value
    [check_id] = [r[0] for r in db.execute("SELECT id FROM maintenance.job_checks WHERE job_id = %s", (job_id,)).fetchall()]
    now = datetime.datetime.now(datetime.timezone.utc)
    assert isinstance(jobs.record_entry(
        tenant_id=TENANT, actor_id=sup, job_id=job_id, check_id=check_id, performer_employee_id=employee, outcome="ok",
        note=None, measured_value=None, started_at=now - datetime.timedelta(minutes=5), finished_at=now,
        manual_minutes=None, photo=None, actor_can_plan=True, now=now,
    ), Ok)
    jobs.submit(tenant_id=TENANT, actor_id=sup, job_id=job_id, actor_can_plan=True)
    jobs.review(tenant_id=TENANT, actor_id=sup, job_id=job_id, verdicts=[(check_id, "accepted", None)])
    assert isinstance(jobs.close(tenant_id=TENANT, actor_id=sup, job_id=job_id), Ok)

    wrapped = _Connection(db)
    monkeypatch.setattr(history_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    current = {"user": sup}
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=current["user"], session_token="t")

    def acting_as(user_id: str) -> None:
        current["user"] = user_id

    return SimpleNamespace(client=TestClient(app), acting_as=acting_as, sup=sup, valuer=valuer, nobody=nobody, machine=machine, job=job_id, db=db)


PERIOD = f"from={TODAY.replace(month=1, day=1).isoformat()}&to={TODAY.isoformat()}"


def test_history_routes_need_view_jobs(api):
    api.acting_as(api.nobody)
    for path in (
        f"/maintenance/history/indicators?{PERIOD}",
        f"/maintenance/history/journal?{PERIOD}",
        f"/maintenance/history/journal/export?{PERIOD}",
        f"/maintenance/equipment/{api.machine}/history?{PERIOD}",
        "/maintenance/checkpoints/whatever/history",
    ):
        assert api.client.get(path).status_code == 403, path


def test_costs_follow_the_valuation_right(api):
    plain = api.client.get(f"/maintenance/history/journal?{PERIOD}").json()
    assert plain["costs_visible"] is False and plain["rows"][0]["parts_cost"] is None
    api.acting_as(api.valuer)
    valued = api.client.get(f"/maintenance/history/journal?{PERIOD}").json()
    assert valued["costs_visible"] is True and valued["rows"][0]["parts_cost"] == 0


def test_indicators_and_logbook_answer(api):
    indicators = api.client.get(f"/maintenance/history/indicators?{PERIOD}")
    assert indicators.status_code == 200
    assert api.machine in {m["equipment_id"] for m in indicators.json()["machines"]}
    logbook = api.client.get(f"/maintenance/equipment/{api.machine}/history?{PERIOD}")
    assert logbook.status_code == 200 and logbook.json()["timeline"][0]["job"]["job_id"] == api.job


def test_error_codes(api):
    reversed_period = api.client.get(f"/maintenance/history/journal?from={TODAY.isoformat()}&to=2000-01-01")
    assert reversed_period.status_code == 422 and reversed_period.json()["detail"]["code"] == "INVALID_PERIOD"
    assert api.client.get(f"/maintenance/history/journal?{PERIOD}&status=open").json()["detail"]["code"] == "INVALID_FILTER"
    unknown = api.client.get(f"/maintenance/equipment/nope/history?{PERIOD}")
    assert unknown.status_code == 404 and unknown.json()["detail"]["message_fr"]
    assert api.client.get("/maintenance/checkpoints/nope/history").status_code == 404


def test_the_excel_journal_holds_the_rows_and_hides_costs_without_the_right(api):
    response = api.client.get(f"/maintenance/history/journal/export?{PERIOD}&lang=fr")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    sheet = load_workbook(io.BytesIO(response.content)).active
    headers = [cell.value for cell in sheet[2]]
    assert headers[:3] == ["N°", "Clôturée le", "Machine"] and "Coût (XOF)" not in headers
    numbers = [row[0].value for row in sheet.iter_rows(min_row=3) if row[0].value and str(row[0].value).startswith("MT-")]
    assert len(numbers) == 1

    api.acting_as(api.valuer)
    valued = load_workbook(io.BytesIO(api.client.get(f"/maintenance/history/journal/export?{PERIOD}&lang=en").content)).active
    assert "Cost (XOF)" in [cell.value for cell in valued[2]]


def test_the_excel_journal_cannot_smuggle_a_formula_into_a_cell(api):
    """A job title is free text typed by a user. Excel treats a cell starting with = + - @
    as a formula, so an exported title like "=1+1" would run on whoever opens the file.
    The text has to come back as text."""
    api.acting_as(api.sup)
    jobs = JobService(api.db)
    for title in ("=1+1", "+34", "-7", "@SUM(A1)"):
        job_id = jobs.create_job(
            tenant_id=TENANT, actor_id=api.sup, equipment_id=api.machine, title=title, description=None,
            kind="corrective", priority="normal", due_date=TODAY, stops_machine=False, checkpoint_ids=[],
            tasks=[{"label": "Tâche", "action": "clean"}], chef_user_id=api.sup,
        ).value
        api.db.execute(
            "UPDATE maintenance.jobs SET status = 'closed', closed_at = NOW() WHERE id = %s", (job_id,)
        )

    sheet = load_workbook(io.BytesIO(api.client.get(f"/maintenance/history/journal/export?{PERIOD}").content)).active

    titles = [row[4].value for row in sheet.iter_rows(min_row=3) if row[4].value]
    for dangerous in ("=1+1", "+34", "-7", "@SUM(A1)"):
        assert f"'{dangerous}" in titles, f"{dangerous!r} is not neutralised: {titles}"
    # openpyxl also marks a cell it would treat as a formula; none should be left.
    assert [c.data_type for row in sheet.iter_rows(min_row=3) for c in row if c.value].count("f") == 0

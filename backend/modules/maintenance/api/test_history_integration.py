"""Integration tests for a machine's history, against a real database.

Production's figures come from a fake reader: building validated shifts is production's
own concern (its stops analytics tests cover "validated shifts only"); here we check what
maintenance does with them.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.employee_service import EmployeeService
from modules.hr.domain.employee import EmployeeFile
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.history_service import HistoryService
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.map_service import MapService

T = "integration-test-history"
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 2, 12, tzinfo=UTC)
PERIOD = (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
SEPT = 30 * 24 * 60
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50


def _user(db, full_name, *, permissions=()):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, T, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


def _employee(db, first_name, last_name):
    created = EmployeeService(db).create_employee(
        tenant_id=T,
        actor_id=str(ULID()),
        employee=EmployeeFile(employee_no=f"E-{ULID()}", first_name=first_name, last_name=last_name, hire_date=datetime.date(2024, 1, 1)),
    )
    assert isinstance(created, Ok), created
    return created.value["id"]


def _machine(db, actor, code="EXT-L1"):
    created = EquipmentService(db).create_equipment(
        tenant_id=T, actor_id=actor, work_center_id="wc-1", code=code, name=f"Machine {code}"
    )
    assert isinstance(created, Ok), created
    return created.value.id


def _view_with_points(db, actor, machine, points):
    maps = MapService(db)
    view = maps.create_view(tenant_id=T, actor_id=actor, equipment_id=machine, label="Face", image=JPEG_BYTES, mime="image/jpeg").value
    ids = []
    for index, (label, action, extra) in enumerate(points):
        point = maps.add_checkpoint(
            tenant_id=T, actor_id=actor, view_id=view["id"], x_pct=10 + index, y_pct=20, label=label, action=action, **extra
        ).value
        maps.update_checkpoint(tenant_id=T, actor_id=actor, checkpoint_id=point["id"], sort_order=index + 1)
        ids.append(point["id"])
    return view["id"], ids


@pytest.fixture
def ctx(db):
    sup = _user(db, "Sara Superviseur", permissions=("maintenance.plan_jobs",))
    chef = _user(db, "Chef Keita", permissions=("maintenance.execute_jobs",))
    machine = _machine(db, sup)
    view, points = _view_with_points(
        db, sup, machine,
        [("Roulement", "lubricate", {}), ("Température palier", "measure", {"measure_unit": "°C"}), ("Courroie", "inspect", {})],
    )
    employees = [_employee(db, "Awa", "Diarra"), _employee(db, "Moussa", "Traoré")]
    return SimpleNamespace(sup=sup, chef=chef, machine=machine, view=view, points=points, employees=employees)


def _job(db, ctx, **overrides) -> str:
    arguments = dict(
        tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Graissage", description=None,
        kind="corrective", priority="normal", due_date=datetime.date(2026, 9, 10), stops_machine=False,
        checkpoint_ids=[ctx.points[0]], tasks=[], chef_user_id=ctx.chef,
    )
    arguments.update(overrides)
    created = JobService(db).create_job(**arguments)
    assert isinstance(created, Ok), created
    return created.value


def _entry(db, ctx, job_id, check_id, **overrides):
    now = datetime.datetime.now(UTC)
    arguments = dict(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, check_id=check_id, performer_employee_id=ctx.employees[0],
        outcome="ok", note=None, measured_value=None, started_at=now - datetime.timedelta(minutes=5), finished_at=now,
        manual_minutes=None, photo=None, actor_can_plan=False, now=now,
    )
    arguments.update(overrides)
    recorded = JobService(db).record_entry(**arguments)
    assert isinstance(recorded, Ok), recorded


def _checks(db, job_id) -> list[str]:
    return [row[0] for row in db.execute(
        "SELECT id FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order, id", (job_id,)
    ).fetchall()]


def _close(db, ctx, job_id, outcomes):
    """Records one entry per check with the given outcomes, submits, accepts all, closes."""
    jobs = JobService(db)
    checks = _checks(db, job_id)
    for check_id, outcome in zip(checks, outcomes):
        _entry(db, ctx, job_id, check_id, outcome=outcome)
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False), Ok)
    assert isinstance(jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(c, "accepted", None) for c in checks]), Ok)
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)


def _set_job_times(db, job_id, **columns):
    """Moves a job's timestamps into the test period: the service writes NOW()."""
    for column, value in columns.items():
        db.execute(f"UPDATE maintenance.jobs SET {column} = %s WHERE id = %s", (value, job_id))


def _set_audit_times(db, machine, times):
    """Every status change in one test transaction has the same NOW(), and their ids give no
    reliable order: place each one by the status it moved to (`times`: {to_status: when})."""
    for to_status, when in times.items():
        updated = db.execute(
            "UPDATE core.audit_log SET occurred_at = %s "
            "WHERE entity_id = %s AND action = 'equipment.status_changed' AND payload->>'to_status' = %s",
            (when, machine, to_status),
        ).rowcount
        assert updated == 1, (to_status, updated)


class FakeProduction:
    def __init__(self, stops=(), running=None):
        self._stops = list(stops)
        self._running = running or {}

    def stops(self, *, tenant_id, date_from, date_to, equipment_id=None):
        return [s for s in self._stops if equipment_id is None or s["equipment_id"] == equipment_id]

    def running_minutes(self, *, tenant_id, date_from, date_to):
        return dict(self._running)


def _stop(equipment_id, minutes, downtime_type="corrective", classification="mechanical", started_at="2026-09-12T08:00:00+00:00"):
    return {
        "equipment_id": equipment_id, "work_center_id": "wc-1", "team": "B", "report_date": started_at[:10],
        "started_at": started_at, "ended_at": started_at, "minutes": minutes, "downtime_type": downtime_type,
        "classification": classification, "motif": "die_jam", "source": "manual", "shift_report_id": "shift-1",
        "note": "filière démontée", "corrective_action": None,
    }


def _service(db, production=None):
    return HistoryService(db, production=production, now=NOW)


def _indicators(db, production=None, **overrides):
    arguments = dict(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    arguments.update(overrides)
    result = _service(db, production).indicators(**arguments)
    assert isinstance(result, Ok), result
    return result.value


def _row(indicators, machine):
    [row] = [m for m in indicators["machines"] if m["equipment_id"] == machine]
    return row


def test_immobilisation_comes_from_the_status_changes(db, ctx):
    equipment = EquipmentService(db)
    for status in ("down", "maintenance", "operational"):
        assert isinstance(equipment.transition_status(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, new_status=status), Ok)
    _set_audit_times(db, ctx.machine, {
        "down": datetime.datetime(2026, 9, 2, 8, tzinfo=UTC),
        "maintenance": datetime.datetime(2026, 9, 2, 9, tzinfo=UTC),
        "operational": datetime.datetime(2026, 9, 2, 10, tzinfo=UTC),
    })
    job_id = _job(db, ctx)
    _set_job_times(db, job_id, created_at=datetime.datetime(2026, 9, 2, 8, tzinfo=UTC))

    block = _row(_indicators(db), ctx.machine)["maintenance"]

    assert (block["immobilised_minutes"], block["immobilisations"], block["mean_immobilisation_minutes"]) == (120, 1, 120)
    assert block["breakdowns"] == 1
    assert block["calendar_minutes"] == SEPT
    assert block["calendar_mtbf_minutes"] == SEPT - 120
    assert block["status_changes"] == 3


def test_preventive_due_closed_on_time_and_overdue(db, ctx):
    rows = [
        # (due, status, closed_at)
        (datetime.date(2026, 9, 5), "closed", datetime.datetime(2026, 9, 5, 15, tzinfo=UTC)),   # on time
        (datetime.date(2026, 9, 6), "closed", datetime.datetime(2026, 9, 8, 9, tzinfo=UTC)),    # late
        (datetime.date(2026, 9, 20), "assigned", None),                                          # overdue (now is Oct 2)
        (datetime.date(2026, 9, 21), "cancelled", None),                                         # not counted
        (datetime.date(2026, 10, 20), "assigned", None),                                         # outside the period
    ]
    for due, status, closed_at in rows:
        job_id = _job(db, ctx)
        db.execute(
            "UPDATE maintenance.jobs SET kind = 'preventive', due_date = %s, status = %s, closed_at = %s WHERE id = %s",
            (due, status, closed_at, job_id),
        )

    block = _row(_indicators(db), ctx.machine)["maintenance"]

    assert block["preventive"] == {"due": 3, "closed": 2, "closed_on_time": 1, "overdue": 1}
    assert block["breakdowns"] == 0 and block["calendar_mtbf_minutes"] is None


def test_production_block_comes_from_the_production_reader(db, ctx):
    production = FakeProduction(
        stops=[_stop(ctx.machine, 30), _stop(ctx.machine, 20, classification="electric"),
               _stop(ctx.machine, 15, downtime_type="preventive"), _stop(None, 10)],
        running={ctx.machine: 600},
    )

    indicators = _indicators(db, production)
    block = _row(indicators, ctx.machine)["production"]

    assert (block["breakdowns"], block["breakdown_minutes"], block["mttr_minutes"], block["mtbf_minutes"]) == (2, 50, 25, 300)
    assert block["stops"] == 3
    assert indicators["unattributed_stops"] == {"count": 1, "minutes": 10}
    assert indicators["production_available"] is True


def test_without_production_the_block_is_unavailable(db, ctx):
    indicators = _indicators(db, production=None)
    assert indicators["production_available"] is False
    assert _row(indicators, ctx.machine)["production"] is None
    assert indicators["unattributed_stops"] is None


def test_a_machine_with_no_production_figure_gets_an_empty_block(db, ctx):
    block = _row(_indicators(db, FakeProduction()), ctx.machine)["production"]
    assert (block["stops"], block["breakdowns"], block["mtbf_minutes"]) == (0, 0, None)


def test_an_archived_machine_is_listed_only_with_activity(db, ctx):
    idle = _machine(db, ctx.sup, code="OLD-1")
    busy = _machine(db, ctx.sup, code="OLD-2")
    job_id = JobService(db).create_job(
        tenant_id=T, actor_id=ctx.sup, equipment_id=busy, title="Panne", description=None, kind="corrective",
        priority="urgent", due_date=datetime.date(2026, 9, 3), stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Réparer", "action": "replace"}], chef_user_id=ctx.chef,
    ).value
    _set_job_times(db, job_id, created_at=datetime.datetime(2026, 9, 3, tzinfo=UTC))
    for machine in (idle, busy):
        assert isinstance(EquipmentService(db).archive_equipment(tenant_id=T, actor_id=ctx.sup, equipment_id=machine), Ok)

    listed = {m["equipment_id"] for m in _indicators(db)["machines"]}

    assert busy in listed and idle not in listed and ctx.machine in listed


def test_the_photo_is_the_first_view_with_an_image(db, ctx):
    row = _row(_indicators(db), ctx.machine)
    assert row["photo_view_id"] == ctx.view and row["photo_version"] is not None


def test_a_reversed_period_and_an_unknown_machine_are_refused(db, ctx):
    service = _service(db)
    reversed_period = service.indicators(tenant_id=T, date_from=PERIOD[1], date_to=PERIOD[0], costs_visible=True)
    assert isinstance(reversed_period, Err) and reversed_period.code == "INVALID_PERIOD"
    unknown = service.indicators(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True, equipment_id="nope")
    assert isinstance(unknown, Err) and unknown.code == "NOT_FOUND"


from modules.maintenance.api.parts_service import PartsService, list_part_requests  # noqa: E402
from modules.warehouse.api.location_service import LocationService  # noqa: E402
from modules.warehouse.api.service import StockService  # noqa: E402


def _journal(db, **overrides):
    arguments = dict(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    arguments.update(overrides)
    result = _service(db).journal(**arguments)
    assert isinstance(result, Ok), result
    return result.value["rows"]


def test_journal_row_tells_what_was_done_with_rework(db, ctx):
    jobs = JobService(db)
    job_id = _job(db, ctx, checkpoint_ids=ctx.points[:1], tasks=[{"label": "Nettoyer", "action": "clean"}])
    first, second = _checks(db, job_id)
    _entry(db, ctx, job_id, first)
    _entry(db, ctx, job_id, second, performer_employee_id=ctx.employees[1])
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(first, "accepted", None), (second, "rejected", "mal fait")])
    _entry(db, ctx, job_id, second, outcome="issue")
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(second, "accepted", None)])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)
    _set_job_times(db, job_id, closed_at=datetime.datetime(2026, 9, 10, 9, tzinfo=UTC))

    [row] = _journal(db)

    assert row["job_id"] == job_id and row["status"] == "closed"
    assert row["date"].startswith("2026-09-10")
    assert row["outcomes"] == {"ok": 1, "issue": 1, "not_done": 0, "pending": 0}
    assert row["technician_seconds"] == 3 * 300  # three attempts' latest entries, five minutes each
    assert [p["name"] for p in row["performers"]] == ["Awa Diarra", "Moussa Traoré"]
    assert row["closed_on_time"] is True and row["chef_name"] == "Chef Keita"
    assert _journal(db, status="cancelled") == []
    assert _journal(db, kind="preventive") == []


def test_journal_lists_cancelled_jobs_by_their_cancel_date(db, ctx):
    job_id = _job(db, ctx)
    assert isinstance(JobService(db).cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason="doublon"), Ok)
    _set_job_times(db, job_id, cancelled_at=datetime.datetime(2026, 9, 4, tzinfo=UTC))

    assert _journal(db) == []
    [row] = _journal(db, status="all")
    assert (row["status"], row["cancel_reason"], row["date"][:10]) == ("cancelled", "doublon", "2026-09-04")


def test_journal_parts_cost_needs_the_valuation_right(db, ctx):
    uom = str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, 'pc', 'Pièce', 'unit', true)", (uom, T))
    bearing = str(ULID())
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'ROUL-6204', 'Roulement 6204', %s)", (bearing, T, uom))
    store = LocationService(db).create_location(tenant_id=T, actor_id=ctx.sup, code="MAG-PDR", name="Magasin pièces").value.id
    assert isinstance(StockService(db).receive_stock(
        tenant_id=T, product_id=bearing, location_id=store, quantity=5, correlation_id=str(ULID()),
        reference="history-test", actor_id=ctx.sup, unit_cost=5000,
    ), Ok)
    job_id = _job(db, ctx)
    parts = PartsService(db)
    request_id = parts.create_request(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, lines=[{"product_id": bearing, "uom_id": uom, "quantity": 2}],
        note=None, actor_can_plan=False,
    ).value
    [request] = list_part_requests(db, T, job_id=job_id)
    [line] = request["lines"]
    assert isinstance(parts.approve(
        tenant_id=T, actor_id=ctx.sup, request_id=request_id,
        lines=[{"line_id": line["id"], "location_id": store, "issue_quantity": 2}], note=None, correlation_id=str(ULID()),
    ), Ok)
    _close(db, ctx, job_id, ["ok"])
    _set_job_times(db, job_id, closed_at=datetime.datetime(2026, 9, 12, tzinfo=UTC))

    [visible] = _journal(db)
    [hidden] = _journal(db, costs_visible=False)

    assert visible["parts"] == {"issued_lines": 1, "purchase_lines": 0}
    assert visible["parts_cost"] == 10_000
    assert hidden["parts_cost"] is None and hidden["parts"] == {"issued_lines": 1, "purchase_lines": 0}


def test_journal_refuses_unknown_filters(db, ctx):
    refused = _service(db).journal(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True, status="open")
    assert isinstance(refused, Err) and refused.code == "INVALID_FILTER"


def _history(db, ctx, production=None, **overrides):
    arguments = dict(tenant_id=T, equipment_id=ctx.machine, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    arguments.update(overrides)
    result = _service(db, production).equipment_history(**arguments)
    assert isinstance(result, Ok), result
    return result.value


def test_the_logbook_mixes_jobs_stops_and_status_changes_newest_first(db, ctx):
    closed = _job(db, ctx, title="Graissage mensuel")
    _close(db, ctx, closed, ["ok"])
    _set_job_times(db, closed, created_at=datetime.datetime(2026, 9, 3, tzinfo=UTC), closed_at=datetime.datetime(2026, 9, 5, tzinfo=UTC))
    still_open = _job(db, ctx, title="Fuite d'huile")
    _set_job_times(db, still_open, created_at=datetime.datetime(2026, 8, 1, tzinfo=UTC))  # open: listed whatever its age
    old = _job(db, ctx, title="Ancienne")
    _close(db, ctx, old, ["ok"])
    _set_job_times(db, old, created_at=datetime.datetime(2026, 7, 1, tzinfo=UTC), closed_at=datetime.datetime(2026, 7, 2, tzinfo=UTC))
    EquipmentService(db).transition_status(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, new_status="down")
    _set_audit_times(db, ctx.machine, {"down": datetime.datetime(2026, 9, 20, 14, tzinfo=UTC)})
    production = FakeProduction(stops=[_stop(ctx.machine, 75, started_at="2026-09-12T09:40:00+00:00")], running={ctx.machine: 600})

    history = _history(db, ctx, production)

    assert [(item["kind"], item["at"][:10]) for item in history["timeline"]] == [
        ("status_change", "2026-09-20"),
        ("production_stop", "2026-09-12"),
        ("job", "2026-09-05"),
        ("job", "2026-08-01"),
    ]
    status_change = history["timeline"][0]
    assert (status_change["from_status"], status_change["to_status"], status_change["actor_name"]) == ("operational", "down", "Sara Superviseur")
    stop = history["timeline"][1]["stop"]
    assert (stop["minutes"], stop["classification"], stop["note"]) == (75, "mechanical", "filière démontée")
    assert history["equipment"]["equipment_id"] == ctx.machine
    assert history["indicators"]["production"]["breakdowns"] == 1


def test_the_logbook_summarises_each_checkpoint(db, ctx):
    for value, outcome in ((68, "ok"), (71, "issue")):
        job_id = _job(db, ctx, checkpoint_ids=[ctx.points[1]])
        [check] = _checks(db, job_id)
        _entry(db, ctx, job_id, check, measured_value=value, outcome=outcome)
        jobs = JobService(db)
        jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
        jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(check, "accepted", None)])
        jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id)
    MapService(db).archive_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=ctx.points[2])

    points = {p["checkpoint_id"]: p for p in _history(db, ctx)["checkpoints"]}

    measured = points[ctx.points[1]]
    assert (measured["checks_count"], measured["issues_count"], measured["last_outcome"]) == (2, 1, "issue")
    assert measured["last_measured_value"] == 71
    assert [m["value"] for m in measured["recent_measures"]] == [68, 71]
    assert points[ctx.points[0]]["checks_count"] == 0 and points[ctx.points[0]]["last_checked_at"] is None
    assert ctx.points[2] not in points  # archived and never checked


def test_an_unknown_machine_has_no_logbook(db, ctx):
    missing = _service(db).equipment_history(tenant_id=T, equipment_id="nope", date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"

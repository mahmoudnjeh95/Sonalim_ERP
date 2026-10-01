"""Integration tests for maintenance preventive programs: the recurrence rule itself,
the due-job sweep (`run_due`), overdue notification, and the calendar's projection of
future occurrences that have no job yet.

A program's job is a snapshot like any other (Review Focus 5 / B4): the sweep only
decides *when* and *which checkpoints*; `JobService.create_job` does the actual
snapshotting and already sends the "job due" notification. This file only proves the
sweep never double-creates an occurrence, respects lead_days and the program's own
creation date, and raises the overdue notice exactly once per job.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.job_queries import job_detail, list_jobs
from modules.maintenance.api.map_service import MapService
from modules.maintenance.api.program_service import ProgramService

T = "integration-test-programs"
TODAY = datetime.date.today()

JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50
JPEG_MIME = "image/jpeg"


def _user(db, full_name, *, tenant=T, permissions=()):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, tenant, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


def _machine(db, actor, *, tenant=T, code="PRESSE-9"):
    created = EquipmentService(db).create_equipment(
        tenant_id=tenant, actor_id=actor, work_center_id="wc-1", code=code, name=f"Machine {code}"
    )
    assert isinstance(created, Ok), created
    return created.value.id


def _view_with_points(db, actor, machine, points):
    maps = MapService(db)
    view = maps.create_view(
        tenant_id=T, actor_id=actor, equipment_id=machine, label="Face", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    ids = []
    for index, (label, action) in enumerate(points):
        checkpoint = maps.add_checkpoint(
            tenant_id=T, actor_id=actor, view_id=view["id"], x_pct=10 + index, y_pct=20, label=label, action=action
        ).value
        maps.update_checkpoint(tenant_id=T, actor_id=actor, checkpoint_id=checkpoint["id"], sort_order=index + 1)
        ids.append(checkpoint["id"])
    return view["id"], ids


@pytest.fixture
def ctx(db):
    from types import SimpleNamespace

    sup = _user(db, "Sara Superviseur", permissions=("maintenance.plan_jobs",))
    chef = _user(db, "Chef Keita", permissions=("maintenance.execute_jobs",))
    machine = _machine(db, sup)
    view, points = _view_with_points(db, sup, machine, [("Roulement", "lubricate"), ("Courroie", "inspect")])
    return SimpleNamespace(sup=sup, chef=chef, machine=machine, view=view, points=points)


def _create_program(programs, ctx, **overrides):
    arguments = dict(
        tenant_id=T,
        actor_id=ctx.sup,
        equipment_id=ctx.machine,
        name="Graissage mensuel",
        description=None,
        interval_value=1,
        interval_unit="month",
        start_date=TODAY,
        lead_days=0,
        estimated_minutes=None,
        default_team_id=None,
        stops_machine=False,
        checkpoint_ids=list(ctx.points),
    )
    arguments.update(overrides)
    return programs.create_program(**arguments)


def _created_at_on(db, program_id, when: datetime.date) -> None:
    db.execute(
        "UPDATE maintenance.programs SET created_at = %s WHERE id = %s",
        (datetime.datetime.combine(when, datetime.time(0, 0), tzinfo=datetime.timezone.utc), program_id),
    )


def _jobs_for_program(db, program_id):
    return db.execute(
        "SELECT occurrence_date FROM maintenance.jobs WHERE program_id = %s ORDER BY occurrence_date", (program_id,)
    ).fetchall()


def test_run_due_twice_creates_one_job_per_occurrence(db, ctx):
    programs = ProgramService(db)
    created = _create_program(
        programs, ctx, interval_value=1, interval_unit="day", start_date=TODAY, lead_days=0
    )
    assert isinstance(created, Ok), created
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=30))

    first = programs.run_due(tenant_id=T, today=TODAY)
    assert first["created"] == 1
    second = programs.run_due(tenant_id=T, today=TODAY)
    assert second["created"] == 0

    rows = _jobs_for_program(db, program_id)
    assert len(rows) == 1
    assert rows[0][0] == TODAY


def test_lead_days_controls_when_the_job_appears(db, ctx):
    programs = ProgramService(db)
    occurrence = TODAY + datetime.timedelta(days=3)
    created = _create_program(
        programs, ctx, interval_value=1, interval_unit="day", start_date=occurrence, lead_days=3
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=1))

    # lead_days=3, today=occurrence-3: inside the window.
    result = programs.run_due(tenant_id=T, today=occurrence - datetime.timedelta(days=3))
    assert result["created"] == 1
    rows = _jobs_for_program(db, program_id)
    assert len(rows) == 1 and rows[0][0] == occurrence


def test_lead_days_excludes_before_the_window(db, ctx):
    programs = ProgramService(db)
    occurrence = TODAY + datetime.timedelta(days=4)
    created = _create_program(
        programs, ctx, interval_value=1, interval_unit="day", start_date=occurrence, lead_days=3
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=1))

    result = programs.run_due(tenant_id=T, today=occurrence - datetime.timedelta(days=4))
    assert result["created"] == 0
    assert _jobs_for_program(db, program_id) == []


def test_program_without_points_still_creates_a_job(db, ctx):
    programs = ProgramService(db)
    created = _create_program(
        programs, ctx, interval_value=1, interval_unit="day", start_date=TODAY, lead_days=0, checkpoint_ids=[]
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=1))

    # Program has no explicit checkpoints and we also give it a machine whose points
    # are not attached -- empty checkpoint_ids means "every active checkpoint of the
    # machine" is resolved at creation time, so use a fresh, pointless machine instead.
    bare_machine = _machine(db, ctx.sup, code="PRESSE-BARE")
    bare = _create_program(
        programs,
        ctx,
        equipment_id=bare_machine,
        interval_value=1,
        interval_unit="day",
        start_date=TODAY,
        lead_days=0,
        checkpoint_ids=[],
    )
    bare_id = bare.value["id"]
    _created_at_on(db, bare_id, TODAY - datetime.timedelta(days=1))

    result = programs.run_due(tenant_id=T, today=TODAY)
    assert result["created"] >= 1

    rows = db.execute(
        "SELECT j.id FROM maintenance.jobs j WHERE j.program_id = %s AND j.occurrence_date = %s", (bare_id, TODAY)
    ).fetchone()
    assert rows is not None
    detail = job_detail(db, T, rows[0], TODAY)
    assert detail["checks_total"] == 1
    assert detail["checks"][0]["label"] == "Graissage mensuel"
    assert detail["checks"][0]["checkpoint_id"] is None


def test_program_checkpoint_subset_is_snapshotted(db, ctx):
    programs = ProgramService(db)
    created = _create_program(
        programs,
        ctx,
        interval_value=1,
        interval_unit="day",
        start_date=TODAY,
        lead_days=0,
        checkpoint_ids=[ctx.points[0]],
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=1))

    result = programs.run_due(tenant_id=T, today=TODAY)
    assert result["created"] == 1

    row = db.execute(
        "SELECT id FROM maintenance.jobs WHERE program_id = %s AND occurrence_date = %s", (program_id, TODAY)
    ).fetchone()
    detail = job_detail(db, T, row[0], TODAY)
    assert detail["checks_total"] == 1
    assert detail["checks"][0]["checkpoint_id"] == ctx.points[0]


def test_overdue_notified_once(db, ctx):
    programs = ProgramService(db)
    created = _create_program(
        programs,
        ctx,
        interval_value=1,
        interval_unit="day",
        start_date=TODAY - datetime.timedelta(days=5),
        lead_days=0,
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=10))

    past_today = TODAY - datetime.timedelta(days=3)
    first_sweep = programs.run_due(tenant_id=T, today=past_today)
    assert first_sweep["created"] >= 1

    # Advance to today: the job(s) created for dates before today are now overdue.
    second_sweep = programs.run_due(tenant_id=T, today=TODAY)
    assert second_sweep["overdue_notified"] >= 1

    third_sweep = programs.run_due(tenant_id=T, today=TODAY)
    assert third_sweep["overdue_notified"] == 0

    rows = db.execute(
        "SELECT overdue_notified_at FROM maintenance.jobs WHERE program_id = %s AND due_date < %s", (program_id, TODAY)
    ).fetchall()
    assert rows and all(r[0] is not None for r in rows)


def test_calendar_projects_future_occurrences_without_jobs(db, ctx):
    programs = ProgramService(db)
    created = _create_program(
        programs, ctx, interval_value=1, interval_unit="week", start_date=TODAY, lead_days=0
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=30))

    # Materialise only the first occurrence (today); leave future occurrences unmaterialised.
    run = programs.run_due(tenant_id=T, today=TODAY)
    assert run["created"] == 1

    calendar = programs.calendar(
        tenant_id=T, date_from=TODAY, date_to=TODAY + datetime.timedelta(days=21), today=TODAY
    )
    assert len(calendar["jobs"]) == 1
    projected_dates = {p["date"] for p in calendar["projected"] if p["program_id"] == program_id}
    # today's occurrence has a job already -> not projected; the next two weekly occurrences are.
    assert TODAY.isoformat() not in projected_dates
    assert (TODAY + datetime.timedelta(days=7)).isoformat() in projected_dates
    assert (TODAY + datetime.timedelta(days=14)).isoformat() in projected_dates
    entry = next(p for p in calendar["projected"] if p["program_id"] == program_id)
    assert entry["program_name"] == "Graissage mensuel"
    assert entry["equipment_id"] == ctx.machine


def test_inactive_program_is_not_run_or_projected(db, ctx):
    programs = ProgramService(db)
    created = _create_program(
        programs, ctx, interval_value=1, interval_unit="day", start_date=TODAY, lead_days=0
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY - datetime.timedelta(days=1))

    updated = programs.update_program(tenant_id=T, actor_id=ctx.sup, program_id=program_id, active=False)
    assert isinstance(updated, Ok), updated
    assert updated.value["active"] is False
    assert updated.value["next_occurrence"] is None

    result = programs.run_due(tenant_id=T, today=TODAY)
    assert result["created"] == 0
    assert _jobs_for_program(db, program_id) == []

    calendar = programs.calendar(tenant_id=T, date_from=TODAY, date_to=TODAY + datetime.timedelta(days=10), today=TODAY)
    assert all(p["program_id"] != program_id for p in calendar["projected"])

    listed = programs.list_programs(T, TODAY)
    entry = next(p for p in listed if p["id"] == program_id)
    assert entry["active"] is False and entry["next_occurrence"] is None


def test_no_backfill_before_program_creation(db, ctx):
    programs = ProgramService(db)
    # Program started a year ago but was only entered into the system today: no
    # backfill of the many past occurrences, only the one(s) due from creation on.
    created = _create_program(
        programs,
        ctx,
        interval_value=1,
        interval_unit="month",
        start_date=TODAY - datetime.timedelta(days=365),
        lead_days=0,
    )
    program_id = created.value["id"]
    _created_at_on(db, program_id, TODAY)

    result = programs.run_due(tenant_id=T, today=TODAY)
    assert result["created"] == 1
    rows = _jobs_for_program(db, program_id)
    assert len(rows) == 1
    assert rows[0][0] == TODAY


def test_run_due_endpoint_is_per_tenant(db, ctx):
    other_tenant = "integration-test-programs-other"
    other_sup = _user(db, "Autre Sup", tenant=other_tenant, permissions=("maintenance.plan_jobs",))
    other_machine = _machine(db, other_sup, tenant=other_tenant, code="PRESSE-OTHER")
    programs = ProgramService(db)
    created = programs.create_program(
        tenant_id=other_tenant,
        actor_id=other_sup,
        equipment_id=other_machine,
        name="Autre programme",
        description=None,
        interval_value=1,
        interval_unit="day",
        start_date=TODAY,
        lead_days=0,
        estimated_minutes=None,
        default_team_id=None,
        stops_machine=False,
        checkpoint_ids=[],
    )
    assert isinstance(created, Ok), created
    _created_at_on(db, created.value["id"], TODAY - datetime.timedelta(days=1))

    result = programs.run_due(tenant_id=T, today=TODAY)
    assert result["created"] == 0
    assert _jobs_for_program(db, created.value["id"]) == []

    other_result = programs.run_due(tenant_id=other_tenant, today=TODAY)
    assert other_result["created"] == 1


def test_tenants_with_active_programs(db, ctx):
    programs = ProgramService(db)
    created = _create_program(programs, ctx, interval_value=1, interval_unit="day", start_date=TODAY, lead_days=0)
    assert isinstance(created, Ok), created
    tenants = programs.tenants_with_active_programs()
    assert T in tenants


def test_list_and_update_program_shape(db, ctx):
    programs = ProgramService(db)
    created = _create_program(programs, ctx, interval_value=2, interval_unit="week", start_date=TODAY, lead_days=5)
    assert isinstance(created, Ok), created
    program = created.value
    assert set(program) == {
        "id", "equipment_id", "equipment_name", "name", "description", "interval_value", "interval_unit",
        "start_date", "lead_days", "estimated_minutes", "default_team_id", "default_team_name", "stops_machine",
        "active", "checkpoint_ids", "next_occurrence",
    }
    assert program["equipment_name"] is not None
    assert program["next_occurrence"] == TODAY.isoformat()
    assert set(program["checkpoint_ids"]) == set(ctx.points)

    updated = programs.update_program(
        tenant_id=T, actor_id=ctx.sup, program_id=program["id"], name="Graissage renommé", lead_days=2
    )
    assert isinstance(updated, Ok), updated
    assert updated.value["name"] == "Graissage renommé"
    assert updated.value["lead_days"] == 2

    listed = programs.list_programs(T, TODAY)
    assert any(p["id"] == program["id"] and p["name"] == "Graissage renommé" for p in listed)


def test_invalid_program_is_refused(db, ctx):
    programs = ProgramService(db)
    bad = _create_program(programs, ctx, interval_value=0)
    assert isinstance(bad, Err)
    assert bad.code == "INVALID_INTERVAL"


def test_unknown_equipment_is_refused(db, ctx):
    programs = ProgramService(db)
    bad = _create_program(programs, ctx, equipment_id=str(ULID()))
    assert isinstance(bad, Err)
    assert bad.code == "NOT_FOUND"

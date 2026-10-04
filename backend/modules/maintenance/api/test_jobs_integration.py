"""Integration tests for maintenance jobs, against a real database.

A job snapshots the points it asks for, a chef records who did each point, when and
for how long, the supervisor reviews point by point, and a rejection reopens only the
rejected points -- every earlier attempt stays in the job's history.
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
from modules.maintenance.api.job_queries import entry_photo, job_detail, list_jobs
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.map_service import MapService
from modules.maintenance.api.team_service import TeamService

T = "integration-test-jobs"
OTHER_TENANT = "integration-test-jobs-other"
TODAY = datetime.date.today()
YEAR = TODAY.year

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


def _employee(db, first_name, last_name, *, status="active"):
    created = EmployeeService(db).create_employee(
        tenant_id=T,
        actor_id=str(ULID()),
        employee=EmployeeFile(
            employee_no=f"E-{ULID()}",
            first_name=first_name,
            last_name=last_name,
            hire_date=datetime.date(2024, 1, 1),
            status=status,
        ),
    )
    assert isinstance(created, Ok), created
    return created.value["id"]


def _machine(db, actor, *, tenant=T, code="PRESSE-1"):
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
    for index, (label, action, extra) in enumerate(points):
        checkpoint = maps.add_checkpoint(
            tenant_id=T, actor_id=actor, view_id=view["id"], x_pct=10 + index, y_pct=20, label=label, action=action, **extra
        ).value
        # add_checkpoint leaves sort_order at 0: number them so the snapshot order is the map's order.
        maps.update_checkpoint(tenant_id=T, actor_id=actor, checkpoint_id=checkpoint["id"], sort_order=index + 1)
        ids.append(checkpoint["id"])
    return view["id"], ids


@pytest.fixture
def ctx(db):
    sup = _user(db, "Sara Superviseur", permissions=("maintenance.plan_jobs",))
    chef = _user(db, "Chef Keita", permissions=("maintenance.execute_jobs",))
    other = _user(db, "Autre Chef", permissions=("maintenance.execute_jobs",))
    machine = _machine(db, sup)
    view, points = _view_with_points(
        db,
        sup,
        machine,
        [("Roulement", "lubricate", {}), ("Vis de serrage", "tighten", {}), ("Courroie", "inspect", {})],
    )
    employees = [_employee(db, "Awa", "Diarra"), _employee(db, "Moussa", "Traoré")]
    return SimpleNamespace(sup=sup, chef=chef, other=other, machine=machine, view=view, points=points, employees=employees)


def _create(jobs, ctx, **overrides):
    arguments = dict(
        tenant_id=T,
        actor_id=ctx.sup,
        equipment_id=ctx.machine,
        title="Graissage",
        description=None,
        kind="corrective",
        priority="normal",
        due_date=TODAY,
        stops_machine=False,
        checkpoint_ids=ctx.points[:2],
        tasks=[],
        chef_user_id=ctx.chef,
    )
    arguments.update(overrides)
    return jobs.create_job(**arguments)


def _entry(jobs, ctx, job_id, check_id, **overrides):
    now = datetime.datetime.now(datetime.timezone.utc)
    arguments = dict(
        tenant_id=T,
        actor_id=ctx.chef,
        job_id=job_id,
        check_id=check_id,
        performer_employee_id=ctx.employees[0],
        outcome="ok",
        note=None,
        measured_value=None,
        started_at=now - datetime.timedelta(minutes=5),
        finished_at=now,
        manual_minutes=None,
        photo=None,
        actor_can_plan=False,
        now=now,
    )
    arguments.update(overrides)
    return jobs.record_entry(**arguments)


def _equipment_status(db, equipment_id):
    return db.execute("SELECT status FROM maintenance.equipment WHERE id = %s", (equipment_id,)).fetchone()[0]


def _notifications(db, user_id):
    rows = db.execute(
        "SELECT kind, title, title_fr, link FROM core.notifications WHERE tenant_id = %s AND user_id = %s ORDER BY created_at, id",
        (T, user_id),
    ).fetchall()
    return [{"kind": r[0], "title": r[1], "title_fr": r[2], "link": r[3]} for r in rows]


def _submitted_job(db, ctx, **overrides):
    """A job whose every check has an entry and that the chef has submitted."""
    jobs = JobService(db)
    job_id = _create(jobs, ctx, **overrides).value
    detail = job_detail(db, T, job_id, TODAY)
    for check in detail["checks"]:
        assert isinstance(_entry(jobs, ctx, job_id, check["id"]), Ok)
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False), Ok)
    return jobs, job_id, [c["id"] for c in detail["checks"]]


# ---- the whole lifecycle ---------------------------------------------------


def test_full_flow_with_rework(db, ctx):
    jobs = JobService(db)
    job_id = jobs.create_job(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Graissage", description=None,
                             kind="corrective", priority="urgent", due_date=TODAY, stops_machine=True,
                             checkpoint_ids=ctx.points[:2], tasks=[{"label": "Nettoyer la trémie", "action": "clean"}],
                             chef_user_id=ctx.chef).value
    detail = job_detail(db, T, job_id, TODAY)
    assert detail["status"] == "assigned" and len(detail["checks"]) == 3 and detail["checks"][2]["view_id"] is None
    for check in detail["checks"]:
        assert isinstance(_entry(jobs, ctx, job_id, check["id"]), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False), Ok)
    ids = [c["id"] for c in detail["checks"]]
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id,
                verdicts=[(ids[0], "accepted", None), (ids[1], "rejected", "vis non graissée"), (ids[2], "accepted", None)])
    after = job_detail(db, T, job_id, TODAY)
    assert after["status"] == "rework"
    assert [c["state"] for c in after["checks"]] == ["accepted", "pending", "accepted"]
    assert after["checks"][1]["attempt"] == 2 and len(after["checks"][1]["entries"]) == 1
    _entry(jobs, ctx, job_id, ids[1])
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(ids[1], "accepted", None)])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)
    final = job_detail(db, T, job_id, TODAY)
    assert final["status"] == "closed" and len(final["checks"][1]["entries"]) == 2
    assert _equipment_status(db, ctx.machine) == "operational"

    # the timeline tells the whole story, in order, and names who did what
    assert [e["kind"] for e in final["timeline"]] == [
        "created", "assigned", "started", "check_done", "check_done", "check_done", "submitted",
        "rework", "check_done", "submitted", "reviewed", "closed",
    ]
    assert final["timeline"][0]["actor_name"] == "Sara Superviseur"
    assert final["timeline"][2]["actor_name"] == "Chef Keita"
    assert final["closed_at"] is not None and final["started_at"] is not None and final["submitted_at"] is not None


def test_rework_reopens_only_rejected_checks_and_keeps_history(db, ctx):
    jobs, job_id, ids = _submitted_job(db, ctx, checkpoint_ids=ctx.points)

    reviewed = jobs.review(
        tenant_id=T,
        actor_id=ctx.sup,
        job_id=job_id,
        verdicts=[(ids[0], "accepted", None), (ids[1], "rejected", "vis non graissée"), (ids[2], "accepted", None)],
    )
    assert isinstance(reviewed, Ok)

    # an accepted point is locked: it is not redone
    locked = _entry(jobs, ctx, job_id, ids[0])
    assert isinstance(locked, Err) and locked.code == "CHECK_LOCKED"

    # only the rejected point is reopened, on a new attempt, and its first entry is still there
    after = job_detail(db, T, job_id, TODAY)
    assert after["status"] == "rework"
    assert [(c["state"], c["attempt"]) for c in after["checks"]] == [("accepted", 1), ("pending", 2), ("accepted", 1)]
    rejected = after["checks"][1]
    assert [e["attempt"] for e in rejected["entries"]] == [1]
    assert [(r["attempt"], r["verdict"], r["reason"], r["reviewer_name"]) for r in rejected["reviews"]] == [
        (1, "rejected", "vis non graissée", "Sara Superviseur")
    ]
    assert [(r["attempt"], r["verdict"]) for r in after["checks"][0]["reviews"]] == [(1, "accepted")]

    # the job cannot be submitted again until the reopened point is redone
    pending = jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    assert isinstance(pending, Err) and pending.code == "CHECKS_PENDING"

    assert isinstance(_entry(jobs, ctx, job_id, ids[1], performer_employee_id=ctx.employees[1], outcome="issue"), Ok)
    redone = job_detail(db, T, job_id, TODAY)["checks"][1]
    assert redone["state"] == "done"
    assert [(e["attempt"], e["outcome"], e["performer_name"]) for e in redone["entries"]] == [
        (1, "ok", "Awa Diarra"),
        (2, "issue", "Moussa Traoré"),
    ]
    # the other points kept their single, first-attempt entry
    assert [len(c["entries"]) for c in job_detail(db, T, job_id, TODAY)["checks"]] == [1, 2, 1]


def test_review_needs_a_verdict_for_every_submitted_check_and_a_reason_to_reject(db, ctx):
    jobs, job_id, ids = _submitted_job(db, ctx)

    partial = jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(ids[0], "accepted", None)])
    assert isinstance(partial, Err) and partial.code == "REVIEW_INCOMPLETE"

    no_reason = jobs.review(
        tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(ids[0], "accepted", None), (ids[1], "rejected", " ")]
    )
    assert isinstance(no_reason, Err) and no_reason.code == "REASON_REQUIRED"

    unknown_verdict = jobs.review(
        tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(ids[0], "accepted", None), (ids[1], "maybe", None)]
    )
    assert isinstance(unknown_verdict, Err) and unknown_verdict.code == "INVALID_VERDICT"

    # nothing was written by the refused reviews, and the job cannot be closed yet
    detail = job_detail(db, T, job_id, TODAY)
    assert [c["state"] for c in detail["checks"]] == ["done", "done"]
    assert all(c["reviews"] == [] for c in detail["checks"])
    not_yet = jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id)
    assert isinstance(not_yet, Err) and not_yet.code == "NOT_ALL_ACCEPTED"


# ---- creation ----------------------------------------------------------------


def test_snapshot_is_not_changed_by_later_map_edits(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx, checkpoint_ids=ctx.points).value

    maps = MapService(db)
    maps.update_checkpoint(
        tenant_id=T, actor_id=ctx.sup, checkpoint_id=ctx.points[0], label="Renommé", action="replace", x_pct=90, y_pct=90
    )
    maps.archive_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=ctx.points[1])

    checks = job_detail(db, T, job_id, TODAY)["checks"]
    assert [(c["checkpoint_id"], c["label"], c["action"]) for c in checks] == [
        (ctx.points[0], "Roulement", "lubricate"),
        (ctx.points[1], "Vis de serrage", "tighten"),
        (ctx.points[2], "Courroie", "inspect"),
    ]
    assert (checks[0]["view_id"], checks[0]["x_pct"], checks[0]["y_pct"]) == (ctx.view, 10.0, 20.0)
    assert [c["sort_order"] for c in checks] == [1, 2, 3]


def test_checks_follow_the_map_order_then_the_adhoc_tasks(db, ctx):
    jobs = JobService(db)
    job_id = _create(
        jobs,
        ctx,
        checkpoint_ids=[ctx.points[2], ctx.points[0]],
        tasks=[{"label": "Nettoyer la trémie", "action": "clean", "instructions": "à sec"}],
    ).value

    checks = job_detail(db, T, job_id, TODAY)["checks"]
    assert [c["label"] for c in checks] == ["Roulement", "Courroie", "Nettoyer la trémie"]
    assert checks[2]["instructions"] == "à sec" and checks[2]["checkpoint_id"] is None


def test_job_with_only_adhoc_tasks(db, ctx):
    jobs = JobService(db)
    created = _create(
        jobs,
        ctx,
        checkpoint_ids=[],
        tasks=[{"label": "Nettoyer la trémie", "action": "clean"}, {"label": "Changer le filtre", "action": "replace"}],
    )
    assert isinstance(created, Ok)

    detail = job_detail(db, T, created.value, TODAY)
    assert [(c["label"], c["action"], c["state"]) for c in detail["checks"]] == [
        ("Nettoyer la trémie", "clean", "pending"),
        ("Changer le filtre", "replace", "pending"),
    ]
    for check in detail["checks"]:
        assert (check["checkpoint_id"], check["view_id"], check["x_pct"], check["y_pct"]) == (None, None, None, None)
        assert check["requires_photo"] is False and check["entries"] == [] and check["reviews"] == []
        assert isinstance(_entry(jobs, ctx, created.value, check["id"]), Ok)
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=created.value, actor_can_plan=False), Ok)


def test_job_without_any_check_is_refused(db, ctx):
    result = _create(JobService(db), ctx, checkpoint_ids=[], tasks=[])
    assert isinstance(result, Err) and result.code == "NO_CHECKS"
    assert list_jobs(db, T, today=TODAY) == []


def test_checkpoints_must_be_active_points_of_the_job_machine(db, ctx):
    jobs = JobService(db)
    other_machine = _machine(db, ctx.sup, code="PRESSE-2")
    _, foreign_points = _view_with_points(db, ctx.sup, other_machine, [("Autre machine", "inspect", {})])

    foreign = _create(jobs, ctx, checkpoint_ids=[ctx.points[0], foreign_points[0]])
    assert isinstance(foreign, Err) and foreign.code == "UNKNOWN_CHECKPOINT"

    missing = _create(jobs, ctx, checkpoint_ids=["does-not-exist"])
    assert isinstance(missing, Err) and missing.code == "UNKNOWN_CHECKPOINT"

    MapService(db).archive_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=ctx.points[0])
    archived = _create(jobs, ctx, checkpoint_ids=[ctx.points[0]])
    assert isinstance(archived, Err) and archived.code == "UNKNOWN_CHECKPOINT"

    assert list_jobs(db, T, today=TODAY) == []


def test_job_numbers_increment_per_tenant(db, ctx):
    jobs = JobService(db)
    first = _create(jobs, ctx).value
    second = _create(jobs, ctx).value

    other_user = _user(db, "Autre tenant", tenant=OTHER_TENANT)
    other_machine = _machine(db, other_user, tenant=OTHER_TENANT)
    elsewhere = jobs.create_job(
        tenant_id=OTHER_TENANT, actor_id=other_user, equipment_id=other_machine, title="Ailleurs", description=None,
        kind="corrective", priority="normal", due_date=TODAY, stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Vérifier", "action": "inspect"}],
    ).value

    assert job_detail(db, T, first, TODAY)["number"] == f"MT-{YEAR}-0001"
    assert job_detail(db, T, second, TODAY)["number"] == f"MT-{YEAR}-0002"
    assert job_detail(db, OTHER_TENANT, elsewhere, TODAY)["number"] == f"MT-{YEAR}-0001"
    # a job is only ever visible inside its own tenant
    assert job_detail(db, OTHER_TENANT, first, TODAY) is None


def test_job_without_a_chef_is_planned_then_assigned(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx, chef_user_id=None).value
    planned = job_detail(db, T, job_id, TODAY)
    assert (planned["status"], planned["chef_user_id"], planned["chef_name"]) == ("planned", None, None)

    # nothing can be recorded before the job has a chef
    early = _entry(jobs, ctx, job_id, planned["checks"][0]["id"], actor_id=ctx.sup, actor_can_plan=True)
    assert isinstance(early, Err) and early.code == "INVALID_TRANSITION"

    no_chef = jobs.assign_job(tenant_id=T, actor_id=ctx.sup, job_id=job_id, team_id=None, chef_user_id=None)
    assert isinstance(no_chef, Err) and no_chef.code == "CHEF_REQUIRED"

    assigned = jobs.assign_job(tenant_id=T, actor_id=ctx.sup, job_id=job_id, team_id=None, chef_user_id=ctx.chef)
    assert isinstance(assigned, Ok)
    detail = job_detail(db, T, job_id, TODAY)
    assert (detail["status"], detail["chef_user_id"], detail["chef_name"]) == ("assigned", ctx.chef, "Chef Keita")
    assert [e["kind"] for e in detail["timeline"]] == ["created", "assigned"]
    assert [n["kind"] for n in _notifications(db, ctx.chef)] == ["maintenance.job_assigned"]


def test_a_team_without_an_explicit_chef_brings_its_own(db, ctx):
    team = TeamService(db).create_team(tenant_id=T, actor_id=ctx.sup, name="Équipe A", chef_user_id=ctx.chef).value
    jobs = JobService(db)

    created = _create(jobs, ctx, team_id=team["id"], chef_user_id=None).value
    detail = job_detail(db, T, created, TODAY)
    assert (detail["status"], detail["team_id"], detail["team_name"], detail["chef_user_id"]) == (
        "assigned", team["id"], "Équipe A", ctx.chef,
    )

    planned = _create(jobs, ctx, chef_user_id=None).value
    assert isinstance(
        jobs.assign_job(tenant_id=T, actor_id=ctx.sup, job_id=planned, team_id=team["id"], chef_user_id=None), Ok
    )
    assert job_detail(db, T, planned, TODAY)["chef_user_id"] == ctx.chef

    unknown_team = _create(jobs, ctx, team_id="missing-team", chef_user_id=None)
    assert isinstance(unknown_team, Err) and unknown_team.code == "UNKNOWN_TEAM"
    unknown_chef = _create(jobs, ctx, chef_user_id="missing-user")
    assert isinstance(unknown_chef, Err) and unknown_chef.code == "UNKNOWN_CHEF"


def test_a_program_occurrence_is_materialised_once_by_the_system_actor(db, ctx):
    program_id = str(ULID())
    db.execute(
        """
        INSERT INTO maintenance.programs
            (id, tenant_id, equipment_id, name, interval_value, interval_unit, start_date, lead_days, created_by)
        VALUES (%s, %s, %s, 'Graissage mensuel', 1, 'month', %s, 0, %s)
        """,
        (program_id, T, ctx.machine, TODAY, ctx.sup),
    )
    jobs = JobService(db)
    arguments = dict(
        actor_id="system:maintenance-sweep", kind="preventive", chef_user_id=None, program_id=program_id, occurrence_date=TODAY
    )

    first = _create(jobs, ctx, **arguments)
    assert isinstance(first, Ok)
    again = _create(jobs, ctx, **arguments)
    assert isinstance(again, Err) and again.code == "ALREADY_EXISTS"

    listed = list_jobs(db, T, today=TODAY)
    assert [(j["id"], j["program_id"], j["occurrence_date"], j["kind"]) for j in listed] == [
        (first.value, program_id, TODAY.isoformat(), "preventive")
    ]
    detail = job_detail(db, T, first.value, TODAY)
    assert (detail["created_by"], detail["created_by_name"]) == ("system:maintenance-sweep", "system:maintenance-sweep")
    # the refused second call left no orphan checks behind
    assert db.execute("SELECT count(*) FROM maintenance.job_checks WHERE tenant_id = %s", (T,)).fetchone()[0] == 2
    # supervisors are told a preventive job has come due
    assert [n["kind"] for n in _notifications(db, ctx.sup)] == ["maintenance.job_due"]


# ---- delegation and entries ----------------------------------------------------


def test_delegate_sets_the_assignee_of_each_check(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx).value
    checks = job_detail(db, T, job_id, TODAY)["checks"]

    delegated = jobs.delegate(
        tenant_id=T,
        actor_id=ctx.chef,
        job_id=job_id,
        assignments=[(checks[0]["id"], ctx.employees[0]), (checks[1]["id"], ctx.employees[1])],
        actor_can_plan=False,
    )
    assert isinstance(delegated, Ok)
    after = job_detail(db, T, job_id, TODAY)
    assert [(c["assignee_employee_id"], c["assignee_name"]) for c in after["checks"]] == [
        (ctx.employees[0], "Awa Diarra"),
        (ctx.employees[1], "Moussa Traoré"),
    ]
    assert after["timeline"][-1]["kind"] == "delegated"

    cleared = jobs.delegate(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, assignments=[(checks[0]["id"], None)], actor_can_plan=False
    )
    assert isinstance(cleared, Ok)
    assert job_detail(db, T, job_id, TODAY)["checks"][0]["assignee_employee_id"] is None

    stranger = jobs.delegate(
        tenant_id=T, actor_id=ctx.other, job_id=job_id, assignments=[(checks[0]["id"], ctx.employees[0])], actor_can_plan=False
    )
    assert isinstance(stranger, Err) and stranger.code == "NOT_JOB_CHEF"

    unknown_employee = jobs.delegate(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, assignments=[(checks[0]["id"], "missing")], actor_can_plan=False
    )
    assert isinstance(unknown_employee, Err) and unknown_employee.code == "UNKNOWN_EMPLOYEE"

    unknown_check = jobs.delegate(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, assignments=[("missing", ctx.employees[0])], actor_can_plan=False
    )
    assert isinstance(unknown_check, Err) and unknown_check.code == "UNKNOWN_CHECK"


def test_other_executor_cannot_record_on_someone_elses_job(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx).value
    check_id = job_detail(db, T, job_id, TODAY)["checks"][0]["id"]

    refused = _entry(jobs, ctx, job_id, check_id, actor_id=ctx.other)
    assert isinstance(refused, Err) and refused.code == "NOT_JOB_CHEF"
    cannot_submit = jobs.submit(tenant_id=T, actor_id=ctx.other, job_id=job_id, actor_can_plan=False)
    assert isinstance(cannot_submit, Err) and cannot_submit.code == "NOT_JOB_CHEF"

    untouched = job_detail(db, T, job_id, TODAY)
    assert untouched["status"] == "assigned" and untouched["checks"][0]["entries"] == []

    # a supervisor (plan_jobs) may step in on any job
    as_supervisor = _entry(jobs, ctx, job_id, check_id, actor_id=ctx.sup, actor_can_plan=True)
    assert isinstance(as_supervisor, Ok)
    entry = job_detail(db, T, job_id, TODAY)["checks"][0]["entries"][0]
    assert (entry["recorded_by"], entry["recorded_by_name"]) == (ctx.sup, "Sara Superviseur")


def test_unknown_performer_refused(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx).value
    check_id = job_detail(db, T, job_id, TODAY)["checks"][0]["id"]

    unknown = _entry(jobs, ctx, job_id, check_id, performer_employee_id="not-an-employee")
    assert isinstance(unknown, Err) and unknown.code == "UNKNOWN_EMPLOYEE"

    gone = _employee(db, "Ancien", "Salarié", status="inactive")
    inactive = _entry(jobs, ctx, job_id, check_id, performer_employee_id=gone)
    assert isinstance(inactive, Err) and inactive.code == "UNKNOWN_EMPLOYEE"

    detail = job_detail(db, T, job_id, TODAY)
    assert detail["status"] == "assigned" and detail["checks"][0]["entries"] == []


def test_entry_records_who_when_how_long_and_starts_the_job(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx, stops_machine=False).value
    checks = job_detail(db, T, job_id, TODAY)["checks"]
    now = datetime.datetime.now(datetime.timezone.utc)

    timed = _entry(
        jobs, ctx, job_id, checks[0]["id"],
        started_at=now - datetime.timedelta(seconds=150), finished_at=now, now=now, note="  graissé  ",
    )
    assert isinstance(timed, Ok)
    manual = _entry(
        jobs, ctx, job_id, checks[1]["id"],
        performer_employee_id=ctx.employees[1], started_at=None, finished_at=None, manual_minutes=12, outcome="not_done", now=now,
    )
    assert isinstance(manual, Ok)

    detail = job_detail(db, T, job_id, TODAY)
    assert detail["status"] == "in_progress" and detail["started_at"] is not None
    first, second = detail["checks"][0]["entries"][0], detail["checks"][1]["entries"][0]
    assert (first["performer_employee_id"], first["performer_name"], first["recorded_by_name"]) == (
        ctx.employees[0], "Awa Diarra", "Chef Keita",
    )
    assert (first["duration_seconds"], first["duration_source"], first["outcome"], first["note"]) == (150, "timer", "ok", "graissé")
    assert (first["attempt"], first["has_photo"], first["measured_value"]) == (1, False, None)
    assert datetime.datetime.fromisoformat(first["finished_at"]) == now
    assert (second["duration_seconds"], second["duration_source"], second["outcome"]) == (720, "manual", "not_done")
    # a machine the job does not stop stays as it was
    assert _equipment_status(db, ctx.machine) == "operational"

    no_timing = _entry(jobs, ctx, job_id, checks[0]["id"], started_at=None, finished_at=None)
    assert isinstance(no_timing, Err) and no_timing.code == "INVALID_TIMING"
    bad_outcome = _entry(jobs, ctx, job_id, checks[0]["id"], outcome="perfect")
    assert isinstance(bad_outcome, Err) and bad_outcome.code == "INVALID_OUTCOME"
    missing_check = _entry(jobs, ctx, job_id, "missing")
    assert isinstance(missing_check, Err) and missing_check.code == "NOT_FOUND"


def test_submit_needs_the_photo_and_the_measure_the_points_ask_for(db, ctx):
    _, points = _view_with_points(
        db,
        ctx.sup,
        ctx.machine,
        [("Jeu du palier", "measure", {"measure_unit": "mm"}), ("État du joint", "inspect", {"requires_photo": True})],
    )
    jobs = JobService(db)
    job_id = _create(jobs, ctx, checkpoint_ids=points).value
    measure, photo = job_detail(db, T, job_id, TODAY)["checks"]
    assert (measure["measure_unit"], photo["requires_photo"]) == ("mm", True)

    _entry(jobs, ctx, job_id, measure["id"])
    _entry(jobs, ctx, job_id, photo["id"], measured_value=None)
    no_photo = jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    assert isinstance(no_photo, Err) and no_photo.code in ("PHOTO_REQUIRED", "MEASURE_REQUIRED")

    not_an_image = _entry(jobs, ctx, job_id, photo["id"], photo=(b"%PDF-1.4", "application/pdf"))
    assert isinstance(not_an_image, Err) and not_an_image.code == "INVALID_IMAGE"

    # redoing a point before submitting replaces what counts for it: the latest entry of the attempt
    assert isinstance(_entry(jobs, ctx, job_id, photo["id"], photo=(JPEG_BYTES, JPEG_MIME)), Ok)
    no_measure = jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    assert isinstance(no_measure, Err) and no_measure.code == "MEASURE_REQUIRED"
    assert isinstance(_entry(jobs, ctx, job_id, measure["id"], measured_value=0.35), Ok)
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False), Ok)

    detail = job_detail(db, T, job_id, TODAY)
    assert detail["status"] == "submitted"
    assert [e["measured_value"] for e in detail["checks"][0]["entries"]] == [None, 0.35]
    photo_entries = detail["checks"][1]["entries"]
    assert [e["has_photo"] for e in photo_entries] == [False, True]
    assert entry_photo(db, T, photo_entries[1]["id"]) == (JPEG_BYTES, JPEG_MIME)
    assert entry_photo(db, T, photo_entries[0]["id"]) is None
    assert entry_photo(db, OTHER_TENANT, photo_entries[1]["id"]) is None


# ---- cancel, notifications, listing ----------------------------------------------


def test_cancel_requires_reason(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx).value

    for blank in (None, "", "   "):
        refused = jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason=blank)
        assert isinstance(refused, Err) and refused.code == "REASON_REQUIRED"
    assert job_detail(db, T, job_id, TODAY)["status"] == "assigned"

    cancelled = jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason="Machine remplacée")
    assert isinstance(cancelled, Ok)
    detail = job_detail(db, T, job_id, TODAY)
    assert (detail["status"], detail["cancel_reason"]) == ("cancelled", "Machine remplacée")
    assert detail["timeline"][-1]["kind"] == "cancelled"
    assert _notifications(db, ctx.chef)[-1]["kind"] == "maintenance.job_cancelled"

    twice = jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason="Encore")
    assert isinstance(twice, Err) and twice.code == "INVALID_TRANSITION"
    missing = jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id="missing", reason="x")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"


def test_cancelling_a_started_stopping_job_releases_the_machine(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx, stops_machine=True).value
    check_id = job_detail(db, T, job_id, TODAY)["checks"][0]["id"]
    assert isinstance(_entry(jobs, ctx, job_id, check_id), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"

    assert isinstance(jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason="Pièce manquante"), Ok)
    assert _equipment_status(db, ctx.machine) == "operational"
    cancelled = job_detail(db, T, job_id, TODAY)["timeline"][-1]
    assert (cancelled["kind"], cancelled["payload"]["equipment_restarted"]) == ("cancelled", True)

    # a stopping job that never started did not stop the machine: cancelling it leaves a
    # machine someone put in maintenance by hand exactly where it is
    never_started = _create(jobs, ctx, stops_machine=True).value
    EquipmentService(db).transition_status(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, new_status="maintenance")
    assert isinstance(jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=never_started, reason="Doublon"), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"
    assert job_detail(db, T, never_started, TODAY)["timeline"][-1]["payload"]["equipment_restarted"] is False


def test_machine_stays_in_maintenance_while_another_stopping_job_is_open(db, ctx):
    jobs, first, first_ids = _submitted_job(db, ctx, stops_machine=True)
    second = _create(jobs, ctx, stops_machine=True, checkpoint_ids=[ctx.points[2]]).value
    second_check = job_detail(db, T, second, TODAY)["checks"][0]["id"]
    assert isinstance(_entry(jobs, ctx, second, second_check), Ok)
    # a job that does not stop the machine, and a stopping one that has not started, never hold it
    harmless = _create(jobs, ctx, stops_machine=False).value
    _entry(jobs, ctx, harmless, job_detail(db, T, harmless, TODAY)["checks"][0]["id"])
    _create(jobs, ctx, stops_machine=True)
    assert _equipment_status(db, ctx.machine) == "maintenance"

    # closing the first job does not release a machine the second one is still working on
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=first, verdicts=[(i, "accepted", None) for i in first_ids])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=first), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"
    assert job_detail(db, T, first, TODAY)["timeline"][-1]["payload"]["equipment_restarted"] is False

    # still held while the second job waits for its review (submitted) ...
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=second, actor_can_plan=False), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"

    # ... and released when the last stopping job on the machine ends
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=second, verdicts=[(second_check, "accepted", None)])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=second), Ok)
    assert _equipment_status(db, ctx.machine) == "operational"
    assert job_detail(db, T, second, TODAY)["timeline"][-1]["payload"]["equipment_restarted"] is True


def test_cancelling_one_of_two_started_stopping_jobs_keeps_the_machine_stopped(db, ctx):
    jobs = JobService(db)
    started = []
    for point in ctx.points[:2]:
        job_id = _create(jobs, ctx, stops_machine=True, checkpoint_ids=[point]).value
        _entry(jobs, ctx, job_id, job_detail(db, T, job_id, TODAY)["checks"][0]["id"])
        started.append(job_id)

    jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=started[0], reason="Reportée")
    assert _equipment_status(db, ctx.machine) == "maintenance"
    jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=started[1], reason="Reportée")
    assert _equipment_status(db, ctx.machine) == "operational"


def test_notifications_fan_out_on_urgent_and_submit(db, ctx):
    second_sup = _user(db, "Second Superviseur", permissions=("maintenance.plan_jobs",))
    jobs = JobService(db)

    job_id = _create(jobs, ctx, priority="urgent").value
    number = job_detail(db, T, job_id, TODAY)["number"]
    link = f"/maintenance/jobs/{job_id}"

    # urgent: every supervisor and the chef, once each; nobody else
    for user_id in (ctx.sup, second_sup, ctx.chef):
        assert [(n["kind"], n["link"]) for n in _notifications(db, user_id)] == [("maintenance.job_urgent", link)]
    assert _notifications(db, ctx.other) == []
    urgent = _notifications(db, ctx.chef)[0]
    assert number in urgent["title"] and "Machine PRESSE-1" in urgent["title"]
    assert number in urgent["title_fr"] and "Machine PRESSE-1" in urgent["title_fr"]

    for check in job_detail(db, T, job_id, TODAY)["checks"]:
        _entry(jobs, ctx, job_id, check["id"])
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)

    # submitted: supervisors only
    for user_id in (ctx.sup, second_sup):
        assert [n["kind"] for n in _notifications(db, user_id)] == ["maintenance.job_urgent", "maintenance.job_submitted"]
    assert [n["kind"] for n in _notifications(db, ctx.chef)] == ["maintenance.job_urgent"]

    ids = [c["id"] for c in job_detail(db, T, job_id, TODAY)["checks"]]
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(ids[0], "accepted", None), (ids[1], "rejected", "à refaire")])
    # rework: the chef
    assert [n["kind"] for n in _notifications(db, ctx.chef)] == ["maintenance.job_urgent", "maintenance.job_rework"]

    total = db.execute("SELECT count(*) FROM core.notifications WHERE tenant_id = %s", (T,)).fetchone()[0]
    assert total == 3 + 2 + 1


def test_a_normal_assigned_job_only_notifies_its_chef_and_closing_tells_them(db, ctx):
    jobs, job_id, ids = _submitted_job(db, ctx)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(i, "accepted", None) for i in ids])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)

    assert [n["kind"] for n in _notifications(db, ctx.chef)] == ["maintenance.job_assigned", "maintenance.job_closed"]
    assert [n["kind"] for n in _notifications(db, ctx.sup)] == ["maintenance.job_submitted"]


def test_list_jobs_filters_and_reports_progress(db, ctx):
    jobs = JobService(db)
    yesterday = TODAY - datetime.timedelta(days=1)
    tomorrow = TODAY + datetime.timedelta(days=1)

    late = _create(jobs, ctx, title="En retard", due_date=yesterday).value
    planned = _create(jobs, ctx, title="À venir", due_date=tomorrow, chef_user_id=None).value
    other_machine = _machine(db, ctx.sup, code="PRESSE-2")
    elsewhere = _create(
        jobs, ctx, title="Autre machine", equipment_id=other_machine, checkpoint_ids=[],
        tasks=[{"label": "Vérifier", "action": "inspect"}], chef_user_id=ctx.other,
    ).value

    checks = job_detail(db, T, late, TODAY)["checks"]
    now = datetime.datetime.now(datetime.timezone.utc)
    # 4 min, then redone in 10 min on the same attempt: only the latest counts
    _entry(jobs, ctx, late, checks[0]["id"], started_at=None, finished_at=None, manual_minutes=4, now=now)
    _entry(jobs, ctx, late, checks[0]["id"], started_at=None, finished_at=None, manual_minutes=10, now=now)

    everything = {j["id"]: j for j in list_jobs(db, T, today=TODAY)}
    assert set(everything) == {late, planned, elsewhere}
    item = everything[late]
    assert (item["status"], item["checks_total"], item["checks_done"], item["minutes_spent"]) == ("in_progress", 2, 1, 10)
    assert (item["overdue"], item["due_date"]) == (True, yesterday.isoformat())
    assert (item["equipment_code"], item["equipment_name"], item["chef_name"]) == ("PRESSE-1", "Machine PRESSE-1", "Chef Keita")
    assert everything[planned]["overdue"] is False and everything[planned]["minutes_spent"] == 0
    assert set(item) == {
        "id", "number", "equipment_id", "equipment_code", "equipment_name", "kind", "priority", "title", "status",
        "due_date", "team_id", "team_name", "chef_user_id", "chef_name", "program_id", "occurrence_date", "stops_machine",
        "checks_total", "checks_done", "minutes_spent", "overdue", "created_at", "started_at", "submitted_at", "closed_at",
    }

    def ids(**filters):
        return {j["id"] for j in list_jobs(db, T, today=TODAY, **filters)}

    assert ids(statuses=["planned"]) == {planned}
    assert ids(statuses=["planned", "in_progress"]) == {planned, late}
    assert ids(equipment_id=other_machine) == {elsewhere}
    assert ids(chef_user_id=ctx.chef) == {late}
    assert ids(date_from=TODAY) == {planned, elsewhere}
    assert ids(date_to=TODAY) == {late, elsewhere}
    assert ids(date_from=TODAY, date_to=TODAY) == {elsewhere}

    # a cancelled job is no longer overdue
    jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=late, reason="Annulée")
    assert {j["id"]: j for j in list_jobs(db, T, today=TODAY)}[late]["overdue"] is False


def test_job_detail_has_the_contract_shape(db, ctx):
    jobs = JobService(db)
    job_id = _create(jobs, ctx, description="Bruit anormal").value
    detail = job_detail(db, T, job_id, TODAY)

    assert (detail["description"], detail["created_by"], detail["created_by_name"]) == ("Bruit anormal", ctx.sup, "Sara Superviseur")
    assert (detail["cancel_reason"], detail["part_requests"]) == (None, [])
    assert set(detail["checks"][0]) == {
        "id", "sort_order", "checkpoint_id", "view_id", "x_pct", "y_pct", "label", "action", "instructions",
        "measure_unit", "requires_photo", "assignee_employee_id", "assignee_name", "state", "attempt", "entries", "reviews",
        "parts",
    }
    assert set(detail["timeline"][0]) == {"id", "at", "actor_id", "actor_name", "kind", "payload"}

    _entry(jobs, ctx, job_id, detail["checks"][0]["id"])
    entry = job_detail(db, T, job_id, TODAY)["checks"][0]["entries"][0]
    assert set(entry) == {
        "id", "attempt", "performer_employee_id", "performer_name", "recorded_by", "recorded_by_name", "started_at",
        "finished_at", "duration_seconds", "duration_source", "outcome", "note", "measured_value", "has_photo",
    }
    assert job_detail(db, T, "missing", TODAY) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_measure_that_is_not_a_number_is_refused(db, ctx, value):
    """NaN would be stored, then break every later read of the job (JSON has no NaN)."""
    jobs = JobService(db)
    job_id = _create(jobs, ctx, stops_machine=False).value
    check_id = job_detail(db, T, job_id, TODAY)["checks"][0]["id"]

    refused = _entry(jobs, ctx, job_id, check_id, measured_value=value)

    assert isinstance(refused, Err)
    assert refused.code == "INVALID_MEASURE"
    assert job_detail(db, T, job_id, TODAY)["checks"][0]["entries"] == []


def test_cancelling_a_stopping_job_puts_a_broken_machine_back_down(db, ctx):
    """The job did not repair it: a machine that was down when the job stopped it is
    down again once the job is cancelled, not shown as running on the production board."""
    EquipmentService(db).transition_status(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, new_status="down")
    jobs = JobService(db)
    job_id = _create(jobs, ctx, stops_machine=True).value
    check_id = job_detail(db, T, job_id, TODAY)["checks"][0]["id"]
    assert isinstance(_entry(jobs, ctx, job_id, check_id), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"

    assert isinstance(jobs.cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason="Mauvaise équipe"), Ok)

    assert _equipment_status(db, ctx.machine) == "down"
    cancelled = job_detail(db, T, job_id, TODAY)["timeline"][-1]
    assert (cancelled["payload"]["equipment_restarted"], cancelled["payload"]["equipment_status"]) == (False, "down")


def test_a_team_without_a_chef_named_brings_its_own(db, ctx):
    team = TeamService(db).create_team(tenant_id=T, actor_id=ctx.sup, name="Équipe B", chef_user_id=ctx.chef).value
    jobs = JobService(db)

    job_id = _create(jobs, ctx, team_id=team["id"], chef_user_id=None).value

    detail = job_detail(db, T, job_id, TODAY)
    assert (detail["status"], detail["chef_user_id"]) == ("assigned", ctx.chef)


def test_a_team_with_the_chef_left_for_later_stays_to_assign(db, ctx):
    """"Assigner plus tard" picked in the dialog: the team's chef is not filled in behind the user's back."""
    team = TeamService(db).create_team(tenant_id=T, actor_id=ctx.sup, name="Équipe C", chef_user_id=ctx.chef).value
    jobs = JobService(db)

    job_id = _create(jobs, ctx, team_id=team["id"], chef_user_id=None, chef_from_team=False).value

    detail = job_detail(db, T, job_id, TODAY)
    assert (detail["status"], detail["chef_user_id"], detail["team_id"]) == ("planned", None, team["id"])
    assert _notifications(db, ctx.chef) == []


def test_no_job_is_raised_on_an_archived_machine(db, ctx):
    EquipmentService(db).archive_equipment(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine)

    refused = _create(JobService(db), ctx)

    assert isinstance(refused, Err)
    assert refused.code == "EQUIPMENT_ARCHIVED"

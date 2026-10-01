"""Integration tests for teams and machine checkpoint maps, against a real database.

Teams resolve chef (core.users) and member (hr.employees) names server-side; maps
hold a machine's photo(s) with pins (checkpoints) that jobs snapshot from later --
editing or deleting a map must never rewrite a job that already copied from it.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.employee_service import EmployeeService
from modules.hr.domain.employee import EmployeeFile
from modules.maintenance.api.map_service import MapService
from modules.maintenance.api.team_service import TeamService

TENANT = "integration-test-teams-maps"
LINE = "wc-1"

JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50
JPEG_MIME = "image/jpeg"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _make_user(db, full_name=None):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, TENANT, f"{user_id}@test.local", full_name),
    )
    return user_id


def _make_employee(db, first_name="Awa", last_name="Diarra"):
    created = EmployeeService(db).create_employee(
        tenant_id=TENANT,
        actor_id=str(ULID()),
        employee=EmployeeFile(
            employee_no=f"E-{ULID()}",
            first_name=first_name,
            last_name=last_name,
            hire_date=datetime.date(2024, 1, 1),
        ),
    )
    assert isinstance(created, Ok), created
    return created.value["id"]


def _make_equipment(db, code="M-1"):
    equipment_id = str(ULID())
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, %s, %s)",
        (equipment_id, TENANT, LINE, code, f"Machine {code}"),
    )
    return equipment_id


# ---- teams --------------------------------------------------------------


def test_team_lists_chef_and_member_names(db, actor):
    chef_id = _make_user(db, full_name="Chef Keita")
    member_id = _make_employee(db, "Awa", "Diarra")

    created = TeamService(db).create_team(tenant_id=TENANT, actor_id=actor, name="Team A", chef_user_id=chef_id)
    assert isinstance(created, Ok)
    team_id = created.value["id"]

    updated = TeamService(db).set_members(tenant_id=TENANT, actor_id=actor, team_id=team_id, employee_ids=[member_id])
    assert isinstance(updated, Ok)

    team = updated.value
    assert team["chef_user_id"] == chef_id
    assert team["chef_name"] == "Chef Keita"
    assert team["members"] == [{"employee_id": member_id, "name": "Awa Diarra"}]


def test_team_chef_name_falls_back_to_email(db, actor):
    chef_id = _make_user(db, full_name=None)
    created = TeamService(db).create_team(tenant_id=TENANT, actor_id=actor, name="Team B", chef_user_id=chef_id)
    assert isinstance(created, Ok)
    assert created.value["chef_name"] == f"{chef_id}@test.local"


def test_set_members_replaces_the_list(db, actor):
    team = TeamService(db).create_team(tenant_id=TENANT, actor_id=actor, name="Team C", chef_user_id=None).value
    member_1 = _make_employee(db, "First", "One")
    member_2 = _make_employee(db, "Second", "Two")

    first = TeamService(db).set_members(tenant_id=TENANT, actor_id=actor, team_id=team["id"], employee_ids=[member_1])
    assert isinstance(first, Ok)
    assert [m["employee_id"] for m in first.value["members"]] == [member_1]

    replaced = TeamService(db).set_members(tenant_id=TENANT, actor_id=actor, team_id=team["id"], employee_ids=[member_2])
    assert isinstance(replaced, Ok)
    assert [m["employee_id"] for m in replaced.value["members"]] == [member_2]


def test_update_team_can_clear_the_chef_and_archive(db, actor):
    chef_id = _make_user(db, full_name="Chef A")
    team = TeamService(db).create_team(tenant_id=TENANT, actor_id=actor, name="Team D", chef_user_id=chef_id).value

    cleared = TeamService(db).update_team(tenant_id=TENANT, actor_id=actor, team_id=team["id"], chef_user_id=None, chef_user_id_set=True)
    assert isinstance(cleared, Ok)
    assert cleared.value["chef_user_id"] is None
    assert cleared.value["chef_name"] is None

    archived = TeamService(db).update_team(tenant_id=TENANT, actor_id=actor, team_id=team["id"], archived=True)
    assert isinstance(archived, Ok)
    assert archived.value["archived_at"] is not None


def test_update_team_not_mentioning_chef_leaves_it_alone(db, actor):
    chef_id = _make_user(db, full_name="Chef B")
    team = TeamService(db).create_team(tenant_id=TENANT, actor_id=actor, name="Team E", chef_user_id=chef_id).value

    renamed = TeamService(db).update_team(tenant_id=TENANT, actor_id=actor, team_id=team["id"], name="Renamed")
    assert isinstance(renamed, Ok)
    assert renamed.value["name"] == "Renamed"
    assert renamed.value["chef_user_id"] == chef_id


def test_get_team_for_unknown_id_is_none(db):
    assert TeamService(db).get_team(tenant_id=TENANT, team_id="missing") is None


def test_create_team_without_a_name_is_refused(db, actor):
    result = TeamService(db).create_team(tenant_id=TENANT, actor_id=actor, name="   ", chef_user_id=None)
    assert isinstance(result, Err) and result.code == "INVALID_NAME"


# ---- equipment views / maps ----------------------------------------------


def test_view_upload_rejects_non_images_and_oversize(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)

    bad_mime = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime="application/pdf"
    )
    assert isinstance(bad_mime, Err) and bad_mime.code == "INVALID_IMAGE"

    oversize = service.create_view(
        tenant_id=TENANT,
        actor_id=actor,
        equipment_id=equipment_id,
        label="Front",
        image=b"0" * (10 * 1024 * 1024 + 1),
        mime=JPEG_MIME,
    )
    assert isinstance(oversize, Err) and oversize.code == "INVALID_IMAGE"

    assert service.list_views(tenant_id=TENANT, equipment_id=equipment_id) == []


def test_view_upload_for_unknown_equipment_is_not_found(db, actor):
    result = MapService(db).create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id="missing", label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    )
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_view_round_trips_its_image(db, actor):
    equipment_id = _make_equipment(db)
    created = MapService(db).create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    )
    assert isinstance(created, Ok)
    view_id = created.value["id"]

    fetched = MapService(db).get_image(tenant_id=TENANT, view_id=view_id)
    assert fetched == (JPEG_BYTES, JPEG_MIME)


def test_checkpoint_outside_0_100_is_refused(db, actor):
    equipment_id = _make_equipment(db)
    view = MapService(db).create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value

    too_high = MapService(db).add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=101, y_pct=50, label="Bolt", action="tighten"
    )
    assert isinstance(too_high, Err) and too_high.code == "INVALID_POSITION"

    negative = MapService(db).add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=50, y_pct=-1, label="Bolt", action="tighten"
    )
    assert isinstance(negative, Err) and negative.code == "INVALID_POSITION"

    unchanged = MapService(db).list_views(tenant_id=TENANT, equipment_id=equipment_id)
    assert unchanged[0]["checkpoints"] == []


def test_checkpoint_with_unknown_action_is_refused(db, actor):
    equipment_id = _make_equipment(db)
    view = MapService(db).create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value

    result = MapService(db).add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=50, y_pct=50, label="Bolt", action="dance"
    )
    assert isinstance(result, Err) and result.code == "INVALID_ACTION"


def test_archived_checkpoint_hidden_unless_asked(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)
    view = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    checkpoint = service.add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=10, y_pct=20, label="Bolt", action="tighten"
    ).value
    archived = service.archive_checkpoint(tenant_id=TENANT, actor_id=actor, checkpoint_id=checkpoint["id"])
    assert isinstance(archived, Ok) and archived.value["archived_at"] is not None

    default_listing = service.list_views(tenant_id=TENANT, equipment_id=equipment_id)
    assert default_listing[0]["checkpoints"] == []

    with_archived = service.list_views(tenant_id=TENANT, equipment_id=equipment_id, include_archived=True)
    assert [c["id"] for c in with_archived[0]["checkpoints"]] == [checkpoint["id"]]

    active_only = service.active_checkpoints(tenant_id=TENANT, equipment_id=equipment_id)
    assert active_only == []


def test_view_with_snapshotted_checkpoints_cannot_be_deleted(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)
    view = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    checkpoint = service.add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=10, y_pct=20, label="Bolt", action="tighten"
    ).value

    job_id = str(ULID())
    db.execute(
        """
        INSERT INTO maintenance.jobs
            (id, tenant_id, number, equipment_id, kind, priority, title, due_date, status, created_by)
        VALUES (%s, %s, 'JOB-1', %s, 'preventive', 'normal', 'Snapshot test', CURRENT_DATE, 'planned', %s)
        """,
        (job_id, TENANT, equipment_id, actor),
    )
    db.execute(
        """
        INSERT INTO maintenance.job_checks
            (id, tenant_id, job_id, checkpoint_id, view_id, x_pct, y_pct, label, action)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (str(ULID()), TENANT, job_id, checkpoint["id"], view["id"], 10, 20, "Bolt", "tighten"),
    )

    result = service.delete_view(tenant_id=TENANT, actor_id=actor, view_id=view["id"])
    assert isinstance(result, Err) and result.code == "VIEW_IN_USE"

    # the view and its checkpoint are untouched
    still_there = service.list_views(tenant_id=TENANT, equipment_id=equipment_id)
    assert len(still_there) == 1
    assert [c["id"] for c in still_there[0]["checkpoints"]] == [checkpoint["id"]]


def test_delete_view_cascades_its_checkpoints_when_unused(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)
    view = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    service.add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=10, y_pct=20, label="Bolt", action="tighten"
    )

    deleted = service.delete_view(tenant_id=TENANT, actor_id=actor, view_id=view["id"])
    assert isinstance(deleted, Ok)

    assert service.list_views(tenant_id=TENANT, equipment_id=equipment_id) == []
    remaining_checkpoints = db.execute(
        "SELECT count(*) FROM maintenance.checkpoints WHERE view_id = %s", (view["id"],)
    ).fetchone()[0]
    assert remaining_checkpoints == 0


def test_delete_unknown_view_is_not_found(db, actor):
    result = MapService(db).delete_view(tenant_id=TENANT, actor_id=actor, view_id="missing")
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_update_checkpoint_changes_only_given_fields(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)
    view = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    checkpoint = service.add_checkpoint(
        tenant_id=TENANT,
        actor_id=actor,
        view_id=view["id"],
        x_pct=10,
        y_pct=20,
        label="Bolt",
        action="tighten",
        instructions="Torque to spec",
    ).value

    moved = service.update_checkpoint(tenant_id=TENANT, actor_id=actor, checkpoint_id=checkpoint["id"], x_pct=30)
    assert isinstance(moved, Ok)
    assert moved.value["x_pct"] == 30.0
    assert moved.value["y_pct"] == 20.0
    assert moved.value["instructions"] == "Torque to spec"
    assert moved.value["label"] == "Bolt"


def test_checkpoints_by_ids_returns_dicts_in_the_requested_order(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)
    view = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    first = service.add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=10, y_pct=20, label="Bolt", action="tighten"
    ).value
    second = service.add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=40, y_pct=50, label="Filter", action="clean"
    ).value

    result = service.checkpoints_by_ids(tenant_id=TENANT, ids=[second["id"], first["id"]])
    assert isinstance(result, Ok)
    assert [c["id"] for c in result.value] == [second["id"], first["id"]]
    assert set(result.value[0].keys()) == {
        "id", "view_id", "x_pct", "y_pct", "label", "action", "instructions", "measure_unit",
        "requires_photo", "sort_order", "archived_at",
    }


def test_checkpoints_by_ids_refuses_missing_or_archived(db, actor):
    equipment_id = _make_equipment(db)
    service = MapService(db)
    view = service.create_view(
        tenant_id=TENANT, actor_id=actor, equipment_id=equipment_id, label="Front", image=JPEG_BYTES, mime=JPEG_MIME
    ).value
    checkpoint = service.add_checkpoint(
        tenant_id=TENANT, actor_id=actor, view_id=view["id"], x_pct=10, y_pct=20, label="Bolt", action="tighten"
    ).value
    service.archive_checkpoint(tenant_id=TENANT, actor_id=actor, checkpoint_id=checkpoint["id"])

    missing = service.checkpoints_by_ids(tenant_id=TENANT, ids=["does-not-exist"])
    assert isinstance(missing, Err) and missing.code == "UNKNOWN_CHECKPOINT"

    archived = service.checkpoints_by_ids(tenant_id=TENANT, ids=[checkpoint["id"]])
    assert isinstance(archived, Err) and archived.code == "UNKNOWN_CHECKPOINT"

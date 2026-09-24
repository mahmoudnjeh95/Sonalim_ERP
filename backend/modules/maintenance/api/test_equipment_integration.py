"""Integration tests for the production stage of a machine, against a real database.

The equipment registry is where a machine's stage is declared: the production
dashboard reads it from here, so nothing about a machine is entered twice.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.maintenance.api.equipment_service import EquipmentService

TENANT = "integration-test-equipment"
LINE = "wc-1"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _create(db, actor, code="M-1", **extra):
    return EquipmentService(db).create_equipment(
        tenant_id=TENANT, actor_id=actor, work_center_id=LINE, code=code, name=f"Machine {code}", **extra
    )


def _stored_stage(db, equipment_id):
    return db.execute("SELECT production_stage FROM maintenance.equipment WHERE id = %s", (equipment_id,)).fetchone()[0]


def test_a_machine_registered_with_a_stage_is_listed_with_it(db, actor):
    created = _create(db, actor, production_stage="extrusion")
    assert isinstance(created, Ok) and created.value.production_stage == "extrusion"

    listed = EquipmentService(db).list_equipment(tenant_id=TENANT, work_center_id=LINE)
    assert [(e.code, e.production_stage) for e in listed] == [("M-1", "extrusion")]


def test_a_machine_registered_without_a_stage_has_none(db, actor):
    created = _create(db, actor)
    assert isinstance(created, Ok) and created.value.production_stage is None
    assert _stored_stage(db, created.value.id) is None


def test_an_unknown_stage_is_refused_at_registration_and_nothing_is_saved(db, actor):
    result = _create(db, actor, production_stage="drying")
    assert isinstance(result, Err) and result.code == "INVALID_STAGE"
    assert EquipmentService(db).list_equipment(tenant_id=TENANT) == []


def test_update_sets_the_stage_and_leaves_it_alone_when_not_mentioned(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor).value

    staged = service.update_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id, production_stage="versement")
    assert isinstance(staged, Ok) and staged.value.production_stage == "versement"

    renamed = service.update_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id, name="Renamed")
    assert isinstance(renamed, Ok)
    assert (renamed.value.name, renamed.value.production_stage) == ("Renamed", "versement")
    assert _stored_stage(db, machine.id) == "versement"


def test_update_clears_the_stage_when_given_none(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor, production_stage="conditionnement").value

    cleared = service.update_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id, production_stage=None)
    assert isinstance(cleared, Ok) and cleared.value.production_stage is None
    assert _stored_stage(db, machine.id) is None


def test_update_with_an_unknown_stage_leaves_the_machine_untouched(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor, production_stage="extrusion").value

    result = service.update_equipment(
        tenant_id=TENANT, actor_id=actor, equipment_id=machine.id, name="Renamed", production_stage="drying"
    )
    assert isinstance(result, Err) and result.code == "INVALID_STAGE"
    row = db.execute("SELECT name, production_stage FROM maintenance.equipment WHERE id = %s", (machine.id,)).fetchone()
    assert row == ("Machine M-1", "extrusion")


def test_a_status_change_keeps_the_stage(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor, production_stage="extrusion").value

    moved = service.transition_status(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id, new_status="maintenance")
    assert isinstance(moved, Ok)
    assert (moved.value.status, moved.value.production_stage) == ("maintenance", "extrusion")
    assert _stored_stage(db, machine.id) == "extrusion"


def test_the_stage_is_in_the_audit_trail_of_a_registration_and_of_an_edit(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor, production_stage="versement").value
    service.update_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id, production_stage="extrusion")

    payloads = dict(
        db.execute(
            "SELECT action, payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s",
            (TENANT, machine.id),
        ).fetchall()
    )
    assert payloads["equipment.created"]["production_stage"] == "versement"
    assert payloads["equipment.updated"]["production_stage"] == "extrusion"


def test_archiving_a_machine_hides_it_from_the_default_listing(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor).value

    archived = service.archive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)
    assert isinstance(archived, Ok) and archived.value.archived_at is not None

    listed = service.list_equipment(tenant_id=TENANT, work_center_id=LINE)
    assert [e.id for e in listed] == []

    listed_with_archived = service.list_equipment(tenant_id=TENANT, work_center_id=LINE, include_archived=True)
    assert [e.id for e in listed_with_archived] == [machine.id]


def test_unarchiving_a_machine_clears_archived_at(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor).value
    service.archive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)

    unarchived = service.unarchive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)
    assert isinstance(unarchived, Ok) and unarchived.value.archived_at is None


def test_archiving_an_unknown_machine_is_not_found(db, actor):
    result = EquipmentService(db).archive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id="missing")
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_archiving_an_already_archived_machine_is_refused(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor).value
    service.archive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)

    result = service.archive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)
    assert isinstance(result, Err) and result.code == "ALREADY_ARCHIVED"


def test_unarchiving_a_machine_that_was_never_archived_is_refused(db, actor):
    machine = _create(db, actor).value

    result = EquipmentService(db).unarchive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)
    assert isinstance(result, Err) and result.code == "NOT_ARCHIVED"


def test_archive_and_unarchive_are_in_the_audit_trail(db, actor):
    service = EquipmentService(db)
    machine = _create(db, actor).value
    service.archive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)
    service.unarchive_equipment(tenant_id=TENANT, actor_id=actor, equipment_id=machine.id)

    actions = [
        row[0]
        for row in db.execute(
            "SELECT action FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s ORDER BY occurred_at",
            (TENANT, machine.id),
        ).fetchall()
    ]
    assert actions[-2:] == ["equipment.archived", "equipment.unarchived"]

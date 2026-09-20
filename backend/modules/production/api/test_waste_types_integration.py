"""The déchet kinds a plant adds for itself, against a real database.

A kind is a name and the one report it is entered on. Nothing is pre-filled: a
tenant that added nothing has only the built-ins, which live in code.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.waste_type_service import WasteTypeService, custom_waste_categories

TENANT = "integration-test-waste-types"
OTHER_TENANT = "integration-test-waste-types-other"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _create(db, actor, name="Déchet PF fab", report_type="daily", **kwargs):
    result = WasteTypeService(db).create_type(
        tenant_id=TENANT, actor_id=actor, name=name, report_type=report_type, **kwargs
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def test_a_tenant_that_added_nothing_has_no_types(db):
    assert WasteTypeService(db).list_types(tenant_id=TENANT) == []


def test_a_type_is_stored_with_its_name_and_its_report(db, actor):
    created = _create(db, actor, name="Déchet PF fab", report_type="daily", sort_order=3)
    assert created["name"] == "Déchet PF fab"
    assert created["report_type"] == "daily"
    assert created["sort_order"] == 3
    assert created["is_active"] is True
    assert WasteTypeService(db).list_types(tenant_id=TENANT) == [created]


def test_the_name_is_trimmed(db, actor):
    assert _create(db, actor, name="  Pâte non conforme  ")["name"] == "Pâte non conforme"


def test_a_blank_name_and_an_unknown_report_are_refused(db, actor):
    service = WasteTypeService(db)
    blank = service.create_type(tenant_id=TENANT, actor_id=actor, name="  ", report_type="daily")
    assert isinstance(blank, Err) and blank.code == "INVALID_NAME"
    unknown = service.create_type(tenant_id=TENANT, actor_id=actor, name="x", report_type="quality")
    assert isinstance(unknown, Err) and unknown.code == "INVALID_REPORT_TYPE"
    assert service.list_types(tenant_id=TENANT) == []


def test_the_same_name_twice_on_one_report_is_a_duplicate_whatever_the_case(db, actor):
    _create(db, actor, name="Crosse")
    again = WasteTypeService(db).create_type(tenant_id=TENANT, actor_id=actor, name="CROSSE", report_type="daily")
    assert isinstance(again, Err)
    assert again.code == "DUPLICATE_WASTE_TYPE"


def test_the_same_name_may_exist_on_the_other_report(db, actor):
    """"Déchet cello" on the packing report and on the daily report are two
    different stages that happen to share a word."""
    _create(db, actor, name="Déchet", report_type="daily")
    _create(db, actor, name="Déchet", report_type="conditionnement")
    assert len(WasteTypeService(db).list_types(tenant_id=TENANT)) == 2


def test_adding_a_retired_name_brings_it_back(db, actor):
    service = WasteTypeService(db)
    created = _create(db, actor, name="Crosse")
    service.update_type(tenant_id=TENANT, actor_id=actor, waste_type_id=created["id"], is_active=False)

    again = service.create_type(tenant_id=TENANT, actor_id=actor, name="crosse", report_type="daily")
    assert isinstance(again, Ok)
    assert again.value["id"] == created["id"]
    assert again.value["is_active"] is True


def test_a_type_can_be_renamed_and_reordered_but_stays_on_its_report(db, actor):
    service = WasteTypeService(db)
    created = _create(db, actor, name="Crosse", report_type="conditionnement", sort_order=1)
    result = service.update_type(
        tenant_id=TENANT, actor_id=actor, waste_type_id=created["id"], name="Cross", sort_order=7
    )
    assert isinstance(result, Ok)
    assert (result.value["name"], result.value["sort_order"], result.value["report_type"]) == (
        "Cross", 7, "conditionnement",
    )


def test_renaming_onto_an_existing_name_is_refused(db, actor):
    service = WasteTypeService(db)
    _create(db, actor, name="Crosse")
    other = _create(db, actor, name="Pétrin")
    result = service.update_type(tenant_id=TENANT, actor_id=actor, waste_type_id=other["id"], name="crosse")
    assert isinstance(result, Err)
    assert result.code == "DUPLICATE_WASTE_TYPE"


def test_renaming_a_type_to_itself_in_another_case_is_not_a_clash(db, actor):
    created = _create(db, actor, name="crosse")
    result = WasteTypeService(db).update_type(
        tenant_id=TENANT, actor_id=actor, waste_type_id=created["id"], name="Crosse"
    )
    assert isinstance(result, Ok)
    assert result.value["name"] == "Crosse"


def test_updating_a_type_that_does_not_exist_says_so(db, actor):
    result = WasteTypeService(db).update_type(tenant_id=TENANT, actor_id=actor, waste_type_id="nope", name="x")
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


def test_a_type_of_another_tenant_cannot_be_touched(db, actor):
    theirs = WasteTypeService(db).create_type(
        tenant_id=OTHER_TENANT, actor_id=actor, name="Crosse", report_type="daily"
    )
    assert isinstance(theirs, Ok)
    result = WasteTypeService(db).update_type(
        tenant_id=TENANT, actor_id=actor, waste_type_id=theirs.value["id"], name="Mine now"
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"
    assert WasteTypeService(db).list_types(tenant_id=TENANT) == []


def test_types_are_listed_by_report_then_order_then_name(db, actor):
    _create(db, actor, name="Zeta", report_type="daily", sort_order=1)
    _create(db, actor, name="Alpha", report_type="daily", sort_order=1)
    _create(db, actor, name="First", report_type="daily", sort_order=0)
    _create(db, actor, name="Film", report_type="conditionnement")
    listed = WasteTypeService(db).list_types(tenant_id=TENANT)
    assert [(t["report_type"], t["name"]) for t in listed] == [
        ("conditionnement", "Film"), ("daily", "First"), ("daily", "Alpha"), ("daily", "Zeta"),
    ]


def test_retired_types_can_be_left_out_of_a_list(db, actor):
    service = WasteTypeService(db)
    kept = _create(db, actor, name="Kept")
    retired = _create(db, actor, name="Retired")
    service.update_type(tenant_id=TENANT, actor_id=actor, waste_type_id=retired["id"], is_active=False)

    assert [t["id"] for t in service.list_types(tenant_id=TENANT, include_inactive=False)] == [kept["id"]]
    assert {t["id"] for t in service.list_types(tenant_id=TENANT)} == {kept["id"], retired["id"]}


def test_the_categories_a_report_may_use_include_retired_ones_for_that_report_only(db, actor):
    """A retired type stays valid so a report that used it can still be edited;
    a type of the other report is never valid here."""
    daily = _create(db, actor, name="Daily kind", report_type="daily")
    retired = _create(db, actor, name="Old kind", report_type="daily")
    packing = _create(db, actor, name="Packing kind", report_type="conditionnement")
    WasteTypeService(db).update_type(tenant_id=TENANT, actor_id=actor, waste_type_id=retired["id"], is_active=False)

    assert custom_waste_categories(db, tenant_id=TENANT, report_type="daily") == {daily["id"], retired["id"]}
    assert custom_waste_categories(db, tenant_id=TENANT, report_type="conditionnement") == {packing["id"]}
    assert custom_waste_categories(db, tenant_id=OTHER_TENANT, report_type="daily") == frozenset()


def test_creating_and_updating_are_both_audited(db, actor):
    created = _create(db, actor, name="Crosse")
    WasteTypeService(db).update_type(tenant_id=TENANT, actor_id=actor, waste_type_id=created["id"], name="Cross")

    rows = db.execute(
        "SELECT action, actor_id, payload FROM core.audit_log "
        "WHERE tenant_id = %s AND entity_type = 'waste_type' AND entity_id = %s ORDER BY occurred_at, id",
        (TENANT, created["id"]),
    ).fetchall()
    assert [row[0] for row in rows] == ["waste_type.created", "waste_type.updated"]
    assert all(row[1] == actor for row in rows)
    assert rows[1][2]["previous_name"] == "Crosse"
    assert rows[1][2]["name"] == "Cross"

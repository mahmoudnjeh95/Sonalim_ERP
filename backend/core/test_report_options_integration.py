"""Integration tests for the per-tenant shift and team lists.

The behaviour worth pinning is what happens to a name that reports were already
filed under. Reports store the label rather than a reference, so the table is
free to change — which is exactly why the rules have to be deliberate: renaming
must not rewrite history, and retiring must not make the archive unreadable.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.report_options import ReportOptionsService

TENANT = "integration-test-report-options"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _create(db, actor, kind="shift", label="Matin", sort_order=0):
    result = ReportOptionsService(db).create_option(
        tenant_id=TENANT, actor_id=actor, kind=kind, label=label, sort_order=sort_order
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


# --- the list itself --------------------------------------------------------


def test_shifts_and_teams_are_separate_lists(db, actor):
    _create(db, actor, kind="shift", label="Matin")
    _create(db, actor, kind="team", label="Équipe A")

    service = ReportOptionsService(db)
    assert [o["label"] for o in service.list_options(tenant_id=TENANT, kind="shift")] == ["Matin"]
    assert [o["label"] for o in service.list_options(tenant_id=TENANT, kind="team")] == ["Équipe A"]
    assert len(service.list_options(tenant_id=TENANT)) == 2


def test_options_come_back_in_the_order_the_plant_thinks_in(db, actor):
    """Morning, afternoon, night — not alphabetical, which would read A, M, N."""
    _create(db, actor, label="Nuit", sort_order=3)
    _create(db, actor, label="Après-midi", sort_order=2)
    _create(db, actor, label="Matin", sort_order=1)

    labels = [o["label"] for o in ReportOptionsService(db).list_options(tenant_id=TENANT, kind="shift")]
    assert labels == ["Matin", "Après-midi", "Nuit"]


def test_a_blank_name_is_refused(db, actor):
    result = ReportOptionsService(db).create_option(
        tenant_id=TENANT, actor_id=actor, kind="shift", label="   "
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_LABEL"


def test_an_unknown_kind_is_refused(db, actor):
    result = ReportOptionsService(db).create_option(
        tenant_id=TENANT, actor_id=actor, kind="crew", label="Matin"
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_KIND"


def test_the_name_is_trimmed_on_the_way_in(db, actor):
    option = _create(db, actor, label="  Matin  ")
    assert option["label"] == "Matin"


# --- duplicates -------------------------------------------------------------


def test_the_same_shift_cannot_be_added_twice(db, actor):
    _create(db, actor, label="Matin")
    duplicate = ReportOptionsService(db).create_option(
        tenant_id=TENANT, actor_id=actor, kind="shift", label="Matin"
    )
    assert isinstance(duplicate, Err)
    assert duplicate.code == "DUPLICATE_OPTION"


def test_case_and_spacing_do_not_make_a_new_shift(db, actor):
    """"matin" and "Matin" are the same shift. Letting both in is the mess the
    table exists to prevent."""
    _create(db, actor, label="Matin")
    duplicate = ReportOptionsService(db).create_option(
        tenant_id=TENANT, actor_id=actor, kind="shift", label="  matin "
    )
    assert isinstance(duplicate, Err)
    assert duplicate.code == "DUPLICATE_OPTION"


def test_a_shift_and_a_team_may_share_a_name(db, actor):
    _create(db, actor, kind="shift", label="A")
    result = ReportOptionsService(db).create_option(tenant_id=TENANT, actor_id=actor, kind="team", label="A")
    assert isinstance(result, Ok)


def test_re_adding_a_retired_name_brings_it_back(db, actor):
    """A supervisor typing the name again means "we run this shift again", not
    "give me a second copy of it"."""
    service = ReportOptionsService(db)
    option = _create(db, actor, label="Nuit")
    service.update_option(tenant_id=TENANT, actor_id=actor, option_id=option["id"], is_active=False)

    revived = service.create_option(tenant_id=TENANT, actor_id=actor, kind="shift", label="Nuit")
    assert isinstance(revived, Ok)
    assert revived.value["id"] == option["id"], "the same row, not a duplicate"
    assert revived.value["is_active"] is True


# --- renaming ---------------------------------------------------------------


def test_renaming_leaves_filed_reports_alone(db, actor):
    """The report says what it was filed as. Renaming the option changes what the
    next report may choose, never what an old one claims happened."""
    option = _create(db, actor, label="Matin")
    _file_report(db, actor, shift="Matin")

    renamed = ReportOptionsService(db).update_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"], label="Équipe A"
    )
    assert isinstance(renamed, Ok)
    assert renamed.value["label"] == "Équipe A"

    row = db.execute(
        "SELECT shift FROM production.production_reports WHERE tenant_id = %s", (TENANT,)
    ).fetchone()
    assert row[0] == "Matin"


def test_renaming_onto_an_existing_name_is_refused(db, actor):
    _create(db, actor, label="Matin")
    afternoon = _create(db, actor, label="Après-midi")

    clash = ReportOptionsService(db).update_option(
        tenant_id=TENANT, actor_id=actor, option_id=afternoon["id"], label="matin"
    )
    assert isinstance(clash, Err)
    assert clash.code == "DUPLICATE_OPTION"


def test_an_option_can_be_renamed_to_its_own_name(db, actor):
    """Saving a form without touching the name must not trip the duplicate check
    against the row being edited."""
    option = _create(db, actor, label="Matin")
    result = ReportOptionsService(db).update_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"], label="Matin", sort_order=5
    )
    assert isinstance(result, Ok)
    assert result.value["sort_order"] == 5


def test_updating_only_the_order_keeps_the_name(db, actor):
    option = _create(db, actor, label="Matin", sort_order=1)
    result = ReportOptionsService(db).update_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"], sort_order=9
    )
    assert isinstance(result, Ok)
    assert result.value["label"] == "Matin"
    assert result.value["sort_order"] == 9


def test_updating_an_unknown_option_is_not_found(db, actor):
    result = ReportOptionsService(db).update_option(
        tenant_id=TENANT, actor_id=actor, option_id=str(ULID()), label="Matin"
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


# --- retiring and deleting --------------------------------------------------


def test_an_unused_option_is_deleted_outright(db, actor):
    option = _create(db, actor, label="Matin")
    result = ReportOptionsService(db).delete_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"]
    )
    assert isinstance(result, Ok)
    assert result.value["outcome"] == "deleted"
    assert ReportOptionsService(db).list_options(tenant_id=TENANT, include_inactive=True) == []


def test_an_option_reports_were_filed_under_is_retired_not_removed(db, actor):
    """Deleting the row would leave the archive full of shift names nothing
    explains. Retiring takes it off tomorrow's form and keeps the history."""
    option = _create(db, actor, label="Matin")
    _file_report(db, actor, shift="Matin")

    result = ReportOptionsService(db).delete_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"]
    )
    assert isinstance(result, Ok)
    assert result.value["outcome"] == "retired"

    service = ReportOptionsService(db)
    assert service.list_options(tenant_id=TENANT) == [], "no longer offered"
    assert len(service.list_options(tenant_id=TENANT, include_inactive=True)) == 1, "still on record"


def test_a_team_used_by_a_quality_report_is_retired_too(db, actor):
    """qc files against the same lists, so its reports have to count as use."""
    option = _create(db, actor, kind="team", label="Équipe A")
    _file_quality_report(db, actor, team="Équipe A")

    result = ReportOptionsService(db).delete_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"]
    )
    assert isinstance(result, Ok)
    assert result.value["outcome"] == "retired"


def test_use_is_matched_regardless_of_case(db, actor):
    option = _create(db, actor, label="Matin")
    _file_report(db, actor, shift="MATIN")

    result = ReportOptionsService(db).delete_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"]
    )
    assert result.value["outcome"] == "retired"


def test_a_shift_is_not_retired_because_a_team_shares_its_name(db, actor):
    """The shift column is checked for shifts and the team column for teams;
    crossing them would retire options nobody has used."""
    shift = _create(db, actor, kind="shift", label="A")
    _file_report(db, actor, shift="Matin", team="A")

    result = ReportOptionsService(db).delete_option(tenant_id=TENANT, actor_id=actor, option_id=shift["id"])
    assert result.value["outcome"] == "deleted"


def test_deleting_an_unknown_option_is_not_found(db, actor):
    result = ReportOptionsService(db).delete_option(
        tenant_id=TENANT, actor_id=actor, option_id=str(ULID())
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


# --- tenancy and audit ------------------------------------------------------


def test_another_tenants_lists_are_invisible(db, actor):
    _create(db, actor, label="Matin")
    other = ReportOptionsService(db).list_options(tenant_id="some-other-tenant")
    assert other == []


def test_two_tenants_may_use_the_same_shift_name(db, actor):
    other_actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (other_actor, "other-tenant", f"{other_actor}@test.local"),
    )
    _create(db, actor, label="Matin")
    result = ReportOptionsService(db).create_option(
        tenant_id="other-tenant", actor_id=other_actor, kind="shift", label="Matin"
    )
    assert isinstance(result, Ok)


def test_every_change_lands_in_the_audit_trail(db, actor):
    service = ReportOptionsService(db)
    option = _create(db, actor, label="Matin")
    service.update_option(tenant_id=TENANT, actor_id=actor, option_id=option["id"], label="Nuit")
    service.delete_option(tenant_id=TENANT, actor_id=actor, option_id=option["id"])

    actions = [
        row[0]
        for row in db.execute(
            "SELECT action FROM core.audit_log WHERE entity_id = %s ORDER BY occurred_at, action", (option["id"],)
        ).fetchall()
    ]
    assert "report_option.created" in actions
    assert "report_option.updated" in actions
    assert "report_option.deleted" in actions


def test_the_rename_records_what_it_replaced(db, actor):
    option = _create(db, actor, label="Matin")
    ReportOptionsService(db).update_option(
        tenant_id=TENANT, actor_id=actor, option_id=option["id"], label="Nuit"
    )
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'report_option.updated'",
        (option["id"],),
    ).fetchone()[0]
    assert payload["previous_label"] == "Matin"
    assert payload["label"] == "Nuit"


# --- helpers ----------------------------------------------------------------


def _file_report(db, actor, *, shift="Matin", team=None):
    """A bare production report row. The lists are matched on the stored label,
    so nothing here needs to go through the report service."""
    of_id = _work_order(db, actor)
    db.execute(
        "INSERT INTO production.production_reports "
        "(id, tenant_id, of_id, report_type, report_date, team, shift, status, created_by) "
        "VALUES (%s, %s, %s, 'daily', %s, %s, %s, 'draft', %s)",
        (str(ULID()), TENANT, of_id, datetime.date(2026, 9, 1), team, shift, actor),
    )


def _file_quality_report(db, actor, *, shift="Matin", team=None):
    of_id = _work_order(db, actor)
    db.execute(
        "INSERT INTO qc.quality_reports (id, tenant_id, of_id, report_date, team, shift, status, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s)",
        (str(ULID()), TENANT, of_id, datetime.date(2026, 9, 1), team, shift, actor),
    )


def _work_order(db, actor) -> str:
    """The minimum OF a report row can point at."""
    uom, product, work_center, of_id = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, %s, 'Kilogram', 'weight')",
        (uom, TENANT, f"kg-{uom[-6:]}"),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, 'Pasta', %s)",
        (product, TENANT, f"SKU-{product[-6:]}", uom),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Line')",
        (work_center, TENANT, f"WC-{work_center[-6:]}"),
    )
    db.execute(
        "INSERT INTO production.work_orders "
        "(id, tenant_id, reference, product_id, planned_quantity, status, work_center_id) "
        "VALUES (%s, %s, %s, %s, 1000, 'planned', %s)",
        (of_id, TENANT, f"OF-{of_id[-6:]}", product, work_center),
    )
    return of_id

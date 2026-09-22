"""Integration tests for the dashboard's configuration lists, against a real database.

Each list is replaced as a whole and starts empty: a tenant that configured
nothing gets nothing back, not a suggested default.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.domain.dashboard import ShiftWindow

TENANT = "integration-test-dashboard-settings"
T = datetime.time


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def test_a_tenant_that_configured_nothing_gets_empty_lists(db):
    # Nothing about machines: their lines, names, states and stages are read from maintenance.
    assert DashboardSettingsService(db).get_settings(tenant_id=TENANT) == {
        "shift_windows": [],
        "team_rotation": [],
        "store_roles": [],
    }


def test_shift_windows_round_trip_including_a_window_through_midnight(db, actor):
    service = DashboardSettingsService(db)
    windows = [
        ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)),
        ShiftWindow(shift="Shift 3", start=T(23, 0), end=T(7, 0)),
    ]
    assert isinstance(service.replace_shift_windows(tenant_id=TENANT, actor_id=actor, windows=windows), Ok)

    stored = service.get_settings(tenant_id=TENANT)["shift_windows"]
    assert {(w["shift"], w["start_time"], w["end_time"]) for w in stored} == {
        ("Shift 1", "07:00", "15:00"),
        ("Shift 3", "23:00", "07:00"),
    }
    assert {w.shift for w in service.list_shift_windows(tenant_id=TENANT)} == {"Shift 1", "Shift 3"}
    # Each shift says how long it runs, the night one across midnight.
    assert {w["shift"]: w["length_minutes"] for w in stored} == {"Shift 1": 8 * 60, "Shift 3": 8 * 60}


def test_replacing_shift_windows_drops_the_ones_left_out(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor,
        windows=[ShiftWindow(shift="A", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="B", start=T(15, 0), end=T(23, 0))],
    )
    service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor, windows=[ShiftWindow(shift="B", start=T(15, 0), end=T(23, 0))]
    )
    assert [w["shift"] for w in service.get_settings(tenant_id=TENANT)["shift_windows"]] == ["B"]


def test_shift_windows_reject_a_zero_length_shift_and_a_repeated_name(db, actor):
    service = DashboardSettingsService(db)
    zero = service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor, windows=[ShiftWindow(shift="A", start=T(7, 0), end=T(7, 0))]
    )
    assert isinstance(zero, Err) and zero.code == "INVALID_TIME_RANGE"
    twice = service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor,
        windows=[ShiftWindow(shift="A", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="a", start=T(15, 0), end=T(23, 0))],
    )
    assert isinstance(twice, Err) and twice.code == "DUPLICATE_ENTRY"


def test_team_rotation_needs_shifts_configured_first(db, actor):
    result = DashboardSettingsService(db).replace_team_rotation(
        tenant_id=TENANT, actor_id=actor, entries=[{"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 0}]
    )
    assert isinstance(result, Err) and result.code == "NO_SHIFTS_CONFIGURED"


def test_team_rotation_round_trip(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor,
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    entries = [
        {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
        {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
        {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 2},
    ]
    assert isinstance(service.replace_team_rotation(tenant_id=TENANT, actor_id=actor, entries=entries), Ok)
    stored = service.get_settings(tenant_id=TENANT)["team_rotation"]
    assert {(r["team"], r["anchor_date"], r["anchor_stop"]) for r in stored} == {
        ("B", "2026-09-19", 0), ("C", "2026-09-19", 1), ("A", "2026-09-19", 2),
    }


def test_team_rotation_rejects_the_wrong_number_of_teams(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor,
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    result = service.replace_team_rotation(
        tenant_id=TENANT, actor_id=actor, entries=[{"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 0}]
    )
    assert isinstance(result, Err) and result.code == "WRONG_TEAM_COUNT"


def test_replacing_team_rotation_drops_what_it_leaves_out(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(tenant_id=TENANT, actor_id=actor, windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0))])
    service.replace_team_rotation(
        tenant_id=TENANT, actor_id=actor,
        entries=[{"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 0}, {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 1}],
    )
    service.replace_team_rotation(
        tenant_id=TENANT, actor_id=actor,
        entries=[{"team": "C", "anchor_date": "2026-09-20", "anchor_stop": 0}, {"team": "D", "anchor_date": "2026-09-20", "anchor_stop": 1}],
    )
    assert {r["team"] for r in service.get_settings(tenant_id=TENANT)["team_rotation"]} == {"C", "D"}


def test_store_role_is_line_or_final_and_a_store_has_one_role(db, actor):
    service = DashboardSettingsService(db)
    assert isinstance(
        service.replace_store_roles(
            tenant_id=TENANT, actor_id=actor,
            entries=[{"location_id": "loc-1", "role": "line"}, {"location_id": "loc-2", "role": "final"}],
        ),
        Ok,
    )
    twice = service.replace_store_roles(
        tenant_id=TENANT, actor_id=actor,
        entries=[{"location_id": "loc-1", "role": "line"}, {"location_id": "loc-1", "role": "final"}],
    )
    assert isinstance(twice, Err) and twice.code == "DUPLICATE_ENTRY"


def test_settings_are_scoped_to_their_tenant(db, actor):
    service = DashboardSettingsService(db)
    service.replace_store_roles(
        tenant_id=TENANT, actor_id=actor, entries=[{"location_id": "loc-1", "role": "line"}]
    )
    assert service.get_settings(tenant_id="some-other-tenant")["store_roles"] == []


def test_every_replacement_is_audited(db, actor):
    DashboardSettingsService(db).replace_store_roles(
        tenant_id=TENANT, actor_id=actor, entries=[{"location_id": "loc-1", "role": "final"}]
    )
    row = db.execute(
        "SELECT action, entity_type, entity_id FROM core.audit_log WHERE tenant_id = %s AND entity_type = 'dashboard_settings'",
        (TENANT,),
    ).fetchone()
    assert row == ("dashboard_settings.replaced", "dashboard_settings", "store_roles")

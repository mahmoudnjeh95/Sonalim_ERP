"""Integration tests for the dashboard's live board, against a real database.

The board reads recorded facts only: the OF's own status, the machines' own
status (through maintenance's public service), and the roster and shift times
the plant configured.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from core.report_options import ReportOptionsService
from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.api.dashboard_lines_service import DashboardLinesService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.domain.dashboard import ShiftWindow

TENANT = "integration-test-dashboard-lines"
T = datetime.time


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, product_type) VALUES (%s, %s, 'DL-PASTA', 'Doman PL 500 g', %s, 'PL')",
        (product, TENANT, uom),
    )
    return {"actor": actor, "product": product}


def _line(db, code):
    line_id = str(ULID())
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
        (line_id, TENANT, code, f"Ligne {code}"),
    )
    return line_id


def _machine(db, env, line_id, code, status="operational", stage=None):
    machine_id = str(ULID())
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, status, production_stage) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (machine_id, TENANT, line_id, code, f"Machine {code}", status, stage),
    )
    return machine_id


def _of(db, env, line_id, status, reference="OF-1"):
    of_id = str(ULID())
    db.execute(
        "INSERT INTO production.work_orders (id, tenant_id, product_id, planned_quantity, status, reference, work_center_id, product_type, start_date) "
        "VALUES (%s, %s, %s, 100, %s, %s, %s, 'PL', %s)",
        (of_id, TENANT, env["product"], status, reference, line_id, datetime.date(2026, 8, 4)),
    )
    return of_id


def _lines(db, at=T(8, 4), date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 19)):
    return DashboardLinesService(db).get_lines(tenant_id=TENANT, at=at, date=date, today=today)


def _by_code(payload):
    return {line["code"]: line for line in payload["lines"]}


def _team(db, actor, *labels: str) -> None:
    """Register each label as an active team in Report Options -- what a rotation's
    team names are validated against."""
    for label in labels:
        result = ReportOptionsService(db).create_option(tenant_id=TENANT, actor_id=actor, kind="team", label=label)
        assert isinstance(result, Ok), getattr(result, "message", "")


def test_a_line_with_no_open_of_carries_an_empty_list_of_ofs(db, env):
    # The read lists every line (its name is needed to label past figures); it is
    # the board that shows only the lines with an OF on them.
    _line(db, "L1")
    line = _by_code(_lines(db))["L1"]
    assert line["ofs"] == []


def test_ongoing_of_on_operational_machines_is_running(db, env):
    line_id = _line(db, "L1")
    _machine(db, env, line_id, "M1")
    _of(db, env, line_id, "ongoing", "OF-0142")
    of = _by_code(_lines(db))["L1"]["ofs"][0]
    assert (of["reference"], of["state"], of["product_type"], of["product_name"]) == ("OF-0142", "running", "PL", "Doman PL 500 g")
    assert of["start_date"] == "2026-08-04"


def test_machine_in_maintenance_makes_the_line_yellow_and_down_makes_it_red(db, env):
    yellow, red = _line(db, "L1"), _line(db, "L2")
    _machine(db, env, yellow, "M1", "maintenance")
    _machine(db, env, red, "M2", "operational")
    _machine(db, env, red, "M3", "down")
    _of(db, env, yellow, "ongoing", "OF-1")
    _of(db, env, red, "ongoing", "OF-2")
    payload = _by_code(_lines(db))
    assert payload["L1"]["ofs"][0]["state"] == "maintenance"
    assert payload["L2"]["ofs"][0]["state"] == "down"


def test_closed_and_planned_ofs_do_not_appear_and_suspended_does(db, env):
    line_id = _line(db, "L1")
    _of(db, env, line_id, "closed", "OF-C")
    _of(db, env, line_id, "planned", "OF-P")
    _of(db, env, line_id, "suspended", "OF-S")
    ofs = _by_code(_lines(db))["L1"]["ofs"]
    assert [(o["reference"], o["state"]) for o in ofs] == [("OF-S", "suspended")]


def test_two_ofs_on_two_lines_are_each_reported_under_their_own_line(db, env):
    a, b = _line(db, "L1"), _line(db, "L2")
    _of(db, env, a, "ongoing", "OF-A")
    _of(db, env, b, "ongoing", "OF-B")
    payload = _by_code(_lines(db))
    assert [o["reference"] for o in payload["L1"]["ofs"]] == ["OF-A"]
    assert [o["reference"] for o in payload["L2"]["ofs"]] == ["OF-B"]


def test_every_machine_declared_on_a_line_is_listed_without_any_stage_configured(db, env):
    line_id = _line(db, "L1")
    other_line = _line(db, "L2")
    _machine(db, env, line_id, "PL-02")
    _machine(db, env, line_id, "PL-01")
    _machine(db, env, other_line, "PC-01")
    machines = _by_code(_lines(db))["L1"]["machines"]
    assert [(m["code"], m["stage"]) for m in machines] == [("PL-01", None), ("PL-02", None)]

    # A machine added afterwards shows up with no further setup.
    _machine(db, env, line_id, "PL-03")
    machines = _by_code(_lines(db))["L1"]["machines"]
    assert [m["code"] for m in machines] == ["PL-01", "PL-02", "PL-03"]


def test_machines_keep_their_own_status_and_are_never_merged_by_stage(db, env):
    line_id = _line(db, "L1")
    _machine(db, env, line_id, "M1", "operational", stage="versement")
    _machine(db, env, line_id, "M2", "maintenance", stage="extrusion")
    _machine(db, env, line_id, "M3", "down", stage="extrusion")
    machines = _by_code(_lines(db))["L1"]["machines"]
    assert [(m["code"], m["stage"], m["status"]) for m in machines] == [
        ("M1", "versement", "operational"),
        ("M2", "extrusion", "maintenance"),
        ("M3", "extrusion", "down"),
    ]


def test_staged_machines_come_in_stage_order_and_machines_with_no_stage_stay_on_the_belt(db, env):
    line_id = _line(db, "L1")
    _machine(db, env, line_id, "A-PACK", stage="conditionnement")
    _machine(db, env, line_id, "Z-POUR", stage="versement")
    _machine(db, env, line_id, "M-NONE")  # registered with no stage
    machines = _by_code(_lines(db))["L1"]["machines"]
    assert [(m["code"], m["stage"]) for m in machines] == [
        ("Z-POUR", "versement"),
        ("A-PACK", "conditionnement"),
        ("M-NONE", None),
    ]


def test_team_status_is_empty_when_no_rotation_is_configured(db, env):
    _line(db, "L1")
    payload = _lines(db)
    assert payload["current_shift"] is None
    assert _by_code(payload)["L1"]["team_status"] == []


def test_team_status_lists_every_team_with_the_shift_it_is_on_and_flags_the_current_one(db, env):
    line_id = _line(db, "L1")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[
            ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)),
            ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0)),
            ShiftWindow(shift="Shift 3", start=T(23, 0), end=T(7, 0)),
        ],
    )
    _team(db, env["actor"], "B", "C", "D", "A")
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
            {"team": "D", "anchor_date": "2026-09-19", "anchor_stop": 2},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 3},
        ],
    )
    payload = _lines(db, at=T(8, 4), date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 19))
    assert payload["current_shift"]["shift"] == "Shift 1"
    team_status = _by_code(payload)["L1"]["team_status"]
    assert {(e["team"], e["shift"], e["is_current"]) for e in team_status} == {
        ("B", "Shift 1", True), ("C", "Shift 2", False), ("D", "Shift 3", False), ("A", None, False),
    }
    # The rotation moves forward: three days later a different team is on Shift 1.
    later = _by_code(_lines(db, at=T(8, 4), date=datetime.date(2026, 9, 22), today=datetime.date(2026, 9, 22)))["L1"]["team_status"]
    assert {(e["team"], e["shift"]) for e in later} == {
        ("C", "Shift 1"), ("D", "Shift 2"), ("A", "Shift 3"), ("B", None),
    }


def test_team_status_colour_follows_the_shift_report_for_that_slot(db, env):
    line_id = _line(db, "L1")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    _team(db, env["actor"], "B", "C", "A")
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 2},
        ],
    )
    for shift, report_status in (("Shift 1", "validated"), ("Shift 2", "returned")):
        db.execute(
            "INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (str(ULID()), TENANT, line_id, datetime.date(2026, 9, 19), shift, report_status),
        )
    # Viewed as a past day (today is the 20th): the colours reflect the reports, nothing blinks.
    team_status = _by_code(_lines(db, date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 20)))["L1"]["team_status"]
    assert {(e["team"], e["status"]) for e in team_status} == {("B", "validated"), ("C", "returned"), ("A", None)}
    assert all(not e["is_current"] for e in team_status)


def test_team_status_shows_submitted_and_open_reports(db, env):
    line_id = _line(db, "L1")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    _team(db, env["actor"], "B", "C", "A")
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 2},
        ],
    )
    for shift, report_status in (("Shift 1", "submitted"), ("Shift 2", "open")):
        db.execute(
            "INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (str(ULID()), TENANT, line_id, datetime.date(2026, 9, 19), shift, report_status),
        )
    team_status = _by_code(_lines(db, date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 20)))["L1"]["team_status"]
    assert {(e["team"], e["status"]) for e in team_status} == {("B", "submitted"), ("C", "open"), ("A", None)}


def test_team_status_is_isolated_per_line_for_the_same_team_and_date(db, env):
    line1, line2 = _line(db, "L1"), _line(db, "L2")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"], windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0))],
    )
    _team(db, env["actor"], "B", "A")
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 1},
        ],
    )
    db.execute(
        "INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, status) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (str(ULID()), TENANT, line1, datetime.date(2026, 9, 19), "Shift 1", "validated"),
    )
    db.execute(
        "INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, status) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (str(ULID()), TENANT, line2, datetime.date(2026, 9, 19), "Shift 1", "submitted"),
    )
    payload = _by_code(_lines(db, date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 20)))
    team_b_on_l1 = next(e for e in payload["L1"]["team_status"] if e["team"] == "B")
    team_b_on_l2 = next(e for e in payload["L2"]["team_status"] if e["team"] == "B")
    assert team_b_on_l1["status"] == "validated"
    assert team_b_on_l2["status"] == "submitted"


def test_team_status_is_empty_when_the_rotation_no_longer_matches_the_shift_count(db, env):
    _line(db, "L1")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[
            ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)),
            ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0)),
            ShiftWindow(shift="Shift 3", start=T(23, 0), end=T(7, 0)),
        ],
    )
    _team(db, env["actor"], "B", "C", "D", "A")
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
            {"team": "D", "anchor_date": "2026-09-19", "anchor_stop": 2},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 3},
        ],
    )
    # The shift count changes after the rotation was saved (e.g. a shift is removed); the
    # stored stops no longer number the same cycle, so the board must not guess a schedule.
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[
            ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)),
            ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0)),
        ],
    )
    team_status = _by_code(_lines(db, date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 19)))["L1"]["team_status"]
    assert team_status == []


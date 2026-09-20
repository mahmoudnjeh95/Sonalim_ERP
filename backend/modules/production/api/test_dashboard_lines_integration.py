"""Integration tests for the dashboard's live board, against a real database.

The board reads recorded facts only: the OF's own status, the machines' own
status (through maintenance's public service), and the roster and shift times
the plant configured.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

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


def _lines(db, at=T(8, 4)):
    return DashboardLinesService(db).get_lines(tenant_id=TENANT, at=at)


def _by_code(payload):
    return {line["code"]: line for line in payload["lines"]}


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


def test_roster_lists_every_shift_and_flags_the_current_one(db, env):
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
    settings.replace_roster(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"work_center_id": line_id, "shift": "Shift 1", "team": "A"},
            {"work_center_id": line_id, "shift": "Shift 2", "team": "B"},
            {"work_center_id": line_id, "shift": "Shift 3", "team": "C"},
        ],
    )
    payload = _lines(db, at=T(8, 4))
    assert payload["current_shift"]["shift"] == "Shift 1"
    assert [(w["shift"], w["start_time"], w["end_time"]) for w in payload["shift_windows"]] == [
        ("Shift 1", "07:00", "15:00"), ("Shift 2", "15:00", "23:00"), ("Shift 3", "23:00", "07:00"),
    ]
    roster = _by_code(payload)["L1"]["roster"]
    assert [(r["shift"], r["team"], r["is_current"]) for r in roster] == [
        ("Shift 1", "A", True), ("Shift 2", "B", False), ("Shift 3", "C", False),
    ]
    assert roster[0]["start_time"] == "07:00" and roster[2]["end_time"] == "07:00"

    overnight = _lines(db, at=T(1, 30))
    assert overnight["current_shift"]["shift"] == "Shift 3"
    assert [r["is_current"] for r in _by_code(overnight)["L1"]["roster"]] == [False, False, True]


def test_nothing_is_current_when_no_shift_windows_are_configured(db, env):
    line_id = _line(db, "L1")
    DashboardSettingsService(db).replace_roster(
        tenant_id=TENANT, actor_id=env["actor"], entries=[{"work_center_id": line_id, "shift": "Shift 1", "team": "A"}]
    )
    payload = _lines(db)
    assert payload["current_shift"] is None
    roster = _by_code(payload)["L1"]["roster"]
    assert [(r["team"], r["is_current"], r["start_time"]) for r in roster] == [("A", False, None)]


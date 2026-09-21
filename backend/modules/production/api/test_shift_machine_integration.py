"""What validating a shift does to machines: the report's machine, and the silo reading's status change."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "shift-machine-test"
DAY = datetime.date(2030, 8, 5)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor, uom, pasta, semolina, silo, fg, work_center = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((pasta, "SM-PASTA"), (semolina, "SM-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SM-SILO', 'Silo')", (silo, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SM-FG', 'FG')", (fg, TENANT))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg, pasta))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SM-WC', 'Line')", (work_center, TENANT))
    machines = {}
    for stage in ("versement", "extrusion", "conditionnement"):
        machines[stage] = str(ULID())
        db.execute(
            "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, production_stage) VALUES (%s, %s, %s, %s, %s, %s)",
            (machines[stage], TENANT, work_center, f"SM-{stage}", stage, stage),
        )
    ProductClassificationService(db).set_classification(tenant_id=TENANT, actor_id=actor, product_id=pasta, category="finished_good", packaging_format="packet")
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=silo, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "pasta": pasta, "semolina": semolina, "silo": silo, "work_center": work_center, "machines": machines}


def _submitted_shift(db, env, *, day=DAY, silo_rows=None, shift="morning", extra=None) -> str:
    """A shift with a run (no machine named), a packing row (no machine, no stores) and the given silo readings."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=day, shift=shift))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["pasta"], planned_quantity=1000, work_center_id=env["work_center"], start_date=day)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [{
        "of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["silo"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["silo"]}],
    }]}))
    run_id = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"][0]["payload"]["runs"][0]["id"]
    filled = {"packing": {"rows": [{"run_id": run_id, "packets_counted": 120, "lot_number": f"L-{day.isoformat()}-{shift}"}]}}
    if silo_rows:
        filled["silo"] = {"states": silo_rows}
    filled.update(extra or {})
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        elif key in filled:
            _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    return shift_id


def _validate(db, env, shift_id):
    return _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))


def _status(db, machine_id) -> str:
    return db.execute("SELECT status FROM maintenance.equipment WHERE id = %s", (machine_id,)).fetchone()[0]


def test_a_report_without_a_machine_gets_the_lines_machine_at_its_stage(db, env):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    rows = dict(db.execute(
        "SELECT r.report_type, r.equipment_id FROM production.production_reports r JOIN production.shift_runs s ON s.id = r.id WHERE s.shift_report_id = %s "
        "UNION ALL SELECT r.report_type, r.equipment_id FROM production.production_reports r JOIN production.shift_packing_rows p ON p.id = r.id WHERE p.shift_report_id = %s",
        (shift_id, shift_id),
    ).fetchall())
    assert rows == {"daily": env["machines"]["extrusion"], "conditionnement": env["machines"]["conditionnement"]}


SILO_STOPPED = [{"side": "production", "phase": "end", "line_state": "stopped"}]


def test_a_stopped_end_reading_takes_that_sides_machines_down_once_validated(db, env):
    shift_id = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    assert _status(db, env["machines"]["extrusion"]) == "operational"  # nothing changes before validation
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["versement"]) == "down"
    assert _status(db, env["machines"]["extrusion"]) == "down"
    assert _status(db, env["machines"]["conditionnement"]) == "operational"  # the packing side said nothing


def test_a_running_reading_brings_a_down_machine_back(db, env):
    db.execute("UPDATE maintenance.equipment SET status = 'down' WHERE id = %s", (env["machines"]["conditionnement"],))
    shift_id = _submitted_shift(db, env, silo_rows=[{"side": "packing", "phase": "end", "line_state": "running"}])
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["conditionnement"]) == "operational"


def test_a_machine_in_maintenance_is_left_alone(db, env):
    db.execute("UPDATE maintenance.equipment SET status = 'maintenance' WHERE id = %s", (env["machines"]["extrusion"],))
    shift_id = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["extrusion"]) == "maintenance"
    assert _status(db, env["machines"]["versement"]) == "down"


def test_only_start_readings_change_nothing(db, env):
    shift_id = _submitted_shift(db, env, silo_rows=[{"side": "production", "phase": "start", "line_state": "stopped"}])
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["extrusion"]) == "operational"


def test_an_earlier_shift_does_not_override_a_later_validated_one(db, env):
    earlier = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    later = _submitted_shift(db, env, day=DAY + datetime.timedelta(days=1))
    _validate(db, env, later)
    _validate(db, env, earlier)
    assert _status(db, env["machines"]["extrusion"]) == "operational"


def test_each_change_is_audited(db, env):
    shift_id = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    _validate(db, env, shift_id)
    audited = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'equipment.status_changed'", (TENANT,)
    ).fetchone()[0]
    assert audited == 2

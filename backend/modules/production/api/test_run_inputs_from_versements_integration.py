"""A run's dough and rebroyat used are worked out from the shift's versements, not typed."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_sections import check_ready_to_submit, load_section

TENANT = "run-inputs-from-versements-test"
DAY = datetime.date(2030, 8, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, semolina, regrind, other_regrind, silo, regrind_store, work_center = (str(ULID()) for _ in range(8))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 't', 'Tonne', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'RI-SILO', 'Silo')", (silo, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'RI-REG', 'Rebroyat')", (regrind_store, TENANT))
    for product_id, sku, store in (
        (product, "RI-PASTA", None), (semolina, "RI-SEMO", silo), (regrind, "RI-REG", regrind_store), (other_regrind, "RI-REG2", None),
    ):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom, store),
        )
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'RI-WC', 'Line')", (work_center, TENANT))
    service = WorkOrderService(db)
    order = service.create_work_order(
        tenant_id=TENANT, actor_id=actor, product_id=product, planned_quantity=100, work_center_id=work_center, start_date=DAY,
    )
    assert isinstance(order, Ok)
    assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=actor, work_order_id=order.value.id), Ok)
    shift = ShiftReportService(db).open_shift(tenant_id=TENANT, actor_id=actor, work_center_id=work_center, report_date=DAY, shift="morning")
    assert isinstance(shift, Ok)
    return {
        "actor": actor, "of": order.value.id, "shift": shift.value["id"], "semolina": semolina, "regrind": regrind,
        "other_regrind": other_regrind, "regrind_store": regrind_store, "silo": silo,
    }


def _save(db, env, payload):
    return ShiftReportService(db).save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=env["shift"], section_key="runs", payload=payload,
    )


def _runs(db, env) -> list[dict]:
    return load_section(db, tenant_id=TENANT, shift_report_id=env["shift"], section_key="runs")["runs"]


def test_versements_are_shared_across_runs_by_minutes(db, env):
    saved = _save(db, env, {
        "versements": [{"product_id": env["semolina"], "quantity": 8}, {"product_id": env["semolina"], "quantity": 1}],
        "rebroyat_versements": [{"product_id": env["regrind"], "quantity": 0.6}],
        # A typed dough or rebroyat figure is ignored: the versements decide.
        "runs": [
            {"of_id": env["of"], "production_minutes": 100, "dough_quantity": 99, "regrind_input_quantity": 99},
            {"of_id": env["of"], "production_minutes": 200},
        ],
    })
    assert isinstance(saved, Ok), saved

    first, second = _runs(db, env)
    assert first["dough_quantity"] == pytest.approx(3.2)
    assert second["dough_quantity"] == pytest.approx(6.4)
    assert first["regrind_input_quantity"] == pytest.approx(0.2)
    assert second["regrind_input_quantity"] == pytest.approx(0.4)
    for run in (first, second):
        assert run["regrind_input_product_id"] == env["regrind"]
        assert run["raw_material_location_id"] == env["regrind_store"]
    # The MP versé becomes each run's semoule lines, from the MP's own store.
    assert [(l["product_id"], l["location_id"], l["quantity"]) for l in first["semolina_lines"]] == [
        (env["semolina"], env["silo"], pytest.approx(3.0)),
    ]
    assert [(l["product_id"], l["quantity"]) for l in second["semolina_lines"]] == [(env["semolina"], pytest.approx(6.0))]


def test_typed_semoule_lines_are_replaced_by_the_versement(db, env):
    saved = _save(db, env, {
        "versements": [{"product_id": env["semolina"], "quantity": 2}],
        "runs": [{"of_id": env["of"], "production_minutes": 60,
                  "semolina_lines": [{"product_id": env["semolina"], "quantity": 50, "location_id": env["silo"]}]}],
    })
    assert isinstance(saved, Ok), saved
    (run,) = _runs(db, env)
    assert [l["quantity"] for l in run["semolina_lines"]] == [pytest.approx(2.0)]

    assert isinstance(_save(db, env, {"versements": []}), Ok)
    assert _runs(db, env)[0]["semolina_lines"] == []


def test_removing_the_rebroyat_clears_what_the_runs_used(db, env):
    assert isinstance(_save(db, env, {
        "rebroyat_versements": [{"product_id": env["regrind"], "quantity": 1}],
        "runs": [{"of_id": env["of"], "production_minutes": 60}],
    }), Ok)
    run_id = _runs(db, env)[0]["id"]

    assert isinstance(_save(db, env, {"rebroyat_versements": []}), Ok)

    (run,) = _runs(db, env)
    assert run["id"] == run_id
    assert run["dough_quantity"] == 0
    assert run["regrind_input_quantity"] == 0
    assert run["regrind_input_product_id"] is None
    assert run["raw_material_location_id"] is None


def test_rebroyat_versements_must_name_one_item(db, env):
    saved = _save(db, env, {
        "rebroyat_versements": [{"product_id": env["regrind"], "quantity": 1}, {"product_id": env["other_regrind"], "quantity": 1}],
    })
    assert isinstance(saved, Err)
    assert saved.code == "MIXED_REBROYAT"


def test_a_rebroyat_item_without_a_store_blocks_submission(db, env):
    assert isinstance(_save(db, env, {"rebroyat_versements": [{"product_id": env["other_regrind"], "quantity": 1}]}), Ok)
    payload = load_section(db, tenant_id=TENANT, shift_report_id=env["shift"], section_key="runs")
    checked = check_ready_to_submit("runs", payload)
    assert isinstance(checked, Err)
    assert checked.code == "MISSING_STOCK_TARGET"


def test_an_mp_without_a_store_blocks_submission(db, env):
    assert isinstance(_save(db, env, {"versements": [{"product_id": env["other_regrind"], "quantity": 1}]}), Ok)
    payload = load_section(db, tenant_id=TENANT, shift_report_id=env["shift"], section_key="runs")
    checked = check_ready_to_submit("runs", payload)
    assert isinstance(checked, Err)
    assert checked.code == "MISSING_STOCK_TARGET"

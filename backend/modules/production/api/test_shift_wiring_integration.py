"""A shift's data reaches stock, the production board and Fiche & récap.

One line, one day: a morning shift validated, an afternoon shift handed in and waiting,
a night shift still being typed. Every reader must show the validated one as a result and
the others as work in progress, never as nothing.
"""
from __future__ import annotations

import pytest

from modules.production.api.dashboard_day_service import DashboardDayService
from modules.production.api.day_sheet_service import DaySheetService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.test_shift_machine_integration import (  # noqa: F401  (env is a fixture)
    DAY,
    TENANT,
    _ok,
    _submitted_shift,
    _validate,
    env,
)


def _draft_shift(db, env, shift="night") -> str:
    """A shift a team is still typing: one saved run, nothing handed in."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift=shift))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["pasta"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [{
        "of_id": of_id, "start_time": "22:00", "end_time": "23:00", "production_minutes": 60, "finished_product_quantity": 100,
    }], "versements": [{"product_id": env["semolina"], "quantity": 200, "location_id": env["silo"]}]}))
    return shift_id


def _sheet(db, env, *, pending):
    return _ok(DaySheetService(db).get_day_sheet(tenant_id=TENANT, date=DAY, work_center_id=env["work_center"], include_pending=pending))


def _cell(sheet, key, column):
    row = next(r for r in sheet["rows"] if r["key"] == key and not r["ref"])
    return row["by_column"].get(column)


def _column(sheet, key):
    return next(c for c in sheet["columns"] if c["key"] == key)


def _on_hand(db, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def test_validating_moves_stock_through_the_derived_stores(db, env):
    fg = db.execute("SELECT default_location_id FROM core.products WHERE id = %s", (env["pasta"],)).fetchone()[0]
    before = _on_hand(db, env["semolina"], env["silo"])
    _validate(db, env, _submitted_shift(db, env))
    assert _on_hand(db, env["semolina"], env["silo"]) == before - 1000  # the run's semoule went out of its silo
    assert _on_hand(db, env["pasta"], fg) == 120  # the packed pasta came in to the product's own store, none was typed


def test_the_board_counts_a_handed_in_shift_as_awaiting_validation(db, env):
    _submitted_shift(db, env, shift="afternoon")
    day = DashboardDayService(db).get_day(tenant_id=TENANT, date=DAY)
    assert day["awaiting_validation"] == 1
    assert day["totals"]["report_count"] == 0  # nothing is validated yet, so no figure is claimed


def test_the_board_awaiting_count_drops_once_the_shift_is_validated(db, env):
    shift_id = _submitted_shift(db, env, shift="afternoon")
    _validate(db, env, shift_id)
    day = DashboardDayService(db).get_day(tenant_id=TENANT, date=DAY)
    assert day["awaiting_validation"] == 0
    assert day["totals"]["report_count"] == 1


def test_fiche_and_recap_shows_waiting_and_draft_shifts_as_work_in_progress(db, env):
    _validate(db, env, _submitted_shift(db, env, shift="morning"))
    _submitted_shift(db, env, shift="afternoon")
    _draft_shift(db, env, shift="night")

    results = _sheet(db, env, pending=False)
    assert _cell(results, "total_finished", "morning") == pytest.approx(0.06)
    assert _cell(results, "total_finished", "afternoon") is None  # a results sheet does not move for work in progress
    assert _column(results, "morning")["reports"]["daily"] == {"validated": 1, "pending": 0}
    # ...but it never lets a partial day read as complete: the others are counted as waiting.
    assert _column(results, "afternoon")["reports"]["daily"] == {"validated": 0, "pending": 1}
    assert _column(results, "afternoon")["reports"]["conditionnement"] == {"validated": 0, "pending": 1}
    assert _column(results, "night")["reports"]["daily"] == {"validated": 0, "pending": 1}

    progress = _sheet(db, env, pending=True)
    assert _cell(progress, "total_finished", "afternoon") == pytest.approx(0.06)  # a handed-in packing row, read like validation will
    assert _cell(progress, "total_finished", "morning") == pytest.approx(0.06)


def test_a_returned_shift_is_neither_a_result_nor_work_in_progress(db, env):
    shift_id = _submitted_shift(db, env, shift="afternoon")
    from modules.production.api.shift_validation_service import ShiftValidationService
    _ok(ShiftValidationService(db).reject_sections(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["packing"], reason="cartons do not match"))
    sheet = _sheet(db, env, pending=True)
    assert all(c["key"] != "afternoon" for c in sheet["columns"])  # no report of it is shown at all
    assert _cell(sheet, "total_finished", "afternoon") is None


def test_reading_the_sheet_leaves_nothing_behind(db, env):
    shift_id = _submitted_shift(db, env, shift="afternoon")
    _sheet(db, env, pending=True)
    left = db.execute(
        "SELECT count(*) FROM production.production_reports r WHERE r.tenant_id = %s AND r.id IN "
        "(SELECT id FROM production.shift_runs WHERE shift_report_id = %s UNION SELECT id FROM production.shift_packing_rows WHERE shift_report_id = %s)",
        (TENANT, shift_id, shift_id),
    ).fetchone()[0]
    assert left == 0
    assert _ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id))["status"] == "submitted"


def test_a_draft_with_a_stop_still_ongoing_still_shows(db, env):
    shift_id = _draft_shift(db, env, shift="night")
    _ok(ShiftReportService(db).save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="stops",
        payload={"stops": [{"equipment_id": env["machines"]["extrusion"], "started_at": "2030-08-05T22:30:00+00:00"}]},
    ))
    sheet = _sheet(db, env, pending=True)
    assert _column(sheet, "night")["reports"]["daily"] == {"validated": 0, "pending": 1}
    assert _cell(sheet, "downtime_hours", "night") in (None, 0)  # it has not lost any minutes yet


def test_packing_waste_reaches_the_sheet_in_kilos_with_no_item(db, env):
    waste = {"waste_packing": {"waste_lines": [{"category": "packaging", "quantity": 2.5, "note": "torn film"}]}}
    _validate(db, env, _submitted_shift(db, env, extra=waste))
    sheet = _sheet(db, env, pending=False)
    row = next(r for r in sheet["rows"] if r["key"] == "packing_waste" and r["ref"] == "packaging")
    assert (row["by_column"]["morning"], row["unit"]) == (2.5, "kg")


def _machine_rows(db, env):
    from modules.production.api.machine_performance_service import MachinePerformanceService

    rows = MachinePerformanceService(db).list_machine_performance(
        tenant_id=TENANT, grain="day", date_from=DAY.isoformat(), date_to=DAY.isoformat()
    )
    return {r["equipment_id"]: r for r in rows}


def test_machine_performance_receives_a_validated_shift(db, env):
    _validate(db, env, _submitted_shift(db, env))
    rows = _machine_rows(db, env)
    press = rows[env["machines"]["extrusion"]]
    assert (press["production_minutes"], press["produced_quantity"]) == (420, 900)
    assert rows[env["machines"]["conditionnement"]]["report_count"] == 1


def test_a_stop_is_attributed_to_the_machine_that_stopped(db, env):
    stops = {"stops": {"stops": [{
        "equipment_id": env["machines"]["versement"], "started_at": "2030-08-05T09:00:00+00:00",
        "ended_at": "2030-08-05T09:30:00+00:00", "motif": "die_jam",
    }]}}
    _validate(db, env, _submitted_shift(db, env, extra=stops))
    rows = _machine_rows(db, env)
    assert rows[env["machines"]["versement"]]["downtime_minutes"] == 30  # the machine that stopped carries it...
    assert rows[env["machines"]["extrusion"]]["downtime_minutes"] == 0  # ...not the machine the run is filed under
    assert rows[env["machines"]["extrusion"]]["production_minutes"] == 420

"""Integration tests for the day sheet, against a real database.

The sheet reads the Daily and Conditionnement reports a line filed on one day and
lays them on one grid, a column per shift. What is checked here is what the SQL
adds to the layout rules already covered in domain/test_day_sheet.py: which
reports are read, that every figure is restated into the sheet's unit before it
is added, and that a column says how much of it is still waiting for validation.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.day_sheet_service import DaySheetService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    DowntimeLine,
    SemolinaLine,
    WasteLine,
)
from modules.warehouse.api.service import StockService

TENANT = "integration-test-day-sheet"
DAY = datetime.date(2026, 9, 10)
T = datetime.time


@pytest.fixture
def env(db):
    actor = str(ULID())
    ids = {name: str(ULID()) for name in (
        "kg", "tonne", "each", "semolina", "rebroyat", "finished", "finished_b", "film", "carton", "scotch", "ruban",
        "silo", "packaging_store", "goods_store", "line", "other_line", "machine",
    )}
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    for key, code, category, ratio in (("kg", "kg", "weight", 1), ("tonne", "t", "weight", 1000), ("each", "ea", "unit", 1)):
        db.execute(
            "INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) VALUES (%s, %s, %s, %s, %s, %s)",
            (ids[key], TENANT, code, code, category, ratio),
        )
    for key, name, uom in (
        ("semolina", "Semoule extra", "tonne"),
        ("rebroyat", "Rebroyat", "kg"),
        ("finished", "Douman 500 g", "kg"),
        ("finished_b", "Prima 500 g", "kg"),
        ("film", "Film", "kg"),
        ("carton", "Carton", "each"),
        ("scotch", "Scotch", "each"),
        ("ruban", "Ruban", "each"),
    ):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (ids[key], TENANT, f"DS-{key}", name, ids[uom]),
        )
    # 500 g packets: the tonnage of a packing report is its count times this.
    db.execute("UPDATE core.products SET net_weight_grams = 500 WHERE id = ANY(%s)", ([ids["finished"], ids["finished_b"]],))
    for key, code in (("silo", "DS-SILO"), ("packaging_store", "DS-PACK"), ("goods_store", "DS-GOODS")):
        db.execute(
            "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
            (ids[key], TENANT, code, code),
        )
    for key, code in (("line", "DS-L1"), ("other_line", "DS-L2")):
        db.execute(
            "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
            (ids[key], TENANT, code, f"Ligne {code}"),
        )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'DS-EQ', 'Extrudeuse')",
        (ids["machine"], TENANT, ids["line"]),
    )
    stock = StockService(db)
    for product, location in (
        ("semolina", "silo"), ("rebroyat", "silo"),
        ("film", "packaging_store"), ("carton", "packaging_store"), ("scotch", "packaging_store"), ("ruban", "packaging_store"),
    ):
        stock.receive_stock(
            tenant_id=TENANT, product_id=ids[product], location_id=ids[location], quantity=1_000_000,
            correlation_id=str(ULID()), reference="seed", actor_id=actor,
        )
    for shift, start, end in (("morning", T(7), T(14)), ("afternoon", T(14), T(22)), ("night", T(22), T(7))):
        db.execute(
            "INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, %s, %s, %s)",
            (TENANT, shift, start, end),
        )
    return {"actor": actor, **ids}


def _open_of(db, env, product="finished"):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env[product], planned_quantity=1000,
        work_center_id=env["line"], start_date=DAY - datetime.timedelta(days=30),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok)
    return created.value.id


def _finish(db, env, report_id, validate):
    reports = ProductionReportService(db)
    assert isinstance(reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    if validate:
        done = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID()))
        assert isinstance(done, Ok), getattr(done, "message", "")


def _daily(db, env, of_id, *, day=DAY, shift="morning", team="Équipe A", semolina=10.0, regrind_kg=0.0,
           minutes=420, stops=(), waste=(), validate=True, **detail):
    body = DailyReportDetail(
        semolina_lines=(SemolinaLine(product_id=env["semolina"], quantity=semolina, location_id=env["silo"]),),
        raw_material_location_id=env["silo"],
        production_minutes=minutes,
        downtime_lines=tuple(DowntimeLine(motif=motif, minutes=m) for motif, m in stops),
        waste_lines=tuple(WasteLine(category=c, product_id=env["semolina"], quantity=q) for c, q in waste),
        regrind_input_quantity=regrind_kg,
        regrind_input_product_id=env["rebroyat"] if regrind_kg else None,
        **detail,
    )
    created = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of_id, report_date=day, team=team, shift=shift,
        equipment_id=env["machine"], detail=body,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report_id = created.value["report"].id
    _finish(db, env, report_id, validate)
    return report_id


def _packing(db, env, of_id, *, day=DAY, shift="morning", team="Équipe A", tonnes=9.0, validate=True, **detail):
    """A packing report whose count of 500 g packets weighs `tonnes`."""
    detail.setdefault("film_product_id", env["film"])
    detail.setdefault("carton_product_id", env["carton"])
    detail.setdefault("scotch_product_id", env["scotch"])
    detail.setdefault("ruban_product_id", env["ruban"])
    detail.setdefault("packaging_location_id", env["packaging_store"])
    detail.setdefault("finished_goods_location_id", env["goods_store"])
    created = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of_id, report_date=day, team=team, shift=shift,
        equipment_id=env["machine"],
        detail=ConditionnementReportDetail(packets_counted=tonnes * 2000, **detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report_id = created.value["report"].id
    _finish(db, env, report_id, validate)
    return report_id


def _sheet(db, env, *, day=DAY, line=None, pending=False):
    result = DaySheetService(db).get_day_sheet(
        tenant_id=TENANT, date=day, work_center_id=line or env["line"], include_pending=pending
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _row(sheet, key, ref=None):
    return next(r for r in sheet["rows"] if r["key"] == key and r["ref"] == ref)


def test_a_day_nobody_reported_on_still_has_a_column_per_configured_shift_in_day_order(db, env):
    sheet = _sheet(db, env)
    assert [c["key"] for c in sheet["columns"]] == ["morning", "afternoon", "night"]
    assert all(c["reports"]["daily"] == {"validated": 0, "pending": 0} for c in sheet["columns"])
    assert _row(sheet, "total_fab")["total"] is None
    assert _row(sheet, "yield")["total"] is None


def test_a_line_that_does_not_exist_is_not_found_and_neither_is_another_tenants_line(db, env):
    result = DaySheetService(db).get_day_sheet(tenant_id=TENANT, date=DAY, work_center_id=str(ULID()))
    assert isinstance(result, Err) and result.code == "NOT_FOUND"
    result = DaySheetService(db).get_day_sheet(tenant_id="someone-else", date=DAY, work_center_id=env["line"])
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_daily_and_conditionnement_reports_of_a_shift_land_in_the_same_column(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, shift="morning", team="Équipe A", semolina=11.1, water_quantity=4641, electricity_quantity=1990)
    _packing(db, env, of_id, shift="morning", team="Équipe A", tonnes=12.0, lot_number="4187SNL", dlc_date=DAY + datetime.timedelta(days=700))
    _daily(db, env, of_id, shift="night", team="Équipe C", semolina=4.0, water_quantity=1000)
    sheet = _sheet(db, env)

    morning, afternoon, night = sheet["columns"]
    assert morning["teams"] == ["Équipe A"] and morning["lots"] == ["4187SNL"]
    assert morning["reports"] == {"daily": {"validated": 1, "pending": 0}, "conditionnement": {"validated": 1, "pending": 0}}
    assert night["reports"]["conditionnement"] == {"validated": 0, "pending": 0}
    assert afternoon["reports"]["daily"]["validated"] == 0

    assert _row(sheet, "semolina", env["semolina"])["by_column"] == {"morning": pytest.approx(11.1), "night": pytest.approx(4.0)}
    assert _row(sheet, "water")["by_column"] == {"morning": 4641, "night": 1000}
    assert _row(sheet, "total_finished")["by_column"] == {"morning": 12.0}
    # The night team filed a report that says 0 kWh, which is not the same as filing none.
    assert _row(sheet, "electricity")["by_column"] == {"morning": 1990, "night": 0}
    assert _row(sheet, "finished", env["finished"])["name"] == "Douman 500 g"
    assert [(o["id"], o["product_name"]) for o in sheet["ofs"]] == [(of_id, "Douman 500 g")]


def test_rebroyat_in_kilos_is_restated_into_tonnes_before_it_joins_the_total(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, semolina=30, regrind_kg=500)
    sheet = _sheet(db, env)
    assert _row(sheet, "regrind")["total"] == pytest.approx(0.5)
    assert _row(sheet, "total_mp")["total"] == pytest.approx(30)
    assert _row(sheet, "total_fab")["total"] == pytest.approx(30.5)


def test_production_and_stop_time_are_in_hours_and_the_hourly_output_follows(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, semolina=12, minutes=394, stops=[("format_change", 86)])
    sheet = _sheet(db, env)
    assert _row(sheet, "production_hours")["total"] == pytest.approx(394 / 60)
    assert _row(sheet, "downtime_hours")["total"] == pytest.approx(86 / 60)
    assert _row(sheet, "hourly_output")["total"] == pytest.approx(12000 / (394 / 60))


def test_daily_waste_is_in_raw_kilos_per_kind_and_packing_waste_keeps_the_items_unit(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, waste=[("press", 40), ("raw_material", 2)])
    _packing(
        db, env, of_id, carton_quantity=100,
        waste_lines=(
            WasteLine(category="packaging", product_id=env["film"], quantity=8),
            WasteLine(category="packaging", product_id=env["carton"], quantity=3),
        ),
    )
    sheet = _sheet(db, env)
    assert _row(sheet, "waste", "press")["total"] == 40 and _row(sheet, "waste", "raw_material")["total"] == 2
    assert _row(sheet, "total_waste")["total"] == 42
    packing_waste = {r["name"]: r for r in sheet["rows"] if r["key"] == "packing_waste"}
    assert (packing_waste["Film"]["unit"], packing_waste["Film"]["total"]) == ("kg", 8)
    assert (packing_waste["Carton"]["unit"], packing_waste["Carton"]["total"]) == ("ea", 3)


def test_product_lost_while_packing_stays_in_raw_kilos_even_when_an_item_is_named(db, env):
    """`product` (finished product lost while packing) is filled in on the shift's
    Conditionnement form the same way `finished_product_conditioning` is on the
    Daily form: a weight in kilos, whatever the item's own unit is. Naming the item
    (semolina here, whose own unit is a tonne, ratio 1000) must not scale the kilos
    the team actually weighed into a wrong number of tonnes."""
    of_id = _open_of(db, env)
    _packing(db, env, of_id, waste_lines=(WasteLine(category="product", product_id=env["semolina"], quantity=2),))
    sheet = _sheet(db, env)
    row = next(r for r in sheet["rows"] if r["key"] == "packed_product_waste" and r["ref"] == env["semolina"])
    assert (row["section"], row["unit"], row["total"]) == ("waste", "kg", 2)
    # Pasta lost while packing counts in the déchets' total, like the Excel's "PF Cdt".
    assert _row(sheet, "total_waste")["total"] == 2


def test_packaging_rows_are_in_the_items_own_base_unit(db, env):
    of_id = _open_of(db, env)
    _packing(db, env, of_id, film_quantity=104, carton_quantity=1235, scotch_quantity=11, waste_carton_quantity=3, ruban_quantity=1)
    sheet = _sheet(db, env)
    assert [(_row(sheet, key)["unit"], _row(sheet, key)["total"]) for key in ("film", "carton", "waste_carton", "scotch", "ruban")] == [
        ("kg", 104), ("ea", 1235), ("ea", 3), ("ea", 11), ("ea", 1),
    ]


def test_the_yield_is_the_tonnes_conditioned_over_the_tonnes_put_into_fabrication(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, semolina=12, regrind_kg=1000)
    _packing(db, env, of_id, tonnes=11.7)
    assert _row(_sheet(db, env), "yield")["total"] == pytest.approx(11.7 / 13 * 100)


def test_a_report_still_being_filled_in_is_counted_as_waiting_but_not_added_unless_asked_for(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, shift="morning", semolina=10)
    _daily(db, env, of_id, shift="night", team="Équipe C", semolina=99, validate=False)

    default = _sheet(db, env)
    assert default["columns"][2]["reports"]["daily"] == {"validated": 0, "pending": 1}
    assert default["columns"][0]["reports"]["daily"] == {"validated": 1, "pending": 0}
    assert _row(default, "total_mp")["by_column"] == {"morning": pytest.approx(10)}
    assert default["include_pending"] is False

    with_pending = _sheet(db, env, pending=True)
    assert _row(with_pending, "total_mp")["by_column"] == {"morning": pytest.approx(10), "night": pytest.approx(99)}
    assert with_pending["columns"][2]["reports"]["daily"] == {"validated": 0, "pending": 1}


def test_a_rejected_report_is_neither_a_result_nor_work_in_progress(db, env):
    of_id = _open_of(db, env)
    report_id = _daily(db, env, of_id, semolina=50, validate=False)
    rejected = ProductionReportService(db).reject_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, reason="wrong figures"
    )
    assert isinstance(rejected, Ok), getattr(rejected, "message", "")
    sheet = _sheet(db, env, pending=True)
    assert _row(sheet, "total_mp")["total"] is None
    assert sheet["columns"][0]["reports"]["daily"] == {"validated": 0, "pending": 0}


def test_other_days_and_other_lines_are_left_out(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, day=DAY - datetime.timedelta(days=1), semolina=77)
    _daily(db, env, of_id, semolina=10)
    assert _row(_sheet(db, env), "total_mp")["total"] == pytest.approx(10)
    other_line = _sheet(db, env, line=env["other_line"])
    assert _row(other_line, "total_mp")["total"] is None
    assert other_line["work_center"]["code"] == "DS-L2"


def test_a_shift_that_is_not_configured_still_gets_a_column_after_the_configured_ones(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, shift="overtime", semolina=3)
    keys = [c["key"] for c in _sheet(db, env)["columns"]]
    assert keys == ["morning", "afternoon", "night", "overtime"]


def test_a_packing_report_not_yet_validated_shows_the_tonnage_its_count_will_give(db, env):
    of_id = _open_of(db, env)
    # The tonnage is only settled from the count at validation; until then the stored
    # figure is 0, and the sheet must not print 0 t next to 24 000 packets.
    _packing(db, env, of_id, tonnes=12.0, validate=False)
    sheet = _sheet(db, env, pending=True)
    assert _row(sheet, "total_finished")["total"] == pytest.approx(12.0)
    assert _row(sheet, "packets")["total"] == 24000
    assert _row(_sheet(db, env), "total_finished")["total"] is None


# -- the month recap -----------------------------------------------------------

MONTH = datetime.date(2026, 9, 1)


def _recap(db, env, *, month=MONTH, line=None):
    result = DaySheetService(db).get_month_recap(
        tenant_id=TENANT, month=month, work_center_id=line or env["line"]
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def test_the_recap_adds_every_validated_day_of_the_month_into_a_column_per_product(db, env):
    douman, prima = _open_of(db, env), _open_of(db, env, product="finished_b")
    day = lambda n: DAY + datetime.timedelta(days=n)  # noqa: E731
    _daily(db, env, douman, day=day(0), semolina=10)
    _packing(db, env, douman, day=day(0), tonnes=9)
    _daily(db, env, douman, day=day(1), shift="night", semolina=5)
    _packing(db, env, douman, day=day(1), shift="night", tonnes=4)
    _daily(db, env, prima, day=day(2), semolina=20)
    _packing(db, env, prima, day=day(2), tonnes=15)

    recap = _recap(db, env)
    assert recap["month"] == "2026-09"
    assert [(c["name"], c["key"]) for c in recap["columns"]] == [("Douman 500 g", env["finished"]), ("Prima 500 g", env["finished_b"])]
    assert _row(recap, "total_mp")["by_column"] == {env["finished"]: pytest.approx(15), env["finished_b"]: pytest.approx(20)}
    assert _row(recap, "total_mp")["total"] == pytest.approx(35)
    assert _row(recap, "total_finished")["by_column"] == {env["finished"]: pytest.approx(13), env["finished_b"]: pytest.approx(15)}
    # A product's yield is read per column; the line's is its tonnes over its tonnes.
    assert _row(recap, "yield")["by_column"] == {env["finished"]: pytest.approx(13 / 15 * 100), env["finished_b"]: pytest.approx(75)}
    assert _row(recap, "yield")["total"] == pytest.approx(28 / 35 * 100)


def test_the_recap_leaves_out_other_months_other_lines_and_reports_not_yet_validated(db, env):
    of_id = _open_of(db, env)
    _daily(db, env, of_id, day=DAY, semolina=10)
    _daily(db, env, of_id, day=datetime.date(2026, 8, 25), semolina=500)
    _daily(db, env, of_id, day=DAY + datetime.timedelta(days=1), semolina=99, validate=False)

    recap = _recap(db, env)
    assert _row(recap, "total_mp")["total"] == pytest.approx(10)
    # The one still being filled in is not added, but the column says it is there.
    assert recap["columns"][0]["reports"]["daily"] == {"validated": 1, "pending": 1}
    assert _row(_recap(db, env, line=env["other_line"]), "total_mp")["total"] is None


def test_a_month_nobody_reported_on_has_no_columns_and_empty_rows(db, env):
    recap = _recap(db, env, month=datetime.date(2026, 1, 1))
    assert recap["columns"] == [] and recap["month"] == "2026-01"
    assert _row(recap, "total_fab")["total"] is None


def test_the_recap_of_a_line_that_does_not_exist_is_not_found(db, env):
    result = DaySheetService(db).get_month_recap(tenant_id=TENANT, month=MONTH, work_center_id=str(ULID()))
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_the_recap_lists_the_lots_a_product_was_packed_under(db, env):
    of_id = _open_of(db, env)
    for n, lot in ((0, "4187SNL"), (1, "4188SNL")):
        _packing(
            db, env, of_id, day=DAY + datetime.timedelta(days=n), tonnes=1,
            lot_number=lot, dlc_date=DAY + datetime.timedelta(days=700),
        )
    assert _recap(db, env)["columns"][0]["lots"] == ["4187SNL", "4188SNL"]


def test_the_recap_files_a_run_under_the_product_it_packed_not_the_orders_product(db, env):
    # One order can run several products; each packing row names its own.
    of_id = _open_of(db, env)
    _shift_run(db, env, of_id, lot="4187SNL", semolina=10, packed_t=9, product="finished_b")

    recap = _recap(db, env)
    assert [(c["name"], c["key"]) for c in recap["columns"]] == [("Prima 500 g", env["finished_b"])]
    assert _row(recap, "total_mp")["by_column"] == {env["finished_b"]: pytest.approx(10)}
    assert _row(recap, "total_finished")["by_column"] == {env["finished_b"]: pytest.approx(9)}


# -- by lot ---------------------------------------------------------------------

def _shift_run(db, env, of_id, *, day=DAY, shift="morning", team="Équipe A", lot, semolina=10.0, packed_t=None, minutes=420, product=None):
    """A shift filed on the shift screen: a production run under `lot`, and a packing
    row drawing from it when `packed_t` is given. Validated, so the sheet counts it."""
    from modules.production.api.shift_report_service import ShiftReportService
    from modules.production.domain.shift_report import SECTION_KEYS
    from modules.production.api.shift_validation_service import ShiftValidationService

    service = ShiftReportService(db)
    opened = service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["line"], report_date=day, shift=shift, team=team
    )
    assert isinstance(opened, Ok), getattr(opened, "message", "")
    shift_id = opened.value["id"]
    run = {
        "of_id": of_id, "equipment_id": env["machine"], "lot_number": lot, "start_time": "07:00", "end_time": "14:00",
        "production_minutes": minutes, "finished_product_quantity": semolina * 900, "raw_material_location_id": env["silo"],
    }
    versements = [{"product_id": env["semolina"], "location_id": env["silo"], "quantity": semolina}]
    saved = service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [run], "versements": versements},
    )
    assert isinstance(saved, Ok), getattr(saved, "message", "")
    shift = service.get_shift(tenant_id=TENANT, shift_report_id=shift_id).value
    run_id = next(s for s in shift["sections"] if s["key"] == "runs")["payload"]["runs"][0]["id"]
    filled: dict = {"runs": None}
    if packed_t is not None:
        filled["packing"] = {"rows": [{
            "of_id": of_id, "run_id": run_id, "equipment_id": env["machine"], "lot_number": lot,
            "product_id": env[product] if product else None, "packets_counted": packed_t * 2000, "film_quantity": 10, "carton_quantity": packed_t * 100,
            "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
            "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_store"],
            "finished_goods_location_id": env["goods_store"], "dlc_date": (day + datetime.timedelta(days=700)).isoformat(),
        }]}
    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                done = service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key])
                assert isinstance(done, Ok), getattr(done, "message", "")
            done = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key)
        else:
            done = service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key)
        assert isinstance(done, Ok), getattr(done, "message", "")
    validated = ShiftValidationService(db).validate_shift(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, correlation_id=str(ULID())
    )
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    return shift_id


def test_a_day_read_by_lot_puts_a_runs_reports_under_the_lot_it_was_filed_under(db, env):
    of_id = _open_of(db, env)
    _shift_run(db, env, of_id, shift="morning", lot="4187SNL", semolina=10, packed_t=9)
    _shift_run(db, env, of_id, shift="night", team="Équipe C", lot="4188SNL", semolina=5)
    result = DaySheetService(db).get_day_sheet(tenant_id=TENANT, date=DAY, work_center_id=env["line"], group_by="lot")
    assert isinstance(result, Ok), getattr(result, "message", "")
    sheet = result.value
    assert sheet["group_by"] == "lot"
    assert [(c["key"], c["name"], c["teams"], c["products"]) for c in sheet["columns"]] == [
        ("4187SNL", "4187SNL", ["Équipe A"], ["Douman 500 g"]),
        ("4188SNL", "4188SNL", ["Équipe C"], ["Douman 500 g"]),
    ]
    assert _row(sheet, "total_mp")["by_column"] == {"4187SNL": pytest.approx(10), "4188SNL": pytest.approx(5)}
    assert _row(sheet, "total_finished")["by_column"] == {"4187SNL": pytest.approx(9)}
    # A lot is a whole run, so its yield is read per column.
    assert _row(sheet, "yield")["by_column"] == {"4187SNL": pytest.approx(90)}


def test_an_old_style_daily_report_borrows_the_lot_of_the_packing_that_drew_from_it_else_has_none(db, env):
    of_id = _open_of(db, env)
    daily_id = _daily(db, env, of_id, shift="morning", semolina=10)
    _packing(db, env, of_id, shift="morning", tonnes=9, lot_number="4187SNL", daily_report_id=daily_id, dlc_date=DAY + datetime.timedelta(days=700))
    _daily(db, env, of_id, shift="night", team="Équipe C", semolina=5)
    sheet = DaySheetService(db).get_day_sheet(tenant_id=TENANT, date=DAY, work_center_id=env["line"], group_by="lot").value
    assert [c["key"] for c in sheet["columns"]] == ["4187SNL", ""]
    assert sheet["columns"][1]["name"] is None
    assert _row(sheet, "total_mp")["by_column"] == {"4187SNL": pytest.approx(10), "": pytest.approx(5)}


def test_the_month_read_by_lot_orders_the_lots_as_they_were_started_and_says_their_days(db, env):
    of_id = _open_of(db, env)
    _shift_run(db, env, of_id, day=DAY + datetime.timedelta(days=2), lot="4189SNL", semolina=3)
    _shift_run(db, env, of_id, day=DAY, lot="4187SNL", semolina=10, packed_t=9)
    _shift_run(db, env, of_id, day=DAY + datetime.timedelta(days=1), lot="4187SNL", semolina=4, packed_t=3)
    result = DaySheetService(db).get_month_recap(tenant_id=TENANT, month=MONTH, work_center_id=env["line"], group_by="lot")
    assert isinstance(result, Ok), getattr(result, "message", "")
    recap = result.value
    assert recap["group_by"] == "lot"
    assert [(c["key"], c["date_from"], c["date_to"]) for c in recap["columns"]] == [
        ("4187SNL", "2026-09-10", "2026-09-11"),
        ("4189SNL", "2026-09-12", "2026-09-12"),
    ]
    assert _row(recap, "total_mp")["by_column"] == {"4187SNL": pytest.approx(14), "4189SNL": pytest.approx(3)}
    assert _row(recap, "yield")["by_column"] == {"4187SNL": pytest.approx(12 / 14 * 100)}
    # Read by product, the same month lists both lots under the one product.
    by_product = _recap(db, env)
    assert by_product["columns"][0]["lots"] == ["4187SNL", "4189SNL"]


def test_an_unknown_grouping_is_refused(db, env):
    result = DaySheetService(db).get_day_sheet(tenant_id=TENANT, date=DAY, work_center_id=env["line"], group_by="team")
    assert isinstance(result, Err) and result.code == "INVALID_GROUPING"
    result = DaySheetService(db).get_month_recap(tenant_id=TENANT, month=MONTH, work_center_id=env["line"], group_by="shift")
    assert isinstance(result, Err) and result.code == "INVALID_GROUPING"


# -- the month workbook -----------------------------------------------------------

def test_the_month_workbook_lists_the_pc_lines_days_before_the_pl_lines_and_leaves_grinders_out(db, env):
    import io

    from openpyxl import load_workbook

    from modules.production.api.month_recap_export import build_month_recap_workbook, collect_month_recap

    db.execute("UPDATE production.work_centers SET name = 'Line_1_PL' WHERE id = %s", (env["line"],))
    db.execute("UPDATE production.work_centers SET name = 'Line_2_PC' WHERE id = %s", (env["other_line"],))
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name, line_type) VALUES (%s, %s, 'DS-BRY', 'Broyeur', 'grinder')",
        (str(ULID()), TENANT),
    )
    of_id = _open_of(db, env)
    _shift_run(db, env, of_id, lot="4187SNL", semolina=10, packed_t=9)
    _daily(db, env, of_id, day=DAY + datetime.timedelta(days=1), semolina=99, validate=False)

    data = collect_month_recap(db, tenant_id=TENANT, month=MONTH, today=DAY + datetime.timedelta(days=2))
    assert [(l.tag, l.line["name"], l.sheet_prefix) for l in data.lines] == [("PC", "Line_2_PC", "PC"), ("PL", "Line_1_PL", "PL")]
    pl = data.lines[1]
    assert [c["name"] for c in pl.by_product["columns"]] == ["Douman 500 g"]
    # The report still being filled in named no lot: it is a waiting column, not a figure.
    assert [(c["key"], c["reports"]["daily"]["pending"]) for c in pl.by_lot["columns"]] == [("4187SNL", 0), ("", 1)]
    # One sheet per day from the 1st to "today", the idle days included.
    assert [d["date"].day for d in pl.days] == list(range(1, 13))
    assert [(d["validated"], d["pending"]) for d in pl.days[9:]] == [(2, 0), (0, 1), (0, 0)]

    workbook = load_workbook(io.BytesIO(build_month_recap_workbook(data)))
    assert workbook.sheetnames == [
        "Récap", "Récap par lot", *[f"PC {d:02d}" for d in range(1, 13)], *[f"PL {d:02d}" for d in range(1, 13)],
        "Conso production", "Conso conditionnement", "Énergie", "Arrêts", "Déchets", "Équipes", "Tendance",
    ]
    day_sheet = workbook["PL 10"]
    header = next(r for r in range(1, 12) if day_sheet.cell(row=r, column=1).value == "Line_1_PL")
    assert [day_sheet.cell(row=header, column=c).value for c in range(3, 7)] == ["Morning", "Afternoon", "Night", "Total"]

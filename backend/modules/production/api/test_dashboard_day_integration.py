"""Integration tests for the dashboard's day and trend read model, against a real database.

Only validated reports count, every figure is computed per report and then
added up, and a period nobody reported on is `None`, never a fake zero.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.dashboard_day_service import DashboardDayService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.dashboard import ShiftWindow
from modules.production.domain.production_report import DailyReportDetail, DowntimeLine, SemolinaLine, WasteLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-dashboard-day"
DAY = datetime.date(2026, 9, 19)
T = datetime.time


@pytest.fixture
def env(db):
    actor = str(ULID())
    kg, tonne, semolina, rebroyat, finished, location, line, machine = (str(ULID()) for _ in range(8))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) VALUES (%s, %s, 'kg', 'Kilogram', 'weight', 1)", (kg, TENANT))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) VALUES (%s, %s, 't', 'Tonne', 'weight', 1000)", (tonne, TENANT))
    for product_id, sku, name, uom in (
        (semolina, "DD-SEM", "Semoule extra", tonne),
        (rebroyat, "DD-REB", "Rebroyat", kg),
        (finished, "DD-PASTA", "Doman PL 500 g", kg),
    ):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, name, uom),
        )
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'DD-LOC', 'Silo')", (location, TENANT))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'DD-WC', 'Ligne 1')", (line, TENANT))
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'DD-EQ', 'Extrudeuse')",
        (machine, TENANT, line),
    )
    for product in (semolina, rebroyat):
        StockService(db).receive_stock(
            tenant_id=TENANT, product_id=product, location_id=location, quantity=1_000_000,
            correlation_id=str(ULID()), reference="seed", actor_id=actor,
        )
    return {"actor": actor, "semolina": semolina, "rebroyat": rebroyat, "finished": finished, "location": location, "line": line, "machine": machine}


def _open_of(db, env):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["finished"], planned_quantity=1000,
        work_center_id=env["line"], start_date=DAY - datetime.timedelta(days=30),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok)
    return created.value.id


def _report(db, env, of_id, *, day=DAY, team="A", shift="Shift 1", semolina=0.0, finished=0.0, regrind_kg=0.0,
            waste=(), stops=(), validate=True):
    detail = DailyReportDetail(
        semolina_lines=(SemolinaLine(product_id=env["semolina"], quantity=semolina, location_id=env["location"]),),
        raw_material_location_id=env["location"],
        finished_product_quantity=finished,
        production_minutes=480,
        downtime_lines=tuple(DowntimeLine(motif=motif, minutes=minutes) for motif, minutes in stops),
        waste_lines=tuple(WasteLine(category=c, product_id=env["semolina"], quantity=q) for c, q in waste),
        regrind_input_quantity=regrind_kg,
        regrind_input_product_id=env["rebroyat"] if regrind_kg else None,
    )
    reports = ProductionReportService(db)
    created = reports.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of_id, report_date=day, team=team, shift=shift,
        equipment_id=env["machine"], detail=detail,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report_id = created.value["report"].id
    assert isinstance(reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    if validate:
        done = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID()))
        assert isinstance(done, Ok), getattr(done, "message", "")
    return report_id


def _day(db, day=DAY):
    return DashboardDayService(db).get_day(tenant_id=TENANT, date=day)


def test_a_day_nobody_reported_on_has_zero_totals_and_no_yield_or_comparison(db, env):
    payload = _day(db)
    assert payload["totals"]["semolina_poured"] == 0 and payload["totals"]["finished_product"] == 0
    assert payload["totals"]["yield_pct"] is None
    assert payload["previous_totals"] is None
    assert set(payload["directions"].values()) == {None}
    assert payload["ofs"] == [] and payload["waste"] == [] and payload["stops"] == []
    assert payload["awaiting_validation"] == 0


def test_rebroyat_in_kg_is_restated_into_the_semoule_unit_before_it_is_added(db, env):
    of_id = _open_of(db, env)
    # 30 t of semoule plus 500 kg of rebroyat is 30.5 t poured, not 530.
    _report(db, env, of_id, semolina=30, regrind_kg=500, finished=29)
    payload = _day(db)
    assert payload["unit"] == "t"
    assert payload["totals"]["semolina_poured"] == pytest.approx(30.5)
    assert payload["totals"]["yield_pct"] == pytest.approx(29 / 30.5 * 100)
    of = payload["ofs"][0]
    assert of["regrind_input"] == pytest.approx(0.5)
    assert [(p["name"], p["quantity"]) for p in of["semolina_by_product"]] == [("Semoule extra", 30.0)]


def test_only_validated_reports_count_and_submitted_ones_are_reported_as_waiting(db, env):
    of_id = _open_of(db, env)
    _report(db, env, of_id, semolina=10, finished=9.5)
    _report(db, env, of_id, team="B", shift="Shift 2", semolina=99, finished=99, validate=False)
    payload = _day(db)
    assert payload["totals"]["semolina_poured"] == pytest.approx(10)
    assert payload["awaiting_validation"] == 1


def test_one_of_is_cut_by_shift_and_team(db, env):
    of_id = _open_of(db, env)
    _report(db, env, of_id, team="A", shift="Shift 1", semolina=10, finished=9.6)
    _report(db, env, of_id, team="B", shift="Shift 2", semolina=12, finished=11.5)
    of = _day(db)["ofs"][0]
    assert of["semolina_poured"] == pytest.approx(22) and of["finished_product"] == pytest.approx(21.1)
    assert [(o["shift"], o["team"], round(o["finished_product"], 1)) for o in of["output_by_shift"]] == [
        ("Shift 1", "A", 9.6), ("Shift 2", "B", 11.5),
    ]


def test_two_ofs_on_the_same_line_are_kept_apart(db, env):
    first, second = _open_of(db, env), _open_of(db, env)
    _report(db, env, first, semolina=10, finished=9)
    _report(db, env, second, semolina=20, finished=18)
    ofs = {o["of_id"]: o for o in _day(db)["ofs"]}
    assert ofs[first]["finished_product"] == pytest.approx(9) and ofs[second]["finished_product"] == pytest.approx(18)
    assert ofs[first]["work_center_id"] == ofs[second]["work_center_id"] == env["line"]
    assert ofs[first]["reference"] and ofs[first]["reference"] != ofs[second]["reference"]


def test_stops_and_waste_are_reported_by_reason_team_and_line(db, env):
    of_id = _open_of(db, env)
    _report(db, env, of_id, team="A", semolina=10, finished=9, stops=[("extruder_failure", 60)], waste=[("press", 40)])
    _report(db, env, of_id, team="B", shift="Shift 2", semolina=10, finished=9, stops=[("format_change", 30)], waste=[("pouring", 10)])
    payload = _day(db)
    assert {(s["motif"], s["team"], s["work_center_id"], s["value"]) for s in payload["stops"]} == {
        ("extruder_failure", "A", env["line"], 60), ("format_change", "B", env["line"], 30),
    }
    assert {(w["category"], w["team"], w["value"]) for w in payload["waste"]} == {("press", "A", 40.0), ("pouring", "B", 10.0)}
    assert payload["totals"]["downtime_minutes"] == 90
    of = payload["ofs"][0]
    assert of["downtime_minutes"] == 90 and of["waste_kg"] == pytest.approx(50)
    assert of["stops"][0] == {"motif": "extruder_failure", "team": "A", "minutes": 60}


def test_direction_against_the_previous_day_is_read_at_display_precision(db, env):
    of_id = _open_of(db, env)
    _report(db, env, of_id, day=DAY - datetime.timedelta(days=1), semolina=20, finished=19, stops=[("extruder_failure", 10)])
    _report(db, env, of_id, semolina=30, finished=29)
    payload = _day(db)
    assert payload["previous_date"] == "2026-09-18"
    assert payload["directions"]["semolina_poured"] == "up"
    assert payload["directions"]["finished_product"] == "up"
    assert payload["directions"]["yield_pct"] == "up"  # 96.7 vs 95.0
    assert payload["directions"]["downtime_minutes"] == "down"  # 0 vs 10


def test_trend_by_day_keeps_a_missing_day_as_none_and_aligns_the_previous_period(db, env):
    of_id = _open_of(db, env)
    _report(db, env, of_id, day=datetime.date(2026, 9, 17), semolina=10, finished=9)
    _report(db, env, of_id, day=datetime.date(2026, 9, 19), semolina=12, finished=11)
    _report(db, env, of_id, day=datetime.date(2026, 9, 14), semolina=8, finished=7)  # previous window, middle day
    trend = DashboardDayService(db).get_trend(
        tenant_id=TENANT, date_from=datetime.date(2026, 9, 17), date_to=datetime.date(2026, 9, 19), granularity="day"
    )
    assert (trend["previous"]["from"], trend["previous"]["to"]) == ("2026-09-14", "2026-09-16")
    assert [p["key"] for p in trend["current"]["points"]] == ["2026-09-17", "2026-09-18", "2026-09-19"]
    assert [p["semolina_poured"] for p in trend["current"]["points"]] == [10, None, 12]
    assert [p["finished_product"] for p in trend["current"]["points"]] == [9, None, 11]
    assert [p["semolina_poured"] for p in trend["previous"]["points"]] == [8, None, None]
    assert trend["unit"] == "t"


def test_trend_by_shift_follows_the_configured_shift_order(db, env):
    of_id = _open_of(db, env)
    DashboardSettingsService(db).replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0)), ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0))],
    )
    _report(db, env, of_id, shift="Shift 2", team="B", semolina=12, finished=11)
    _report(db, env, of_id, shift="Shift 1", team="A", semolina=10, finished=9)
    trend = DashboardDayService(db).get_trend(tenant_id=TENANT, date_from=DAY, date_to=DAY, granularity="shift")
    assert [p["key"] for p in trend["current"]["points"]] == ["Shift 1", "Shift 2"]
    assert [p["finished_product"] for p in trend["current"]["points"]] == [9, 11]
    assert [p["finished_product"] for p in trend["previous"]["points"]] == [None, None]


def test_trend_by_week_buckets_on_monday(db, env):
    of_id = _open_of(db, env)
    _report(db, env, of_id, day=datetime.date(2026, 9, 9), semolina=10, finished=9)   # week of 7 Sep
    _report(db, env, of_id, day=datetime.date(2026, 9, 12), semolina=5, finished=4)   # same week
    _report(db, env, of_id, day=datetime.date(2026, 9, 16), semolina=20, finished=18)  # week of 14 Sep
    trend = DashboardDayService(db).get_trend(
        tenant_id=TENANT, date_from=datetime.date(2026, 9, 7), date_to=datetime.date(2026, 9, 20), granularity="week"
    )
    assert [p["key"] for p in trend["current"]["points"]] == ["2026-09-07", "2026-09-14"]
    assert [p["semolina_poured"] for p in trend["current"]["points"]] == [15, 20]
    assert [p["key"] for p in trend["previous"]["points"]] == ["2026-08-24", "2026-08-31"]

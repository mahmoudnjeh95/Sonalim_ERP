"""Integration tests for team-performance aggregation, against a real database.

The property under test: totals are bucketed by team and by calendar period, and
only validated reports count — the same validated-only rule every other
aggregate in this module follows.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.team_performance_service import TeamPerformanceService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.domain.production_report import DailyReportDetail, DowntimeLine, SemolinaLine, WasteLine
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "integration-test-team-performance"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, work_center, equipment = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TP-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TP-LOC', 'Test location')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TP-WC', 'Test line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'TP-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    # Needed only by tests that validate a report with rebroyat above zero —
    # harmless to the rest, which never set regrind_quantity.
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=product)
    return {"actor": actor, "product": product, "location": location, "work_center": work_center, "equipment": equipment}


def _validated_report(
    db, env, *, team, report_date, semolina_quantity, production_minutes, downtime_minutes,
    downtime_reason=None, water_percentage=0, semolina_flow_rate=0, downtime_lines=None,
    waste_lines=(), regrind_quantity=0, recipe_id=None,
    semolina_product_id=None, regrind_input_quantity=0, regrind_input_product_id=None,
    equipment_id=None, regrind_product_id=...,
):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=report_date,
        recipe_id=recipe_id,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)

    reports = ProductionReportService(db)
    detail = DailyReportDetail(
        semolina_lines=(
            SemolinaLine(
                product_id=semolina_product_id or env["product"], quantity=semolina_quantity, location_id=env["location"]
            ),
        ),
        raw_material_location_id=env["location"],
        production_minutes=production_minutes,
        downtime_lines=downtime_lines
        if downtime_lines is not None
        else (
            (
                DowntimeLine(
                    motif=downtime_reason or ("other" if downtime_minutes else None),
                    minutes=downtime_minutes,
                ),
            )
            if downtime_minutes
            else ()
        ),
        water_percentage=water_percentage,
        semolina_flow_rate=semolina_flow_rate,
        waste_lines=waste_lines,
        regrind_quantity=regrind_quantity,
        regrind_product_id=(
            (env["product"] if regrind_quantity else None) if regrind_product_id is ... else regrind_product_id
        ),
        regrind_input_quantity=regrind_input_quantity,
        regrind_input_product_id=regrind_input_product_id,
    )
    created_report = reports.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=report_date,
        team=team, shift="morning", equipment_id=equipment_id or env["equipment"], detail=detail,
    )
    assert isinstance(created_report, Ok), getattr(created_report, "message", "")
    report_id = created_report.value["report"].id
    assert isinstance(reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID()))
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    return order.id


def test_totals_are_bucketed_by_team_and_period(db, env):
    # Same week, two teams: their totals must not bleed into each other.
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=500, production_minutes=400, downtime_minutes=20,
    )
    _validated_report(
        db, env, team="B", report_date=datetime.date(2026, 9, 2),
        semolina_quantity=300, production_minutes=350, downtime_minutes=50,
    )
    # A later week for team A, to prove periods don't collapse into one bucket.
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 10),
        semolina_quantity=200, production_minutes=200, downtime_minutes=10,
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    by_key = {(r["team"], r["period"]): r for r in rows}

    week1_a = next(r for (team, _), r in by_key.items() if team == "A" and r["semolina_quantity"] == 500)
    assert week1_a["production_minutes"] == 400
    assert week1_a["downtime_minutes"] == 20
    assert week1_a["report_count"] == 1

    week1_b = next(r for (team, _), r in by_key.items() if team == "B")
    assert week1_b["semolina_quantity"] == 300

    week2_a = next(r for (team, _), r in by_key.items() if team == "A" and r["semolina_quantity"] == 200)
    assert week1_a["period"] != week2_a["period"]


def test_net_semoule_waste_is_daily_waste_net_of_declared_regrind(db, env):
    """The écart the plant wants to minimise: semoule déchet across the daily
    report's own stages, net of what the shift declared as recoverable rebroyat
    over the same reports — never conditionnement's product/packaging waste,
    which isn't semoule any more."""
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, production_minutes=400, downtime_minutes=0,
        waste_lines=(
            WasteLine(category="press", product_id=env["product"], quantity=30),
            WasteLine(category="kneading", product_id=env["product"], quantity=10),
        ),
        regrind_quantity=25,
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    row = next(r for r in rows if r["team"] == "A")

    assert row["daily_waste_by_category"] == {"press": 30.0, "kneading": 10.0}
    assert row["regrind_quantity"] == 25.0
    assert row["net_semoule_waste"] == 15.0


def test_net_semoule_waste_nets_rebroyat_in_tonnes_as_kilos(db, env):
    """`regrind_quantity` is counted in the rebroyat product's own unit —
    tonnes here, same as OfConsolidationService's fixture — while
    `net_semoule_waste` nets against the daily déchet's raw kilos. Netting the
    native tonnes figure straight against kilos would read 150 kg of rebroyat
    as cancelling 150 t of déchet."""
    tonne_uom, rebroyat = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) "
        "VALUES (%s, %s, 'ton', 'Tonne', 'weight', 1000)",
        (tonne_uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TP-REB-T', 'Rebroyat', %s)",
        (rebroyat, TENANT, tonne_uom),
    )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=env["actor"], output_product_id=rebroyat)

    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, production_minutes=400, downtime_minutes=0,
        waste_lines=(WasteLine(category="press", product_id=env["product"], quantity=200),),
        regrind_quantity=0.15, regrind_product_id=None,
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    row = next(r for r in rows if r["team"] == "A")

    assert row["regrind_quantity"] == 0.15
    assert row["regrind_quantity_kg"] == pytest.approx(150)
    assert row["net_semoule_waste"] == pytest.approx(200 - 150)


def test_daily_waste_by_category_is_not_restated_against_the_item_unit(db, env):
    """The bug this closed: `daily_waste_by_category` used to restate each
    stage into its own item's unit of measure (same idea as `waste_by_product`
    below) — fine for a single figure read in isolation, but `finished_product_
    conditioning` is routinely logged against a finished-good item stocked in
    kg while the other five stages use bulk semoule stocked in tonnes. Once the
    production dashboard's semoule-waste chart stacks and compares stages side
    by side, a 12 kg category rendered as a *bigger* bar than a 12 000 kg one,
    because 12 (kg) and 12 (tonnes-of-12000kg) look identical on a shared axis.
    `daily_waste_by_category` must stay in raw kilos — the form's own basis,
    same as `net_semoule_waste` — so stages stay comparable regardless of which
    item each one happens to be logged against.
    """
    tonne_uom, tonne_product = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) "
        "VALUES (%s, %s, 'ton', 'Tonne', 'weight', 1000)",
        (tonne_uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TP-TONNE', 'Tonne product', %s)",
        (tonne_product, TENANT, tonne_uom),
    )

    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=500, production_minutes=100, downtime_minutes=0,
        waste_lines=(
            WasteLine(category="press", product_id=tonne_product, quantity=12_000),
            WasteLine(category="finished_product_conditioning", product_id=env["product"], quantity=12),
        ),
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    row = next(r for r in rows if r["team"] == "A")

    # 12 000 kg of press waste stays visibly 1000x the 12 kg of finished-
    # product waste, not collapsed to the same "12" by a per-item conversion.
    assert row["daily_waste_by_category"]["press"] == 12_000.0
    assert row["daily_waste_by_category"]["finished_product_conditioning"] == 12.0
    by_product = {entry["product_id"]: entry["quantity"] for entry in row["waste_by_product"]}
    # waste_by_product is unaffected -- it's still keyed one row per product,
    # so restating a single product's own figure into its own unit there is
    # unambiguous (no stacking, nothing to compare it against).
    assert by_product[tonne_product] == pytest.approx(12.0)
    assert row["net_semoule_waste"] == 12_012.0


def test_material_input_restates_regrind_input_against_the_semoule_unit(db, env):
    """The bug this closed: material_input_quantity summed semolina_quantity
    (a tonne-denominated product here) and regrind_input_quantity (a
    kg-denominated rebroyat product) as if they were the same unit, inflating
    the denominator by up to 1000x and crashing the team's reported yield —
    exactly what surfaced as Équipe B's rendement falling to ~33% on the
    production dashboard for a week that included one large, kg-recorded
    rebroyat input. WorkOrderYieldService and OfConsolidationService already
    restate rebroyat against the semoule side's own unit; this is the same
    fix for TeamPerformanceService.
    """
    ton_uom, ton_product = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) "
        "VALUES (%s, %s, 'ton', 'Tonne', 'weight', 1000)",
        (ton_uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TP-TON-SEM', 'Tonne semoule', %s)",
        (ton_product, TENANT, ton_uom),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=ton_product, location_id=env["location"], quantity=1000,
        correlation_id=str(ULID()), reference="test-seed-ton", actor_id=env["actor"],
    )
    # env["product"] is kg-denominated (see the env fixture) and doubles as
    # the rebroyat-input product here, so no separate product/stock is needed.

    _validated_report(
        db, env, team="B", report_date=datetime.date(2026, 9, 10),
        semolina_quantity=12, production_minutes=100, downtime_minutes=0,
        semolina_product_id=ton_product,
        regrind_input_quantity=95, regrind_input_product_id=env["product"],
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    row = next(r for r in rows if r["team"] == "B")

    assert row["semolina_quantity"] == 12
    assert row["regrind_input_quantity"] == 95, "the native kg figure is left alone for display"
    # 95 kg restated into tonnes (95 / 1000) before joining the tonne-denominated semoule.
    assert row["material_input_quantity"] == pytest.approx(12.095), (
        "regrind_input_quantity must be converted to the semoule's own unit, "
        "not added to it raw"
    )


def test_draft_reports_are_excluded(db, env):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=datetime.date(2026, 9, 15),
    )
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 15),
        team="C", shift="morning",
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=999, location_id=env["location"]),),
            raw_material_location_id=env["location"],
        ),
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    assert not any(r["team"] == "C" for r in rows)


def test_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="fortnight")


def test_downtime_reasons_are_summed_across_reports(db, env):
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=100, production_minutes=400, downtime_minutes=20, downtime_reason="extruder_failure",
    )
    _validated_report(
        db, env, team="B", report_date=datetime.date(2026, 9, 2),
        semolina_quantity=100, production_minutes=400, downtime_minutes=15, downtime_reason="extruder_failure",
    )
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 3),
        semolina_quantity=100, production_minutes=400, downtime_minutes=5, downtime_reason="electrical_failure",
    )
    # No downtime at all: must not show up as a reason of its own.
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 4),
        semolina_quantity=100, production_minutes=400, downtime_minutes=0,
    )

    rows = {r["reason"]: r for r in TeamPerformanceService(db).list_downtime_reasons(tenant_id=TENANT)}
    assert rows["extruder_failure"]["minutes"] == 35
    assert rows["extruder_failure"]["report_count"] == 2
    assert rows["electrical_failure"]["minutes"] == 5
    # Worst offender first.
    ordered = TeamPerformanceService(db).list_downtime_reasons(tenant_id=TENANT)
    assert ordered[0]["reason"] == "extruder_failure"


def test_one_report_can_contribute_more_than_one_reason(db, env):
    """The capability the single downtime_minutes/downtime_reason column never
    had: one shift, two stoppages, two motifs, both counted."""
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 5),
        semolina_quantity=100, production_minutes=400, downtime_minutes=0,
        downtime_lines=(
            DowntimeLine(motif="extruder_failure", minutes=12),
            DowntimeLine(motif="electrical_failure", minutes=8),
        ),
    )

    rows = {r["reason"]: r for r in TeamPerformanceService(db).list_downtime_reasons(tenant_id=TENANT)}
    assert rows["extruder_failure"]["minutes"] == 12
    assert rows["electrical_failure"]["minutes"] == 8

    performance = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="day")
    row = next(r for r in performance if r["team"] == "A" and r["period"] == "2026-09-05")
    assert row["downtime_minutes"] == 20, "both stoppages count toward the team's total"


def test_downtime_breakdown_carries_team_and_machine_per_row(db, env):
    equipment_2 = str(ULID())
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'TP-EQ-2', 'Test machine 2')",
        (equipment_2, TENANT, env["work_center"]),
    )
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 10),
        semolina_quantity=100, production_minutes=400, downtime_minutes=20, downtime_reason="extruder_failure",
    )
    _validated_report(
        db, env, team="B", report_date=datetime.date(2026, 9, 11),
        semolina_quantity=100, production_minutes=400, downtime_minutes=10, downtime_reason="electrical_failure",
        equipment_id=equipment_2,
    )

    rows = TeamPerformanceService(db).list_downtime_breakdown(tenant_id=TENANT)
    team_a_row = next(r for r in rows if r["team"] == "A" and r["reason"] == "extruder_failure")
    assert team_a_row["equipment_id"] == env["equipment"]
    assert team_a_row["minutes"] == 20

    team_b_row = next(r for r in rows if r["team"] == "B" and r["reason"] == "electrical_failure")
    assert team_b_row["equipment_id"] == equipment_2
    assert team_b_row["minutes"] == 10


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _validated_shift(db, env, *, team, report_date, semolina_quantity, water_percentage=0, semolina_flow_rate=0, recipe_id=None) -> str:
    """A new OF and one validated shift of `team` running it: the recipe correlation reads shift runs."""
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=1000,
        work_center_id=env["work_center"], start_date=report_date, recipe_id=recipe_id,
    )).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    shifts = ShiftReportService(db)
    shift_id = _ok(shifts.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=report_date,
        shift="morning", team=team,
    ))["id"]
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 400, "finished_product_quantity": 900, "raw_material_location_id": env["location"],
        "water_percentage": water_percentage, "semolina_flow_rate": semolina_flow_rate,
    }
    versements = [{"product_id": env["product"], "quantity": semolina_quantity, "location_id": env["location"]}]
    _ok(shifts.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
                            payload={"runs": [run], "versements": versements}))
    for key in SECTION_KEYS:
        hand_in = shifts.submit_section if key == "runs" else shifts.declare_nothing
        _ok(hand_in(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return of_id


def test_recipe_correlation_pairs_shift_inputs_with_the_ofs_yield(db, env):
    of_id = _validated_shift(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, water_percentage=32, semolina_flow_rate=4.5,
    )

    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["of_id"] == of_id
    assert row["water_percentage"] == 32
    assert row["semolina_flow_rate"] == 4.5
    assert row["yield_ratio"] is not None


def test_recipe_correlation_skips_shifts_with_no_dosage_recorded(db, env):
    _validated_shift(db, env, team="A", report_date=datetime.date(2026, 9, 1), semolina_quantity=1000)
    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)
    assert rows == []


def test_recipe_correlation_carries_the_recipes_water_target_range(db, env):
    """The OF's recipe names a water component with a min/max %; the shift's
    own water_percentage should be checkable against it without recomputing
    anything recipe_check_service already owns — that service compares poured
    *quantities*, and water here is a bare percentage with no quantity of its
    own to join against.
    """
    water_product = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES "
        "(%s, %s, 'TP-WATER', 'Water', (SELECT uom_id FROM core.products WHERE id = %s))",
        (water_product, TENANT, env["product"]),
    )
    ProductClassificationService(db).set_classification(
        tenant_id=TENANT, actor_id=env["actor"], product_id=water_product,
        category="raw_material", is_water=True,
    )
    recipe_id = str(ULID())
    db.execute(
        "INSERT INTO production.recipes (id, tenant_id, target_product_id, version, status) "
        "VALUES (%s, %s, %s, 1, 'active')",
        (recipe_id, TENANT, env["product"]),
    )
    db.execute(
        "INSERT INTO production.recipe_lines "
        "(id, recipe_id, tenant_id, component_product_id, default_percentage, min_percentage, max_percentage, is_hard_limit) "
        "VALUES (%s, %s, %s, %s, 30, 28, 32, false)",
        (str(ULID()), recipe_id, TENANT, water_product),
    )

    _validated_shift(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, water_percentage=35, semolina_flow_rate=4.5, recipe_id=recipe_id,
    )

    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["water_percentage"] == 35
    assert row["water_target_min"] == 28
    assert row["water_target_max"] == 32
    assert row["water_target_default"] == 30
    assert row["report_date"] == "2026-09-01"
    assert row["team"] == "A"

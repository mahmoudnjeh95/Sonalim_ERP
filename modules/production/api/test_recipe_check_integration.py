"""Integration tests for the recipe limit check.

The domain tests pin the arithmetic. What matters here is where the mix comes
from, because two tables record material entering an OF and they overlap: a
product named on a daily report must never also be counted from the OF's poured
input lines, or a correct mix produces a warning.

Nothing here asserts a refusal. The check is advisory by design, and the last
test in the file says so against the real report flow.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.recipe_check_service import RecipeCheckService
from modules.production.api.regrind_service import RegrindDefaultsService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import DailyReportDetail, SemolinaLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-recipe-check"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, semoule, rebroyat, additive, pasta, location, work_center, equipment = (str(ULID()) for _ in range(8))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    for product_id, sku in (
        (semoule, "RC-SEMOULE"),
        (rebroyat, "RC-REBROYAT"),
        (additive, "RC-ADDITIVE"),
        (pasta, "RC-PASTA"),
    ):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'RM', 'Raw materials')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'RC-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'RC-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    stock = StockService(db)
    for product_id in (semoule, rebroyat, additive):
        stock.receive_stock(
            tenant_id=TENANT, product_id=product_id, location_id=location, quantity=100_000,
            correlation_id=str(ULID()), reference="seed", actor_id=actor,
        )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=rebroyat)
    return {
        "actor": actor,
        "semoule": semoule,
        "rebroyat": rebroyat,
        "additive": additive,
        "pasta": pasta,
        "location": location,
        "work_center": work_center,
        "equipment": equipment,
    }


def _recipe(db, env, *lines) -> str:
    """An active recipe. `lines` are (product_id, min, max, is_hard)."""
    recipe_id = str(ULID())
    db.execute(
        "INSERT INTO production.recipes (id, tenant_id, target_product_id, version, status) "
        "VALUES (%s, %s, %s, 1, 'active')",
        (recipe_id, TENANT, env["pasta"]),
    )
    for product_id, minimum, maximum, hard in lines:
        db.execute(
            "INSERT INTO production.recipe_lines "
            "(id, recipe_id, tenant_id, component_product_id, default_percentage, min_percentage, max_percentage, is_hard_limit) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (str(ULID()), recipe_id, TENANT, product_id, (minimum + maximum) / 2, minimum, maximum, hard),
        )
    return recipe_id


def _of(db, env, *, recipe_id=None, poured_inputs=None, start_date=None):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        product_id=env["pasta"],
        planned_quantity=1000,
        work_center_id=env["work_center"],
        recipe_id=recipe_id,
        poured_inputs=poured_inputs or [],
        poured_inputs_location_id=env["location"] if poured_inputs else None,
        start_date=start_date,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _daily(db, env, of, *, date, shift="morning", validate=True, **detail):
    semolina_lines = detail.pop("semolina_lines", None)
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(
                product_id=detail.pop("semolina_product_id", env["semoule"]),
                quantity=detail.pop("semolina_quantity", 0),
                location_id=env["location"],
            ),
        )
    detail["semolina_lines"] = semolina_lines
    detail.setdefault("raw_material_location_id", env["location"])
    service = ProductionReportService(db)
    created = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=date, shift=shift,
        equipment_id=env["equipment"],
        detail=DailyReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    if validate:
        result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
        assert isinstance(result, Ok), getattr(result, "message", "")
    return report


def _check(db, of) -> dict:
    result = RecipeCheckService(db).check_work_order(tenant_id=TENANT, of_id=of.id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _codes(check) -> set:
    return {(f["code"], f["component_product_id"]) for f in check["findings"]}


# --- where the mix comes from -----------------------------------------------


def test_the_mix_is_read_from_validated_daily_reports(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True), (env["rebroyat"], 5, 15, False))
    of = _of(db, env, recipe_id=recipe)
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=900, regrind_input_quantity=100, regrind_input_product_id=env["rebroyat"],
    )

    check = _check(db, of)
    assert check["mix_total"] == 1000
    assert check["findings"] == []


def test_a_draft_report_is_not_part_of_the_mix_yet(db, env):
    """Only validated reports moved stock, so only they describe what was poured."""
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True))
    of = _of(db, env, recipe_id=recipe)
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=900, validate=False)

    check = _check(db, of)
    assert check["mix_total"] == 0
    assert check["findings"] == [], "nothing poured yet is nothing broken"


def test_shifts_accumulate_into_one_mix(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True), (env["rebroyat"], 5, 15, False))
    of = _of(db, env, recipe_id=recipe)
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1), shift="morning",
        semolina_quantity=450, regrind_input_quantity=50, regrind_input_product_id=env["rebroyat"],
    )
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1), shift="afternoon",
        semolina_quantity=450, regrind_input_quantity=50, regrind_input_product_id=env["rebroyat"],
    )

    check = _check(db, of)
    assert check["mix_total"] == 1000
    assert check["findings"] == []


def test_poured_input_lines_supply_components_the_daily_report_cannot_record(db, env):
    """A daily report has fields for semoule and rebroyat and nothing else, so an
    additive only ever reaches the mix through the OF's input lines."""
    recipe = _recipe(db, env, (env["semoule"], 95, 99, True), (env["additive"], 1, 5, False))
    of = _of(db, env, recipe_id=recipe, poured_inputs=[(env["additive"], 20)])
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=980)

    check = _check(db, of)
    assert check["mix_total"] == 1000
    assert check["findings"] == []


def test_a_product_on_a_report_is_not_counted_twice_from_the_input_lines(db, env):
    """The OF was opened declaring 900 kg of semoule and the shift then reported
    pouring the same 900. Counting both makes 1800 and turns a correct mix into a
    violation — the exact failure this rule exists to prevent."""
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True), (env["rebroyat"], 5, 15, False))
    of = _of(db, env, recipe_id=recipe, poured_inputs=[(env["semoule"], 900)])
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=900, regrind_input_quantity=100, regrind_input_product_id=env["rebroyat"],
    )

    check = _check(db, of)
    assert check["mix_total"] == 1000, "the report's figure, not the sum of both records"
    assert check["findings"] == []


# --- what it reports --------------------------------------------------------


def test_too_much_rebroyat_is_reported_against_its_limit(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True), (env["rebroyat"], 5, 15, False))
    of = _of(db, env, recipe_id=recipe)
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=700, regrind_input_quantity=300, regrind_input_product_id=env["rebroyat"],
    )

    check = _check(db, of)
    assert ("ABOVE_MAXIMUM", env["rebroyat"]) in _codes(check)
    assert ("BELOW_MINIMUM", env["semoule"]) in _codes(check)
    assert check["hard_finding_count"] == 1, "semoule's limit is hard, rebroyat's is soft"


def test_a_component_the_recipe_names_but_nobody_poured_is_reported(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 100, True), (env["additive"], 1, 5, False))
    of = _of(db, env, recipe_id=recipe)
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)

    assert ("COMPONENT_NOT_POURED", env["additive"]) in _codes(_check(db, of))


def test_a_product_the_recipe_does_not_name_is_reported(db, env):
    recipe = _recipe(db, env, (env["semoule"], 0, 100, True))
    of = _of(db, env, recipe_id=recipe, poured_inputs=[(env["additive"], 50)])
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=950)

    assert ("NOT_IN_RECIPE", env["additive"]) in _codes(_check(db, of))


def test_an_of_without_a_recipe_says_so_rather_than_passing(db, env):
    """An empty findings list on a screen reads as "checked, all good". An OF with
    no formula was never checked at all, and the flag is how the UI can say that."""
    of = _of(db, env)
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)

    check = _check(db, of)
    assert check["has_recipe"] is False
    assert ("NOT_IN_RECIPE", env["semoule"]) in _codes(check)


def test_an_of_with_no_reports_yet_has_broken_nothing(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True))
    of = _of(db, env, recipe_id=recipe)

    check = _check(db, of)
    assert check["mix"] == []
    assert check["findings"] == []
    assert check["has_findings"] is False


def test_an_unknown_of_is_not_found(db, env):
    result = RecipeCheckService(db).check_work_order(tenant_id=TENANT, of_id=str(ULID()))
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


def test_another_tenant_cannot_read_the_check(db, env):
    of = _of(db, env)
    result = RecipeCheckService(db).check_work_order(tenant_id="some-other-tenant", of_id=of.id)
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


# --- advisory, and only advisory --------------------------------------------


def test_a_mix_far_outside_a_hard_limit_still_files_and_validates(db, env):
    """The decision the plant settled on: warn, never block. The line has already
    run — refusing the paperwork changes nothing about what went into the mix, and
    loses the record of it."""
    recipe = _recipe(db, env, (env["semoule"], 95, 100, True))
    of = _of(db, env, recipe_id=recipe)

    report = _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=500, regrind_input_quantity=500, regrind_input_product_id=env["rebroyat"],
    )

    stored = db.execute(
        "SELECT status FROM production.production_reports WHERE id = %s", (report.id,)
    ).fetchone()
    assert stored[0] == "validated", "the report went all the way through"

    check = _check(db, of)
    assert check["hard_finding_count"] >= 1, "and the drift is still reported"


# --- drift summary, aggregated across OFs ------------------------------------


def test_drift_summary_aggregates_hard_and_soft_ofs_by_recipe(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True), (env["rebroyat"], 5, 15, False))
    clean = _of(db, env, recipe_id=recipe)
    _daily(
        db, env, clean, date=datetime.date(2026, 9, 1),
        semolina_quantity=900, regrind_input_quantity=100, regrind_input_product_id=env["rebroyat"],
    )
    drifted = _of(db, env, recipe_id=recipe)
    _daily(
        db, env, drifted, date=datetime.date(2026, 9, 2),
        semolina_quantity=500, regrind_input_quantity=500, regrind_input_product_id=env["rebroyat"],
    )

    rows = RecipeCheckService(db).list_recipe_drift(tenant_id=TENANT)
    row = next(r for r in rows if r["recipe_id"] == recipe)
    assert row["of_count"] == 2
    assert row["hard_finding_of_count"] == 1, "the drifted OF trips semoule's hard limit"
    assert row["soft_finding_of_count"] == 0, "an OF with a hard finding counts as hard, not also soft"
    assert row["top_finding_count"] == 1


def test_drift_summary_excludes_ofs_with_no_recipe(db, env):
    of = _of(db, env)
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)

    rows = RecipeCheckService(db).list_recipe_drift(tenant_id=TENANT)
    assert rows == []


def test_drift_summary_is_filtered_by_start_date(db, env):
    recipe = _recipe(db, env, (env["semoule"], 85, 95, True))
    in_range = _of(db, env, recipe_id=recipe, start_date=datetime.date(2026, 9, 5))
    _daily(db, env, in_range, date=datetime.date(2026, 9, 5), semolina_quantity=1000)
    out_of_range = _of(db, env, recipe_id=recipe, start_date=datetime.date(2026, 1, 1))
    _daily(db, env, out_of_range, date=datetime.date(2026, 1, 1), semolina_quantity=1000)

    rows = RecipeCheckService(db).list_recipe_drift(tenant_id=TENANT, date_from="2026-09-01", date_to="2026-09-30")
    row = next(r for r in rows if r["recipe_id"] == recipe)
    assert row["of_count"] == 1

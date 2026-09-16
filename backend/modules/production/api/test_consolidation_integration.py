"""Integration tests for OF consolidation and the rewritten yield (Phase 6).

The property under test throughout: **only validated reports count, and nothing is
stored**. A draft or rejected report is a claim nobody approved, and from Phase 5 a
validated one is also what moved stock — so consolidating anything else would let
unapproved figures into the OF's official result.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.of_consolidation_service import OfConsolidationService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService
from modules.production.api.service import WorkOrderService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    DowntimeLine,
    SemolinaLine,
    WasteLine,
)
from modules.qc.api.quality_service import QualityReportService
from modules.qc.domain.quality import QualityReportDetail
from modules.warehouse.api.service import StockService

TENANT = "integration-test-consolidation"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, film, carton, location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(8))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    # net_weight_grams=1_000_000 makes the finished good's own "packet" a tonne,
    # so passing packets_counted=N to _packing below reads as N tonnes with no
    # carton tier involved — the simplest fixture that exercises the same
    # decision-24 tonnage_from_count path production actually uses (Phase 9),
    # without every test having to pick a carton size to get a round number.
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, net_weight_grams) VALUES (%s, %s, %s, %s, %s, %s)",
        (product, TENANT, "CONSO-PASTA", "CONSO-PASTA", uom, 1_000_000),
    )
    for product_id, sku in ((film, "CONSO-FILM"), (carton, "CONSO-CARTON")):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
    for location_id, code in ((location, "FG"), (packaging_location, "PACK")):
        db.execute(
            "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
            (location_id, TENANT, code, code),
        )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'CONSO-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'CONSO-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )

    stock = StockService(db)
    stock.receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="seed", actor_id=actor,
    )
    stock.receive_stock(
        tenant_id=TENANT, product_id=film, location_id=packaging_location, quantity=10_000,
        correlation_id=str(ULID()), reference="seed", actor_id=actor,
    )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=product)
    return {
        "actor": actor,
        "product": product,
        "film": film,
        "carton": carton,
        "location": location,
        "packaging_location": packaging_location,
        "work_center": work_center,
        "equipment": equipment,
    }


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        product_id=env["product"],
        planned_quantity=1000,
        work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _daily(db, env, of, *, date, shift="morning", validate=True, **detail):
    semolina_lines = detail.pop("semolina_lines", None)
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(
                product_id=detail.pop("semolina_product_id", env["product"]),
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


def _packing(db, env, of, *, date, shift="afternoon", validate=True, **detail):
    detail.setdefault("film_product_id", env["film"])
    detail.setdefault("packaging_location_id", env["packaging_location"])
    detail.setdefault("finished_goods_location_id", env["location"])
    created = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=date, shift=shift,
        equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    service = ProductionReportService(db)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    if validate:
        result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
        assert isinstance(result, Ok), getattr(result, "message", "")
    return report


def _consolidate(db, of) -> dict:
    result = OfConsolidationService(db).consolidate(tenant_id=TENANT, of_id=of.id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


# --- what consolidation sums ------------------------------------------------


def test_consolidation_sums_every_validated_shift(db, env, of):
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, water_quantity=50, fuel_quantity=20, gasoil_quantity=8,
    )
    _daily(
        db, env, of, date=datetime.date(2026, 9, 2),
        semolina_quantity=800, water_quantity=40, fuel_quantity=15, gasoil_quantity=6,
    )
    _packing(db, env, of, date=datetime.date(2026, 9, 1), packets_counted=900, film_quantity=30)
    _packing(db, env, of, date=datetime.date(2026, 9, 2), packets_counted=700, film_quantity=25)

    result = _consolidate(db, of)
    assert result["raw_material"]["semolina_quantity"] == 1800
    assert result["utilities"]["water_quantity"] == 90
    assert result["utilities"]["fuel_quantity"] == 35
    assert result["utilities"]["gasoil_quantity"] == 14
    assert result["produced_quantity"] == 1600
    assert result["packaging"]["film_quantity"] == 55
    assert result["report_counts"] == {"daily": 2, "conditionnement": 2, "quality": 0}


def test_downtime_across_several_daily_reports_and_several_arrets_each(db, env, of):
    """Two reports, each with two of its own arrêts: the OF-level total sums
    every line, not just one figure per report."""
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=500,
        downtime_lines=(DowntimeLine(motif="extruder_failure", minutes=10), DowntimeLine(motif="electrical_failure", minutes=5)),
    )
    _daily(
        db, env, of, date=datetime.date(2026, 9, 2), semolina_quantity=500,
        downtime_lines=(DowntimeLine(motif="die_jam", minutes=20),),
    )

    result = _consolidate(db, of)
    assert result["time"]["downtime_minutes"] == 35


def test_a_draft_report_is_not_consolidated(db, env, of):
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)
    # A second shift entered but never submitted.
    ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=datetime.date(2026, 9, 2),
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=9999, location_id=env["location"]),),
            raw_material_location_id=env["location"],
        ),
    )
    assert _consolidate(db, of)["raw_material"]["semolina_quantity"] == 1000


def test_a_rejected_report_is_not_consolidated(db, env, of):
    service = ProductionReportService(db)
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)
    rejected = _daily(db, env, of, date=datetime.date(2026, 9, 2), semolina_quantity=5000, validate=False)
    service.reject_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=rejected.id, reason="silo reading wrong"
    )
    assert _consolidate(db, of)["raw_material"]["semolina_quantity"] == 1000


def test_the_daily_finished_product_figure_is_not_added_to_produced(db, env, of):
    """Locked decision 7 — the same pasta must not be counted twice."""
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000, finished_product_quantity=900)
    _packing(db, env, of, date=datetime.date(2026, 9, 1), packets_counted=900)

    assert _consolidate(db, of)["produced_quantity"] == 900


def test_the_consolidated_figures_name_their_product(db, env, of):
    """A total is only readable in a unit, and the unit comes from the product.
    Where every report named the same one, the consolidation says which."""
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)
    _daily(db, env, of, date=datetime.date(2026, 9, 2), semolina_quantity=800)
    _packing(db, env, of, date=datetime.date(2026, 9, 1), packets_counted=900, film_quantity=5)

    result = _consolidate(db, of)
    assert result["raw_material"]["semolina_product_id"] == env["product"]
    assert result["packaging"]["film_product_id"] == env["film"]


def test_disagreeing_reports_name_no_product_at_all(db, env, of):
    """Two shifts poured different semoules. Summing them is still right -- both
    are kilograms -- but naming one of the two products would make the screen
    claim a provenance the total does not have."""
    other = str(ULID())
    uom = db.execute(
        "SELECT id FROM core.uoms WHERE tenant_id = %s LIMIT 1", (TENANT,)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'CONSO-SEM2', 'Semoule 2', %s)",
        (other, TENANT, uom),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=other, location_id=env["location"], quantity=10_000,
        correlation_id=str(ULID()), reference="seed", actor_id=env["actor"],
    )
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)
    _daily(
        db, env, of, date=datetime.date(2026, 9, 2),
        semolina_quantity=800, semolina_product_id=other,
    )

    result = _consolidate(db, of)
    assert result["raw_material"]["semolina_quantity"] == 1800
    assert result["raw_material"]["semolina_product_id"] is None


def test_waste_is_grouped_by_stage_and_by_item(db, env, of):
    """Both groupings come from the same lines, so they cannot disagree."""
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, regrind_quantity=10,
        waste_lines=(
            WasteLine(category="raw_material", product_id=env["product"], quantity=5),
            WasteLine(category="press", product_id=env["product"], quantity=3),
        ),
    )
    _packing(
        db, env, of, date=datetime.date(2026, 9, 1),
        packets_counted=900,
        waste_lines=(
            WasteLine(category="product", product_id=env["product"], quantity=2),
            WasteLine(category="packaging", product_id=env["film"], quantity=1),
            WasteLine(category="packaging", product_id=env["carton"], quantity=4),
        ),
    )

    waste = _consolidate(db, of)["waste"]
    assert waste["by_category"] == {"raw_material": 5, "press": 3, "product": 2, "packaging": 5}

    by_product = {entry["product_id"]: entry["quantity"] for entry in waste["by_product"]}
    assert by_product == {env["product"]: 10, env["carton"]: 4, env["film"]: 1}
    # Worst loss first: a list ordered by product id is a list nobody scans.
    assert [entry["quantity"] for entry in waste["by_product"]] == [10, 4, 1]
    assert waste["unattributed_quantity"] == 0

    # Rebroyat is reported beside the déchets but is not one of them: it is
    # recovered material that opens its own OF.
    assert waste["regrind"]["quantity"] == 10
    assert "total" not in waste, "a total across items in different units means nothing"

    # The écart: daily-report déchet only (raw_material + press, never the
    # packing report's product/packaging, which isn't semoule any more), net
    # of the rebroyat declared over the same reports.
    assert waste["net_semoule_waste"] == 5 + 3 - 10


def test_waste_lines_for_the_same_item_are_summed(db, env, of):
    """Two spills of the same film in one shift are two events and one total."""
    _packing(
        db, env, of, date=datetime.date(2026, 9, 1),
        packets_counted=900,
        waste_lines=(
            WasteLine(category="packaging", product_id=env["film"], quantity=1.5, note="reel change"),
            WasteLine(category="packaging", product_id=env["film"], quantity=2.5, note="seal fault"),
        ),
    )

    waste = _consolidate(db, of)["waste"]
    assert waste["by_category"] == {"packaging": 4}
    assert waste["by_product"] == [{"product_id": env["film"], "quantity": 4}]


def test_only_validated_reports_contribute_waste(db, env, of):
    """A draft is a team's working notes, and its déchets are not the OF's yet."""
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1), validate=False,
        semolina_quantity=1000,
        waste_lines=(WasteLine(category="press", product_id=env["product"], quantity=7),),
    )

    waste = _consolidate(db, of)["waste"]
    assert waste["by_category"] == {}
    assert waste["by_product"] == []


def test_waste_recorded_before_it_named_an_item_is_reported_apart(db, env, of):
    """Backfilled lines carry no product, so they carry no unit either.

    Folding them into a per-item total would attach them to an item nobody
    chose; dropping them would quietly shrink the OF's waste. They are counted
    on their own so they can be gone back and fixed.
    """
    report = _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=1000,
        waste_lines=(WasteLine(category="press", product_id=env["product"], quantity=3),),
    )
    # Exactly what migration 0022's backfill leaves behind for déchet presse.
    db.execute(
        "UPDATE production.report_waste_lines SET product_id = NULL WHERE report_id = %s",
        (report.id,),
    )

    waste = _consolidate(db, of)["waste"]
    assert waste["by_category"] == {"press": 3}
    assert waste["by_product"] == []
    assert waste["unattributed_quantity"] == 3


def test_daily_waste_in_kg_is_restated_against_a_tonne_product(db, env, of):
    """The daily report's déchet is always weighed in kg (WasteLinesField's
    fixedUnit), even for an item stocked by the tonne. A 200 kg spill on a
    semoule declared in tonnes must read as 0.2 t, not 200 t -- and the écart
    the plant tracks (net_semoule_waste) must still net against the form's
    own kilos, not the converted figure.
    """
    tonne_uom, tonne_product = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base) "
        "VALUES (%s, %s, 'ton', 'Tonne', 'weight', 1000)",
        (tonne_uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'CONSO-TONNE', 'Semoule en tonnes', %s)",
        (tonne_product, TENANT, tonne_uom),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=tonne_product, location_id=env["location"], quantity=100,
        correlation_id=str(ULID()), reference="seed", actor_id=env["actor"],
    )

    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=12, semolina_product_id=tonne_product,
        regrind_quantity=10,
        waste_lines=(WasteLine(category="raw_material", product_id=tonne_product, quantity=200),),
    )

    result = _consolidate(db, of)
    waste = result["waste"]
    # 200 kg restated against the tonne product's own unit.
    assert waste["by_category"]["raw_material"] == pytest.approx(0.2)
    by_product = {entry["product_id"]: entry["quantity"] for entry in waste["by_product"]}
    assert by_product[tonne_product] == pytest.approx(0.2)

    # Netted against the form's own kilos, not the converted 0.2 t figure --
    # summing the converted by_category here would have read this as -9.8.
    assert waste["net_semoule_waste"] == 200 - 10


def test_time_is_summed_across_both_report_types(db, env, of):
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, production_minutes=400,
        downtime_lines=(DowntimeLine(motif="die_jam", minutes=20),),
    )
    _packing(
        db, env, of, date=datetime.date(2026, 9, 1),
        packets_counted=900, production_minutes=380, downtime_minutes=15, downtime_reason="film_jam",
    )

    time = _consolidate(db, of)["time"]
    assert time["production_minutes"] == 780
    assert time["downtime_minutes"] == 35


def test_completion_is_measured_against_the_plan(db, env, of):
    _packing(db, env, of, date=datetime.date(2026, 9, 1), packets_counted=750)
    result = _consolidate(db, of)
    assert result["planned_quantity"] == 1000
    assert result["completion_ratio"] == 0.75


def test_an_of_with_no_validated_reports_consolidates_to_zero(db, env, of):
    result = _consolidate(db, of)
    assert result["produced_quantity"] == 0
    assert result["completion_ratio"] == 0
    assert result["quality"]["conformity_rate"] is None


def test_consolidation_survives_an_unset_planned_quantity(db, env):
    """A mold-created OF (0024) is lightweight: quantity is assigned later via
    the edit form, so `planned_quantity` starts out NULL. The consolidation
    endpoint used to 500 on this — `float(None)` — leaving the OF details page
    showing nothing at all, even once its reports were validated."""
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    unquantified = created.value

    result = _consolidate(db, unquantified)
    assert result["planned_quantity"] is None
    assert result["completion_ratio"] is None

    _daily(db, env, unquantified, date=datetime.date(2026, 9, 1), semolina_quantity=500)
    result = _consolidate(db, unquantified)
    assert result["raw_material"]["semolina_quantity"] == 500
    assert result["planned_quantity"] is None
    assert result["completion_ratio"] is None


def test_consolidation_works_while_the_of_is_still_running(db, env, of):
    """A cockpit needs the figure before closure, not only after it."""
    WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id)
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000)

    result = _consolidate(db, of)
    assert result["status"] == "ongoing"
    assert result["raw_material"]["semolina_quantity"] == 1000


# --- quality comes from qc, through its service -----------------------------


def test_quality_conformity_comes_from_the_qc_module(db, env, of):
    packing = _packing(db, env, of, date=datetime.date(2026, 9, 1))
    quality = QualityReportService(db)
    created = quality.create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing.id,
        detail=QualityReportDetail(conforming_cartons=90, non_conforming_cartons=10, defect_details="bad seal"),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    quality.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    quality.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )

    result = _consolidate(db, of)["quality"]
    assert result["conforming_cartons"] == 90
    assert result["non_conforming_cartons"] == 10
    assert result["conformity_rate"] == 0.9
    assert result["validated_report_count"] == 1


def test_an_unvalidated_quality_report_does_not_count(db, env, of):
    packing = _packing(db, env, of, date=datetime.date(2026, 9, 1))
    quality = QualityReportService(db)
    created = quality.create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing.id,
        detail=QualityReportDetail(conforming_cartons=90),
    )
    quality.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=created.value["report"].id)

    result = _consolidate(db, of)["quality"]
    assert result["validated_report_count"] == 0
    assert result["conformity_rate"] is None


def test_a_validated_defect_with_no_case_raised_is_flagged(db, env, of):
    """A validated report can log `non_conforming_cartons` and still have nobody
    raise the case for it -- that carton then never gets pulled off the market
    (decision 21 in NonConformityService.get_rejected_quantity_for_of), which a
    conformity percentage alone cannot show. `pending_nc_reports` is what lets a
    screen warn about it, and it must clear once the case is actually raised.
    """
    packing = _packing(db, env, of, date=datetime.date(2026, 9, 1))
    quality = QualityReportService(db)
    created = quality.create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing.id,
        detail=QualityReportDetail(conforming_cartons=90, non_conforming_cartons=10, defect_details="bad seal"),
    )
    report = created.value["report"]
    quality.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    quality.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )

    result = _consolidate(db, of)["quality"]
    assert result["pending_nc_reports"] == [
        {"report_id": report.id, "report_date": "2026-09-01", "non_conforming_cartons": 10.0}
    ]

    from modules.qc.api.non_conformity_service import NonConformityService

    quarantine = str(ULID())
    db.execute(
        """
        INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked, blocked_reason)
        VALUES (%s, %s, 'CONSO-QUAR', 'Quarantine', TRUE, 'non-conformity')
        """,
        (quarantine, TENANT),
    )
    raised = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"],
        quantity=1, source_location_id=env["location"], quarantine_location_id=quarantine,
        defect_type="bad seal", correlation_id=str(ULID()), quality_report_id=report.id,
    )
    assert isinstance(raised, Ok), getattr(raised, "message", "")

    result = _consolidate(db, of)["quality"]
    assert result["pending_nc_reports"] == []


# --- yield, recomputed off the reports --------------------------------------


def test_yield_is_computed_from_validated_reports(db, env, of):
    """finished product / semoule poured in, with every term from the daily reports.

    finished_product_quantity comes off the daily report's own Produit fini —
    the tonnage weighed at the press — not the conditionnement report, which can
    validate days later. A conditionnement report is added here with a different
    figure specifically to prove it is ignored.
    """
    _daily(
        db, env, of, date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, regrind_quantity=50, finished_product_quantity=900,
    )
    _packing(db, env, of, date=datetime.date(2026, 9, 1), finished_product_quantity=750)

    computed = WorkOrderYieldService(db).get_work_order_yield(tenant_id=TENANT, work_order_id=of.id)
    assert computed is not None
    assert computed["semoule_quantity_total"] == 1000
    assert computed["produced_quantity"] == 900
    assert computed["rebroyat_quantity"] == 50
    assert computed["yield_ratio"] == pytest.approx(0.9)


def test_yield_is_available_before_closure(db, env, of):
    """Available off the daily report alone -- no conditionnement report needed,
    since packaging can lag the press by days and a supervisor wants the figure
    while the shift can still act on it."""
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000, finished_product_quantity=900)

    assert WorkOrderYieldService(db).get_work_order_yield(tenant_id=TENANT, work_order_id=of.id) is not None


def test_yield_is_undefined_without_validated_semoule(db, env, of):
    """No denominator means no answer — not a zero."""
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=0, finished_product_quantity=900)
    assert WorkOrderYieldService(db).get_work_order_yield(tenant_id=TENANT, work_order_id=of.id) is None


def test_the_of_carries_no_stored_output_column_any_more(db, env, of):
    columns = {
        row[0]
        for row in db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'production' AND table_name = 'work_orders'"
        ).fetchall()
    }
    assert "actual_output_quantity" not in columns, "consolidation forbids stored totals"


def test_a_regrind_batch_still_records_what_it_yielded(db, env, of):
    """The exception: a rebroyat batch has no report behind it, so the figure lives
    on the batch rather than as a cached total on the OF."""
    columns = {
        row[0]
        for row in db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'production' AND table_name = 'regrind_batches'"
        ).fetchall()
    }
    assert "actual_output_quantity" in columns

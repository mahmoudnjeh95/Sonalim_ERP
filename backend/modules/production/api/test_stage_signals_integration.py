"""Integration tests for ProductionReportService.list_stage_signals.

The property under test: one call returns the same three yes/no answers
(poured semoule, weighed finished product, counted packets) that the OF page's
Flux de production card used to get by fetching every report's full detail —
one round trip per report. A rejected report never carries a signal, whether
or not it has figures typed on it; everything else does, draft or validated.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import ConditionnementReportDetail, DailyReportDetail, SemolinaLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-stage-signals"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, film, location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(7))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, net_weight_grams) VALUES (%s, %s, %s, %s, %s, %s)",
        (product, TENANT, "STAGE-PASTA", "STAGE-PASTA", uom, 1_000_000),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'STAGE-FILM', 'STAGE-FILM', %s)",
        (film, TENANT, uom),
    )
    for location_id, code in ((location, "FG"), (packaging_location, "PACK")):
        db.execute(
            "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
            (location_id, TENANT, code, code),
        )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'STAGE-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'STAGE-EQ', 'Test machine')",
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
        "actor": actor, "product": product, "film": film, "location": location,
        "packaging_location": packaging_location, "work_center": work_center, "equipment": equipment,
    }


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
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
        equipment_id=env["equipment"], detail=DailyReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    if validate is not None:
        service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
        if validate:
            result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
            assert isinstance(result, Ok), getattr(result, "message", "")
        else:
            rejected = service.reject_report(
                tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="test rejection"
            )
            assert isinstance(rejected, Ok), getattr(rejected, "message", "")
    return report


def _packing(db, env, of, *, date, shift="afternoon", validate=True, **detail):
    detail.setdefault("film_product_id", env["film"])
    detail.setdefault("packaging_location_id", env["packaging_location"])
    detail.setdefault("finished_goods_location_id", env["location"])
    created = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=date, shift=shift,
        equipment_id=env["equipment"], detail=ConditionnementReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    service = ProductionReportService(db)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    if validate:
        result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
        assert isinstance(result, Ok), getattr(result, "message", "")
    return report


def test_signals_read_semoule_finished_product_and_packets(db, env, of):
    daily = _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=1000, finished_product_quantity=900)
    packing = _packing(db, env, of, date=datetime.date(2026, 9, 1), packets_counted=850)

    signals = ProductionReportService(db).list_stage_signals(tenant_id=TENANT, of_id=of.id)

    assert signals[daily.id] == {
        "poured_semoule": True,
        "weighed_finished_product": True,
        "counted_packets": False,
    }
    assert signals[packing.id] == {
        "poured_semoule": False,
        "weighed_finished_product": False,
        "counted_packets": True,
    }


def test_a_report_with_nothing_typed_carries_no_signal(db, env, of):
    empty = _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=0, finished_product_quantity=0)

    signals = ProductionReportService(db).list_stage_signals(tenant_id=TENANT, of_id=of.id)

    assert signals[empty.id] == {
        "poured_semoule": False,
        "weighed_finished_product": False,
        "counted_packets": False,
    }


def test_a_draft_still_carries_its_signal(db, env, of):
    """The flow card lights a stage up as soon as a team types a figure, not
    only once it is validated — same as deriveStageStates reading a report
    regardless of status, other than rejected."""
    draft = _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=500, validate=None)

    signals = ProductionReportService(db).list_stage_signals(tenant_id=TENANT, of_id=of.id)

    assert signals[draft.id]["poured_semoule"] is True


def test_a_rejected_report_carries_no_signal(db, env, of):
    rejected = _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=500, validate=False)

    signals = ProductionReportService(db).list_stage_signals(tenant_id=TENANT, of_id=of.id)

    assert rejected.id not in signals


def test_signals_are_scoped_to_the_named_of(db, env, of):
    other = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=500, work_center_id=env["work_center"],
    ).value
    _daily(db, env, of, date=datetime.date(2026, 9, 1), semolina_quantity=500)
    other_report = _daily(db, env, other, date=datetime.date(2026, 9, 1), semolina_quantity=200)

    signals = ProductionReportService(db).list_stage_signals(tenant_id=TENANT, of_id=of.id)

    assert other_report.id not in signals

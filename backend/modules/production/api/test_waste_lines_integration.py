"""Déchets as a list of items, against a real database.

The behaviour under test: a waste line survives every path a report takes —
draft, correction after validation, deletion — carries the item that gives its
figure a unit, and never moves stock. The last one matters most: naming a
product on a waste line looks exactly like naming one on a consumption line, and
a reader could reasonably expect it to deduct. It must not, because the material
was already deducted when it was poured.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    SemolinaLine,
    WasteLine,
)
from modules.warehouse.api.service import StockService

TENANT = "integration-test-waste-lines"


@pytest.fixture
def env(db):
    actor = str(ULID())
    weight_uom, count_uom = str(ULID()), str(ULID())
    product, rebut, scotch, location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(7))

    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    # Two units on purpose: the whole point of naming the item is that a kilo of
    # rebut and a roll of scotch are not the same kind of number.
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogramme', 'weight')",
        (weight_uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'ea', 'Pièce', 'unit')",
        (count_uom, TENANT),
    )
    for product_id, sku, uom in (
        (product, "WASTE-PASTA", count_uom),
        (rebut, "WASTE-REBUT", weight_uom),
        (scotch, "WASTE-SCOTCH", count_uom),
    ):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
    for location_id, code in ((location, "WASTE-RAW"), (packaging_location, "WASTE-PACK")):
        db.execute(
            "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
            (location_id, TENANT, code, code),
        )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'WASTE-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'WASTE-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="seed", actor_id=actor,
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=scotch, location_id=packaging_location, quantity=10_000,
        correlation_id=str(ULID()), reference="seed", actor_id=actor,
    )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=product)
    return {
        "actor": actor,
        "product": product,
        "rebut": rebut,
        "scotch": scotch,
        "location": location,
        "packaging_location": packaging_location,
        "work_center": work_center,
        "equipment": equipment,
    }


@pytest.fixture
def of(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert isinstance(
        service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok
    )
    return created.value


def _draft(db, env, of, **detail):
    semolina_lines = detail.pop("semolina_lines", None)
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(
                product_id=detail.pop("semolina_product_id", env["product"]),
                quantity=detail.pop("semolina_quantity", 500),
                location_id=env["location"],
            ),
        )
    detail["semolina_lines"] = semolina_lines
    detail.setdefault("raw_material_location_id", env["location"])
    created = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 1), shift="morning",
        equipment_id=env["equipment"],
        detail=DailyReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value["report"]


def _validate(db, env, report_id):
    service = ProductionReportService(db)
    assert isinstance(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result


def _read(db, report_id):
    return ProductionReportService(db).get_report(tenant_id=TENANT, report_id=report_id)


def _stock_move_count(db) -> int:
    return db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0]


# --- round trip -------------------------------------------------------------


def test_a_waste_line_is_stored_and_read_back_whole(db, env, of):
    report = _draft(
        db, env, of,
        waste_lines=(
            WasteLine(category="press", product_id=env["rebut"], quantity=4.5, note="die change"),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert len(detail.waste_lines) == 1
    line = detail.waste_lines[0]
    assert (line.category, line.product_id, line.quantity, line.note) == ("press", env["rebut"], 4.5, "die change")


def test_the_order_the_shift_entered_them_in_is_kept(db, env, of):
    report = _draft(
        db, env, of,
        waste_lines=(
            WasteLine(category="press", product_id=env["rebut"], quantity=1),
            WasteLine(category="raw_material", product_id=env["product"], quantity=2),
            WasteLine(category="press", product_id=env["rebut"], quantity=3),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert [line.quantity for line in detail.waste_lines] == [1, 2, 3]


def test_editing_a_draft_replaces_the_whole_list(db, env, of):
    """A form that removed a row must not leave the row behind in the database."""
    report = _draft(
        db, env, of,
        waste_lines=(
            WasteLine(category="press", product_id=env["rebut"], quantity=1),
            WasteLine(category="raw_material", product_id=env["product"], quantity=2),
        ),
    )
    updated = ProductionReportService(db).update_daily_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=500, location_id=env["location"]),),
            raw_material_location_id=env["location"],
            waste_lines=(WasteLine(category="press", product_id=env["rebut"], quantity=9),),
        ),
    )
    assert isinstance(updated, Ok), getattr(updated, "message", "")
    detail = _read(db, report.id)["detail"]
    assert [(line.category, line.quantity) for line in detail.waste_lines] == [("press", 9)]


def test_blank_rows_are_not_stored(db, env, of):
    """Three empty rows in a form recorded nothing. Storing them as zeroes with
    no item would put lines with no unit into the OF's consolidation."""
    report = _draft(
        db, env, of,
        waste_lines=(
            WasteLine(category="press", product_id=env["rebut"], quantity=2),
            WasteLine(category="press", quantity=0),
            WasteLine(category="raw_material", quantity=0),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert len(detail.waste_lines) == 1


def test_a_zero_line_carrying_a_note_is_kept(db, env, of):
    """"Nothing lost at the press today" is a fact a shift chose to record."""
    report = _draft(
        db, env, of,
        waste_lines=(WasteLine(category="press", product_id=env["rebut"], quantity=0, note="none"),),
    )
    detail = _read(db, report.id)["detail"]
    assert len(detail.waste_lines) == 1
    assert detail.waste_lines[0].note == "none"


# --- what the list is allowed to say ---------------------------------------


def test_the_renamed_and_added_daily_categories_are_accepted(db, env, of):
    """découpe became "cross", and pétrin / finished_product_conditioning
    joined it as daily-report stages."""
    report = _draft(
        db, env, of,
        waste_lines=(
            WasteLine(category="cross", product_id=env["rebut"], quantity=1),
            WasteLine(category="kneading", product_id=env["rebut"], quantity=2),
            WasteLine(category="finished_product_conditioning", product_id=env["product"], quantity=3),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert {line.category for line in detail.waste_lines} == {"cross", "kneading", "finished_product_conditioning"}


def test_cutting_is_no_longer_a_valid_category(db, env, of):
    """The old name is refused end-to-end, not just in the domain layer --
    the database's own check constraint was renamed alongside it."""
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 2), shift="night",
        detail=DailyReportDetail(
            raw_material_location_id=env["location"],
            waste_lines=(WasteLine(category="cutting", product_id=env["rebut"], quantity=1),),
        ),
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_a_daily_report_is_refused_a_packing_stage(db, env, of):
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 2), shift="night",
        detail=DailyReportDetail(
            raw_material_location_id=env["location"],
            waste_lines=(WasteLine(category="packaging", product_id=env["scotch"], quantity=1),),
        ),
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_a_draft_may_carry_a_quantity_with_no_item(db, env, of):
    report = _draft(db, env, of, waste_lines=(WasteLine(category="press", quantity=3),))
    detail = _read(db, report.id)["detail"]
    assert detail.waste_lines[0].product_id is None


def test_submitting_that_draft_is_refused(db, env, of):
    """The validation desk cannot judge "3" without knowing what three of."""
    report = _draft(db, env, of, waste_lines=(WasteLine(category="press", quantity=3),))
    result = ProductionReportService(db).submit_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_WASTE_PRODUCT"


# --- stock ------------------------------------------------------------------


def test_validating_waste_moves_no_stock(db, env, of):
    """The pivot for this whole change. Semoule left stock when it was poured;
    the part of it that ended up as déchet is not a second withdrawal."""
    report = _draft(
        db, env, of, semolina_quantity=500,
        waste_lines=(
            WasteLine(category="raw_material", product_id=env["product"], quantity=5),
            WasteLine(category="press", product_id=env["rebut"], quantity=3),
        ),
    )
    before = _stock_move_count(db)
    _validate(db, env, report.id)

    # Exactly one movement: the semoule poured. Neither waste line added a second.
    assert _stock_move_count(db) - before == 1
    moved = db.execute(
        """
        SELECT product_id FROM warehouse.stock_moves
        WHERE reference = %s
        """,
        (f"production_report:{report.id}",),
    ).fetchall()
    assert [row[0] for row in moved] == [env["product"]]


def test_packaging_waste_moves_no_stock_either(db, env, of):
    """Scotch is deducted at the quantity consumed, which already includes what
    was spoiled. Deducting the déchet too would take the same roll out twice."""
    service = ConditionnementReportService(db)
    created = service.create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 3), shift="morning",
        equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(
            finished_product_quantity=0.2,
            packets_counted=400,
            scotch_quantity=6,
            scotch_product_id=env["scotch"],
            packaging_location_id=env["packaging_location"],
            finished_goods_location_id=env["location"],
            waste_lines=(WasteLine(category="packaging", product_id=env["scotch"], quantity=2),),
        ),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    before = _stock_move_count(db)
    _validate(db, env, report.id)

    # Finished product in, scotch out. Nothing for the déchet.
    assert _stock_move_count(db) - before == 2
    scotch_moves = db.execute(
        """
        SELECT SUM(quantity) FROM warehouse.stock_moves
        WHERE reference = %s AND product_id = %s
        """,
        (f"production_report:{report.id}", env["scotch"]),
    ).fetchone()[0]
    assert float(scotch_moves) == 6, "the consumed quantity, not consumed plus waste"


# --- corrections and deletion ----------------------------------------------


def test_correcting_a_validated_report_rewrites_its_waste_list(db, env, of):
    report = _draft(
        db, env, of,
        waste_lines=(WasteLine(category="press", product_id=env["rebut"], quantity=3),),
    )
    _validate(db, env, report.id)

    corrected = ProductionReportService(db).correct_validated_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=500, location_id=env["location"]),),
            raw_material_location_id=env["location"],
            waste_lines=(
                WasteLine(category="press", product_id=env["rebut"], quantity=8),
                WasteLine(category="raw_material", product_id=env["product"], quantity=1),
            ),
        ),
        reason="the press waste was weighed again",
    )
    assert isinstance(corrected, Ok), getattr(corrected, "message", "")
    detail = _read(db, report.id)["detail"]
    assert sorted(line.quantity for line in detail.waste_lines) == [1, 8]


def test_deleting_a_report_takes_its_waste_list_with_it(db, env, of):
    report = _draft(
        db, env, of,
        waste_lines=(WasteLine(category="press", product_id=env["rebut"], quantity=3),),
    )
    result = ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="entered against the wrong OF"
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    remaining = db.execute(
        "SELECT count(*) FROM production.report_waste_lines WHERE report_id = %s", (report.id,)
    ).fetchone()[0]
    assert remaining == 0


def test_the_deletion_audit_records_the_waste_that_was_there(db, env, of):
    """The rows are gone afterwards, so the audit entry is the only account of
    what the report said — including its déchets."""
    report = _draft(
        db, env, of,
        waste_lines=(WasteLine(category="press", product_id=env["rebut"], quantity=3),),
    )
    ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="duplicate"
    )
    payload = db.execute(
        """
        SELECT payload FROM core.audit_log
        WHERE entity_id = %s AND action = 'production_report.deleted'
        """,
        (report.id,),
    ).fetchone()[0]
    assert payload["detail"]["waste_lines"] == [
        {"category": "press", "product_id": env["rebut"], "quantity": 3.0, "note": None, "line_order": 0}
    ]


# --- rebroyat ---------------------------------------------------------------


def test_rebroyat_scrap_always_uses_the_tenant_regrind_product(db, env, of):
    """A report naming a different item here (a raw material, say) used to send
    that product's own identity onto the scrap record -- typically whichever
    purchased semolina was in use that shift, denominated in that product's own
    unit (tonnes). Since every regrind batch resolves to the same one output
    product regardless (see RegrindService.create_regrind_batch), that free
    choice added nothing but a unit-mismatch risk. The scrap now always opens
    against the tenant's configured regrind output product, no matter what
    regrind_product_id names -- `env["rebut"]` here stands in for "a report
    author picked something else."""
    report = _draft(db, env, of, regrind_quantity=12, regrind_product_id=env["rebut"])
    _validate(db, env, report.id)

    scrap = db.execute(
        """
        SELECT product_id, quantity FROM production.scrap_records
        WHERE tenant_id = %s AND work_order_id = %s AND scrap_type = 'daily_report'
        """,
        (TENANT, of.id),
    ).fetchone()
    assert scrap[0] == env["product"]
    assert float(scrap[1]) == 12


def test_rebroyat_with_no_item_named_still_uses_the_tenant_regrind_product(db, env, of):
    """Same invariant with regrind_product_id left unset entirely -- it no
    longer falls back to the OF's own finished product (a wrapped 500g packet
    is not what goes back through the mill); it uses the same tenant-wide
    regrind product as every other path."""
    report = _draft(db, env, of, regrind_quantity=12)
    _validate(db, env, report.id)

    scrap = db.execute(
        """
        SELECT product_id FROM production.scrap_records
        WHERE tenant_id = %s AND work_order_id = %s AND scrap_type = 'daily_report'
        """,
        (TENANT, of.id),
    ).fetchone()
    assert scrap[0] == env["product"]

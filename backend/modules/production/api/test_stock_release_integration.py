"""Packed goods wait in the line store, then a supervisor releases them to the final store."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.stock_release_service import StockReleaseService
from modules.qc.api.quality_service import QualityReportService
from modules.warehouse.api.service import StockService
from modules.production.api.test_shift_machine_integration import (  # noqa: F401  (env is a fixture)
    DAY,
    TENANT,
    _ok,
    _submitted_shift,
    _validate,
    env,
)


@pytest.fixture
def stores(db, env):
    """A line store next to the production, and the pasta's own store as the final store."""
    line = str(ULID())
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SR-LINE', 'Stock ligne')", (line, TENANT))
    fg = db.execute("SELECT default_location_id FROM core.products WHERE id = %s", (env["pasta"],)).fetchone()[0]
    _ok(DashboardSettingsService(db).replace_store_roles(
        tenant_id=TENANT, actor_id=env["actor"], entries=[{"location_id": line, "role": "line"}, {"location_id": fg, "role": "final"}]
    ))
    return {"line": line, "final": fg}


def _on_hand(db, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def _release(db, env, items, day=DAY):
    return StockReleaseService(db).release(tenant_id=TENANT, actor_id=env["actor"], day=day, items=items)


def _list(db, day=DAY, today=None):
    return StockReleaseService(db).get_release_list(tenant_id=TENANT, day=day, today=today)


# `_submitted_shift` packs the pasta as packets_counted = 120 with no carton count, so 120 pieces
# are packed. Validation freezes the pasta's packets_per_carton (12) on the packing row, and QC
# counts in cartons: every carton QC clears is 12 pieces, so 10 cartons clear all 120.
ALL_PACKED_CARTONS = 10


def _qc_report(db, env, shift_id, *, conforming, non_conforming=0, defect_details=None, validate=True):
    """A QC report on the shift's one packing row, submitted and (by default) validated."""
    qc = QualityReportService(db)
    report = _ok(qc.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))["report"]
    [line] = qc._load_lines(tenant_id=TENANT, report_id=report.id)
    _ok(qc.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{
            "shift_packing_row_id": line.shift_packing_row_id,
            "conforming_cartons": conforming, "non_conforming_cartons": non_conforming, "defect_details": defect_details,
        }],
    ))
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    if validate:
        _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))
    return report.id


def _validated_and_cleared(db, env, **shift_kwargs) -> str:
    """A validated shift whose QC report cleared everything it packed."""
    shift_id = _submitted_shift(db, env, **shift_kwargs)
    _validate(db, env, shift_id)
    _qc_report(db, env, shift_id, conforming=ALL_PACKED_CARTONS)
    return shift_id


# ---- where packed goods land -------------------------------------------------


def test_packed_goods_land_in_the_line_store_when_one_is_configured(db, env, stores):
    _validate(db, env, _submitted_shift(db, env))
    assert _on_hand(db, env["pasta"], stores["line"]) == 120
    assert _on_hand(db, env["pasta"], stores["final"]) == 0


def test_two_line_stores_are_not_guessed_between(db, env, stores):
    other = str(ULID())
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SR-LINE2', 'Stock ligne 2')", (other, TENANT))
    _ok(DashboardSettingsService(db).replace_store_roles(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[{"location_id": stores["line"], "role": "line"}, {"location_id": other, "role": "line"}, {"location_id": stores["final"], "role": "final"}],
    ))
    _validate(db, env, _submitted_shift(db, env))
    assert _on_hand(db, env["pasta"], stores["final"]) == 120  # falls back to the product's own store


# ---- the release list --------------------------------------------------------


def test_the_list_shows_what_was_packed_that_day_and_where_it_will_go(db, env, stores):
    _validated_and_cleared(db, env)
    listed = _list(db)
    assert listed["line_store"] == {"id": stores["line"], "name": "Stock ligne"}
    assert listed["day"] == DAY.isoformat()
    [item] = listed["items"]
    assert item["product_id"] == env["pasta"] and item["product_name"] == "SM-PASTA"
    assert (item["packed"], item["released"], item["remaining"], item["releasable"]) == (120, 0, 120, 120)
    assert item["packets_per_carton"] == 12  # the screen shows 10 cartons and takes cartons back
    assert item["packaging_format"] == "packet"
    assert item["destination"]["id"] == stores["final"]


def test_a_product_packed_on_several_lines_is_one_row(db, env, stores):
    _validate(db, env, _submitted_shift(db, env, shift="morning"))
    _validate(db, env, _submitted_shift(db, env, shift="afternoon"))
    [item] = _list(db)["items"]
    assert item["packed"] == 240


def test_only_the_asked_day_is_listed(db, env, stores):
    _validate(db, env, _submitted_shift(db, env))
    assert _list(db, day=DAY + datetime.timedelta(days=1))["items"] == []


def test_a_shift_nobody_validated_is_not_listed(db, env, stores):
    _submitted_shift(db, env)
    assert _list(db)["items"] == []


def test_cartons_decide_the_quantity_when_the_product_has_a_carton_tier(db, env, stores):
    shift_id = _submitted_shift(db, env)
    # Any item will do as the carton, with some in the packaging store so nothing falls short.
    StockService(db).receive_stock(tenant_id=TENANT, product_id=env["semolina"], location_id=stores["final"], quantity=100, correlation_id=str(ULID()), reference="seed", actor_id=env["actor"])
    db.execute(
        "UPDATE production.shift_packing_rows SET carton_quantity = 10, waste_carton_quantity = 1, packets_counted = 999, "
        "carton_product_id = %s, packaging_location_id = %s WHERE shift_report_id = %s",
        (env["semolina"], stores["final"], shift_id),
    )
    _validate(db, env, shift_id)
    [item] = _list(db)["items"]
    assert item["packed"] == 108  # (10 - 1) cartons of 12, what validation posted to stock


def test_the_list_is_capped_at_what_the_line_store_holds(db, env, stores):
    _validated_and_cleared(db, env)
    db.execute(
        "UPDATE warehouse.stock_items SET quantity_on_hand = 30 WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, env["pasta"], stores["line"]),
    )
    [item] = _list(db)["items"]
    assert (item["remaining"], item["releasable"]) == (120, 30)


def test_the_list_opens_on_yesterday_then_on_today_once_yesterday_is_released(db, env, stores):
    today = DAY + datetime.timedelta(days=1)
    _validated_and_cleared(db, env)  # packed yesterday
    _validate(db, env, _submitted_shift(db, env, day=today))  # packed today
    service = StockReleaseService(db)
    opened = service.get_release_list(tenant_id=TENANT, day=None, today=today)
    assert opened["day"] == DAY.isoformat() and opened["today"] == today.isoformat()
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 120}]))
    assert service.get_release_list(tenant_id=TENANT, day=None, today=today)["day"] == today.isoformat()
    # the picker still reaches yesterday, now fully released
    [item] = _list(db, today=today)["items"]
    assert (item["packed"], item["released"], item["releasable"]) == (120, 120, 0)


# ---- releasing ---------------------------------------------------------------


def test_releasing_moves_the_goods_to_the_products_own_store(db, env, stores):
    _validated_and_cleared(db, env)
    released = _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 120}]))
    assert released["released"] == [{"product_id": env["pasta"], "quantity": 120, "to_location_id": stores["final"]}]
    assert _on_hand(db, env["pasta"], stores["line"]) == 0
    assert _on_hand(db, env["pasta"], stores["final"]) == 120
    moved = db.execute(
        "SELECT move_type FROM warehouse.stock_moves WHERE tenant_id = %s AND reference = %s ORDER BY move_type", (TENANT, released["reference"])
    ).fetchall()
    assert [m[0] for m in moved] == ["transfer_in", "transfer_out"]


def test_part_of_a_product_can_be_released_and_the_rest_waits(db, env, stores):
    _validated_and_cleared(db, env)
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 50}]))
    assert _on_hand(db, env["pasta"], stores["line"]) == 70
    assert _on_hand(db, env["pasta"], stores["final"]) == 50


def test_more_than_is_in_the_line_store_is_refused_and_nothing_moves(db, env, stores):
    _validated_and_cleared(db, env)
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 121}])
    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_STOCK"
    assert _on_hand(db, env["pasta"], stores["line"]) == 120


def test_one_bad_line_stops_the_whole_release(db, env, stores):
    _validated_and_cleared(db, env)
    other = str(ULID())
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) SELECT %s, tenant_id, 'SR-OTHER', 'Other', uom_id FROM core.products WHERE id = %s", (other, env["pasta"]))
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 60}, {"product_id": other, "quantity": 5}])
    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_STOCK"
    assert _on_hand(db, env["pasta"], stores["line"]) == 120  # the good line did not move either
    assert _on_hand(db, env["pasta"], stores["final"]) == 0


def test_a_release_is_audited(db, env, stores):
    _validated_and_cleared(db, env)
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 120}]))
    audited = db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'stock.released'", (TENANT,)).fetchone()[0]
    assert audited == 1


def test_an_empty_or_nonpositive_release_is_refused(db, env, stores):
    assert _release(db, env, []).code == "NOTHING_TO_RELEASE"
    _validate(db, env, _submitted_shift(db, env))
    assert _release(db, env, [{"product_id": env["pasta"], "quantity": 0}]).code == "INVALID_QUANTITY"


def test_a_shift_saved_before_the_line_store_was_set_still_lands_in_it(db, env):
    shift_id = _submitted_shift(db, env)  # its packing row was filled in with the product's own store
    line = str(ULID())
    fg = db.execute("SELECT default_location_id FROM core.products WHERE id = %s", (env["pasta"],)).fetchone()[0]
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SR-LINE3', 'Stock ligne')", (line, TENANT))
    _ok(DashboardSettingsService(db).replace_store_roles(
        tenant_id=TENANT, actor_id=env["actor"], entries=[{"location_id": line, "role": "line"}, {"location_id": fg, "role": "final"}]
    ))
    _validate(db, env, shift_id)
    assert _on_hand(db, env["pasta"], line) == 120
    assert _on_hand(db, env["pasta"], fg) == 0


def test_yesterday_stays_open_while_anything_of_it_is_unreleased_even_if_the_line_store_lacks_it(db, env, stores):
    today = DAY + datetime.timedelta(days=1)
    _validated_and_cleared(db, env)
    db.execute("DELETE FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s", (TENANT, stores["line"]))
    opened = StockReleaseService(db).get_release_list(tenant_id=TENANT, day=None, today=today)
    assert opened["day"] == DAY.isoformat()
    [item] = opened["items"]
    assert (item["remaining"], item["releasable"]) == (120, 0)  # shown, but greyed out on screen


# ---- what a release remembers ------------------------------------------------


def test_a_release_is_remembered_against_the_day_it_came_from(db, env, stores):
    _validated_and_cleared(db, env)
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 50}]))
    [item] = _list(db)["items"]
    assert (item["packed"], item["released"], item["remaining"], item["releasable"]) == (120, 50, 70, 70)
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 70}]))
    [item] = _list(db)["items"]
    assert (item["released"], item["remaining"]) == (120, 0)


def test_more_than_was_packed_that_day_is_refused_even_if_the_line_store_holds_it(db, env, stores):
    _validated_and_cleared(db, env)  # day 1: 120
    _validate(db, env, _submitted_shift(db, env, day=DAY + datetime.timedelta(days=1)))  # day 2: 120, same store
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 121}])
    assert isinstance(refused, Err) and refused.code == "EXCEEDS_PACKED"
    assert _on_hand(db, env["pasta"], stores["line"]) == 240


def test_a_day_with_nothing_packed_releases_nothing(db, env, stores):
    _validate(db, env, _submitted_shift(db, env))
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 1}], day=DAY + datetime.timedelta(days=3))
    assert isinstance(refused, Err) and refused.code == "EXCEEDS_PACKED"


def test_a_refused_release_leaves_no_memory(db, env, stores):
    _validated_and_cleared(db, env)
    db.execute("UPDATE core.products SET default_location_id = NULL WHERE id = %s", (env["pasta"],))
    assert _release(db, env, [{"product_id": env["pasta"], "quantity": 120}]).code == "NO_DEFAULT_LOCATION"
    assert db.execute("SELECT count(*) FROM production.stock_release_lines WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0


# ---- only what QC validated as conforming may go ---------------------------------


def test_qc_validated_conforming_counts_cartons_of_the_packing_rows_frozen_size(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _qc_report(db, env, shift_id, conforming=8, non_conforming=2, defect_details="soudure")
    assert QualityReportService(db).get_validated_conforming(tenant_id=TENANT, day=DAY) == {env["pasta"]: 96.0}  # 8 x 12
    assert QualityReportService(db).get_validated_conforming(tenant_id=TENANT, day=DAY + datetime.timedelta(days=1)) == {}


def test_a_product_with_no_qc_report_yet_is_all_pending(db, env, stores):
    _validate(db, env, _submitted_shift(db, env))
    [item] = _list(db)["items"]
    assert (item["packed"], item["remaining"], item["releasable"], item["pending_qc"]) == (120, 120, 0, 120)


def test_a_qc_report_not_yet_validated_releases_nothing(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _qc_report(db, env, shift_id, conforming=ALL_PACKED_CARTONS, validate=False)  # submitted only
    [item] = _list(db)["items"]
    assert (item["releasable"], item["pending_qc"]) == (0, 120)
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 1}])
    assert isinstance(refused, Err) and refused.code == "EXCEEDS_QC_VALIDATED"


def test_qc_validated_conforming_becomes_releasable_and_the_rest_stays_pending(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _qc_report(db, env, shift_id, conforming=8, non_conforming=2, defect_details="soudure")
    [item] = _list(db)["items"]
    # 8 conforming cartons of 12 = 96 pieces; the 2 non-conforming cartons (24 pieces) never become releasable.
    assert (item["packed"], item["remaining"], item["releasable"], item["pending_qc"]) == (120, 120, 96, 24)


def test_release_is_refused_above_the_qc_validated_cap_even_within_on_hand(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _qc_report(db, env, shift_id, conforming=5)  # 5 cartons of 12 = 60 pieces, half of the 120 on hand
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 61}])
    assert isinstance(refused, Err) and refused.code == "EXCEEDS_QC_VALIDATED"
    assert _on_hand(db, env["pasta"], stores["line"]) == 120  # nothing moved
    assert db.execute("SELECT count(*) FROM production.stock_release_lines WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 60}]))  # exactly what QC cleared goes
    assert _on_hand(db, env["pasta"], stores["line"]) == 60


def test_what_was_already_released_counts_against_the_qc_cap(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _qc_report(db, env, shift_id, conforming=5)  # 60 pieces cleared
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 50}]))
    [item] = _list(db)["items"]
    # 120 packed, 50 released: 70 remain and 70 are in the line store, but only 60 - 50 = 10 are cleared and unreleased.
    assert (item["remaining"], item["releasable"], item["pending_qc"]) == (70, 10, 60)
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 11}])
    assert isinstance(refused, Err) and refused.code == "EXCEEDS_QC_VALIDATED"
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 10}]))


# ---- a QC verdict on a packing row that has since changed clears nothing ------------


def _two_cleared_shifts(db, env) -> tuple[str, str]:
    """Morning and afternoon shifts of DAY, each packing 120 pasta that QC cleared in full."""
    morning = _validated_and_cleared(db, env, shift="morning")
    afternoon = _validated_and_cleared(db, env, shift="afternoon")
    assert QualityReportService(db).get_validated_conforming(tenant_id=TENANT, day=DAY) == {env["pasta"]: 240.0}
    return morning, afternoon


def test_a_packing_row_recorded_again_under_a_new_id_no_longer_counts_as_cleared(db, env, stores):
    morning, _afternoon = _two_cleared_shifts(db, env)
    # A correction re-saves the morning's packing row: same goods, new row, so QC's line points at nothing.
    db.execute("CREATE TEMP TABLE fix5_rows ON COMMIT DROP AS SELECT * FROM production.shift_packing_rows WHERE shift_report_id = %s", (morning,))
    db.execute("DELETE FROM production.shift_packing_rows WHERE shift_report_id = %s", (morning,))
    db.execute("UPDATE fix5_rows SET id = %s", (str(ULID()),))
    db.execute("INSERT INTO production.shift_packing_rows SELECT * FROM fix5_rows")

    assert QualityReportService(db).get_validated_conforming(tenant_id=TENANT, day=DAY) == {env["pasta"]: 120.0}
    [item] = _list(db)["items"]
    assert (item["packed"], item["releasable"], item["pending_qc"]) == (240, 120, 120)
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 121}])
    assert isinstance(refused, Err) and refused.code == "EXCEEDS_QC_VALIDATED"
    _ok(_release(db, env, [{"product_id": env["pasta"], "quantity": 120}]))


def test_a_packing_row_whose_product_was_corrected_no_longer_counts_as_cleared(db, env, stores):
    morning, _afternoon = _two_cleared_shifts(db, env)
    db.execute("UPDATE production.shift_packing_rows SET product_id = %s WHERE shift_report_id = %s", (env["semolina"], morning))

    # Neither the old product nor the new one is cleared by a verdict about other goods.
    assert QualityReportService(db).get_validated_conforming(tenant_id=TENANT, day=DAY) == {env["pasta"]: 120.0}
    refused = _release(db, env, [{"product_id": env["pasta"], "quantity": 121}])
    assert isinstance(refused, Err)
    refused = _release(db, env, [{"product_id": env["semolina"], "quantity": 1}])
    assert isinstance(refused, Err)

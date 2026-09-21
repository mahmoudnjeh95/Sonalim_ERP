"""The shift report service, against a real database.

Every test runs in the `db` fixture's transaction and is rolled back. Reference rows
(user, product, line, work order) are built here so the tests pass on any migrated
database, seeded or empty.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.domain.shift_report import SECTION_KEYS

TENANT = "shift-service-test"
OTHER_TENANT = "shift-service-other"
DAY = datetime.date(2030, 3, 4)


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, work_center = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'SH-PASTA', 'Shift pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SH-WC', 'Shift line')",
        (work_center, TENANT),
    )
    return {"actor": actor, "product": product, "work_center": work_center}


def _of(db, env, *, started: bool = True) -> str:
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        product_id=env["product"],
        planned_quantity=1000,
        work_center_id=env["work_center"],
        start_date=DAY,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    if started:
        assert isinstance(
            service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok
        )
    return created.value.id


def _open(db, env, *, shift: str = "morning") -> str:
    result = ShiftReportService(db).open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift=shift
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value["id"]


def _save(db, env, shift_id, key, payload, **kwargs):
    return ShiftReportService(db).save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=payload, **kwargs
    )


def _submit(db, env, shift_id, key):
    return ShiftReportService(db).submit_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key
    )


def _nothing(db, env, shift_id, key):
    return ShiftReportService(db).declare_nothing(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key
    )


def _get(db, shift_id) -> dict:
    result = ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _section(shift: dict, key: str) -> dict:
    return next(s for s in shift["sections"] if s["key"] == key)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


# ---- opening ---------------------------------------------------------------


def test_opening_twice_returns_the_same_shift_with_nine_empty_sections(db, env):
    first = _open(db, env)
    assert _open(db, env) == first
    shift = _get(db, first)
    assert [s["key"] for s in shift["sections"]] == list(SECTION_KEYS)
    assert {s["status"] for s in shift["sections"]} == {"empty"}
    assert shift["status"] == "open"


def test_opening_needs_a_line_of_the_tenant_and_a_shift(db, env):
    service = ShiftReportService(db)
    unknown_line = service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id="nope", report_date=DAY, shift="morning"
    )
    blank_shift = service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="  "
    )
    assert isinstance(unknown_line, Err) and unknown_line.code == "NOT_FOUND"
    assert isinstance(blank_shift, Err) and blank_shift.code == "INVALID_VALUE"


def test_another_tenant_cannot_see_the_shift(db, env):
    shift_id = _open(db, env)
    result = ShiftReportService(db).get_shift(tenant_id=OTHER_TENANT, shift_report_id=shift_id)
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_header_names_can_be_updated(db, env):
    shift_id = _open(db, env)
    updated = _ok(
        ShiftReportService(db).update_header(
            tenant_id=TENANT,
            actor_id=env["actor"],
            shift_report_id=shift_id,
            fields={"team": "B", "conducteur": "Alou Traoré", "machiniste": "D. Samaké", "ignored": "x"},
        )
    )
    assert (updated["team"], updated["conducteur"], updated["machiniste"]) == ("B", "Alou Traoré", "D. Samaké")


def test_list_filters_by_date_and_status(db, env):
    _open(db, env, shift="morning")
    _open(db, env, shift="night")
    service = ShiftReportService(db)
    assert len(service.list_shifts(tenant_id=TENANT, report_date=DAY)) == 2
    assert service.list_shifts(tenant_id=TENANT, report_date=DAY, status="validated") == []
    assert service.list_shifts(tenant_id=TENANT, report_date=DAY + datetime.timedelta(days=1)) == []


# ---- runs and their neighbours ---------------------------------------------


def _run(of_id, **fields):
    return {
        "of_id": of_id,
        "start_time": "07:00",
        "end_time": "14:00",
        "production_minutes": 420,
        "finished_product_quantity": 9.45,
        "water_percentage": 30.9,
        "humidity_percentage": 11.56,
        "raw_material_location_id": "silo-1",
        "semolina_lines": [
            {"product_id": "semoule-extra", "location_id": "silo-1", "quantity": 4.65, "bag_count": 93, "lot_number": "BSTK1"}
        ],
        **fields,
    }


def test_saved_runs_come_back_with_server_ids_and_their_semolina(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    saved = _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    assert saved["status"] == "draft"
    payload = _section(_get(db, shift_id), "runs")["payload"]
    (run,) = payload["runs"]
    assert run["id"] and run["of_id"] == of_id
    assert run["humidity_percentage"] == 11.56
    assert run["start_time"] == "07:00:00"
    (semolina,) = run["semolina_lines"]
    assert semolina["bag_count"] == 93 and semolina["quantity"] == 4.65


def test_saving_again_keeps_ids_and_the_waste_that_points_at_them(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    run_id = _section(_get(db, shift_id), "runs")["payload"]["runs"][0]["id"]
    _ok(
        _save(
            db,
            env,
            shift_id,
            "waste_production",
            {"waste_lines": [{"category": "press", "quantity": 6.4, "run_id": run_id, "note": "Nettoyage presse"}]},
        )
    )
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id, id=run_id, finished_product_quantity=10)]}))
    shift = _get(db, shift_id)
    (run,) = _section(shift, "runs")["payload"]["runs"]
    assert run["id"] == run_id and run["finished_product_quantity"] == 10
    (waste,) = _section(shift, "waste_production")["payload"]["waste_lines"]
    assert waste["run_id"] == run_id


def test_removing_a_run_keeps_its_waste_line_unassigned(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    run_id = _section(_get(db, shift_id), "runs")["payload"]["runs"][0]["id"]
    _ok(_save(db, env, shift_id, "waste_production", {"waste_lines": [{"category": "press", "quantity": 1, "run_id": run_id}]}))
    _ok(_save(db, env, shift_id, "runs", {"runs": []}))
    (waste,) = _section(_get(db, shift_id), "waste_production")["payload"]["waste_lines"]
    assert waste["run_id"] is None


def test_a_client_supplied_id_from_another_shift_is_ignored(db, env):
    shift_a, shift_b = _open(db, env, shift="morning"), _open(db, env, shift="night")
    of_id = _of(db, env)
    _ok(_save(db, env, shift_a, "runs", {"runs": [_run(of_id)]}))
    foreign_id = _section(_get(db, shift_a), "runs")["payload"]["runs"][0]["id"]
    _ok(_save(db, env, shift_b, "runs", {"runs": [_run(of_id, id=foreign_id)]}))
    (mine,) = _section(_get(db, shift_b), "runs")["payload"]["runs"]
    assert mine["id"] != foreign_id
    assert len(_section(_get(db, shift_a), "runs")["payload"]["runs"]) == 1


def test_a_run_needs_an_open_order_but_an_existing_run_may_be_edited_after_closure(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    db.execute("UPDATE production.work_orders SET status = 'closed' WHERE id = %s", (of_id,))
    run_id = _section(_get(db, shift_id), "runs")["payload"]["runs"][0]["id"]
    # The same run on the now-closed order can still be corrected...
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id, id=run_id, finished_product_quantity=9)]}))
    # ...but a new run on it is refused.
    refused = _save(db, env, shift_id, "runs", {"runs": [_run(of_id, id=run_id), _run(of_id)]})
    assert isinstance(refused, Err) and refused.code == "OF_NOT_OPEN"


def test_a_run_without_an_order_or_with_a_negative_quantity_is_refused(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    missing = _save(db, env, shift_id, "runs", {"runs": [{"start_time": "07:00"}]})
    negative = _save(db, env, shift_id, "runs", {"runs": [_run(of_id, finished_product_quantity=-1)]})
    assert isinstance(missing, Err) and missing.code == "INVALID_VALUE"
    assert isinstance(negative, Err) and negative.code == "INVALID_VALUE"


# ---- waste, stops, silo, singletons ---------------------------------------


def test_waste_of_the_other_report_type_is_refused(db, env):
    shift_id = _open(db, env)
    result = _save(db, env, shift_id, "waste_production", {"waste_lines": [{"category": "packaging", "quantity": 1}]})
    assert isinstance(result, Err) and result.code == "INVALID_WASTE_CATEGORY"
    ok = _save(db, env, shift_id, "waste_packing", {"waste_lines": [{"category": "packaging", "quantity": 1}]})
    assert isinstance(ok, Ok)


def test_a_stop_cannot_end_before_it_starts_and_needs_a_known_motif(db, env):
    shift_id = _open(db, env)
    backwards = _save(
        db, env, shift_id, "stops",
        {"stops": [{"started_at": "2030-03-04T10:00:00+00:00", "ended_at": "2030-03-04T09:00:00+00:00"}]},
    )
    bad_motif = _save(
        db, env, shift_id, "stops",
        {"stops": [{"started_at": "2030-03-04T10:00:00+00:00", "motif": "tea_break"}]},
    )
    assert isinstance(backwards, Err) and backwards.code == "INVALID_VALUE"
    assert isinstance(bad_motif, Err) and bad_motif.code == "INVALID_DOWNTIME_MOTIF"


def test_a_stop_is_stored_as_manual_with_its_corrective_action(db, env):
    shift_id = _open(db, env)
    _ok(
        _save(
            db, env, shift_id, "stops",
            {"stops": [{
                "started_at": "2030-03-04T08:55:00+00:00", "ended_at": "2030-03-04T09:06:00+00:00",
                "motif": "extruder_failure", "downtime_type": "corrective", "classification": "mécanique",
                "corrective_action": "Nettoyage puis la production",
            }]},
        )
    )
    (stop,) = _section(_get(db, shift_id), "stops")["payload"]["stops"]
    assert stop["source"] == "manual" and stop["corrective_action"] == "Nettoyage puis la production"
    assert stop["motif"] == "extruder_failure"


def test_silo_state_is_unique_per_side_and_phase(db, env):
    shift_id = _open(db, env)
    row = {"side": "production", "phase": "start", "format": "Torsade", "level_percent": 0}
    _ok(_save(db, env, shift_id, "silo", {"states": [row, {**row, "phase": "end"}]}))
    duplicate = _save(db, env, shift_id, "silo", {"states": [row, row]})
    assert isinstance(duplicate, Err) and duplicate.code == "DUPLICATE_ROW"
    too_full = _save(db, env, shift_id, "silo", {"states": [{**row, "level_percent": 130}]})
    assert isinstance(too_full, Err) and too_full.code == "INVALID_VALUE"


def test_energy_and_staffing_are_single_records(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 600, "electricity_quantity": 1500.5}}))
    _ok(_save(db, env, shift_id, "staffing", {"staffing": {"control_room": 1, "petrin": 2, "semoule": 1, "broyage": 1}}))
    shift = _get(db, shift_id)
    assert _section(shift, "energy")["payload"]["energy"]["fuel_quantity"] == 600
    assert _section(shift, "staffing")["payload"]["staffing"]["petrin"] == 2
    _ok(_save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 550}}))
    assert _section(_get(db, shift_id), "energy")["payload"]["energy"]["fuel_quantity"] == 550


# ---- section life cycle ----------------------------------------------------


def test_an_empty_draft_cannot_be_submitted(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "packet_checks", {"checks": []}))
    result = _submit(db, env, shift_id, "packet_checks")
    assert isinstance(result, Err) and result.code == "EMPTY_SECTION"


def test_an_untouched_section_cannot_be_submitted(db, env):
    shift_id = _open(db, env)
    result = _submit(db, env, shift_id, "packet_checks")
    assert isinstance(result, Err) and result.code == "INVALID_TRANSITION"


def test_declaring_nothing_clears_the_rows_and_marks_the_section(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "packet_checks", {"checks": [{"checked_at": "2030-03-04T08:00:00+00:00", "packet_weight_grams": 500}]}))
    _ok(_nothing(db, env, shift_id, "packet_checks"))
    section = _section(_get(db, shift_id), "packet_checks")
    assert section["status"] == "nothing_to_report" and section["payload"]["checks"] == []


def test_the_shift_is_submitted_when_every_section_is_in(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    _ok(_submit(db, env, shift_id, "runs"))
    for key in SECTION_KEYS:
        if key != "runs":
            _ok(_nothing(db, env, shift_id, key))
    assert _get(db, shift_id)["status"] == "submitted"


def test_editing_a_submitted_section_saves_a_revision_and_flags_it(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    _ok(_submit(db, env, shift_id, "runs"))
    run_id = _section(_get(db, shift_id), "runs")["payload"]["runs"][0]["id"]
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id, id=run_id, finished_product_quantity=8.8)]}, reason="typo"))
    section = _section(_get(db, shift_id), "runs")
    assert (section["status"], section["revision"], section["revised_after_submit"]) == ("submitted", 2, True)
    revisions = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    assert [r["revision"] for r in revisions] == [2, 1]
    assert revisions[0]["reason"] == "typo"
    assert revisions[0]["snapshot"]["runs"][0]["finished_product_quantity"] == 8.8
    assert revisions[1]["snapshot"]["runs"][0]["finished_product_quantity"] == 9.45


def test_resubmitting_a_returned_section_clears_the_flag(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    _ok(_submit(db, env, shift_id, "runs"))
    db.execute(
        "UPDATE production.shift_report_sections SET status = 'returned', revised_after_submit = TRUE, return_reason = 'check it' "
        "WHERE shift_report_id = %s AND section_key = 'runs'",
        (shift_id,),
    )
    run_id = _section(_get(db, shift_id), "runs")["payload"]["runs"][0]["id"]
    assert _get(db, shift_id)["status"] == "open"  # derived only when a service call refreshes it
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id, id=run_id)]}))
    _ok(_submit(db, env, shift_id, "runs"))
    section = _section(_get(db, shift_id), "runs")
    assert (section["status"], section["revised_after_submit"], section["return_reason"]) == ("submitted", False, None)


def test_a_validated_shift_refuses_every_edit(db, env):
    shift_id = _open(db, env)
    db.execute("UPDATE production.shift_reports SET status = 'validated' WHERE id = %s", (shift_id,))
    for result in (
        _save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 1}}),
        _nothing(db, env, shift_id, "silo"),
        ShiftReportService(db).update_header(
            tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, fields={"team": "A"}
        ),
    ):
        assert isinstance(result, Err) and result.code == "NOT_EDITABLE"


def test_an_unknown_section_is_refused(db, env):
    shift_id = _open(db, env)
    result = _save(db, env, shift_id, "reels", {})
    assert isinstance(result, Err) and result.code == "INVALID_SECTION"


def test_state_changes_are_audited(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 1}}))
    _ok(_nothing(db, env, shift_id, "silo"))
    actions = {
        row[0]
        for row in db.execute(
            "SELECT action FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s", (TENANT, shift_id)
        ).fetchall()
    }
    assert {"shift_report.opened", "shift_report.section_saved", "shift_report.section_nothing_to_report"} <= actions


# ---- what must be filled in before a section can be submitted ---------------


def test_submitting_runs_needs_the_item_and_store_of_every_semolina_line(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    unlabelled = _run(of_id, semolina_lines=[{"quantity": 4.65, "location_id": "silo-1"}])
    _ok(_save(db, env, shift_id, "runs", {"runs": [unlabelled]}))  # a half-typed draft may be saved
    refused = _submit(db, env, shift_id, "runs")
    assert isinstance(refused, Err) and refused.code == "MISSING_STOCK_TARGET"
    assert "run 1" in refused.message


def test_submitting_a_waste_section_needs_to_say_what_was_lost(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "waste_production", {"waste_lines": [{"category": "press", "quantity": 6.4}]}))
    refused = _submit(db, env, shift_id, "waste_production")
    assert isinstance(refused, Err) and refused.code == "MISSING_WASTE_PRODUCT"
    _ok(_save(db, env, shift_id, "waste_production", {"waste_lines": [{"category": "press", "quantity": 6.4, "product_id": "dough"}]}))
    assert isinstance(_submit(db, env, shift_id, "waste_production"), Ok)


def test_submitting_packing_needs_the_stores_its_figures_move_through(db, env):
    shift_id = _open(db, env)
    of_id = _of(db, env)
    _ok(_save(db, env, shift_id, "runs", {"runs": [_run(of_id)]}))
    run_id = _ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"][0]["payload"]["runs"][0]["id"]
    row = {"run_id": run_id, "packets_counted": 1600, "film_quantity": 40, "film_product_id": "film-1"}
    _ok(_save(db, env, shift_id, "packing", {"rows": [row]}))
    # The stores now come from the products' own default storage locations; this product has none.
    refused = _submit(db, env, shift_id, "packing")
    assert isinstance(refused, Err) and refused.code == "NO_DEFAULT_LOCATION"
    complete = {**row, "finished_goods_location_id": "fg-1", "packaging_location_id": "pack-1"}
    _ok(_save(db, env, shift_id, "packing", {"rows": [complete]}))
    assert isinstance(_submit(db, env, shift_id, "packing"), Ok)


def test_a_packing_waste_section_needs_no_item(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "waste_packing", {"waste_lines": [{"category": "packaging", "quantity": 2.5, "note": "torn film"}]}))
    assert isinstance(_submit(db, env, shift_id, "waste_packing"), Ok)

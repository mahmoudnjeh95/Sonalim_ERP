"""What validating, reversing and correcting a shift leaves behind in the warehouse:
the move ledger has to add up to on-hand, and the cost layers have to stay the ones
the stock really came from."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.test_shift_validation_integration import (  # noqa: F401 -- `env` is a fixture
    TENANT,
    _ok,
    _on_hand,
    _shift,
    _submitted_shift,
    _validate,
    env,
)
from modules.warehouse.api.service import StockService
from modules.warehouse.api.valuation_service import ValuationService
from modules.warehouse.domain.analytics import signed_quantity


def _ids(db, shift_id) -> tuple[str, str]:
    shift = _shift(db, shift_id)
    run_id = shift["sections"][0]["payload"]["runs"][0]["id"]
    packing_id = next(s for s in shift["sections"] if s["key"] == "packing")["payload"]["rows"][0]["id"]
    return run_id, packing_id


def _ledger(db, product_id: str, location_id: str) -> float:
    """On-hand as the move history reads it: every row signed by its type."""
    rows = db.execute(
        "SELECT move_type, quantity FROM warehouse.stock_moves WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchall()
    return sum(signed_quantity(move_type, float(quantity)) for move_type, quantity in rows)


def _reverse(db, env, shift_id, **kwargs):
    return ShiftValidationService(db).reverse_shift(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason=kwargs.pop("reason", "test"), **kwargs
    )


# ---- #2: a reversal reads as a reversal in the move history ------------------------


def test_a_reversal_is_stored_as_its_own_move_type_and_the_ledger_matches_on_hand(db, env):
    shift_id = _submitted_shift(db, env)
    run_id, packing_id = _ids(db, shift_id)
    _ok(_validate(db, env, shift_id))
    _ok(_reverse(db, env, shift_id))

    types = {
        (source_id, move_type)
        for source_id, move_type in db.execute(
            "SELECT source_id, move_type FROM warehouse.stock_moves WHERE source_id = ANY(%s)", ([run_id, packing_id],)
        ).fetchall()
    }
    assert (run_id, "production_consumption") in types and (run_id, "production_consumption_reversal") in types
    assert (packing_id, "production") in types and (packing_id, "production_reversal") in types
    for product_key, location_key in (("semolina", "location"), ("product", "fg_location"), ("film", "packaging_location")):
        assert _ledger(db, env[product_key], env[location_key]) == pytest.approx(_on_hand(db, env, product_key, location_key))


# ---- #5: a reversal goes back through the cost layers it came from ------------------


def test_reversing_puts_the_semoule_back_into_its_own_cost_layer(db, env):
    # A dearer, newer layer on top of the seeded one: FIFO draws the old one first.
    db.execute("UPDATE core.products SET purchase_price = 900 WHERE id = %s", (env["semolina"],))
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["semolina"], location_id=env["location"], quantity=500,
        correlation_id=str(ULID()), reference="seed-2", actor_id=env["actor"], unit_cost=900,
    )
    layers_before = {
        layer.id: layer.quantity_remaining
        for layer in ValuationService(db).list_layers(tenant_id=TENANT, product_id=env["semolina"])
    }
    shift_id = _submitted_shift(db, env)
    run_id, _ = _ids(db, shift_id)
    _ok(_validate(db, env, shift_id))
    _ok(_reverse(db, env, shift_id))

    layers_after = {
        layer.id: layer.quantity_remaining
        for layer in ValuationService(db).list_layers(tenant_id=TENANT, product_id=env["semolina"])
    }
    assert layers_after == pytest.approx(layers_before), "no new layer at today's price, the old one is whole again"
    netted = ValuationService(db).cost_of_reference(tenant_id=TENANT, reference=f"shift_run:{run_id}")
    assert netted["quantity"] == pytest.approx(0)


def test_reversing_takes_the_finished_goods_out_of_the_layer_validation_opened(db, env):
    # Older finished goods already on the shelf at another cost.
    db.execute("UPDATE core.products SET purchase_price = 100 WHERE id = %s", (env["product"],))
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["fg_location"], quantity=50,
        correlation_id=str(ULID()), reference="older", actor_id=env["actor"], unit_cost=100,
    )
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    _ok(_reverse(db, env, shift_id))

    open_layers = ValuationService(db).list_layers(tenant_id=TENANT, product_id=env["product"])
    assert [(layer.reference, layer.quantity_remaining) for layer in open_layers] == [("older", 50)]


# ---- #3: the shortfall is judged on the whole shift --------------------------------


def _drain_semolina_to(db, env, quantity: float) -> None:
    StockService(db).adjust_stock(
        tenant_id=TENANT, product_id=env["semolina"], location_id=env["location"],
        delta=quantity - _on_hand(db, env, "semolina"), reason="test", actor_id=env["actor"],
    )


def test_runs_that_each_fit_but_together_overdraw_need_a_shortfall_comment(db, env):
    from modules.production.api.test_shift_validation_integration import _of, _run

    of_id = _of(db, env)
    shift_id = _submitted_shift(
        db, env, packing=False,
        runs=[_run(env, of_id, minutes=240, semolina=600), _run(env, of_id, minutes=240, semolina=600)],
    )
    _drain_semolina_to(db, env, 1000)  # each run's 600 fits; the shift's 1200 does not

    refused = _validate(db, env, shift_id)
    assert isinstance(refused, Err) and refused.code == "SHORTFALL_COMMENT_REQUIRED"

    _ok(_validate(db, env, shift_id, shortfall_comment="silo count was behind"))
    assert _on_hand(db, env, "semolina") == pytest.approx(-200)


# ---- #1: a correction after validation moves the stock with it ----------------------


def _unlocked_edit(db, env, shift_id, section_key, payload, **kwargs):
    return ShiftValidationService(db).edit_section_after_validation(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=section_key,
        payload=payload, reason=kwargs.pop("reason", "typo"), **kwargs,
    )


def _runs_payload(db, shift_id, *, semolina=None, regrind=None) -> dict:
    payload = _shift(db, shift_id)["sections"][0]["payload"]
    if semolina is not None:
        payload["versements"][0]["quantity"] = semolina
    if regrind is not None:
        payload["runs"][0]["regrind_quantity"] = regrind
    return {"runs": payload["runs"], "versements": payload["versements"]}


def _packing_payload(db, shift_id, **fields) -> dict:
    rows = next(s for s in _shift(db, shift_id)["sections"] if s["key"] == "packing")["payload"]["rows"]
    rows[0].update(fields)
    return {"rows": rows}


def test_correcting_the_runs_after_validation_moves_the_semoule_and_the_report_copy(db, env):
    shift_id = _submitted_shift(db, env)
    run_id, _ = _ids(db, shift_id)
    before = _on_hand(db, env, "semolina")
    _ok(_validate(db, env, shift_id))
    assert _on_hand(db, env, "semolina") == pytest.approx(before - 1000)

    _ok(_unlocked_edit(db, env, shift_id, "runs", _runs_payload(db, shift_id, semolina=1400)))

    assert _on_hand(db, env, "semolina") == pytest.approx(before - 1400)
    copied = db.execute(
        "SELECT SUM(quantity) FROM production.report_semolina_lines WHERE report_id = %s", (run_id,)
    ).fetchone()[0]
    assert float(copied) == pytest.approx(1400), "the read-only report copy follows the correction"
    assert _ledger(db, env["semolina"], env["location"]) == pytest.approx(_on_hand(db, env, "semolina"))

    # And a reversal afterwards takes back exactly what is posted now: nothing is left behind.
    _ok(_reverse(db, env, shift_id))
    assert _on_hand(db, env, "semolina") == pytest.approx(before)


def test_correcting_the_packing_keeps_the_packaging_pinned_at_validation(db, env):
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 20 WHERE id = %s", (env["product"],))
    shift_id = _submitted_shift(db, env)
    film_before = _on_hand(db, env, "film", "packaging_location")
    _ok(_validate(db, env, shift_id))
    assert _on_hand(db, env, location_key="fg_location") == pytest.approx(2000)  # 100 cartons x 20
    # The catalog changes after validation; the validated row keeps what it was judged on.
    db.execute("UPDATE core.products SET packets_per_carton = 24 WHERE id = %s", (env["product"],))

    _ok(_unlocked_edit(db, env, shift_id, "packing", _packing_payload(db, shift_id, carton_quantity=90, film_quantity=35)))

    assert _on_hand(db, env, location_key="fg_location") == pytest.approx(1800)  # 90 x the pinned 20
    assert _on_hand(db, env, "film", "packaging_location") == pytest.approx(film_before - 35)
    _ok(_reverse(db, env, shift_id))
    assert _on_hand(db, env, location_key="fg_location") == pytest.approx(0)
    assert _on_hand(db, env, "film", "packaging_location") == pytest.approx(film_before)


def test_a_section_that_moves_no_stock_is_corrected_without_reposting(db, env):
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    moves = db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0]

    _ok(_unlocked_edit(db, env, shift_id, "energy", {"energy": None}))

    assert db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == moves


def test_a_correction_above_a_ground_rebroyat_batch_needs_force_and_changes_nothing_until_then(db, env):
    from modules.production.api.test_shift_validation_integration import _close_the_regrind_batch, _rebroyat

    _rebroyat(db, env)
    shift_id = _submitted_shift(db, env, packing=False)
    run_id, = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]
    db.execute("UPDATE production.shift_runs SET regrind_quantity = 40 WHERE id = %s", (run_id,))
    _ok(_validate(db, env, shift_id))
    _close_the_regrind_batch(db, env)
    semolina_after = _on_hand(db, env, "semolina")

    refused = _unlocked_edit(db, env, shift_id, "runs", _runs_payload(db, shift_id, semolina=1200, regrind=50))

    assert isinstance(refused, Err) and refused.code == "REGRIND_DELTA_REQUIRES_NEW_ORDER"
    assert _on_hand(db, env, "semolina") == pytest.approx(semolina_after), "a refusal leaves stock as it was"
    assert float(_shift(db, shift_id)["sections"][0]["payload"]["versements"][0]["quantity"]) == 1000, "and the rows too"

    _ok(_unlocked_edit(db, env, shift_id, "runs", _runs_payload(db, shift_id, semolina=1200, regrind=50), force=True))

    assert _on_hand(db, env, "semolina") == pytest.approx(semolina_after - 200)
    batches = db.execute(
        "SELECT rb.input_quantity_total FROM production.regrind_batches rb WHERE rb.tenant_id = %s ORDER BY rb.input_quantity_total",
        (TENANT,),
    ).fetchall()
    assert [float(b[0]) for b in batches] == [10, 40], "the ground batch stays, a second one opens for the 10 kg more"


# ---- #4: finished goods are valued at what went into them --------------------------


def _price_the_seeded_layers(db, env, **unit_costs) -> None:
    for key, unit_cost in unit_costs.items():
        db.execute(
            "UPDATE warehouse.cost_layers SET unit_cost = %s WHERE tenant_id = %s AND product_id = %s",
            (unit_cost, TENANT, env[key]),
        )


def _finished_layer_cost(db, packing_id) -> float | None:
    row = db.execute(
        "SELECT unit_cost FROM warehouse.cost_layers WHERE tenant_id = %s AND reference = %s AND move_type = 'production'",
        (TENANT, f"shift_packing_row:{packing_id}"),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def test_packed_goods_are_valued_at_the_semoule_and_packaging_they_consumed(db, env):
    _price_the_seeded_layers(db, env, semolina=500, film=10, carton=10, scotch=10, ruban=10)
    shift_id = _submitted_shift(db, env)
    _, packing_id = _ids(db, shift_id)

    _ok(_validate(db, env, shift_id))

    material = 1000 * 500
    packaging = (40 + 100 + 2 + 1) * 10
    assert _finished_layer_cost(db, packing_id) == pytest.approx((material + packaging) / 1600)  # 1600 packets


def test_without_a_known_material_cost_the_catalog_fallback_values_the_goods(db, env):
    _price_the_seeded_layers(db, env, film=10, carton=10, scotch=10, ruban=10)  # semoule left unvalued
    db.execute("UPDATE core.products SET purchase_price = 77 WHERE id = %s", (env["product"],))
    shift_id = _submitted_shift(db, env)
    _, packing_id = _ids(db, shift_id)

    _ok(_validate(db, env, shift_id))

    assert _finished_layer_cost(db, packing_id) == pytest.approx(77), "not a packaging-only figure that looks real"


def test_correcting_the_runs_revalues_the_packed_goods(db, env):
    _price_the_seeded_layers(db, env, semolina=500, film=10, carton=10, scotch=10, ruban=10)
    shift_id = _submitted_shift(db, env)
    _, packing_id = _ids(db, shift_id)
    _ok(_validate(db, env, shift_id))

    _ok(_unlocked_edit(db, env, shift_id, "runs", _runs_payload(db, shift_id, semolina=1200)))

    open_layers = [
        layer for layer in ValuationService(db).list_layers(tenant_id=TENANT, product_id=env["product"])
        if layer.reference == f"shift_packing_row:{packing_id}"
    ]
    assert [layer.quantity_remaining for layer in open_layers] == [pytest.approx(1600)]
    assert open_layers[0].unit_cost == pytest.approx((1200 * 500 + 1430) / 1600)

"""Scrap recording and its regrind traceability, against a real database.

The behaviour under test:

1. `record_scrap` refuses a `product_id` that isn't a real product, cleanly
   (a domain `Err` -> 400), instead of letting the `scrap_records.product_id`
   foreign key raise an unhandled `psycopg.errors.ForeignKeyViolation`. That
   used to surface in the browser as a misleading CORS failure -- the crash
   happens outside CORSMiddleware, so the 500 response carries no
   Access-Control-Allow-Origin header, and Chrome reports the wrong cause.

2. `get_regrind_batch` traces a finished batch's output back to the scrap it
   was built from -- and, through each scrap record's own `work_order_id`,
   back to the production OF that generated it. That join used to only be
   reachable id-by-id (`scrap_record_ids` with no detail), so nothing in the
   product surfaced "this rebroyat came from OF-X's cutting scrap".
"""
from __future__ import annotations

from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService, ScrapService
from modules.production.api.service import WorkOrderService
from modules.warehouse.api.service import StockService

TENANT = "integration-test-scrap-records"


def _seed(db):
    actor = str(ULID())
    weight_uom = str(ULID())
    pasta_product, semoule_product, location, work_center = (str(ULID()) for _ in range(4))

    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogramme', 'weight')",
        (weight_uom, TENANT),
    )
    for product_id, sku in ((pasta_product, "SCRAP-PASTA"), (semoule_product, "SCRAP-SEMOULE")):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, weight_uom),
        )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SCRAP-LOC', 'Loc')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SCRAP-WC', 'Line')",
        (work_center, TENANT),
    )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=semoule_product)

    work_order_service = WorkOrderService(db)
    production_of = work_order_service.create_work_order(
        tenant_id=TENANT, actor_id=actor, product_id=pasta_product, planned_quantity=1000, work_center_id=work_center,
    )
    assert isinstance(production_of, Ok), getattr(production_of, "message", "")

    return {
        "actor": actor,
        "pasta_product": pasta_product,
        "semoule_product": semoule_product,
        "location": location,
        "work_center": work_center,
        "production_of": production_of.value,
    }


def test_record_scrap_rejects_unknown_product(db):
    env = _seed(db)
    result = ScrapService(db).record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id="not-a-real-product", quantity=1, work_order_id=env["production_of"].id,
    )
    assert isinstance(result, Err)
    assert result.code == "PRODUCT_NOT_FOUND"


def test_record_scrap_accepts_a_real_product(db):
    env = _seed(db)
    result = ScrapService(db).record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=1, work_order_id=env["production_of"].id,
    )
    assert isinstance(result, Ok), getattr(result, "message", "")


def test_regrind_batch_traces_back_to_the_production_of(db):
    env = _seed(db)
    scrap = ScrapService(db).record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=2.5, work_order_id=env["production_of"].id,
    )
    assert isinstance(scrap, Ok), getattr(scrap, "message", "")

    regrind = RegrindService(db)
    batch = regrind.create_regrind_batch(
        tenant_id=TENANT, actor_id=env["actor"],
        scrap_record_ids=[scrap.value.id], work_center_id=env["work_center"],
    )
    assert isinstance(batch, Ok), getattr(batch, "message", "")

    fetched = regrind.get_regrind_batch(tenant_id=TENANT, work_order_id=batch.value["work_order"].id)
    assert fetched is not None
    assert fetched["scrap_record_ids"] == [scrap.value.id]
    [source] = fetched["scrap_inputs"]
    assert source["id"] == scrap.value.id
    assert source["work_order_id"] == env["production_of"].id
    assert source["product_id"] == env["pasta_product"]
    assert source["scrap_type"] == "cutting"
    assert source["quantity"] == 2.5


def test_scrap_list_names_the_ofr_that_consumed_it_and_only_then(db):
    env = _seed(db)
    scraps = ScrapService(db)
    consumed = scraps.record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=2.5, work_order_id=env["production_of"].id,
    )
    available = scraps.record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=1, work_order_id=env["production_of"].id,
    )
    batch = RegrindService(db).create_regrind_batch(
        tenant_id=TENANT, actor_id=env["actor"],
        scrap_record_ids=[consumed.value.id], work_center_id=env["work_center"],
    )
    assert isinstance(batch, Ok), getattr(batch, "message", "")

    by_id = {s.id: s for s in scraps.list_scrap(tenant_id=TENANT)}
    assert by_id[consumed.value.id].regrind_work_order_id == batch.value["work_order"].id
    assert by_id[available.value.id].regrind_work_order_id is None


def test_only_the_regrind_order_is_flagged_is_regrind(db):
    env = _seed(db)
    scrap = ScrapService(db).record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=2.5, work_order_id=env["production_of"].id,
    )
    batch = RegrindService(db).create_regrind_batch(
        tenant_id=TENANT, actor_id=env["actor"],
        scrap_record_ids=[scrap.value.id], work_center_id=env["work_center"],
    )
    assert isinstance(batch, Ok), getattr(batch, "message", "")

    flags = {o.id: o.is_regrind for o in WorkOrderService(db).list_work_orders(TENANT)}
    assert flags == {env["production_of"].id: False, batch.value["work_order"].id: True}


def test_new_regrind_orders_are_numbered_in_the_ofr_series(db):
    env = _seed(db)
    scrap = ScrapService(db).record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=2.5, work_order_id=env["production_of"].id,
    )
    batch = RegrindService(db).create_regrind_batch(
        tenant_id=TENANT, actor_id=env["actor"],
        scrap_record_ids=[scrap.value.id], work_center_id=env["work_center"],
    )
    assert isinstance(batch, Ok), getattr(batch, "message", "")
    assert batch.value["work_order"].reference.startswith("OFR-")
    assert env["production_of"].reference.startswith("OF-")


def test_repair_migration_renumbers_a_regrind_order_left_on_the_of_series(db):
    from pathlib import Path

    env = _seed(db)
    scraps = ScrapService(db)
    regrind = RegrindService(db)
    orders = []
    for _ in range(3):
        scrap = scraps.record_scrap(
            tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
            product_id=env["pasta_product"], quantity=1, work_order_id=env["production_of"].id,
        )
        batch = regrind.create_regrind_batch(
            tenant_id=TENANT, actor_id=env["actor"],
            scrap_record_ids=[scrap.value.id], work_center_id=env["work_center"],
        )
        assert isinstance(batch, Ok), getattr(batch, "message", "")
        orders.append(batch.value["work_order"].id)
    first, second, third = orders

    # What a pre-0037 backend left behind: the middle batch on the "OF-" series.
    db.execute("UPDATE production.work_orders SET reference = 'OF-000999' WHERE id = %s", (second,))
    before = {
        oid: ref for oid, ref in db.execute(
            "SELECT id, reference FROM production.work_orders WHERE tenant_id = %s", (TENANT,)
        ).fetchall()
    }

    migration = Path(__file__).parents[1] / "migrations" / "0044_production_regrind_reference_repair.sql"
    db.execute(migration.read_text(encoding="utf-8"))

    after = {
        oid: ref for oid, ref in db.execute(
            "SELECT id, reference FROM production.work_orders WHERE tenant_id = %s", (TENANT,)
        ).fetchall()
    }
    assert after[first] == before[first]
    assert after[third] == before[third]
    assert after[env["production_of"].id] == before[env["production_of"].id]
    assert after[second].startswith("OFR-") and after[second] not in (before[first], before[third])
    # ...and the counter moved past it, so the next regrind order cannot collide.
    next_batch_scrap = scraps.record_scrap(
        tenant_id=TENANT, actor_id=env["actor"], scrap_type="cutting",
        product_id=env["pasta_product"], quantity=1, work_order_id=env["production_of"].id,
    )
    nxt = regrind.create_regrind_batch(
        tenant_id=TENANT, actor_id=env["actor"],
        scrap_record_ids=[next_batch_scrap.value.id], work_center_id=env["work_center"],
    )
    assert isinstance(nxt, Ok), getattr(nxt, "message", "")
    assert nxt.value["work_order"].reference not in after.values()

    # Re-running it changes nothing.
    db.execute(migration.read_text(encoding="utf-8"))
    again = {oid: ref for oid, ref in db.execute(
        "SELECT id, reference FROM production.work_orders WHERE tenant_id = %s", (TENANT,)
    ).fetchall() if oid in after}
    assert again == after

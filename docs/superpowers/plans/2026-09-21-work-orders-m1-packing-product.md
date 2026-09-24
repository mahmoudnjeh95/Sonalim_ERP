# Milestone 1: Finished Product on the Packing Row — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Packing rows name their own finished product; type, packets, stores, stock posting, packaging variance and finished-goods readers follow that product, so one OF can carry several products and take its first one from its first validated shift.

**Architecture:** A `product_id` column on `shift_packing_rows` and on the old-shaped `conditionnement_reports` table (which validation still posts stock from). A pure rule in the domain resolves a packing row's OF; `packing_derivation_service` uses it and derives everything from the row's own product. One helper (`finished_product_of_report`) replaces every direct read of `work_orders.product_id` that concerns a packing report. Validation stamps an OF that has no product with its first packing row's product.

**Tech Stack:** Python 3 / FastAPI / psycopg 3 / PostgreSQL (raw SQL migrations), pytest against the dev database (every test rolls back); React 18 + TypeScript + TanStack Query on the frontend.

**Spec:** `docs/superpowers/specs/2026-09-21-work-orders-product-from-shift-design.md` (Milestone 1: sections 1.1 to 1.5). Milestone 2 (OF list and OF page) gets its own plan once this one is built.

## Global Constraints

- Run backend commands from `backend/`: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest <path> -q`.
- Frontend: `cd frontend && npx tsc -b --force` (never plain `tsc -b`); it must end with no errors.
- Tests are integration tests on the real dev DB inside a rolled-back transaction (`db` fixture); do not commit data.
- Do not commit to git: the branch holds a large uncommitted body and no commit was requested. Skip every "commit" step; leave changes in the working tree.
- Screen strings are bilingual through `L(en, fr)` in `shift/shiftText.ts`; backend messages are English.
- Nothing is guessed from names: the packing type comes from the product's `net_weight_grams` and its classified `packaging_format`.
- Old-shaped rows (`production_reports`, `conditionnement_reports`) still exist and validation posts stock from them; do not remove them.

## File Structure

| File | Change |
|---|---|
| `backend/modules/production/migrations/0055_production_packing_product.sql` | new: the two columns, backfill, index |
| `backend/modules/production/domain/packing_derivation.py` | add `resolve_packing_order` (pure) |
| `backend/modules/production/domain/test_packing_derivation.py` | tests for it |
| `backend/modules/production/api/report_product.py` | new: `finished_product_of_report`, `stamp_order_products` |
| `backend/modules/production/api/packing_derivation_service.py` | rewrite around the row's product |
| `backend/modules/production/api/shift_sections.py` | `product_id` column in `_PACKING`; submit check |
| `backend/modules/production/api/legacy_report_ledger.py` | `product_id` in `_PACKING_COLUMNS`; store rule reads the row's product |
| `backend/modules/production/api/production_report_service.py` | 3 reads use the helper |
| `backend/modules/production/api/conditionnement_service.py` | DLC lot uses the helper |
| `backend/modules/production/api/shift_validation_service.py` | stamp before materialising |
| `backend/modules/production/api/packaging_variance_service.py` | per-row product; multi-product `for_of` |
| `backend/modules/production/api/finished_goods_service.py`, `stock_release_service.py` | group by the row's product |
| `backend/modules/production/api/of_consolidation_service.py` | `product_ids` |
| `backend/modules/production/api/test_packing_product_integration.py` | new: derivation + submit tests |
| `backend/modules/production/api/test_packing_product_validation_integration.py` | new: stock, stamping, variance, consolidation tests |
| `frontend/src/features/production/shift/{packingType.ts,sectionConfig.ts,ShiftGrid.tsx,useShiftReferenceData.ts}` | the screen |
| `frontend/src/features/production/{api.ts,WorkOrderDetailsPage.tsx}` | multi-product variance |
| `frontend/src/lib/i18n.tsx` | one heading string |

---

### Task 1: Schema: product on the packing row

**Files:**
- Create: `backend/modules/production/migrations/0055_production_packing_product.sql`
- Test: `backend/modules/production/api/test_packing_product_integration.py` (created here, extended in Task 3)

**Interfaces:**
- Produces: `production.shift_packing_rows.product_id TEXT`, `production.conditionnement_reports.product_id TEXT` (both nullable, opaque ids into `core.products`, no foreign key like `equipment_id`).

- [ ] **Step 1: Write the failing test** (`test_packing_product_integration.py`, new file)

```python
"""A packing row names its own finished product; everything else follows from it."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService

TENANT = "packing-product-test"
DAY = datetime.date(2030, 9, 9)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def test_the_product_columns_exist(db):
    columns = {
        (table, column)
        for table, column in db.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'production' AND column_name = 'product_id' "
            "AND table_name IN ('shift_packing_rows', 'conditionnement_reports')"
        ).fetchall()
    }
    assert columns == {("shift_packing_rows", "product_id"), ("conditionnement_reports", "product_id")}
```

- [ ] **Step 2: Run it, expect FAIL** (`assert set() == {...}`)

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_packing_product_integration.py -q`

- [ ] **Step 3: Write the migration**

```sql
-- A packing row names the finished product it made. An OF can pack several products (a PC mold
-- change starts a new product on the same OF), so the product lives on the row, not only on the OF.
-- Opaque reference into core.products, like equipment_id: production keeps no foreign key into core.
ALTER TABLE production.shift_packing_rows ADD COLUMN IF NOT EXISTS product_id TEXT;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS product_id TEXT;

-- Existing rows made what their OF was for.
UPDATE production.shift_packing_rows p
SET product_id = w.product_id
FROM production.work_orders w
WHERE w.id = p.of_id AND w.tenant_id = p.tenant_id AND p.product_id IS NULL AND w.product_id IS NOT NULL;

UPDATE production.conditionnement_reports c
SET product_id = w.product_id
FROM production.production_reports r
JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
WHERE r.id = c.report_id AND r.tenant_id = c.tenant_id AND c.product_id IS NULL AND w.product_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS shift_packing_rows_product_idx ON production.shift_packing_rows (tenant_id, product_id);
```

- [ ] **Step 4: Apply it to the dev DB and rerun the test**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Then the pytest command from Step 2. Expected: PASS.

- [ ] **Step 5: Check the backfill on the dev data**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -c "import psycopg,os; c=psycopg.connect(os.environ['DATABASE_URL']); print(c.execute('select count(*) filter (where p.product_id is null), count(*) from production.shift_packing_rows p').fetchone())"`
Expected: the first number is the count of rows whose OF has no product (small); the second is the total. No row whose OF has a product is left null: `select count(*) from production.shift_packing_rows p join production.work_orders w on w.id = p.of_id where p.product_id is null and w.product_id is not null` must be `0`.

---

### Task 2: The rule that finds a packing row's OF

**Files:**
- Modify: `backend/modules/production/domain/packing_derivation.py`
- Test: `backend/modules/production/domain/test_packing_derivation.py`

**Interfaces:**
- Produces: `resolve_packing_order(*, given_of_id: str | None, run_of_id: str | None, shift_orders: Mapping[str, str | None], product_id: str | None) -> tuple[str | None, str | None]`. Returns `(of_id, None)` or `(None, error_code)` with `error_code` in `{"PRODUCTION_FIRST", "OF_AMBIGUOUS"}`. `shift_orders` maps each distinct OF of the shift's runs to that OF's own product (or `None`).

- [ ] **Step 1: Write the failing tests** (append to `test_packing_derivation.py`, add `resolve_packing_order` to the import)

```python
from modules.production.domain.packing_derivation import resolve_packing_order


def test_a_named_run_decides_the_order():
    assert resolve_packing_order(given_of_id="of-x", run_of_id="of-run", shift_orders={"of-1": None}, product_id=None) == ("of-run", None)


def test_an_order_the_row_already_holds_is_kept():
    assert resolve_packing_order(given_of_id="of-x", run_of_id=None, shift_orders={"of-1": None, "of-2": None}, product_id=None) == ("of-x", None)


def test_the_only_order_of_the_shift_is_the_one():
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders={"of-1": None}, product_id="p") == ("of-1", None)


def test_several_orders_are_told_apart_by_the_rows_product():
    orders = {"of-1": "p1", "of-2": "p2"}
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders=orders, product_id="p2") == ("of-2", None)


def test_several_orders_with_no_product_match_are_ambiguous():
    orders = {"of-1": "p1", "of-2": "p2"}
    for product in (None, "p3"):
        assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders=orders, product_id=product) == (None, "OF_AMBIGUOUS")


def test_several_orders_of_the_same_product_are_ambiguous():
    orders = {"of-1": "p1", "of-2": "p1"}
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders=orders, product_id="p1") == (None, "OF_AMBIGUOUS")


def test_a_shift_with_no_production_cannot_place_the_row():
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders={}, product_id="p") == (None, "PRODUCTION_FIRST")
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'resolve_packing_order'`)

Run: `... -m pytest modules/production/domain/test_packing_derivation.py -q`

- [ ] **Step 3: Implement** (add to `domain/packing_derivation.py`; add `from collections.abc import Iterable, Mapping`)

```python
def resolve_packing_order(
    *,
    given_of_id: str | None,
    run_of_id: str | None,
    shift_orders: Mapping[str, str | None],
    product_id: str | None,
) -> tuple[str | None, str | None]:
    """The work order a packing row belongs to: `(of_id, None)`, or `(None, why_not)`.

    A run the row names decides it (an old row); then an order the row already holds; then the
    shift's own production: its only order, else the one order whose product is the row's.
    `shift_orders` maps each distinct order of the shift's runs to that order's own product.
    """
    if run_of_id:
        return run_of_id, None
    if given_of_id:
        return given_of_id, None
    if not shift_orders:
        return None, "PRODUCTION_FIRST"
    if len(shift_orders) == 1:
        return next(iter(shift_orders)), None
    matching = [of_id for of_id, of_product in shift_orders.items() if product_id and of_product == product_id]
    if len(matching) == 1:
        return matching[0], None
    return None, "OF_AMBIGUOUS"
```

- [ ] **Step 4: Run, expect PASS** (same command)

---

### Task 3: Derive a packing row from its own product

**Files:**
- Modify: `backend/modules/production/api/packing_derivation_service.py`
- Modify: `backend/modules/production/api/shift_sections.py` (`_PACKING` at ~195-224; `check_ready_to_submit` at ~698-701)
- Modify: `backend/modules/production/api/test_packing_derivation_integration.py` (two tests change meaning)
- Test: `backend/modules/production/api/test_packing_product_integration.py`

**Interfaces:**
- Consumes: `resolve_packing_order` (Task 2), the two columns (Task 1).
- Produces: after `derive_packing_rows`, every row dict carries `of_id` (resolved), `product_id` (its own, else the OF's, else `None`), `run_id` (its own, else the OF's only run on the shift, else `None`), `packing_type`, `packets_counted`, `finished_goods_location_id`, `packaging_location_id`. Errors: `PRODUCTION_FIRST`, `OF_AMBIGUOUS`, `PACKAGING_STORES_DIFFER`. Submit refuses a row with no product: `PRODUCT_REQUIRED`. `load_section("packing")` returns `product_id` on each row.

- [ ] **Step 1: Write the failing tests** (append to `test_packing_product_integration.py`)

```python
@pytest.fixture
def env(db):
    actor, uom, small, big, film, carton, fg_small, fg_big, pack, work_center = (str(ULID()) for _ in range(10))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((small, "PP-200"), (big, "PP-500"), (film, "PP-FILM"), (carton, "PP-CARTON")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    for location_id, code in ((fg_small, "PP-FG-200"), (fg_big, "PP-FG-500"), (pack, "PP-PACK")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (location_id, TENANT, code, code))
    db.execute("UPDATE core.products SET net_weight_grams = 200, packets_per_carton = 24, default_location_id = %s WHERE id = %s", (fg_small, small))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg_big, big))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = ANY(%s)", (pack, [film, carton]))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'PP-WC', 'Line')", (work_center, TENANT))
    for product_id in (small, big):
        ProductClassificationService(db).set_classification(
            tenant_id=TENANT, actor_id=actor, product_id=product_id, category="finished_good", packaging_format="packet"
        )
    return {"actor": actor, "small": small, "big": big, "film": film, "carton": carton, "fg_small": fg_small, "fg_big": fg_big, "pack": pack, "work_center": work_center}


def _open_shift(db, env, shift="morning"):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift=shift))["id"]
    return service, shift_id


def _order(db, env, *, product_id=None):
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=product_id, planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    return of_id


def _save_runs(service, env, shift_id, of_ids):
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [{"of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900} for of_id in of_ids]},
    ))


def _save_packing(service, env, shift_id, rows):
    return service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing", payload={"rows": rows})


def _packing_rows(service, shift_id):
    sections = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"]
    return next(s for s in sections if s["key"] == "packing")["payload"]["rows"]


def test_a_row_derives_type_packets_and_store_from_its_own_product(db, env):
    service, shift_id = _open_shift(db, env)
    of_id = _order(db, env)  # created with no product, as the screen creates it
    _save_runs(service, env, shift_id, [of_id])
    _ok(_save_packing(service, env, shift_id, [{"product_id": env["small"], "carton_quantity": 10}]))
    [row] = _packing_rows(service, shift_id)
    assert row["of_id"] == of_id
    assert row["product_id"] == env["small"]
    assert row["packing_type"] == "Sachet 200 g"
    assert row["packets_counted"] == 240  # 10 cartons x 24 packets
    assert row["finished_goods_location_id"] == env["fg_small"]
    assert row["run_id"] is not None  # the OF has exactly one run on the shift


def test_a_row_without_a_product_takes_its_orders_product(db, env):
    service, shift_id = _open_shift(db, env)
    of_id = _order(db, env, product_id=env["big"])
    _save_runs(service, env, shift_id, [of_id])
    _ok(_save_packing(service, env, shift_id, [{"carton_quantity": 10}]))
    [row] = _packing_rows(service, shift_id)
    assert row["product_id"] == env["big"] and row["packing_type"] == "Sachet 500 g"


def test_changing_the_product_re_derives_the_row(db, env):
    service, shift_id = _open_shift(db, env)
    _save_runs(service, env, shift_id, [_order(db, env)])
    _ok(_save_packing(service, env, shift_id, [{"product_id": env["small"], "carton_quantity": 10}]))
    [saved] = _packing_rows(service, shift_id)
    # The screen re-sends the row without the fields the server derived and clears the OF on a product change.
    _ok(_save_packing(service, env, shift_id, [{"id": saved["id"], "product_id": env["big"], "carton_quantity": 10}]))
    [row] = _packing_rows(service, shift_id)
    assert (row["packing_type"], row["packets_counted"], row["finished_goods_location_id"]) == ("Sachet 500 g", 120, env["fg_big"])


def test_two_orders_are_told_apart_by_the_rows_product(db, env):
    service, shift_id = _open_shift(db, env)
    small_of = _order(db, env, product_id=env["small"])
    big_of = _order(db, env, product_id=env["big"])
    _save_runs(service, env, shift_id, [small_of, big_of])
    _ok(_save_packing(service, env, shift_id, [{"product_id": env["big"], "carton_quantity": 1}]))
    [row] = _packing_rows(service, shift_id)
    assert row["of_id"] == big_of


def test_two_orders_and_no_product_is_ambiguous(db, env):
    service, shift_id = _open_shift(db, env)
    _save_runs(service, env, shift_id, [_order(db, env, product_id=env["small"]), _order(db, env, product_id=env["big"])])
    refused = _save_packing(service, env, shift_id, [{"carton_quantity": 1}])
    assert isinstance(refused, Err) and refused.code == "OF_AMBIGUOUS"


def test_a_shift_with_no_production_says_to_enter_it_first(db, env):
    service, shift_id = _open_shift(db, env)
    refused = _save_packing(service, env, shift_id, [{"product_id": env["small"], "carton_quantity": 1}])
    assert isinstance(refused, Err) and refused.code == "PRODUCTION_FIRST"


def test_handing_in_needs_a_product(db, env):
    service, shift_id = _open_shift(db, env)
    _save_runs(service, env, shift_id, [_order(db, env)])  # an order with no product either
    _ok(_save_packing(service, env, shift_id, [{"carton_quantity": 3}]))  # a draft may be saved without one
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "PRODUCT_REQUIRED"
```

- [ ] **Step 2: Run, expect FAIL** (`test_a_row_derives...` fails on `KeyError: 'product_id'`; the others fail similarly or on the old `INVALID_VALUE`)

Run: `... -m pytest modules/production/api/test_packing_product_integration.py -q`

- [ ] **Step 3: Add the column to `_PACKING`** in `shift_sections.py`: in the `columns=(` tuple of `_PACKING`, directly after `Col("run_id", "run_ref"),` insert:

```python
        Col("product_id"),
```

- [ ] **Step 4: Replace the submit check.** In `check_ready_to_submit`, `elif section_key == "packing":` block, replace

```python
            if not row.get("run_id"):
                return Err("RUN_REQUIRED", f"packing row {index}: pick the production this lot comes from")
```

with

```python
            if not row.get("product_id"):
                return Err("PRODUCT_REQUIRED", f"packing row {index}: pick the product this lot is made of")
```

- [ ] **Step 5: Rewrite `derive_packing_rows`.** In `packing_derivation_service.py`, change the import line `from modules.production.domain.packing_derivation import packing_type_label, pick_packaging_location` to also import `resolve_packing_order`, and replace the function body (from `def derive_packing_rows` to `return Ok(None)`) with:

```python
_ORDER_PROBLEMS = {
    "PRODUCTION_FIRST": "packing row {n}: enter and save this shift's production first; a lot is filed under its work order",
    "OF_AMBIGUOUS": "packing row {n}: this shift ran several work orders; pick the OF for this lot",
}


def derive_packing_rows(connection: psycopg.Connection, *, tenant_id: str, shift_id: str, rows: list[dict]) -> Result[None]:
    """Complete the cleaned packing rows in place, or say why one cannot be saved."""
    core = CoreService(connection)
    classifications = ProductClassificationService(connection)
    # Packed goods wait in the line store, next to the production, until they are released;
    # with none set they go straight to the product's own store.
    line_store = DashboardSettingsService(connection).line_store_id(tenant_id=tenant_id)

    run_order: dict[str, str] = {}  # run id -> its work order
    runs_of_order: dict[str, list[str]] = {}  # work order -> its runs on this shift
    order_product: dict[str, str | None] = {}  # work order -> its own product
    for run_id, of_id, of_product in connection.execute(
        """
        SELECT r.id, r.of_id, w.product_id
        FROM production.shift_runs r
        JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
        WHERE r.tenant_id = %s AND r.shift_report_id = %s
        ORDER BY r.line_order, r.id
        """,
        (tenant_id, shift_id),
    ).fetchall():
        run_order[run_id] = of_id
        runs_of_order.setdefault(of_id, []).append(run_id)
        order_product.setdefault(of_id, of_product)

    def product_of_order(of_id: str) -> str | None:
        if of_id not in order_product:
            found = connection.execute(
                "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s", (of_id, tenant_id)
            ).fetchone()
            order_product[of_id] = found[0] if found else None
        return order_product[of_id]

    for index, row in enumerate(rows, start=1):
        of_id, problem = resolve_packing_order(
            given_of_id=row["of_id"],
            run_of_id=run_order.get(row["run_id"]) if row["run_id"] else None,
            shift_orders={of: order_product[of] for of in runs_of_order},
            product_id=row["product_id"],
        )
        if problem:
            return Err(problem, _ORDER_PROBLEMS[problem].format(n=index))
        row["of_id"] = of_id
        if not row["run_id"] and len(runs_of_order.get(of_id, [])) == 1:
            row["run_id"] = runs_of_order[of_id][0]
        if not row["product_id"]:
            row["product_id"] = product_of_order(of_id)

        product = core.get_product(tenant_id, row["product_id"]) if row["product_id"] else None
        if product is not None:
            classification = classifications.get_classification(tenant_id, row["product_id"])
            row["packing_type"] = packing_type_label(
                packaging_format=classification.packaging_format if classification else None,
                net_weight_grams=product.net_weight_grams,
            )
            if not row["packets_counted"]:
                row["packets_counted"] = finished_quantity_from_count(
                    packets_per_carton=product.packets_per_carton,
                    carton_quantity=row["carton_quantity"],
                    packets_counted=0.0,
                    waste_carton_quantity=row["waste_carton_quantity"],
                )
            if not row["finished_goods_location_id"]:
                row["finished_goods_location_id"] = line_store or product.default_location_id

        if not row["packaging_location_id"]:
            stores = []
            for column in _PACKAGING_PRODUCTS:
                item = core.get_product(tenant_id, row[column]) if row[column] else None
                if item is not None:
                    stores.append(item.default_location_id)
            location, conflict = pick_packaging_location(stores)
            if conflict:
                return Err(
                    "PACKAGING_STORES_DIFFER",
                    f"packing row {index}: its packaging items have different default storage locations; "
                    "packaging is taken from one store per row",
                )
            row["packaging_location_id"] = location
    return Ok(None)
```

Also update the module docstring's first paragraph to: "A row names the product it packs. The OF comes from the shift's production (or the OF the row already holds); from the product come the packing type, the packets its cartons make and the finished-goods store; from each packaging item's default storage location, the stores stock moves through."

Note (a re-saved row): a row's derived `packing_type`, `packets_counted`, `finished_goods_location_id` and `packaging_location_id` are not sent back by the screen (`serverDerived`), so they follow the product on every save. `product_id` and `of_id` are sent back; the screen clears `of_id` when the product changes (Task 6).

- [ ] **Step 6: Update the two old tests** in `test_packing_derivation_integration.py`.

Replace `test_a_row_with_neither_run_nor_of_is_refused_on_save` with:

```python
def test_a_row_with_no_production_on_the_shift_is_refused_on_save(db, env):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="night"))["id"]
    refused = _save_packing(service, env, shift_id, [{"carton_quantity": 3}])
    assert isinstance(refused, Err) and refused.code == "PRODUCTION_FIRST"
```

Replace `test_submitting_needs_the_run` with:

```python
def test_submitting_needs_a_product(db, env):
    service, shift_id, of_id, _ = _shift_with_run(db, env)
    db.execute("UPDATE production.work_orders SET product_id = NULL WHERE id = %s", (of_id,))
    _ok(_save_packing(service, env, shift_id, [{"of_id": of_id, "packets_counted": 10, "finished_goods_location_id": env["fg"]}]))
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "PRODUCT_REQUIRED"
```

- [ ] **Step 7: Run both files and the shift suites, expect PASS**

Run: `... -m pytest modules/production/api/test_packing_product_integration.py modules/production/api/test_packing_derivation_integration.py modules/production/api/test_shift_service_integration.py -q` (use `modules/production/api/test_shift_*_integration.py` if that file name differs)
Expected: all pass. If another test still expects `RUN_REQUIRED` or a run-only OF, fix its expectation to the new rule, never the rule.

---

### Task 4: Stock, DLC lot and stamping use the row's product

**Files:**
- Create: `backend/modules/production/api/report_product.py`
- Modify: `backend/modules/production/api/legacy_report_ledger.py` (`_PACKING_COLUMNS` ~37-44, `_finished_goods_store` ~73-90)
- Modify: `backend/modules/production/api/production_report_service.py` (~619-640, ~720-737, ~1132-1146)
- Modify: `backend/modules/production/api/conditionnement_service.py` (~160-169)
- Modify: `backend/modules/production/api/shift_validation_service.py` (`validate_shift`, ~98-103)
- Test: `backend/modules/production/api/test_packing_product_validation_integration.py`

**Interfaces:**
- Consumes: Tasks 1 and 3.
- Produces: `finished_product_of_report(connection, *, tenant_id: str, report_id: str) -> str | None` (the packing report's own product, else its OF's); `stamp_order_products(connection, *, tenant_id: str, shift_report_id: str) -> None` (an OF with no product takes its first packing row's product, only ever when null). Validating posts each packing row's finished goods under that row's product; reversing undoes each; a lot's DLC registers under the row's product.

- [ ] **Step 1: Write the failing tests** (new file `test_packing_product_validation_integration.py`)

```python
"""Validating a shift with two products posts each under its own product and stamps the order."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "packing-product-validation-test"
DAY = datetime.date(2030, 9, 12)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor, uom, small, big, semolina, silo, fg_small, fg_big, work_center = (str(ULID()) for _ in range(9))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((small, "PV-200"), (big, "PV-500"), (semolina, "PV-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    for location_id, code in ((silo, "PV-SILO"), (fg_small, "PV-FG-200"), (fg_big, "PV-FG-500")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (location_id, TENANT, code, code))
    db.execute("UPDATE core.products SET net_weight_grams = 200, packets_per_carton = 24, default_location_id = %s WHERE id = %s", (fg_small, small))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg_big, big))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'PV-WC', 'Line')", (work_center, TENANT))
    for stage in ("versement", "extrusion", "conditionnement"):
        db.execute(
            "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, production_stage) VALUES (%s, %s, %s, %s, %s, %s)",
            (str(ULID()), TENANT, work_center, f"PV-{stage}", stage, stage),
        )
    for product_id in (small, big):
        ProductClassificationService(db).set_classification(tenant_id=TENANT, actor_id=actor, product_id=product_id, category="finished_good", packaging_format="packet")
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=silo, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "small": small, "big": big, "semolina": semolina, "silo": silo, "fg_small": fg_small, "fg_big": fg_big, "work_center": work_center}


def _on_hand(db, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def _two_product_shift(db, env):
    """One OF with no product, one run, and a packing row for each of two products."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [{
        "of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["silo"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["silo"]}],
    }]}))
    filled = {"packing": {"rows": [
        {"product_id": env["big"], "packets_counted": 120, "lot_number": "PV-L1"},
        {"product_id": env["small"], "packets_counted": 240, "lot_number": "PV-L2"},
    ]}}
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        elif key in filled:
            _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    return shift_id, of_id


def test_each_product_is_posted_under_its_own_product(db, env):
    shift_id, _ = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert _on_hand(db, env["big"], env["fg_big"]) == 120
    assert _on_hand(db, env["small"], env["fg_small"]) == 240


def test_reversing_takes_each_product_back_out(db, env):
    shift_id, _ = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="test"))
    assert _on_hand(db, env["big"], env["fg_big"]) == 0
    assert _on_hand(db, env["small"], env["fg_small"]) == 0


def test_the_first_validation_stamps_an_order_that_has_no_product(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    assert db.execute("SELECT product_id FROM production.work_orders WHERE id = %s", (of_id,)).fetchone()[0] is None
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert db.execute("SELECT product_id FROM production.work_orders WHERE id = %s", (of_id,)).fetchone()[0] == env["big"]  # its first row


def test_a_product_already_on_the_order_is_never_overwritten(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    db.execute("UPDATE production.work_orders SET product_id = %s WHERE id = %s", (env["small"], of_id))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert db.execute("SELECT product_id FROM production.work_orders WHERE id = %s", (of_id,)).fetchone()[0] == env["small"]
    assert _on_hand(db, env["big"], env["fg_big"]) == 120  # the row still posts under its own product
```

- [ ] **Step 2: Run, expect FAIL** (stock lands under a null/other product or validation errors on the OF's missing product)

Run: `... -m pytest modules/production/api/test_packing_product_validation_integration.py -q`

- [ ] **Step 3: Create `report_product.py`**

```python
"""The finished product a packing report is about.

A packing report names its own product because one work order can pack several (a PC mold
change starts a new product on the same order). An old report that names none falls back to its
work order's product. Everything that posts stock or judges a packaging variance asks here
instead of reading `work_orders.product_id` directly.
"""
from __future__ import annotations

import psycopg


def finished_product_of_report(connection: psycopg.Connection, *, tenant_id: str, report_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT COALESCE(c.product_id, w.product_id)
        FROM production.production_reports r
        JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
        LEFT JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
        WHERE r.id = %s AND r.tenant_id = %s
        """,
        (report_id, tenant_id),
    ).fetchone()
    return row[0] if row else None


def stamp_order_products(connection: psycopg.Connection, *, tenant_id: str, shift_report_id: str) -> None:
    """An order with no product yet takes the product of its first packing row in this shift.

    Set only when empty and never changed afterwards: the order's own product is the "primary"
    one for readers that still need exactly one. The products it really packed are the rows'.
    """
    connection.execute(
        """
        UPDATE production.work_orders w
        SET product_id = first_row.product_id
        FROM (
            SELECT DISTINCT ON (p.of_id) p.of_id, p.product_id
            FROM production.shift_packing_rows p
            WHERE p.tenant_id = %s AND p.shift_report_id = %s AND p.product_id IS NOT NULL
            ORDER BY p.of_id, p.line_order, p.id
        ) first_row
        WHERE w.id = first_row.of_id AND w.tenant_id = %s AND w.product_id IS NULL
        """,
        (tenant_id, shift_report_id, tenant_id),
    )
```

- [ ] **Step 4: The ledger writes the row's product.** In `legacy_report_ledger.py` add `"product_id"` to `_PACKING_COLUMNS` (after `"waste_carton_quantity"`), and change `_finished_goods_store` so the "is this the product's own store" comparison uses the row's product:

```python
    product_id = row.get("product_id") or (
        connection.execute(
            "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s", (row["of_id"], tenant_id)
        ).fetchone()
        or (None,)
    )[0]
    product = CoreService(connection).get_product(tenant_id, product_id) if product_id else None
    return line_store if product is not None and stored == product.default_location_id else stored
```

(replacing the old `product_id = connection.execute(...)` / `product = ...` / `return ...` three statements, keeping the earlier `if line_store is None` and `if not stored` returns).

- [ ] **Step 5: Use the helper at the three stock sites in `production_report_service.py`.** Add `from modules.production.api.report_product import finished_product_of_report` at the top. In each of the three places that do `work_order = SELECT product_id ... FROM production.work_orders` for a conditionnement report (validate ~621, reverse ~722, correct ~1134), keep the existing existence check where there is one and pass the helper's value instead of `work_order[0]`:

```python
finished_product_id = finished_product_of_report(self._connection, tenant_id=tenant_id, report_id=report_id)  # header.id in the reverse path
```

then use `finished_product_id` for `freeze_packaging_parameters(..., product_id=...)` (validate) and for `finished_product_id=` of `post_conditionnement_report` in all three. (In the reverse path the report id variable is `header.id`.)

- [ ] **Step 6: The DLC lot.** In `conditionnement_service.register_dlc_lot`, replace the `product_row = connection.execute("SELECT product_id FROM production.work_orders ...")` block (and its `NOT_FOUND` branch) with:

```python
    product_id = finished_product_of_report(connection, tenant_id=tenant_id, report_id=header.id)
    if product_id is None:
        return Err("NOT_FOUND", f"work order {header.of_id} not found or has no product")
```

and pass `product_id=product_id` to `register_lot`. Add the import from `report_product`.

- [ ] **Step 6b: Stamp before materialising.** In `shift_validation_service.validate_shift`, inside `with self._connection.transaction():` and before `materialised = materialize_shift(...)`:

```python
                stamp_order_products(self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id)
```

(add the import from `report_product`).

- [ ] **Step 7: Run the new tests and the existing validation suites, expect PASS**

Run: `... -m pytest modules/production/api/test_packing_product_validation_integration.py modules/production/api/test_shift_wiring_integration.py modules/production/api/test_shift_validation_integration.py modules/production/api/test_conditionnement_flow_integration.py -q`
Expected: all pass (the wiring test `test_validating_moves_stock_through_the_derived_stores` still gets 120 under the OF's product because Task 1's backfill and Task 3's fill make the row's product equal to it).

---

### Task 5: Readers that group or judge by product

**Files:**
- Modify: `backend/modules/production/api/packaging_variance_service.py` (`for_report` ~206-217, `for_of` ~274-358, `by_product` ~379-530)
- Modify: `backend/modules/production/api/finished_goods_service.py` (~21-59), `stock_release_service.py` (~54-78)
- Modify: `backend/modules/production/api/of_consolidation_service.py` (~78-110)
- Modify: `backend/modules/production/api/router.py` (the variance route, only if it forwards args; otherwise untouched)
- Test: `backend/modules/production/api/test_packing_product_validation_integration.py` (extend)

**Interfaces:**
- Consumes: Task 4's validated two-product shift.
- Produces: `PackagingVarianceService.by_product(*, tenant_id, date_from=None, date_to=None, of_id=None)` (groups by the report's own product; an OF with several products in the result contributes no tonnage to any product); `for_of` returns `{"scope": "work_order", "of_id", "of_reference", "multi_product": True, "products": [<by_product entries for this OF>]}` when the OF's validated packing reports cover more than one product, otherwise its old shape; consolidation output gains `"product_ids": list[str]` (distinct products of the OF's validated packing reports, first appearance first; `[product_id]` of the OF when there are none and it has one; else `[]`).

- [ ] **Step 1: Write the failing tests** (append to `test_packing_product_validation_integration.py`; add imports `from modules.production.api.packaging_variance_service import PackagingVarianceService` and `from modules.production.api.of_consolidation_service import OfConsolidationService`)

```python
def _validated(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return of_id


def test_the_product_view_groups_by_the_rows_product(db, env):
    _validated(db, env)
    by_product = {p["product_id"]: p for p in PackagingVarianceService(db).by_product(tenant_id=TENANT)}
    assert set(by_product) == {env["big"], env["small"]}
    assert by_product[env["big"]]["counted_packets"] == 120 and by_product[env["small"]]["counted_packets"] == 240
    assert by_product[env["big"]]["net_weight_grams"] == 500 and by_product[env["small"]]["net_weight_grams"] == 200


def test_a_two_product_order_returns_one_breakdown_per_product(db, env):
    of_id = _validated(db, env)
    result = _ok(PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of_id))
    assert result["multi_product"] is True
    assert {p["product_id"] for p in result["products"]} == {env["big"], env["small"]}
    assert all(p["tonnage"] is None for p in result["products"])  # an order's tonnage cannot be split by product


def test_a_one_product_order_keeps_its_old_shape(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    db.execute("UPDATE production.shift_packing_rows SET product_id = %s WHERE shift_report_id = %s", (env["big"], shift_id))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    result = _ok(PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of_id))
    assert "multi_product" not in result and result["product_id"] == env["big"]


def test_consolidation_lists_every_product_of_the_order(db, env):
    of_id = _validated(db, env)
    consolidation = _ok(OfConsolidationService(db).consolidate(tenant_id=TENANT, of_id=of_id))
    assert consolidation["product_ids"] == [env["big"], env["small"]]
```

- [ ] **Step 2: Run, expect FAIL** (`by_product` groups both under the OF's one product; `for_of` has no `multi_product`; no `product_ids`)

- [ ] **Step 3: `by_product` by the row's product, with an optional OF filter.** In `packaging_variance_service.py`:

Change the signature to `def by_product(self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None, of_id: str | None = None) -> list[dict]:` and, after the two date clauses, add:

```python
        if of_id:
            clauses.append("r.of_id = %s")
            params.append(of_id)
```

In the SELECT, replace `SELECT w.product_id, r.of_id, w.reference, r.id, ...` with `SELECT COALESCE(c.product_id, w.product_id) AS product_id, r.of_id, w.reference, r.id, ...` and `ORDER BY w.product_id, r.report_date` with `ORDER BY 1, r.report_date`. Track which products each OF covers: right after `grouped: dict[str, dict] = {}` add `products_of_order: dict[str, set[str]] = {}`, and inside the row loop (after the `bucket["of_ids"].add(of_id)` line) add `products_of_order.setdefault(of_id, set()).add(product_id)`. In the tonnage loop (`for of_id in bucket["of_ids"]:`), rename the loop variable to `order_id` and skip an order whose tonnage cannot be attributed:

```python
            for order_id in bucket["of_ids"]:
                rejected = self._rejected(tenant_id=tenant_id, of_id=order_id, product_id=product_id)
                subtractable += rejected["subtractable"]
                undecided += rejected["undecided"]
                quality_available = quality_available and rejected["available"]

                # An order that packed several products declares one tonnage for all of them; it
                # cannot be split, so it is attributed to none of them rather than to each.
                if len(products_of_order[order_id]) > 1:
                    continue
                of_tonnage = self._daily_tonnage(tenant_id=tenant_id, of_id=order_id, date_from=date_from, date_to=date_to)
                if of_tonnage is not None:
                    tonnage_known = True
                    tonnage_total += of_tonnage
```

- [ ] **Step 4: `for_report` reads the report's product.** In `for_report`'s SELECT replace `w.product_id` (second column) with `COALESCE(c.product_id, w.product_id)`.

- [ ] **Step 5: `for_of` for several products.** After the `work_order` lookup and `product_id, reference = work_order`, insert:

```python
        packed_products = [
            row[0]
            for row in self._connection.execute(
                f"""
                SELECT DISTINCT COALESCE(c.product_id, w.product_id)
                FROM production.production_reports r
                JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
                JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
                WHERE r.tenant_id = %s AND r.of_id = %s AND r.report_type = 'conditionnement' AND r.{_VALIDATED}
                """,
                (tenant_id, of_id),
            ).fetchall()
            if row[0] is not None
        ]
        if len(packed_products) > 1:
            return Ok(
                {
                    "scope": "work_order",
                    "of_id": of_id,
                    "of_reference": reference,
                    "multi_product": True,
                    "products": self.by_product(tenant_id=tenant_id, of_id=of_id),
                }
            )
```

- [ ] **Step 6: Finished goods and stock release group by the row's product.** In `finished_goods_service.list_finished_goods`: change the clause `"w.product_id IS NOT NULL"` to `"COALESCE(c.product_id, w.product_id) IS NOT NULL"`, the select column `w.product_id,` to `COALESCE(c.product_id, w.product_id) AS product_id,`, and `GROUP BY w.product_id, w.product_type` to `GROUP BY COALESCE(c.product_id, w.product_id), w.product_type`. In `stock_release_service._packed_on`, change `SELECT w.product_id, c.carton_quantity, ...` to `SELECT COALESCE(c.product_id, w.product_id), c.carton_quantity, ...`.

- [ ] **Step 7: Consolidation lists the products.** In `of_consolidation_service.consolidate`, right after the `reference, product_id, ... = work_order` unpack, add:

```python
        packed_products = [
            row[0]
            for row in self._connection.execute(
                """
                SELECT COALESCE(c.product_id, w.product_id)
                FROM production.production_reports r
                JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
                JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
                WHERE r.tenant_id = %s AND r.of_id = %s AND r.report_type = 'conditionnement' AND r.status = 'validated'
                GROUP BY 1
                ORDER BY MIN(r.report_date), MIN(r.created_at)
                """,
                (tenant_id, of_id),
            ).fetchall()
            if row[0] is not None
        ]
        product_ids = packed_products or ([product_id] if product_id else [])
```

and beside `"product_id": product_id,` in the returned dict (~line 108) add `"product_ids": product_ids,`. If this method's date-order differs (validated report date), keep the ordering expression as written: it must put the product of the earliest packing report first.

- [ ] **Step 8: Run the new tests and the wider production suite, expect PASS**

Run: `... -m pytest modules/production -q`
Expected: all pass. Anything that fails because it seeded a report on an OF product and now reads it through `COALESCE`, fix by checking the seed carries `product_id` on the old detail row (the column is nullable, so the OF's product is the fallback and existing seeds are unaffected).

---

### Task 6: The shift screen: Produit, OF and the type

**Files:**
- Create: `frontend/src/features/production/shift/packingType.ts`
- Modify: `frontend/src/features/production/shift/sectionConfig.ts`
- Modify: `frontend/src/features/production/shift/ShiftGrid.tsx` (`Cell` readonly case ~217; `setCell` ~333)
- Modify: `frontend/src/features/production/shift/useShiftReferenceData.ts`

**Interfaces:**
- Produces: `packingTypeLabel(netWeightGrams, packagingFormat): string`; `OptionSource` gains `"finishedProducts" | "shiftOrders" | "packingTypes"`; `Column` gains `valueFor?: (row: Row, options: OptionMap) => string | null` and `resets?: readonly string[]`.

- [ ] **Step 1: `packingType.ts`**

```ts
const FORMAT_NAME: Record<string, string> = { packet: "Sachet", carton: "Carton", sac: "Sac" };

/**
 * "Sachet 500 g": the classified packaging format and the net weight, as the paper fiche writes it.
 * Mirrors the server's rule so the type shows the moment a product is picked; the server's own
 * value replaces it on the next load.
 */
export function packingTypeLabel(netWeightGrams: number | null | undefined, packagingFormat: string | null | undefined): string {
  const name = FORMAT_NAME[packagingFormat ?? ""];
  const grams = netWeightGrams && netWeightGrams > 0 ? Number(netWeightGrams) : null;
  const weight = grams === null ? null : `${Number.isInteger(grams) ? grams : Number(grams.toPrecision(12))} g`;
  return [name, weight].filter(Boolean).join(" ");
}
```

- [ ] **Step 2: `sectionConfig.ts`.** Add `"finishedProducts" | "shiftOrders" | "packingTypes"` to `OptionSource`. In `Column` add:

```ts
  /** For a read-only cell: what to show from the row as it is being edited, before the server has derived it. */
  valueFor?: (row: Row, options: OptionMap) => string | null;
  /** Fields cleared when this cell changes, so the server derives them again from the new value. */
  resets?: readonly string[];
```

Add beside `moldsForOrder`:

```ts
/** The packing type of the row's chosen product, read from the option list built from the products. */
export function packingTypeFor(row: Row, options: OptionMap): string | null {
  return options.packingTypes.find((option) => option.value === row.product_id)?.label ?? null;
}
```

In the `packing` section: add `"run_id"` to the part's `serverDerived` (`["run_id", "packing_type", "packets_counted", "finished_goods_location_id", "packaging_location_id"]`) and replace the first three columns (`run_id`, `lot_number`, `packing_type`) with:

```ts
          { ...pick("product_id", L("Product", "Produit"), "finishedProducts", true), resets: ["of_id"] },
          pick("of_id", L("Work order", "OF"), "shiftOrders"),
          text("lot_number", L("Lot", "N° lot")),
          { ...derived("packing_type", L("Packing type", "Type de conditionnement")), valueFor: packingTypeFor },
```

Change the section's `hint` to `"One row per lot packed: the product, what it used and what it made."` / `"Une ligne par lot conditionné : le produit, ce qu'il a consommé, ce qu'il a produit."`.

- [ ] **Step 3: `ShiftGrid.tsx`.** In `Cell`'s `case "readonly":` replace `{asText(value) || "—"}` with:

```tsx
          {(column.valueFor && row ? column.valueFor(row, options) : null) || asText(value) || "—"}
```

Replace `setCell` with:

```tsx
  const setCell = (index: number, key: string, value: unknown) => {
    const cleared = Object.fromEntries((columns.find((column) => column.key === key)?.resets ?? []).map((field) => [field, null]));
    onChange(rows.map((row, i) => (i === index ? { ...row, ...cleared, _fresh: false, [key]: value } : row)));
  };
```

- [ ] **Step 4: `useShiftReferenceData.ts`.** Add `import { packingTypeLabel } from "./packingType";`. In `buildOptions`, after `const itemsOfKind = ...` add:

```ts
      // Products of a packing row: finished goods only (every product while classifications cannot be read).
      const finishedProducts = classifications.data
        ? productList.filter((p) => classOf.get(p.id)?.category === "finished_good").map(asOption)
        : productList.map(asOption);
      // Only orders that have a production row on this shift can be the OF of a lot.
      const runOrderIds = new Set(rowsOf("runs", "runs").map((r) => String(r.of_id)));
```

and in the returned object add:

```ts
        finishedProducts,
        shiftOrders: all.filter((o) => runOrderIds.has(o.id)).map(orderOption),
        packingTypes: productList
          .map((p) => ({ value: p.id, label: packingTypeLabel(p.net_weight_grams, classOf.get(p.id)?.packaging_format) }))
          .filter((option) => option.label),
```

- [ ] **Step 5: Typecheck**

Run (in `frontend/`): `npx tsc -b --force`
Expected: no errors. If `OptionMap` consumers elsewhere build the map by hand, add the three new keys (`[]`) there.

---

### Task 7: The OF page shows a per-product variance

**Files:**
- Modify: `frontend/src/features/production/api.ts` (~1697-1706, ~1729-1734)
- Modify: `frontend/src/features/production/WorkOrderDetailsPage.tsx` (~443-457, `productUom` ~237)
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: Task 5's `for_of` shape and `product_ids`.
- Produces: `getWorkOrderPackagingVariance` returns `WorkOrderPackagingVariance | MultiProductOrderVariance`; `OfConsolidation` has `product_ids: string[]`.

- [ ] **Step 1: Types.** In `api.ts` add after `WorkOrderPackagingVariance`:

```ts
/** An order whose validated packing reports cover several products: one breakdown per product, no order-wide figure. */
export interface MultiProductOrderVariance {
  scope: "work_order";
  multi_product: true;
  of_id: string;
  of_reference: string;
  products: ProductPackagingVariance[];
}
```

Change `getWorkOrderPackagingVariance` to `apiFetch<WorkOrderPackagingVariance | MultiProductOrderVariance>(...)`. In `OfConsolidation` add `/** Every product the order's validated packing reports cover; the order's own when it has none yet. */ product_ids: string[];` next to `product_id`.

- [ ] **Step 2: i18n.** Add to `frontend/src/lib/i18n.tsx` in both language tables (next to the other `production.packagingVariance.*` keys): `"production.packagingVariance.perProduct": "Per product"` (en) and `"production.packagingVariance.perProduct": "Par produit"` (fr).

- [ ] **Step 3: The page.** Replace the `{packagingVariance && ( <Card>...</Card> )}` block (~443-457) with:

```tsx
      {packagingVariance && (
        <Card>
          <CardHeader>
            <CardTitle>{t("production.ofDetails.packagingVariance.title")}</CardTitle>
            {"multi_product" in packagingVariance && (
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.packagingVariance.perProduct")}</p>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {"multi_product" in packagingVariance ? (
              packagingVariance.products.map((entry) => (
                <div key={entry.product_id} className="space-y-2">
                  <p className="text-sm font-medium">{productName(entry.product_id)}</p>
                  <PackagingVariancePanel variance={entry} net dispositionSummary={dispositionSummary} />
                </div>
              ))
            ) : (
              <>
                <PackagingVariancePanel variance={packagingVariance} net dispositionSummary={dispositionSummary} />
                {packagingVariance.parameters_varied && (
                  <p className="text-xs text-muted-foreground">{t("production.packagingVariance.parametersVaried")}</p>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}
```

Note the existing comment above the block ("The écart net. Read-only by decision 22 ...") stays.

- [ ] **Step 4: Packet unit across products.** Replace `const productUom = productUnit(order?.product_id, products, uoms);` with the common unit of every product the order covers, bare when they differ:

```tsx
  const orderUnits = new Set(
    (consolidation?.product_ids?.length ? consolidation.product_ids : order?.product_id ? [order.product_id] : []).map(
      (id) => productUnit(id, products, uoms) ?? "",
    ),
  );
  const productUom = orderUnits.size === 1 && [...orderUnits][0] ? [...orderUnits][0] : null;
```

- [ ] **Step 5: Typecheck**

Run (in `frontend/`): `npx tsc -b --force`
Expected: no errors.

---

### Task 8: Verify end to end

**Files:** none changed here (fix what the checks show, in the file that caused it).

- [ ] **Step 1: Backend suites**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules core -q`
Expected: every test passes (954 before this milestone, plus the new ones). Report the exact counts.

- [ ] **Step 2: Typecheck**: `cd frontend && npx tsc -b --force` → no errors.

- [ ] **Step 3: Drive the screen in a real browser, without saving anything.** Use the headless-Chrome CDP recipe from `feedback_verify_frontend_in_repo.md` (Playwright MCP is often locked). Open `/production?tab=shift-report`, wait until "Add a lot" appears (the dev box is slow, up to about 40 s), open the Packing section and add a lot. Confirm from the DOM: the first column header is "Product"/"Produit", its select lists finished-good products (not empty), the "Work order" select exists, and picking a product fills "Packing type" immediately (for example "Sachet 500 g" for a 500 g product). Screenshot it and compare with the client's screenshot.

- [ ] **Step 4: Check the read-only paths against the dev data.** `GET /production/work-orders/<an existing OF id>/packaging-variance` and `/consolidation` (login as `demo@sonalim-erp.local`): both still answer 200 for an existing one-product OF, `product_ids` has one entry, and the variance keeps its old shape (no `multi_product`).

- [ ] **Step 5: Report** the counts, the screenshot path and anything unverified. Do not claim more than was run.

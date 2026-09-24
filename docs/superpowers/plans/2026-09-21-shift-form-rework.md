# Shift Form Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the shift report screen and its backend so lists show only the right items, dropped fields are derived from data the system already holds, and a validated silo reading drives machine status.

**Architecture:** Pure derivation rules live in two small domain modules; `shift_sections.save_section_rows` calls a packing derivation service so the stored row is complete before submit; the legacy ledger fills a machine by stage; validation applies the silo rule through Maintenance's own `EquipmentService`. The frontend stays config-driven: new option sources and an `optionsFor` hook on a column, plus a read-only cell.

**Tech Stack:** Python 3 / FastAPI / psycopg / pytest against the real dev Postgres; React + TypeScript + TanStack Query (no frontend test runner: `npx tsc -b --force` and a real browser).

**Spec:** `docs/superpowers/specs/2026-09-21-shift-form-rework-design.md` (this plan corrects a few points of it, listed in Task 11).

## Global Constraints

- Commands run from `D:\mahmoud repo\Sonalim_ERP\backend` (backend) or `...\frontend` (frontend). Backend tests: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest <path> -q`. Domain tests need no database.
- **Do not commit** unless the user asks; the branch already holds a large uncommitted body of work. Leave changes in the working tree.
- Frontend typecheck is `npx tsc -b --force` only (plain `tsc -b` gives false passes). Browser checks use the demo login recipe in memory (`demo@sonalim-erp.local` / `demo1234`, seed `sessionStorage["sonalim-erp.session"]`), backend :8000, Vite :5173. Never save data in the owner's shifts.
- No invented thresholds or name matching: every list comes from a recorded field (`status`, `is_regrind`, classification `category` / `packaging_kind`, mold `type`, product `default_location_id`).
- Production may hold only opaque `equipment_id`s; it reads and changes machines through `modules.maintenance.api.equipment_service.EquipmentService`.
- Values (exact): packaging kinds `film | carton | bobine | scotch | ruban`; silo line states `running | stopped`; packet checks `good | not_good`; machine statuses `operational | down | maintenance`; silo sides `production | packing`; stages `versement | extrusion | conditionnement`.
- Shift screen strings go in `frontend/src/features/production/shift/shiftText.ts` style `L("English", "Français")`; the Classifications tab uses the app dictionary `frontend/src/lib/i18n.tsx` (keys in both the English and French blocks).
- Migrations are applied when the backend starts. To apply now: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`.
- Existing dev data: 52 products, all with `default_location_id` and a category (30 `finished_good`, 22 `raw_material`); no `packaging_component` yet.

---

## File map

Backend, create:
- `modules/production/domain/packing_derivation.py`: `packing_type_label`, `pick_packaging_location`.
- `modules/production/domain/line_machines.py`: `pick_stage_machine`, `silo_machine_changes`.
- `modules/production/api/packing_derivation_service.py`: `derive_packing_rows`.
- `modules/production/api/silo_machine_status.py`: `apply_silo_machine_status`.
- `modules/production/migrations/0052_production_packaging_kind.sql`, `0053_production_silo_line_state_codes.sql`.
- Tests: `domain/test_packing_derivation.py`, `domain/test_line_machines.py`, `api/test_packaging_kind_integration.py`, `api/test_packing_derivation_integration.py`, `api/test_shift_machine_integration.py`.

Backend, modify: `domain/product_classification.py`, `api/product_classification_service.py`, `api/router.py`, `api/shift_sections.py`, `domain/production_report.py`, `api/legacy_report_ledger.py`, `api/shift_validation_service.py`, `domain/test_waste_lines.py`, and any existing tests that submit a packing row without a run (Task 3).

Frontend, modify (all under `frontend/src`): `features/production/api.ts`, `features/production/ProductClassificationsTab.tsx`, `lib/i18n.tsx`, `features/production/shift/{sectionConfig.ts,ShiftGrid.tsx,useShiftReferenceData.ts}`.

---

### Task 1: Pure derivation rules

**Files:**
- Create: `backend/modules/production/domain/packing_derivation.py`, `backend/modules/production/domain/line_machines.py`
- Test: `backend/modules/production/domain/test_packing_derivation.py`, `backend/modules/production/domain/test_line_machines.py`

**Interfaces:**
- Produces: `packing_type_label(*, packaging_format: str | None, net_weight_grams: float | None) -> str | None`; `pick_packaging_location(locations: Iterable[str | None]) -> tuple[str | None, bool]` (location, conflict); `pick_stage_machine(machines: Sequence[tuple[str, str | None, str]], stage: str) -> str | None` (machines are `(id, production_stage, status)`); `silo_machine_changes(*, side: str, line_state: str | None, machines: Sequence[tuple[str, str | None, str]]) -> list[tuple[str, str]]` (`(machine_id, new_status)`).

- [ ] **Step 1: Write the failing tests**

`backend/modules/production/domain/test_packing_derivation.py`:

```python
from modules.production.domain.packing_derivation import packing_type_label, pick_packaging_location


def test_type_label_reads_the_format_and_the_weight():
    assert packing_type_label(packaging_format="packet", net_weight_grams=500) == "Sachet 500 g"
    assert packing_type_label(packaging_format="carton", net_weight_grams=4540.0) == "Carton 4540 g"
    assert packing_type_label(packaging_format="sac", net_weight_grams=0) == "Sac"
    assert packing_type_label(packaging_format=None, net_weight_grams=250.5) == "250.5 g"
    assert packing_type_label(packaging_format=None, net_weight_grams=None) is None


def test_one_shared_store_is_picked():
    assert pick_packaging_location(["store-a", "store-a", None]) == ("store-a", False)


def test_no_default_store_is_not_a_conflict():
    assert pick_packaging_location([None, None]) == (None, False)
    assert pick_packaging_location([]) == (None, False)


def test_different_stores_are_a_conflict():
    assert pick_packaging_location(["store-a", "store-b"]) == (None, True)
```

`backend/modules/production/domain/test_line_machines.py`:

```python
from modules.production.domain.line_machines import pick_stage_machine, silo_machine_changes

MACHINES = [
    ("p1", "versement", "operational"),
    ("p2", "extrusion", "operational"),
    ("p3", "conditionnement", "down"),
    ("p4", None, "operational"),
]


def test_a_stage_with_exactly_one_machine_names_it():
    assert pick_stage_machine(MACHINES, "extrusion") == "p2"


def test_a_stage_with_none_or_several_machines_names_nothing():
    assert pick_stage_machine(MACHINES, "missing") is None
    assert pick_stage_machine([*MACHINES, ("p5", "extrusion", "operational")], "extrusion") is None


def test_a_stopped_production_side_takes_versement_and_extrusion_down():
    assert silo_machine_changes(side="production", line_state="stopped", machines=MACHINES) == [
        ("p1", "down"),
        ("p2", "down"),
    ]


def test_a_running_packing_side_brings_conditionnement_back():
    assert silo_machine_changes(side="packing", line_state="running", machines=MACHINES) == [("p3", "operational")]


def test_maintenance_and_machines_already_there_are_left_alone():
    machines = [("a", "extrusion", "maintenance"), ("b", "versement", "down")]
    assert silo_machine_changes(side="production", line_state="stopped", machines=machines) == []


def test_an_unknown_or_missing_state_changes_nothing():
    assert silo_machine_changes(side="production", line_state=None, machines=MACHINES) == []
    assert silo_machine_changes(side="production", line_state="En marche", machines=MACHINES) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/domain/test_packing_derivation.py modules/production/domain/test_line_machines.py -q`
Expected: FAIL with `ModuleNotFoundError` for both new modules.

- [ ] **Step 3: Write the implementation**

`backend/modules/production/domain/packing_derivation.py`:

```python
"""Rules for the figures a packing row is derived from instead of typed."""
from __future__ import annotations

from collections.abc import Iterable

_FORMAT_NAME = {"packet": "Sachet", "carton": "Carton", "sac": "Sac"}


def packing_type_label(*, packaging_format: str | None, net_weight_grams: float | None) -> str | None:
    """'Sachet 500 g': the product's packaging format and net weight, as the paper fiche writes it."""
    name = _FORMAT_NAME.get(packaging_format or "")
    weight = None
    if net_weight_grams and net_weight_grams > 0:
        grams = float(net_weight_grams)
        weight = f"{int(grams)} g" if grams == int(grams) else f"{grams:g} g"
    return " ".join(part for part in (name, weight) if part) or None


def pick_packaging_location(locations: Iterable[str | None]) -> tuple[str | None, bool]:
    """The one store all of a row's packaging comes from: `(location, conflict)`.

    Stock posting draws every packaging item of a row from a single store, so items with
    different default stores cannot be posted as one row: that is a conflict, not a guess.
    """
    found = {location for location in locations if location}
    if len(found) == 1:
        return next(iter(found)), False
    return None, len(found) > 1
```

`backend/modules/production/domain/line_machines.py`:

```python
"""Which machine of a line a stage names, and what a silo reading does to machine status."""
from __future__ import annotations

from collections.abc import Sequence

# (machine id, production stage, status) as Maintenance's registry records them.
Machine = tuple[str, str | None, str]

# The silo has two sides; each side reads the stages that work on it.
SIDE_STAGES = {"production": ("versement", "extrusion"), "packing": ("conditionnement",)}
STATE_TARGET = {"stopped": "down", "running": "operational"}


def pick_stage_machine(machines: Sequence[Machine], stage: str) -> str | None:
    """The machine at `stage`, only when the line has exactly one there."""
    at_stage = [machine_id for machine_id, machine_stage, _ in machines if machine_stage == stage]
    return at_stage[0] if len(at_stage) == 1 else None


def silo_machine_changes(*, side: str, line_state: str | None, machines: Sequence[Machine]) -> list[tuple[str, str]]:
    """`(machine_id, new_status)` for the machines a silo reading moves.

    A machine in `maintenance` belongs to Maintenance and is left alone, as is one already
    in the target status. An unknown state (or none) changes nothing.
    """
    target = STATE_TARGET.get(line_state or "")
    stages = SIDE_STAGES.get(side, ())
    if target is None:
        return []
    return [
        (machine_id, target)
        for machine_id, stage, status in machines
        if stage in stages and status not in ("maintenance", target)
    ]
```

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/domain/test_packing_derivation.py modules/production/domain/test_line_machines.py -q`
Expected: 10 passed.

---

### Task 2: `packaging_kind` on classifications

**Files:**
- Create: `backend/modules/production/migrations/0052_production_packaging_kind.sql`
- Modify: `backend/modules/production/domain/product_classification.py`, `backend/modules/production/api/product_classification_service.py`, `backend/modules/production/api/router.py` (`SetProductClassificationRequest` ~line 156, `set_product_classification` ~line 1009, `_serialize_classification` ~line 1182)
- Test: `backend/modules/production/domain/test_product_classification.py` (append), `backend/modules/production/api/test_packaging_kind_integration.py` (create)

**Interfaces:**
- Produces: `ProductClassification.packaging_kind: str | None = None`; `validate_classification(category, is_regrind, packaging_format=None, is_water=False, packaging_kind=None)`; `ProductClassificationService.set_classification(..., packaging_kind: str | None = None)`; the API field `packaging_kind` on POST/GET `/production/product-classifications`. Codes: `PACKAGING_KIND_INVALID`, `INVALID_PACKAGING_KIND`.

- [ ] **Step 1: Write the failing tests**

Append to `domain/test_product_classification.py`:

```python
def test_packaging_kind_is_only_for_packaging_components():
    ok = validate_classification("packaging_component", False, packaging_kind="film")
    assert isinstance(ok, Ok)
    wrong_category = validate_classification("raw_material", False, packaging_kind="film")
    assert isinstance(wrong_category, Err) and wrong_category.code == "PACKAGING_KIND_INVALID"


def test_packaging_kind_must_be_a_known_kind():
    result = validate_classification("packaging_component", False, packaging_kind="bogus")
    assert isinstance(result, Err) and result.code == "INVALID_PACKAGING_KIND"
```

Create `api/test_packaging_kind_integration.py`:

```python
"""A packaging component can be given the kind of packaging it is."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.product_classification_service import ProductClassificationService

TENANT = "packaging-kind-test"


@pytest.fixture
def env(db):
    actor, uom, product = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'PK-FILM', 'Film', %s)", (product, TENANT, uom))
    return {"actor": actor, "product": product}


def test_the_kind_is_stored_and_listed(db, env):
    service = ProductClassificationService(db)
    saved = service.set_classification(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="packaging_component", packaging_kind="film"
    )
    assert isinstance(saved, Ok) and saved.value.packaging_kind == "film"
    assert service.get_classification(TENANT, env["product"]).packaging_kind == "film"
    listed = service.list_classifications(TENANT, category="packaging_component")
    assert [c.packaging_kind for c in listed] == ["film"]


def test_the_kind_is_refused_on_other_categories(db, env):
    result = ProductClassificationService(db).set_classification(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="raw_material", packaging_kind="film"
    )
    assert isinstance(result, Err) and result.code == "PACKAGING_KIND_INVALID"


def test_reclassifying_drops_the_kind(db, env):
    service = ProductClassificationService(db)
    service.set_classification(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="packaging_component", packaging_kind="carton")
    service.set_classification(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="raw_material")
    assert service.get_classification(TENANT, env["product"]).packaging_kind is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/domain/test_product_classification.py modules/production/api/test_packaging_kind_integration.py -q`
Expected: FAIL (`unexpected keyword argument 'packaging_kind'`).

- [ ] **Step 3: Migration**

`backend/modules/production/migrations/0052_production_packaging_kind.sql`:

```sql
-- Which kind of packaging a packaging component is, so the shift screen's film, carton,
-- bobine, scotch and ruban dropdowns can each list their own items. Only meaningful for
-- category 'packaging_component' (enforced in the domain, like packaging_format).
ALTER TABLE production.product_classifications
    ADD COLUMN IF NOT EXISTS packaging_kind TEXT
    CHECK (packaging_kind IN ('film', 'carton', 'bobine', 'scotch', 'ruban'));
```

Apply it: run the `apply_all_migrations()` command from Global Constraints.

- [ ] **Step 4: Domain**

In `domain/product_classification.py`: add below `VALID_PACKAGING_FORMATS`

```python
VALID_PACKAGING_KINDS = {"film", "carton", "bobine", "scotch", "ruban"}
```

add `packaging_kind: str | None = None` as the last field of the `ProductClassification` dataclass, change the signature to

```python
def validate_classification(
    category: str,
    is_regrind: bool,
    packaging_format: str | None = None,
    is_water: bool = False,
    packaging_kind: str | None = None,
) -> Result[None]:
```

and add before the final `return Ok(None)`:

```python
    if packaging_kind is not None:
        if category != "packaging_component":
            return Err("PACKAGING_KIND_INVALID", "packaging_kind only applies to packaging_component products")
        if packaging_kind not in VALID_PACKAGING_KINDS:
            return Err("INVALID_PACKAGING_KIND", f"packaging_kind must be one of {sorted(VALID_PACKAGING_KINDS)}")
```

- [ ] **Step 5: Service**

Replace the body of `product_classification_service.py` from `def set_classification` to the end with:

```python
    def set_classification(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        product_id: str,
        category: str,
        is_regrind: bool = False,
        packaging_format: str | None = None,
        is_water: bool = False,
        packaging_kind: str | None = None,
    ) -> Result[ProductClassification]:
        validation = validate_classification(category, is_regrind, packaging_format, is_water, packaging_kind)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            INSERT INTO production.product_classifications
                (tenant_id, product_id, category, is_regrind, packaging_format, is_water, packaging_kind)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, product_id)
            DO UPDATE SET category = EXCLUDED.category, is_regrind = EXCLUDED.is_regrind,
                packaging_format = EXCLUDED.packaging_format, is_water = EXCLUDED.is_water,
                packaging_kind = EXCLUDED.packaging_kind
            """,
            (tenant_id, product_id, category, is_regrind, packaging_format, is_water, packaging_kind),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="product_classification.set",
            entity_type="product_classification",
            entity_id=product_id,
            payload={
                "category": category, "is_regrind": is_regrind, "packaging_format": packaging_format,
                "is_water": is_water, "packaging_kind": packaging_kind,
            },
        )
        return Ok(
            ProductClassification(
                product_id=product_id, category=category, is_regrind=is_regrind, packaging_format=packaging_format,
                is_water=is_water, packaging_kind=packaging_kind,
            )
        )

    def get_classification(self, tenant_id: str, product_id: str) -> ProductClassification | None:
        row = self._connection.execute(
            """
            SELECT category, is_regrind, packaging_format, is_water, packaging_kind
            FROM production.product_classifications
            WHERE tenant_id = %s AND product_id = %s
            """,
            (tenant_id, product_id),
        ).fetchone()
        if row is None:
            return None
        category, is_regrind, packaging_format, is_water, packaging_kind = row
        return ProductClassification(
            product_id=product_id, category=category, is_regrind=is_regrind, packaging_format=packaging_format,
            is_water=is_water, packaging_kind=packaging_kind,
        )

    def list_classifications(self, tenant_id: str, category: str | None = None) -> list[ProductClassification]:
        where, params = ("tenant_id = %s", (tenant_id,)) if category is None else ("tenant_id = %s AND category = %s", (tenant_id, category))
        rows = self._connection.execute(
            f"""
            SELECT product_id, category, is_regrind, packaging_format, is_water, packaging_kind
            FROM production.product_classifications
            WHERE {where}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
        return [
            ProductClassification(
                product_id=product_id, category=row_category, is_regrind=is_regrind, packaging_format=packaging_format,
                is_water=is_water, packaging_kind=packaging_kind,
            )
            for product_id, row_category, is_regrind, packaging_format, is_water, packaging_kind in rows
        ]
```

- [ ] **Step 6: Router**

In `router.py`: add `packaging_kind: str | None = None` to `SetProductClassificationRequest`; add `packaging_kind=body.packaging_kind,` to the `service.set_classification(...)` call in `set_product_classification`; add `"packaging_kind": classification.packaging_kind,` to `_serialize_classification`.

- [ ] **Step 7: Run to verify they pass, plus the existing classification tests**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/domain/test_product_classification.py modules/production/api/test_packaging_kind_integration.py modules/production/api/test_team_performance_integration.py -q`
Expected: all pass.

---

### Task 3: Packing rows derived on save; run required on submit

**Files:**
- Create: `backend/modules/production/api/packing_derivation_service.py`
- Modify: `backend/modules/production/api/shift_sections.py` (the `_PACKING` `of_id` column, `save_section_rows`, `check_ready_to_submit`)
- Test: `backend/modules/production/api/test_packing_derivation_integration.py`

**Interfaces:**
- Consumes: `packing_type_label`, `pick_packaging_location` (Task 1); `finished_quantity_from_count` (`modules.production.domain.packaging_estimate`); `CoreService.get_product(tenant_id, product_id)` (fields `net_weight_grams`, `packets_per_carton`, `default_location_id`); `ProductClassificationService.get_classification`.
- Produces: `derive_packing_rows(connection, *, tenant_id: str, shift_id: str, rows: list[dict]) -> Result[None]` (mutates the cleaned rows). Error codes on save: `INVALID_VALUE` (no run and no OF), `PACKAGING_STORES_DIFFER`. On submit: `RUN_REQUIRED`, `NO_DEFAULT_LOCATION`.

- [ ] **Step 1: Write the failing tests**

Create `api/test_packing_derivation_integration.py`:

```python
"""A packing row takes its OF, type, packets and stores from data the system already holds."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService

TENANT = "packing-derivation-test"
DAY = datetime.date(2030, 7, 8)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor, uom, pasta, film, carton, fg, pack, other, work_center = (str(ULID()) for _ in range(9))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((pasta, "PD-PASTA"), (film, "PD-FILM"), (carton, "PD-CARTON")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    for location_id, code in ((fg, "PD-FG"), (pack, "PD-PACK"), (other, "PD-OTHER")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (location_id, TENANT, code, code))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg, pasta))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = ANY(%s)", (pack, [film, carton]))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'PD-WC', 'Line')", (work_center, TENANT))
    ProductClassificationService(db).set_classification(
        tenant_id=TENANT, actor_id=actor, product_id=pasta, category="finished_good", packaging_format="packet"
    )
    return {"actor": actor, "pasta": pasta, "film": film, "carton": carton, "fg": fg, "pack": pack, "other": other, "work_center": work_center}


def _shift_with_run(db, env):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["pasta"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [{"of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900}]},
    ))
    run_id = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"][0]["payload"]["runs"][0]["id"]
    return service, shift_id, of_id, run_id


def _save_packing(service, env, shift_id, rows):
    return service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing", payload={"rows": rows})


def _saved_row(service, shift_id):
    sections = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"]
    return next(s for s in sections if s["key"] == "packing")["payload"]["rows"][0]


def test_the_row_takes_its_of_type_packets_and_stores_from_the_run(db, env):
    service, shift_id, of_id, run_id = _shift_with_run(db, env)
    _ok(_save_packing(service, env, shift_id, [{
        "run_id": run_id, "carton_quantity": 10, "waste_carton_quantity": 1, "carton_product_id": env["carton"],
        "film_product_id": env["film"], "film_quantity": 5,
    }]))
    row = _saved_row(service, shift_id)
    assert row["of_id"] == of_id
    assert row["packing_type"] == "Sachet 500 g"
    assert row["packets_counted"] == 108  # (10 - 1) cartons x 12 packets
    assert row["finished_goods_location_id"] == env["fg"]
    assert row["packaging_location_id"] == env["pack"]


def test_what_the_team_typed_is_kept(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    _ok(_save_packing(service, env, shift_id, [{
        "run_id": run_id, "packets_counted": 50, "finished_goods_location_id": env["other"], "packaging_location_id": env["other"],
        "film_product_id": env["film"], "film_quantity": 1,
    }]))
    row = _saved_row(service, shift_id)
    assert (row["packets_counted"], row["finished_goods_location_id"], row["packaging_location_id"]) == (50, env["other"], env["other"])


def test_a_row_with_neither_run_nor_of_is_refused_on_save(db, env):
    service, shift_id, _, _ = _shift_with_run(db, env)
    refused = _save_packing(service, env, shift_id, [{"carton_quantity": 3}])
    assert isinstance(refused, Err) and refused.code == "INVALID_VALUE"


def test_packaging_kept_in_different_stores_is_refused(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = %s", (env["other"], env["carton"]))
    refused = _save_packing(service, env, shift_id, [{
        "run_id": run_id, "film_product_id": env["film"], "carton_product_id": env["carton"], "film_quantity": 1, "carton_quantity": 1,
    }])
    assert isinstance(refused, Err) and refused.code == "PACKAGING_STORES_DIFFER"


def test_submitting_needs_the_run(db, env):
    service, shift_id, of_id, _ = _shift_with_run(db, env)
    _ok(_save_packing(service, env, shift_id, [{"of_id": of_id, "packets_counted": 10, "finished_goods_location_id": env["fg"]}]))
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "RUN_REQUIRED"


def test_submitting_names_a_product_without_a_default_store(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    db.execute("UPDATE core.products SET default_location_id = NULL WHERE id = %s", (env["pasta"],))
    _ok(_save_packing(service, env, shift_id, [{"run_id": run_id, "carton_quantity": 10}]))  # a draft may be saved
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "NO_DEFAULT_LOCATION"
    assert "default storage location" in refused.message
```

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_packing_derivation_integration.py -q`
Expected: FAIL (`of_id is required` on save, or missing keys).

- [ ] **Step 3: Write the derivation service**

Create `backend/modules/production/api/packing_derivation_service.py`:

```python
"""Fills in what a packing row no longer asks the team to type.

A row names the production it comes from. From that run's work order and product the row
takes its OF and its packing type; from the product's own figures, the packets its cartons
make; from each item's default storage location, the stores stock moves through. A figure
the team did type (packets, a store) is never overwritten. A row without a run is an old
one: it keeps whatever it carries and is refused only when it is handed in.
"""
from __future__ import annotations

import psycopg

from core.api.service import CoreService
from core.domain.result import Err, Ok, Result
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.domain.packaging_estimate import finished_quantity_from_count
from modules.production.domain.packing_derivation import packing_type_label, pick_packaging_location

_PACKAGING_PRODUCTS = ("film_product_id", "carton_product_id", "tape_product_id", "scotch_product_id", "ruban_product_id")


def derive_packing_rows(connection: psycopg.Connection, *, tenant_id: str, shift_id: str, rows: list[dict]) -> Result[None]:
    """Complete the cleaned packing rows in place, or say why one cannot be saved."""
    core = CoreService(connection)
    classifications = ProductClassificationService(connection)

    wanted = sorted({row["run_id"] for row in rows if row["run_id"]})
    runs: dict[str, tuple[str, str | None]] = {}
    if wanted:
        for run_id, of_id, product_id in connection.execute(
            """
            SELECT r.id, r.of_id, w.product_id
            FROM production.shift_runs r
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.shift_report_id = %s AND r.id = ANY(%s)
            """,
            (tenant_id, shift_id, wanted),
        ).fetchall():
            runs[run_id] = (of_id, product_id)

    for index, row in enumerate(rows, start=1):
        run = runs.get(row["run_id"]) if row["run_id"] else None
        if run is None:
            if not row["of_id"]:
                return Err("INVALID_VALUE", f"packing row {index}: pick the production this lot comes from")
            continue
        row["of_id"], product_id = run

        product = core.get_product(tenant_id, product_id) if product_id else None
        if product is not None:
            classification = classifications.get_classification(tenant_id, product_id)
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
                row["finished_goods_location_id"] = product.default_location_id

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

- [ ] **Step 4: Wire it into `shift_sections.py`**

1. Add to the imports: `from modules.production.api.packing_derivation_service import derive_packing_rows`.
2. In `_PACKING`, change `Col("of_id", "of", required=True),` to `Col("of_id", "of"),` (the OF now comes from the run).
3. In `save_section_rows`, in the `else:` branch, right after the `rows = _clean_rows(...)` / `isinstance(rows, Err)` check and before `checked = _validate_part(...)`, add:

```python
            if part.table == "shift_packing_rows":
                derived = derive_packing_rows(connection, tenant_id=tenant_id, shift_id=shift_report_id, rows=rows.value)
                if isinstance(derived, Err):
                    return derived
```

4. In `check_ready_to_submit`, inside the `elif section_key == "packing":` loop (`for index, row in enumerate(payload.get("rows") or [], start=1):`), insert these lines at the top of the loop body, before the existing `detail = ConditionnementReportDetail(` line. Everything after them stays exactly as it is:

```python
            if not row.get("run_id"):
                return Err("RUN_REQUIRED", f"packing row {index}: pick the production this lot comes from")
            if float(row.get("packets_counted") or 0) > 0 and not row.get("finished_goods_location_id"):
                return Err(
                    "NO_DEFAULT_LOCATION",
                    f"packing row {index}: the product has no default storage location; set one on the product, then save the section again",
                )
            uses_packaging = any(
                float(row.get(quantity) or 0) > 0
                for quantity in ("film_quantity", "carton_quantity", "tape_quantity", "scotch_quantity", "ruban_quantity")
            )
            if uses_packaging and not row.get("packaging_location_id"):
                return Err(
                    "NO_DEFAULT_LOCATION",
                    f"packing row {index}: a packaging item has no default storage location; set one on the item, then save the section again",
                )
```

- [ ] **Step 5: Run to verify they pass**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_packing_derivation_integration.py -q`
Expected: 6 passed.

- [ ] **Step 6: Run the existing shift suites and repair what the run requirement breaks**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_service_integration.py modules/production/api/test_shift_report_router_integration.py modules/production/api/test_shift_validation_integration.py modules/production/api/test_shift_legacy_conversion_integration.py modules/production/api/test_day_sheet_integration.py -q`
Expected: failures only where a test submits a packing row with no `run_id` (`RUN_REQUIRED`) or saves one without `of_id`/`run_id`. For each, add `run_id` to that packing row (the saved run's id; `test_shift_validation_integration._submitted_shift` already does). Do not weaken the new rule. Re-run until green.

---

### Task 4: Packing waste names no item

The client's packing-waste table is Heure, Type, Quantité (kg), Cause: it has no "Article perdu". The rule "a waste line must name the item" therefore no longer applies to packing waste.

**Files:**
- Modify: `backend/modules/production/domain/production_report.py` (`validate_conditionnement_stock_targets`, ~line 544), `backend/modules/production/api/shift_sections.py` (`check_ready_to_submit`, waste branch)
- Test: `backend/modules/production/domain/test_waste_lines.py`, `backend/modules/production/api/test_shift_report_service_integration.py`

- [ ] **Step 1: Change the tests to the new rule**

In `domain/test_waste_lines.py`, replace `test_the_packing_submit_check_covers_the_waste_list` with:

```python
def test_packing_waste_names_no_item():
    """Packing waste is a kind and a weight in kilos; it is not an item, so nothing is asked for one."""
    detail = ConditionnementReportDetail(
        finished_product_quantity=100,
        finished_goods_location_id="store",
        waste_lines=(WasteLine(category="packaging", quantity=2),),
    )
    assert isinstance(validate_conditionnement_stock_targets(detail), Ok)
```

Append to `api/test_shift_report_service_integration.py` (reuse that file's helpers `_open`, `_save`, `_submit`, `_ok`, `Ok` as used by `test_submitting_a_waste_section_needs_to_say_what_was_lost`):

```python
def test_a_packing_waste_section_needs_no_item(db, env):
    shift_id = _open(db, env)
    _ok(_save(db, env, shift_id, "waste_packing", {"waste_lines": [{"category": "packaging", "quantity": 2.5, "note": "torn film"}]}))
    assert isinstance(_submit(db, env, shift_id, "waste_packing"), Ok)
```

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/domain/test_waste_lines.py modules/production/api/test_shift_report_service_integration.py -q -k "packing_waste or waste_section"`
Expected: the two new tests FAIL with `MISSING_WASTE_PRODUCT`.

- [ ] **Step 3: Implement**

In `production_report.py`, in `validate_conditionnement_stock_targets` change the last line `return validate_waste_products(detail.waste_lines)` to:

```python
    # Packing waste is a kind and a kilo weight (kept as figures, not moved as stock), so
    # unlike production waste it is not asked to name an item.
    return Ok(None)
```

In `shift_sections.check_ready_to_submit`, change the waste branch to:

```python
    elif section_key in _WASTE_REPORT_TYPE:
        if section_key == "waste_packing":
            return Ok(None)
        lines = tuple(
            WasteLine(category=line["category"], product_id=line.get("product_id"), quantity=float(line.get("quantity") or 0))
            for line in payload.get("waste_lines") or []
        )
        return validate_waste_products(lines)
```

- [ ] **Step 4: Run to verify they pass**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/domain/test_waste_lines.py modules/production/api/test_waste_lines_integration.py modules/production/api/test_shift_report_service_integration.py -q`
Expected: all pass (the daily-waste item rule is unchanged).

---

### Task 5: A machine on each report, by stage

**Files:**
- Modify: `backend/modules/production/api/legacy_report_ledger.py` (imports; `materialize_shift` header insert)
- Test: `backend/modules/production/api/test_shift_machine_integration.py` (created here, extended in Task 6)

**Interfaces:**
- Consumes: `pick_stage_machine` (Task 1); `EquipmentService.list_equipment(tenant_id=..., work_center_id=...)` returning machines with `.id`, `.production_stage`, `.status`.

- [ ] **Step 1: Write the failing test and the shared fixture**

Create `api/test_shift_machine_integration.py`:

```python
"""What validating a shift does to machines: the report's machine, and the silo reading's status change."""
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

TENANT = "shift-machine-test"
DAY = datetime.date(2030, 8, 5)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor, uom, pasta, semolina, silo, fg, work_center = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((pasta, "SM-PASTA"), (semolina, "SM-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SM-SILO', 'Silo')", (silo, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SM-FG', 'FG')", (fg, TENANT))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg, pasta))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SM-WC', 'Line')", (work_center, TENANT))
    machines = {}
    for stage in ("versement", "extrusion", "conditionnement"):
        machines[stage] = str(ULID())
        db.execute(
            "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, production_stage) VALUES (%s, %s, %s, %s, %s, %s)",
            (machines[stage], TENANT, work_center, f"SM-{stage}", stage, stage),
        )
    ProductClassificationService(db).set_classification(tenant_id=TENANT, actor_id=actor, product_id=pasta, category="finished_good", packaging_format="packet")
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=silo, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "pasta": pasta, "semolina": semolina, "silo": silo, "work_center": work_center, "machines": machines}


def _submitted_shift(db, env, *, day=DAY, silo_rows=None) -> str:
    """A shift with a run (no machine named), a packing row (no machine, no stores) and the given silo readings."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=day, shift="morning"))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["pasta"], planned_quantity=1000, work_center_id=env["work_center"], start_date=day)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [{
        "of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["silo"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["silo"]}],
    }]}))
    run_id = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"][0]["payload"]["runs"][0]["id"]
    filled = {"packing": {"rows": [{"run_id": run_id, "packets_counted": 120, "lot_number": f"L-{day.isoformat()}"}]}}
    if silo_rows:
        filled["silo"] = {"states": silo_rows}
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        elif key in filled:
            _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    return shift_id


def _validate(db, env, shift_id):
    return _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))


def _status(db, machine_id) -> str:
    return db.execute("SELECT status FROM maintenance.equipment WHERE id = %s", (machine_id,)).fetchone()[0]


def test_a_report_without_a_machine_gets_the_lines_machine_at_its_stage(db, env):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    rows = dict(db.execute(
        "SELECT report_type, equipment_id FROM production.production_reports r JOIN production.shift_runs s ON s.id = r.id WHERE s.shift_report_id = %s "
        "UNION ALL SELECT report_type, equipment_id FROM production.production_reports r JOIN production.shift_packing_rows p ON p.id = r.id WHERE p.shift_report_id = %s",
        (shift_id, shift_id),
    ).fetchall())
    assert rows == {"daily": env["machines"]["extrusion"], "conditionnement": env["machines"]["conditionnement"]}
```

- [ ] **Step 2: Run to verify it fails**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_machine_integration.py -q`
Expected: FAIL: both `equipment_id` values are `None`.

- [ ] **Step 3: Implement in the ledger**

In `legacy_report_ledger.py` add the imports

```python
from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.domain.line_machines import pick_stage_machine
```

and in `materialize_shift`, right after the `if not runs and not packing:` block and before `open_stop = ...`, add:

```python
    machines = [
        (machine.id, machine.production_stage, machine.status)
        for machine in EquipmentService(connection).list_equipment(tenant_id=tenant_id, work_center_id=shift["work_center_id"])
    ]
    # Machine performance reads a machine off each report; the screen no longer asks for one,
    # so a report takes the line's machine at the stage it ran on (only when there is exactly one).
    stage_machine = {
        "daily": pick_stage_machine(machines, "extrusion"),
        "conditionnement": pick_stage_machine(machines, "conditionnement"),
    }
```

and change `row["equipment_id"],` in the header `INSERT` parameters to `row["equipment_id"] or stage_machine[report_type],`.

- [ ] **Step 4: Run to verify it passes**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_machine_integration.py modules/production/api/test_shift_validation_integration.py modules/production/api/test_machine_performance_integration.py -q`
Expected: all pass.

---

### Task 6: Silo reading drives machine status; state codes

**Files:**
- Create: `backend/modules/production/api/silo_machine_status.py`, `backend/modules/production/migrations/0053_production_silo_line_state_codes.sql`
- Modify: `backend/modules/production/api/shift_validation_service.py` (`validate_shift`)
- Test: `backend/modules/production/api/test_shift_machine_integration.py` (append)

**Interfaces:**
- Consumes: `silo_machine_changes` (Task 1); `EquipmentService.list_equipment`, `EquipmentService.transition_status(*, tenant_id, actor_id, equipment_id, new_status)`.
- Produces: `apply_silo_machine_status(connection, *, tenant_id: str, actor_id: str, shift_report_id: str) -> None`.

- [ ] **Step 1: Append the failing tests**

```python
SILO_STOPPED = [{"side": "production", "phase": "end", "line_state": "stopped"}]


def test_a_stopped_end_reading_takes_that_sides_machines_down_once_validated(db, env):
    shift_id = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    assert _status(db, env["machines"]["extrusion"]) == "operational"  # nothing changes before validation
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["versement"]) == "down"
    assert _status(db, env["machines"]["extrusion"]) == "down"
    assert _status(db, env["machines"]["conditionnement"]) == "operational"  # the packing side said nothing


def test_a_running_reading_brings_a_down_machine_back(db, env):
    db.execute("UPDATE maintenance.equipment SET status = 'down' WHERE id = %s", (env["machines"]["conditionnement"],))
    shift_id = _submitted_shift(db, env, silo_rows=[{"side": "packing", "phase": "end", "line_state": "running"}])
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["conditionnement"]) == "operational"


def test_a_machine_in_maintenance_is_left_alone(db, env):
    db.execute("UPDATE maintenance.equipment SET status = 'maintenance' WHERE id = %s", (env["machines"]["extrusion"],))
    shift_id = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["extrusion"]) == "maintenance"
    assert _status(db, env["machines"]["versement"]) == "down"


def test_only_start_readings_change_nothing(db, env):
    shift_id = _submitted_shift(db, env, silo_rows=[{"side": "production", "phase": "start", "line_state": "stopped"}])
    _validate(db, env, shift_id)
    assert _status(db, env["machines"]["extrusion"]) == "operational"


def test_an_earlier_shift_does_not_override_a_later_validated_one(db, env):
    earlier = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    later = _submitted_shift(db, env, day=DAY + datetime.timedelta(days=1))
    _validate(db, env, later)
    _validate(db, env, earlier)
    assert _status(db, env["machines"]["extrusion"]) == "operational"


def test_each_change_is_audited(db, env):
    shift_id = _submitted_shift(db, env, silo_rows=SILO_STOPPED)
    _validate(db, env, shift_id)
    audited = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'equipment.status_changed'", (TENANT,)
    ).fetchone()[0]
    assert audited == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_machine_integration.py -q`
Expected: the six new tests FAIL (statuses unchanged / no audit rows). If `core.audit_log` has a different name in this repo, use the table `record_audit` writes to (see `core/audit.py`).

- [ ] **Step 3: Migration for existing silo text**

`backend/modules/production/migrations/0053_production_silo_line_state_codes.sql`:

```sql
-- The silo's "état de la ligne" is now a choice, stored as a code. Older shifts typed it
-- as text; the two spellings the fiche used are turned into the codes, anything else is
-- left as typed (it still shows, and changes no machine).
UPDATE production.shift_silo_states SET line_state = 'running' WHERE lower(btrim(line_state)) = 'en marche';
UPDATE production.shift_silo_states SET line_state = 'stopped' WHERE lower(btrim(line_state)) IN ('en arrêt', 'en arret');
```

Apply it with the migration command from Global Constraints.

- [ ] **Step 4: Write the service**

`backend/modules/production/api/silo_machine_status.py`:

```python
"""A validated shift's end-of-shift silo reading says whether each side of the line is running.

The report is the newest word from the floor, so once a shift is validated the machines of
the side it names are moved through Maintenance's own status change (audited there). It
applies only when no later shift on the same line has already been validated: validating an
old shift late must not undo what a newer one said. A machine in maintenance is left alone,
and a change Maintenance refuses is skipped, not an error.
"""
from __future__ import annotations

import psycopg

from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.domain.line_machines import silo_machine_changes


def _later_shift_validated(
    connection: psycopg.Connection, *, tenant_id: str, work_center_id: str, report_date, shift: str, shift_report_id: str
) -> bool:
    """A validated shift on this line that starts after this one (date first, then the shift's clock start)."""
    row = connection.execute(
        """
        SELECT 1
        FROM production.shift_reports s
        LEFT JOIN production.shift_windows w ON w.tenant_id = s.tenant_id AND w.shift = s.shift
        LEFT JOIN production.shift_windows mine ON mine.tenant_id = %s AND mine.shift = %s
        WHERE s.tenant_id = %s AND s.work_center_id = %s AND s.status = 'validated' AND s.id <> %s
          AND (s.report_date > %s
               OR (s.report_date = %s AND COALESCE(w.start_time, TIME '00:00') > COALESCE(mine.start_time, TIME '00:00')))
        LIMIT 1
        """,
        (tenant_id, shift, tenant_id, work_center_id, shift_report_id, report_date, report_date),
    ).fetchone()
    return row is not None


def apply_silo_machine_status(
    connection: psycopg.Connection, *, tenant_id: str, actor_id: str, shift_report_id: str
) -> None:
    work_center_id, report_date, shift = connection.execute(
        "SELECT work_center_id, report_date, shift FROM production.shift_reports WHERE id = %s AND tenant_id = %s",
        (shift_report_id, tenant_id),
    ).fetchone()
    if _later_shift_validated(
        connection, tenant_id=tenant_id, work_center_id=work_center_id, report_date=report_date, shift=shift,
        shift_report_id=shift_report_id,
    ):
        return
    readings = connection.execute(
        "SELECT side, line_state FROM production.shift_silo_states "
        "WHERE shift_report_id = %s AND tenant_id = %s AND phase = 'end' AND line_state IS NOT NULL",
        (shift_report_id, tenant_id),
    ).fetchall()
    equipment = EquipmentService(connection)
    for side, line_state in readings:
        machines = [
            (machine.id, machine.production_stage, machine.status)
            for machine in equipment.list_equipment(tenant_id=tenant_id, work_center_id=work_center_id)
        ]
        for machine_id, new_status in silo_machine_changes(side=side, line_state=line_state, machines=machines):
            equipment.transition_status(
                tenant_id=tenant_id, actor_id=actor_id, equipment_id=machine_id, new_status=new_status
            )
```

- [ ] **Step 5: Call it from validation**

In `shift_validation_service.py` add `from modules.production.api.silo_machine_status import apply_silo_machine_status` and, inside `validate_shift`'s `with self._connection.transaction():` block, immediately after the `UPDATE production.shift_reports SET status = 'validated' ...` execute call, add:

```python
                apply_silo_machine_status(
                    self._connection, tenant_id=tenant_id, actor_id=actor_id, shift_report_id=shift_report_id
                )
```

- [ ] **Step 6: Run to verify they pass**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_machine_integration.py modules/production/api/test_shift_validation_integration.py -q`
Expected: all pass.

---

### Task 7: Classifications tab: packaging kind

**Files:**
- Modify: `frontend/src/features/production/api.ts` (~lines 64-79), `frontend/src/features/production/ProductClassificationsTab.tsx`, `frontend/src/lib/i18n.tsx` (English block near line 2609, French block near line 5615)

**Interfaces:**
- Produces: `export type PackagingKind = "film" | "carton" | "bobine" | "scotch" | "ruban"`; `ProductClassification.packaging_kind: PackagingKind | null`; `SetClassificationInput.packaging_kind?: PackagingKind`.

- [ ] **Step 1: API types**

In `api.ts`, after `export type PackagingFormat = ...` add `export type PackagingKind = "film" | "carton" | "bobine" | "scotch" | "ruban";`, add `packaging_kind: PackagingKind | null;` to `ProductClassification` (after `packaging_format`), and `packaging_kind?: PackagingKind;` to `SetClassificationInput` (after `packaging_format?`).

- [ ] **Step 2: Dictionary keys**

In `i18n.tsx` English block, after `"production.classifications.packagingFormat.sac": "Sack",` add:

```ts
  "production.classifications.field.packagingKind": "Kind of packaging",
  "production.classifications.column.packagingKind": "Kind of packaging",
  "production.classifications.packagingKind.film": "Film",
  "production.classifications.packagingKind.carton": "Carton",
  "production.classifications.packagingKind.bobine": "Reel (bobine)",
  "production.classifications.packagingKind.scotch": "Scotch",
  "production.classifications.packagingKind.ruban": "Ribbon",
```

In the French block, after `"production.classifications.packagingFormat.sac": "Sac",` add:

```ts
  "production.classifications.field.packagingKind": "Type d'emballage (consommable)",
  "production.classifications.column.packagingKind": "Type d'emballage (consommable)",
  "production.classifications.packagingKind.film": "Film",
  "production.classifications.packagingKind.carton": "Carton",
  "production.classifications.packagingKind.bobine": "Bobine",
  "production.classifications.packagingKind.scotch": "Scotch",
  "production.classifications.packagingKind.ruban": "Ruban",
```

- [ ] **Step 3: The tab**

In `ProductClassificationsTab.tsx`:
1. Import `PackagingKind` from `./api` alongside `PackagingFormat`.
2. Below `PACKAGING_FORMAT_VALUES` add `const PACKAGING_KIND_VALUES: PackagingKind[] = ["film", "carton", "bobine", "scotch", "ruban"];`.
3. In `formSchema`, add to the object: `packaging_kind: z.preprocess((v) => (v === "" ? undefined : v), z.enum(["film", "carton", "bobine", "scotch", "ruban"]).optional()),`.
4. Below `PACKAGING_FORMAT_LABEL` add:

```ts
  const PACKAGING_KIND_LABEL: Record<PackagingKind, string> = {
    film: t("production.classifications.packagingKind.film"),
    carton: t("production.classifications.packagingKind.carton"),
    bobine: t("production.classifications.packagingKind.bobine"),
    scotch: t("production.classifications.packagingKind.scotch"),
    ruban: t("production.classifications.packagingKind.ruban"),
  };
```

5. In the `mutationFn`, add `packaging_kind: input.category === "packaging_component" ? input.packaging_kind : undefined,` after the `packaging_format` line.
6. Add a column after the `packagingFormat` column:

```tsx
    {
      key: "packagingKind",
      header: t("production.classifications.column.packagingKind"),
      defaultWidth: 160,
      cell: (c) => <span className="text-muted-foreground">{c.packaging_kind ? PACKAGING_KIND_LABEL[c.packaging_kind] : "—"}</span>,
      sortValue: (c) => (c.packaging_kind ? PACKAGING_KIND_LABEL[c.packaging_kind] : null),
    },
```

7. In the dialog, after the `{category === "finished_good" && (...)}` block (inside the same `AnimatePresence`), add the twin block:

```tsx
                  {category === "packaging_component" && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.18 }}
                      className="space-y-1.5"
                    >
                      <Label htmlFor="packaging_kind">{t("production.classifications.field.packagingKind")}</Label>
                      <Select id="packaging_kind" {...register("packaging_kind")}>
                        <option value="">—</option>
                        {PACKAGING_KIND_VALUES.map((value) => (
                          <option key={value} value={value}>
                            {PACKAGING_KIND_LABEL[value]}
                          </option>
                        ))}
                      </Select>
                    </motion.div>
                  )}
```

- [ ] **Step 4: Typecheck**

Run (in `frontend`): `npx tsc -b --force`
Expected: no output (no errors).

---

### Task 8: Grid plumbing: read-only cell, per-row options, new option sources

**Files:**
- Modify: `frontend/src/features/production/shift/sectionConfig.ts`, `frontend/src/features/production/shift/ShiftGrid.tsx`

**Interfaces:**
- Produces: `CellKind` gains `"readonly"`; `OptionSource` gains `"productsOrMp" | "moldsForShift" | "orderTypes" | "moldTypes" | "itemsFilm" | "itemsCarton" | "itemsBobine" | "itemsScotch" | "itemsRuban" | "lineStates" | "checkStates"`; `Column.optionsFor?: (row: Row, options: OptionMap) => Option[]`; exported `moldsForOrder(row, options)`; `Cell` accepts `row?: Row`.

- [ ] **Step 1: `sectionConfig.ts`**

Change the type imports and unions:

```ts
import type { Option, OptionMap } from "./ShiftGrid";
import type { Row, SectionKey } from "./shiftApi";
```

(replace the existing `import type { SectionKey } from "./shiftApi";`), then

```ts
export type CellKind = "text" | "number" | "int" | "time" | "datetime" | "date" | "select" | "expression" | "readonly";
```

Extend `OptionSource` by adding these members before `"partners"`:

```ts
  | "productsOrMp"
  | "moldsForShift"
  | "orderTypes"
  | "moldTypes"
  | "itemsFilm"
  | "itemsCarton"
  | "itemsBobine"
  | "itemsScotch"
  | "itemsRuban"
  | "lineStates"
  | "checkStates"
```

Add to `Column`: `/** Choices that depend on the row being edited; wins over `options`. */ optionsFor?: (row: Row, options: OptionMap) => Option[];`.

Below the `pick` helper add:

```ts
const derived = (key: string, label: Label): Column => ({ key, label, kind: "readonly" });

/** The molds of the type (PL or PC) of the row's work order; every mold while the type is unknown. */
export function moldsForOrder(row: Row, options: OptionMap): Option[] {
  const type = options.orderTypes.find((o) => o.value === row.of_id)?.label;
  if (!type) return options.molds;
  const ofThatType = new Set(options.moldTypes.filter((m) => m.label === type).map((m) => m.value));
  return options.molds.filter((m) => ofThatType.has(m.value));
}
```

(`derived` is used by Task 10; `tsc` may flag it unused until then, which is expected.)

- [ ] **Step 2: `ShiftGrid.tsx`**

1. Import `Row` already exists via `shiftApi`; keep.
2. In `DEFAULT_WIDTH` add `readonly: 150,`.
3. In `Cell`'s props add `row?: Row;` (after `idPrefix: string;`) and destructure `row`.
4. In the `select` case replace `const list = column.options ? options[column.options] : [];` with:

```ts
      const list = column.optionsFor && row ? column.optionsFor(row, options) : column.options ? options[column.options] : [];
```

5. Add a case before `case "number":`:

```tsx
    case "readonly":
      return (
        <div id={id} aria-label={name} className="flex h-8 w-full items-center px-2 text-xs text-muted-foreground">
          {asText(value) || "—"}
        </div>
      );
```

6. In `ShiftGrid`'s body cell render, pass the row: change `<Cell column={column} value={row[column.key]} ... />` to also include `row={row}`.

- [ ] **Step 3: Typecheck**

Run: `npx tsc -b --force`
Expected: it fails only because `OptionMap` now needs the new keys in `useShiftReferenceData.ts` (Task 9 supplies them). If so, continue to Task 9 before re-running.

---

### Task 9: Option lists

**Files:**
- Modify: `frontend/src/features/production/shift/useShiftReferenceData.ts` (replace the file)

**Interfaces:**
- Consumes: `listClassifications`, `PackagingKind` (Task 7); the new `OptionSource`s (Task 8).
- Produces: `buildOptions(shift, workCenterId): OptionMap` with every source.

- [ ] **Step 1: Replace the file with:**

```ts
import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { listEquipment } from "../../maintenance/api";
import { listLocations, listProducts } from "../../warehouse/api";
import { listPartners } from "../../partners/api";
import { listClassifications, listMolds, listWorkCenters, listWorkOrders, type PackagingKind } from "../api";
import { DASHBOARD_SETTINGS_QUERY_KEY, getDashboardSettings } from "../board/api";
import { DOWNTIME_CLASSIFICATIONS, DOWNTIME_MOTIFS, DOWNTIME_TYPES } from "../DowntimeMotifSelect";
import { useWasteTypes } from "../wasteTypes";
import type { Option, OptionMap } from "./ShiftGrid";
import type { Row, SectionKey, ShiftReport } from "./shiftApi";
import { useLabel } from "./shiftText";

/**
 * Everything the shift grids' selects and the header need, loaded once and turned into
 * option lists. Shared by the team's entry screen and the validator's review, so both
 * show a lot, a machine or a work order under the same name.
 */
export function useShiftReferenceData(enabled: boolean) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const label = useLabel();
  const waste = useWasteTypes();

  const workCenters = useQuery({ queryKey: ["production", "shift", "work-centers"], queryFn: () => listWorkCenters(token), enabled });
  const settings = useQuery({ queryKey: DASHBOARD_SETTINGS_QUERY_KEY, queryFn: () => getDashboardSettings(token), enabled });
  const orders = useQuery({ queryKey: ["production", "shift", "orders"], queryFn: () => listWorkOrders(token), enabled });
  const products = useQuery({ queryKey: ["production", "shift", "products"], queryFn: () => listProducts(token), enabled });
  const classifications = useQuery({ queryKey: ["production", "shift", "classifications"], queryFn: () => listClassifications(token), enabled, retry: false });
  const locations = useQuery({ queryKey: ["production", "shift", "locations"], queryFn: () => listLocations(token), enabled });
  const molds = useQuery({ queryKey: ["production", "shift", "molds"], queryFn: () => listMolds(token), enabled });
  const equipment = useQuery({ queryKey: ["production", "shift", "equipment"], queryFn: () => listEquipment(token), enabled });
  const partners = useQuery({ queryKey: ["production", "shift", "partners"], queryFn: () => listPartners(token), enabled });

  /** The option lists for one shift: the runs and packing rows it holds are choices for its waste and stop rows. */
  const buildOptions = useCallback(
    (shift: ShiftReport | undefined, workCenterId: string): OptionMap => {
      const productList = products.data ?? [];
      const productName = new Map(productList.map((p) => [p.id, p.name]));
      const productType = new Map(productList.map((p) => [p.id, p.product_type as string]));
      const all = orders.data ?? [];
      const orderById = new Map(all.map((o) => [o.id, o]));
      const rowsOf = (key: SectionKey, part: string) => {
        const payload = shift?.sections.find((s) => s.key === key)?.payload;
        return (Array.isArray(payload?.[part]) ? (payload![part] as Row[]) : []).filter((r) => typeof r.id === "string");
      };
      const time = (value: unknown) => (typeof value === "string" ? value.slice(0, 5) : "");
      const list = (source: readonly string[], prefix: string): Option[] =>
        source.map((value) => ({ value, label: t(`production.downtime.${prefix}.${value}` as TranslationKey) }));

      // Only orders still running are offered (never a regrind order); one a saved row already holds stays, so its name shows.
      const savedOrders = new Set([...rowsOf("runs", "runs"), ...rowsOf("packing", "rows")].map((r) => String(r.of_id)));
      const orderOption = (o: (typeof all)[number]): Option => ({
        value: o.id,
        label: o.product_id && productName.get(o.product_id) ? `${o.reference} – ${productName.get(o.product_id)}` : o.reference,
      });
      const pickable = all.filter((o) => (o.status === "ongoing" && !o.is_regrind) || savedOrders.has(o.id));

      // Products for the "item lost" and regrind selects: finished goods and raw materials only. If the
      // classifications cannot be read (no permission), nothing is filtered rather than emptying the list.
      const classOf = new Map((classifications.data ?? []).map((c) => [c.product_id, c]));
      const asOption = (p: (typeof productList)[number]): Option => ({ value: p.id, label: p.name });
      const productsOrMp = classifications.data
        ? productList.filter((p) => ["finished_good", "raw_material"].includes(classOf.get(p.id)?.category ?? "")).map(asOption)
        : productList.map(asOption);
      const itemsOfKind = (kind: PackagingKind): Option[] =>
        productList.filter((p) => classOf.get(p.id)?.packaging_kind === kind).map(asOption);

      // Molds follow the type (PL or PC) of the work orders: a run's own row, or the shift's runs for a wash.
      const typeOfOrder = new Map(all.map((o) => [o.id, o.product_type ?? productType.get(o.product_id ?? "") ?? ""]));
      const runTypes = new Set(rowsOf("runs", "runs").map((r) => typeOfOrder.get(String(r.of_id)) ?? "").filter(Boolean));
      const moldList = molds.data ?? [];
      const moldOption = (m: (typeof moldList)[number]): Option => ({ value: m.id, label: `${m.code} – ${m.name}` });

      const runLabel = (r: Row) => {
        const order = orderById.get(String(r.of_id));
        const name = (order?.product_id && productName.get(order.product_id)) || order?.reference || "";
        return [name, time(r.start_time)].filter(Boolean).join(" · ") || String(r.id).slice(-6);
      };

      return {
        orders: pickable.map(orderOption),
        products: productList.map(asOption),
        productsOrMp,
        itemsFilm: itemsOfKind("film"),
        itemsCarton: itemsOfKind("carton"),
        itemsBobine: itemsOfKind("bobine"),
        itemsScotch: itemsOfKind("scotch"),
        itemsRuban: itemsOfKind("ruban"),
        locations: (locations.data ?? []).map((l) => ({ value: l.id, label: l.name })),
        molds: moldList.map(moldOption),
        moldsForShift: moldList.filter((m) => runTypes.size === 0 || runTypes.has(m.type)).map(moldOption),
        orderTypes: [...typeOfOrder].map(([value, type]) => ({ value, label: type })),
        moldTypes: moldList.map((m) => ({ value: m.id, label: m.type })),
        partners: (partners.data ?? []).map((p) => ({ value: p.id, label: p.name })),
        equipment: (equipment.data ?? [])
          .filter((e) => !workCenterId || e.work_center_id === workCenterId)
          .map((e) => ({ value: e.id, label: e.name })),
        motifs: list(DOWNTIME_MOTIFS, "motif"),
        stopTypes: list(DOWNTIME_TYPES, "type"),
        classifications: list(DOWNTIME_CLASSIFICATIONS, "classification"),
        wasteProduction: waste.categoriesFor("daily").map((c) => ({ value: c, label: waste.label(c) })),
        wastePacking: waste.categoriesFor("conditionnement").map((c) => ({ value: c, label: waste.label(c) })),
        runs: rowsOf("runs", "runs").map((r) => ({ value: r.id as string, label: runLabel(r) })),
        packingRows: rowsOf("packing", "rows").map((r) => ({
          value: r.id as string,
          label: String(r.lot_number || orderById.get(String(r.of_id))?.reference || String(r.id).slice(-6)),
        })),
        siloSides: [
          { value: "production", label: label({ en: "Production", fr: "Production" }) },
          { value: "packing", label: label({ en: "Packing", fr: "Conditionnement" }) },
        ],
        siloPhases: [
          { value: "start", label: label({ en: "Start", fr: "Début" }) },
          { value: "end", label: label({ en: "End", fr: "Fin" }) },
        ],
        lineStates: [
          { value: "running", label: label({ en: "Running", fr: "En marche" }) },
          { value: "stopped", label: label({ en: "Stopped", fr: "En arrêt" }) },
        ],
        checkStates: [
          { value: "good", label: label({ en: "Good", fr: "Bon" }) },
          { value: "not_good", label: label({ en: "Not good", fr: "Non bon" }) },
        ],
      };
    },
    // `waste` and `label` are rebuilt every render; what they read is captured by their own deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [orders.data, products.data, classifications.data, locations.data, molds.data, equipment.data, partners.data, waste.types, t],
  );

  return {
    workCenters: workCenters.data,
    workCentersLoading: workCenters.isLoading,
    windows: settings.data?.shift_windows ?? [],
    buildOptions,
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc -b --force`
Expected: no output. If `WorkOrder` lacks a field used here, fix the reference (it has `is_regrind`, `status`, `product_type`, `product_id`, `reference`).

---

### Task 10: Section config

**Files:**
- Modify: `frontend/src/features/production/shift/sectionConfig.ts` (the `SECTIONS` array)

- [ ] **Step 1: Production run columns**

In the `runs` section's first part, replace the `columns: [...]` with (the machine column is gone; regrind item uses the product-or-MP list; the mold follows the OF's type):

```ts
        columns: [
          pick("of_id", L("Work order", "OF"), "orders", true),
          { ...pick("mold_id", L("Mold", "Moule"), "molds"), optionsFor: moldsForOrder },
          text("lot_number", L("Lot", "N° lot")),
          time("start_time", L("Start", "HD prod")),
          time("end_time", L("End", "HF prod")),
          int("production_minutes", L("Minutes run", "Minutes de marche")),
          num("dough_quantity", L("Dough (t)", "Pâte (t)")),
          num("finished_product_quantity", L("Finished (t)", "Produit fini (t)")),
          num("regrind_quantity", L("Regrind made (t)", "Rebroyat produit (t)")),
          num("regrind_input_quantity", L("Regrind used (t)", "Rebroyat utilisé (t)")),
          pick("regrind_input_product_id", L("Regrind item", "Article rebroyat"), "productsOrMp"),
          pick("raw_material_location_id", L("Regrind store", "Magasin rebroyat"), "locations"),
          num("water_percentage", L("Water %", "% eau")),
          num("humidity_percentage", L("Humidity %", "Humidité %")),
          num("semolina_flow_rate", L("Semoule flow (t/h)", "Débit semoule (t/h)")),
        ],
```

- [ ] **Step 2: Waste and molds (`waste_production`)**

Change the waste part's `pick("product_id", L("Item lost", "Article perdu"), "products"),` to use `"productsOrMp"`, and the mold-wash part's `pick("mold_id", L("Mold", "Moule"), "molds"),` to `pick("mold_id", L("Mold", "Moule"), "moldsForShift"),`.

- [ ] **Step 3: Stops**

Replace the `stops` columns with (Type, Système, Motif in that order):

```ts
        columns: [
          pick("equipment_id", L("Machine", "Machine"), "equipment"),
          when("started_at", L("From", "De"), true),
          when("ended_at", L("To", "À")),
          pick("downtime_type", L("Type", "Type"), "stopTypes"),
          pick("classification", L("System", "Système"), "classifications"),
          pick("motif", L("Reason", "Motif"), "motifs"),
          pick("run_id", L("Run", "Production"), "runs"),
          text("note", L("Breakdown", "Panne")),
          text("corrective_action", L("Corrective action", "Action corrective")),
        ],
```

- [ ] **Step 4: Silo**

Replace `text("line_state", L("Line state", "État de la ligne")),` with `pick("line_state", L("Line state", "État de la ligne"), "lineStates"),`.

- [ ] **Step 5: Packing**

Replace the `packing` part's `columns: [...]` with:

```ts
        columns: [
          pick("run_id", L("From production", "De la production"), "runs", true),
          text("lot_number", L("Lot", "N° lot")),
          derived("packing_type", L("Packing type", "Type de conditionnement")),
          pick("film_product_id", L("Film type", "Type film"), "itemsFilm"),
          { key: "film_quantity", label: L("Film (kg)", "Film (kg)"), kind: "expression" },
          pick("carton_product_id", L("Carton type", "Type carton"), "itemsCarton"),
          num("carton_quantity", L("Cartons", "Cartons")),
          num("waste_carton_quantity", L("Empty cartons", "Cartons vides")),
          pick("tape_product_id", L("Reel type", "Type bobine"), "itemsBobine"),
          num("tape_quantity", L("Reels", "Bobines")),
          pick("scotch_product_id", L("Scotch type", "Type scotch"), "itemsScotch"),
          num("scotch_quantity", L("Scotch", "Scotch")),
          pick("ruban_product_id", L("Ribbon type", "Type ruban"), "itemsRuban"),
          num("ruban_quantity", L("Ribbon", "Ruban")),
        ],
```

- [ ] **Step 6: Packet checks**

Replace the `packet_checks` part's `columns: [...]` with (same order as today; film and the three checks become dropdowns):

```ts
        columns: [
          when("checked_at", L("Time", "Heure")),
          pick("film_state", L("Film", "Film"), "checkStates"),
          num("packet_weight_grams", L("Packet weight (g)", "Poids paquet (g)")),
          pick("long_weld", L("Long weld", "Soudure longitudinale"), "checkStates"),
          pick("vertical_weld", L("Vertical weld", "Soudure verticale"), "checkStates"),
          pick("date_print", L("Date print", "Impression date"), "checkStates"),
          text("note", L("Note", "Observation")),
        ],
```

- [ ] **Step 7: Packing waste**

Replace the `waste_packing` part's `columns: [...]` with:

```ts
        columns: [
          when("occurred_at", L("Time", "Heure")),
          pick("category", L("Kind", "Type"), "wastePacking", true),
          num("quantity", L("Quantity (kg)", "Quantité (kg)")),
          text("note", L("Cause", "Cause")),
        ],
```

- [ ] **Step 8: Typecheck**

Run: `npx tsc -b --force`
Expected: no output.

---

### Task 11: Verification, spec corrections, data step

- [ ] **Step 1: Full backend suites**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production modules/warehouse modules/maintenance modules/qc -q`
Expected: all pass (the baseline before this plan was 831 in production+warehouse+qc). Fix regressions properly; never loosen a new rule to make an old test pass.

- [ ] **Step 2: Restart the backend** so it loads the new code and migrations 0052/0053 (the user restarts it; on this machine start it with the command in memory if it is down).

- [ ] **Step 3: Browser walk-through (French, demo login), one section at a time, saving nothing in the owner's shifts.** Open a shift that is not the owner's (or read-only inspect the option lists). Check: Production OF list shows only ongoing non-regrind OFs; the machine column is gone; Article rebroyat and Article perdu list only finished goods/raw materials; the mold list follows the OF type; Lavage des moules lists only the type of the shift's runs; Arrêts columns read Type, Système, Motif and machines are the line's; Silo state is a En marche / En arrêt dropdown; Packing shows De la production (by product name), read-only Type de conditionnement and the five type dropdowns, with no OF, Conditionné, Paquets, Cadence or store columns; Vérification des paquets has Bon / Non bon dropdowns; Déchets de conditionnement is Heure, Type, Quantité (kg), Cause. Then `npx tsc -b --force` once more.

- [ ] **Step 4: Correct the spec** (`docs/superpowers/specs/2026-09-21-shift-form-rework-design.md`): (a) delete section 2.6 and its testing mention: `WorkOrder.is_regrind` already exists in the API; (b) 2.4: stores are filled when the row is saved (not only at validation), refused at submit with `NO_DEFAULT_LOCATION`, `PACKAGING_STORES_DIFFER` on save; (c) add under 2.8: packing waste no longer needs an item (the `validate_conditionnement_stock_targets` waste-item check is removed); (d) 2.7: the silo state codes are `running`/`stopped` and migration 0053 maps the old text.

- [ ] **Step 5: Data step for the user.** After the new Classifications field is live, the client sets film, carton, scotch, ruban (and any bobine) products to category "Packaging component" with the right kind in Production > Classifications; until then those items still appear in the item-lost / regrind lists and the packing dropdowns are empty. Names are not matched by code; the client picks them.

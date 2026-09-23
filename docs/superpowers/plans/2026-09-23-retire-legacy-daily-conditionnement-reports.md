# Retire Legacy Daily/Conditionnement Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the old Daily/Conditionnement report system (`production.production_reports`, `daily_reports`, `conditionnement_reports` + their child tables, services, routes, and frontend dialogs) now that the shift-report system is the team-facing UI, and rebuild the logic that currently only exists on the old tables — stock posting, regrind/scrap, DLC lot registration, and the day sheet — to run directly on the shift tables (`shift_runs`, `shift_packing_rows`, `shift_waste_lines`, `machine_stops`).

**Architecture:** This is milestone 6b of the shift-report program (see project memory `project-shift-report-program`). Today, `ShiftValidationService.validate_shift` fakes old-shaped rows via `legacy_report_ledger.materialize_shift()` and then calls `ProductionReportService.validate_report` / `delete_report`, so the ~1000 lines of stock-posting, regrind-batch, scrap-record and DLC-lot logic never had to move. This plan extracts that logic into a new `ShiftStockService` (backend/modules/production/api/shift_stock_service.py) that reads directly from shift tables and writes stock/regrind/scrap/lot records keyed on shift row ids instead of old report ids. `ShiftValidationService` is rewired to call it directly, `legacy_report_ledger.py` is deleted, `DaySheetService` is ported to read shift tables, the old frontend dialogs and `/reports/daily`, `/reports/conditionnement` routes are removed, dependent tests are rewritten, and finally the old tables are dropped in one migration once nothing reads or writes them.

Each task leaves the app in a working, testable state. The old system keeps functioning (nothing is deleted) until Task 8, so a bad task can be caught before user-facing surface changes.

**Tech Stack:** Python 3.11, psycopg3, FastAPI-style module router, pytest (integration tests hit a real Postgres via `core.db`), React + TypeScript frontend, Vitest/tsc for frontend checks.

**Spec:** No separate spec file — this plan is scoped directly from the existing `legacy_report_ledger.py`, `production_report_service.py`, `report_stock_service.py`, `day_sheet_service.py`, `conditionnement_service.py`, `shift_validation_service.py`, and their migrations, all read in full before this plan was written. Project context: `project-shift-report-program` memory (the M6b milestone this plan executes).

## Global Constraints

- Never touch `production.shift_reports`, `shift_runs`, `shift_packing_rows`, `shift_waste_lines`, `machine_stops`, `shift_energy`, `shift_run_semolina_lines` schemas except where a task explicitly adds a column — these are the system of record going forward.
- Every stock movement must keep posting through `modules.warehouse.api.service.StockService.post_production_movement` / `adjust_stock` — never write to `warehouse.stock_moves` directly.
- Regrind, scrap, and DLC-lot behavior must be **byte-for-byte equivalent** to the current old-table behavior (same product resolution rules, same "carton count wins over packets_counted" rule, same shortfall-comment gate) — this is a schema migration for existing logic, not a redesign. Where the old code has a comment explaining *why* a rule exists (e.g. "never `detail.regrind_product_id`" in `_record_regrind_scrap`), preserve that comment verbatim in the new code — those are hard-won invariants, not style.
- `correlation_id`, `source_type`/`source_id` on every stock movement must reference the **shift row id** (`shift_runs.id` / `shift_packing_rows.id`), not a `shift_report_id` — reversal and audit trail depend on movement-per-row granularity exactly as today's movement-per-old-report-id does.
- No task may drop or alter old tables before Task 8 — every earlier task must leave `legacy_report_ledger.py` and the old services importable and their existing tests green, even after the new engine exists alongside them.
- Follow existing code style: `Result`/`Ok`/`Err` return types, `record_audit` on every state change, `FOR UPDATE` row locks before any status transition, savepoints (`connection.transaction()`) around multi-statement writes.

## Review Focus

- **A shift with two runs on different products (PC mold change mid-shift) reversed after validation.** The old `delete_report` reverses one old-report-id's movements at a time; the new engine must reverse each `shift_runs`/`shift_packing_rows` row's movements independently, in packing-then-runs order, exactly as `reverse_shift` does today — a bug here double-reverses or under-reverses one run's stock while leaving the other's correct.
- **A validated shift whose regrind batch was already ground and received into stock, then the shift is reversed with `force=False`.** Must refuse with `REGRIND_ALREADY_COMPLETED` exactly as today, not silently skip the regrind check because it can no longer find a `daily_reports` row to key off of.
- **A raw-material shortfall on a shift run with no `shortfall_comment` supplied.** Must still gate validation with `SHORTFALL_COMMENT_REQUIRED` — trivial to lose if the new engine restructures where shortfall detection happens relative to the stock-posting loop.
- **A packing row with a carton tier where `packets_counted` disagrees with `carton_quantity * packets_per_carton`.** The carton count must still win for the stock quantity posted (decision 24) — a naive port could accidentally use `packets_counted` as the primary source since the shift screen's UI leads with packet count.
- **The day sheet's "pending" column for an open/submitted shift with no runs yet (an empty shift just opened).** `DaySheetService._present_pending_shifts` today skips a shift with nothing in it silently (comment: "nothing to show; not an error"); the ported version must not crash trying to build a `DailyFact`/`PackingFact` from zero rows, and must not show a phantom empty column.
- **A shift validated, then corrected after validation (`correct_validated_report` equivalent), where the corrected regrind figure is *lower* than what an already-closed regrind batch produced.** Must still hit the `_reconcile_closed_regrind_batch` stock-adjustment path (delta < 0 branch) rather than the generic reversal path — this is the most intricate branch in the old code and the easiest to flatten away by accident.

---

## File Structure

New files:
- `backend/modules/production/api/shift_stock_service.py` — the new engine: `ShiftStockService` class with `validate_shift_production(...)` (posts stock/regrind/scrap for runs) and `validate_shift_packing(...)` (posts stock/DLC-lot for packing rows), plus `reverse_run(...)` / `reverse_packing_row(...)` for undoing a single row's effects. Mirrors `ProductionReportService.validate_report`/`delete_report`'s daily/conditionnement branches, but reads `shift_runs`/`shift_packing_rows` directly instead of `daily_reports`/`conditionnement_reports`.
- `backend/modules/production/api/test_shift_stock_service_integration.py` — integration tests for the new engine, real Postgres.
- `backend/modules/production/migrations/0058_production_drop_legacy_reports.sql` — drops the old tables (Task 8 only).

Modified files:
- `backend/modules/production/api/shift_validation_service.py` — `validate_shift`, `reverse_shift` call `ShiftStockService` instead of `materialize_shift` + `ProductionReportService`.
- `backend/modules/production/api/day_sheet_service.py` — `_reports`, `_read_sheet`, `_present_pending_shifts` rewritten against shift tables; `materialize_shift` import removed.
- `backend/modules/production/api/router.py` — old `/reports/daily`, `/reports/conditionnement`, and the generic report-lifecycle routes removed; `production_report_service`/`conditionnement_service` route wiring removed.
- `backend/modules/production/module.json` — old permissions/service registrations removed.
- `frontend/src/features/production/WorkOrderDetailsPage.tsx` — `DailyReportDialog`/`PackingReportDialog` usage removed.
- `frontend/src/features/production/StageDetailsDialog.tsx` (or wherever `onOpenReport` sources its list) — old-report listing removed/reworked to point at shift data, or the "open report" affordance removed if shift data supersedes it (confirm exact scope in Task 9).

Deleted files (Task 8+):
- `backend/modules/production/api/production_report_service.py`
- `backend/modules/production/api/conditionnement_service.py`
- `backend/modules/production/api/report_stock_service.py`
- `backend/modules/production/api/legacy_report_ledger.py`
- `backend/modules/production/api/downtime_line_store.py`, `waste_line_store.py`, `semolina_line_store.py` (superseded by `shift_waste_lines`, `shift_run_semolina_lines`, `machine_stops` — confirm no other caller before deleting, Task 8)
- `frontend/src/features/production/DailyReportsTab.tsx`, `ConditionnementTab.tsx`
- `backend/scripts/fix_daily_report_*.py` (dead once the tables are gone)
- 25 backend test files listed in Task 7

---

### Task 1: `ShiftStockService` — daily/production-side posting (runs)

**Files:**
- Create: `backend/modules/production/api/shift_stock_service.py`
- Test: `backend/modules/production/api/test_shift_stock_service_integration.py`

**Interfaces:**
- Consumes: `modules.warehouse.api.service.StockService.post_production_movement(*, tenant_id, product_id, location_id, quantity, direction, correlation_id, reference, move_type, actor_id, source_type, source_id, of_id) -> Result[dict]`, `StockService.would_go_negative(*, tenant_id, product_id, location_id, quantity) -> bool`, `StockService.adjust_stock(*, tenant_id, product_id, location_id, delta, reason, actor_id, reference) -> Result[dict]`, `StockService.list_stock_moves(*, tenant_id, product_id, move_type, reference, limit) -> list[dict]`.
- Consumes: `modules.production.api.regrind_service.RegrindDefaultsService.resolve_output_product(*, tenant_id, input_product_id) -> str | None`, `ScrapService.record_scrap(*, tenant_id, actor_id, scrap_type, product_id, quantity, work_order_id=None, work_center_id=None, source_note=None) -> Result[ScrapRecord]` (`ScrapRecord.id: str`), `RegrindService.create_regrind_batch(*, tenant_id, actor_id, scrap_record_ids: list[str], work_center_id: str) -> Result[dict]` (`dict["work_order"].id: str`).
- Produces: `ShiftStockService.__init__(self, connection: psycopg.Connection) -> None`.
- Produces: `ShiftStockService.post_run(self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str) -> Result[dict]` — `run` is a row dict from `production.shift_runs` (as returned by `SELECT * ...`) joined with its `shift_run_semolina_lines`. Returns `Ok({"movements": list[dict]})` or an `Err` (`INVALID_VALUE` etc.) exactly as `ReportStockService.post_daily_report` does today (same shape as its `movements` list: `{"direction", "product_id", "location_id", "quantity"}`).
- Produces: `ShiftStockService.run_shortfalls(self, *, tenant_id: str, run: dict) -> list[dict]` — same shape as `ReportStockService.daily_shortfalls`.
- Produces: `ShiftStockService.record_regrind(self, *, tenant_id: str, actor_id: str, run: dict, regrind_work_center_id: str | None) -> Result[dict]` — returns `Ok({"scrap_record_id": str | None, "regrind_work_order_id": str | None})`. Ports `ProductionReportService._record_regrind_scrap` + `_open_regrind_order` combined into one call, reading `run["regrind_quantity"]`, `run["of_id"]`, `run.get("equipment_id")`/work center resolution identical to the old `header.work_center_id` fallback chain (shift's own `work_center_id`, looked up via the run's `of_id`'s work order if unset).
- Later tasks consume: `post_run`, `run_shortfalls`, `record_regrind` from `ShiftValidationService` (Task 3); `reverse_run` (Task 2) for reversal.

- [ ] **Step 1: Write the failing integration test for shortfall-free posting**

```python
# backend/modules/production/api/test_shift_stock_service_integration.py
from __future__ import annotations

import datetime

from core.db import get_connection
from modules.production.api.shift_stock_service import ShiftStockService
from modules.production.api.shift_report_service import ShiftReportService
from modules.warehouse.api.service import StockService
from tests.production_fixtures import (  # existing fixture helper module used by other production integration tests
    make_tenant, make_product, make_location, make_work_center, make_work_order, make_user,
)


def test_post_run_deducts_raw_material_and_not_finished_product():
    with get_connection() as conn:
        with conn.transaction(force_rollback=True):
            tenant_id = make_tenant(conn)
            actor_id = make_user(conn, tenant_id)
            wc = make_work_center(conn, tenant_id)
            semolina = make_product(conn, tenant_id, name="Semoule test")
            finished = make_product(conn, tenant_id, name="Produit fini test")
            raw_store = make_location(conn, tenant_id)
            of_id = make_work_order(conn, tenant_id, product_id=finished, work_center_id=wc)

            shifts = ShiftReportService(conn)
            header = shifts.open_shift(
                tenant_id=tenant_id, actor_id=actor_id, work_center_id=wc,
                report_date=datetime.date(2026, 9, 1), shift="morning", team="Équipe A",
            ).value
            shifts.save_section(
                tenant_id=tenant_id, actor_id=actor_id, shift_report_id=header["id"], section_key="runs",
                payload={"runs": [{
                    "of_id": of_id, "equipment_id": None, "start_time": "07:00", "end_time": "09:00",
                    "production_minutes": 120, "dough_quantity": 100, "finished_product_quantity": 100,
                    "regrind_quantity": 0, "raw_material_location_id": raw_store,
                    "semolina_lines": [{"product_id": semolina, "location_id": raw_store, "quantity": 50}],
                }]},
            )
            StockService(conn).receive_stock(
                tenant_id=tenant_id, product_id=semolina, location_id=raw_store, quantity=1000,
                correlation_id="seed", reference="test-seed", actor_id=actor_id,
            )

            run_row = conn.execute(
                "SELECT * FROM production.shift_runs WHERE shift_report_id = %s", (header["id"],)
            ).fetchone()
            columns = [d.name for d in conn.cursor().description] if False else None  # placeholder removed below
```

Discard the last two lines above — they are a reminder to fetch column names properly. Replace the final block with:

```python
            cursor = conn.execute("SELECT * FROM production.shift_runs WHERE shift_report_id = %s", (header["id"],))
            names = [d.name for d in cursor.description]
            run = dict(zip(names, cursor.fetchone()))
            semolina_cursor = conn.execute(
                "SELECT * FROM production.shift_run_semolina_lines WHERE run_id = %s", (run["id"],)
            )
            sem_names = [d.name for d in semolina_cursor.description]
            run["semolina_lines"] = [dict(zip(sem_names, row)) for row in semolina_cursor.fetchall()]

            service = ShiftStockService(conn)
            result = service.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id="corr-1")

            assert result.value is not None, result
            movements = result.value["movements"]
            assert len(movements) == 1
            assert movements[0]["direction"] == "out"
            assert movements[0]["product_id"] == semolina
            assert movements[0]["quantity"] == 50

            balance = StockService(conn).get_balance(tenant_id=tenant_id, product_id=semolina, location_id=raw_store)
            assert balance == 950  # 1000 received - 50 consumed; finished_product posts nothing
```

If `tests/production_fixtures.py` does not exist under that exact name, grep the existing suite (`test_report_flow_integration.py` is the closest analog) for however it currently builds tenant/product/location/work-order fixtures and use that same helper module/pattern instead of inventing a new one — this codebase almost certainly already has one; do not duplicate it.

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.production.api.shift_stock_service'`

- [ ] **Step 3: Implement `ShiftStockService.post_run` and `run_shortfalls`**

```python
# backend/modules/production/api/shift_stock_service.py
from __future__ import annotations

import psycopg

from core.domain.result import Err, Ok, Result
from modules.warehouse.api.service import StockService


class ShiftStockService:
    """What validating a shift's runs and packing rows moves in stock.

    Ported from ReportStockService/ProductionReportService onto the shift tables
    directly: a shift_runs row plays the role the old daily_reports row played,
    a shift_packing_rows row plays the role conditionnement_reports played. The
    rules themselves are unchanged -- see the docstrings on post_run/post_packing
    for the same "why" ReportStockService carried.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    @staticmethod
    def _run_lines(run: dict) -> list[tuple[float, str, str]]:
        """Everything a run takes out of stock: semoule and rebroyat alike.

        Mirrors ReportStockService._daily_lines: each semoule line carries its
        own location; rebroyat still draws from the run's one
        raw_material_location_id.
        """
        lines = [
            (float(line["quantity"]), line["product_id"], line["location_id"])
            for line in run.get("semolina_lines", [])
        ]
        if run.get("raw_material_location_id"):
            lines.append(
                (
                    float(run.get("regrind_input_quantity") or 0),
                    run.get("regrind_input_product_id"),
                    run["raw_material_location_id"],
                )
            )
        return [
            (quantity, product_id, location_id)
            for quantity, product_id, location_id in lines
            if quantity > 0 and product_id and location_id
        ]

    def run_shortfalls(self, *, tenant_id: str, run: dict) -> list[dict]:
        """Withdrawals this run would drive below zero."""
        shortfalls: list[dict] = []
        for quantity, product_id, location_id in self._run_lines(run):
            if self._stock.would_go_negative(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id, quantity=quantity
            ):
                shortfalls.append({"product_id": product_id, "location_id": location_id, "quantity": quantity})
        return shortfalls

    def post_run(
        self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, reverse: bool = False
    ) -> Result[dict]:
        """Raw material out. The run's finished_product_quantity posts nothing --
        the packing row owns that tonnage, exactly as the old daily report did.

        With reverse=True the same lines post inward, undoing a validated run's
        effect before it is corrected or deleted.
        """
        direction = "in" if reverse else "out"
        movements: list[dict] = []
        for quantity, product_id, location_id in self._run_lines(run):
            posted = self._stock.post_production_movement(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=location_id,
                quantity=quantity,
                direction=direction,
                correlation_id=correlation_id,
                reference=f"shift_run:{run['id']}",
                move_type="production_consumption",
                actor_id=actor_id,
                source_type="production.shift_run",
                source_id=run["id"],
                of_id=run["of_id"],
            )
            if isinstance(posted, Err):
                return posted
            movements.append({"direction": direction, "product_id": product_id, "location_id": location_id, "quantity": quantity})
        return Ok({"movements": movements})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for regrind scrap + regrind order opening**

```python
def test_record_regrind_opens_batch_when_regrind_quantity_positive():
    with get_connection() as conn:
        with conn.transaction(force_rollback=True):
            tenant_id = make_tenant(conn)
            actor_id = make_user(conn, tenant_id)
            wc = make_work_center(conn, tenant_id)
            finished = make_product(conn, tenant_id, name="Produit fini test")
            regrind_output = make_product(conn, tenant_id, name="Rebroyat test")
            of_id = make_work_order(conn, tenant_id, product_id=finished, work_center_id=wc)

            conn.execute(
                "INSERT INTO production.regrind_defaults (tenant_id, input_product_id, output_product_id) "
                "VALUES (%s, NULL, %s)",
                (tenant_id, regrind_output),
            )

            run = {
                "id": "run-test-1", "of_id": of_id, "work_center_id": wc,
                "regrind_quantity": 12.5, "semolina_lines": [],
            }

            service = ShiftStockService(conn)
            result = service.record_regrind(
                tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=None
            )

            assert result.value is not None, result
            assert result.value["scrap_record_id"] is not None
            assert result.value["regrind_work_order_id"] is not None

            scrap = conn.execute(
                "SELECT quantity, product_id, scrap_type FROM production.scrap_records WHERE id = %s",
                (result.value["scrap_record_id"],),
            ).fetchone()
            assert float(scrap[0]) == 12.5
            assert scrap[1] == regrind_output
            assert scrap[2] == "shift_run"


def test_record_regrind_noop_when_quantity_zero():
    with get_connection() as conn:
        with conn.transaction(force_rollback=True):
            tenant_id = make_tenant(conn)
            actor_id = make_user(conn, tenant_id)
            wc = make_work_center(conn, tenant_id)
            finished = make_product(conn, tenant_id, name="Produit fini test")
            of_id = make_work_order(conn, tenant_id, product_id=finished, work_center_id=wc)

            run = {"id": "run-test-2", "of_id": of_id, "work_center_id": wc, "regrind_quantity": 0, "semolina_lines": []}
            result = ShiftStockService(conn).record_regrind(
                tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=None
            )
            assert result.value == {"scrap_record_id": None, "regrind_work_order_id": None}
```

Note: `scrap_type="shift_run"` (not `"daily_report"`) — this is a deliberate naming change so scrap records created by the new path are distinguishable from any pre-existing `"daily_report"`-typed rows during the transition. Confirm `production.scrap_records.scrap_type` has no CHECK constraint restricting its values before relying on this (grep `scrap_records` migrations); if it does, add `'shift_run'` to the allowed set in this task's migration-free scope is not possible — flag to the plan owner and use `"daily_report"` unchanged instead to avoid a schema change here.

- [ ] **Step 6: Run tests to verify they fail**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v`
Expected: FAIL with `AttributeError: 'ShiftStockService' object has no attribute 'record_regrind'`

- [ ] **Step 7: Implement `record_regrind`**

```python
    def record_regrind(
        self, *, tenant_id: str, actor_id: str, run: dict, regrind_work_center_id: str | None = None,
        quantity_override: float | None = None,
    ) -> Result[dict]:
        """Turn a run's rebroyat figure into a scrap record, and open the rebroyat
        OF it calls for. Ports ProductionReportService._record_regrind_scrap +
        _open_regrind_order combined -- same rule: the scrap product is always the
        tenant's one rebroyat default (never the run's own regrind_product_id,
        which is informational only), because every regrind batch resolves to
        that single product regardless of what fed it.
        """
        from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService, ScrapService

        quantity = quantity_override if quantity_override is not None else float(run.get("regrind_quantity") or 0)
        if quantity <= 0:
            return Ok({"scrap_record_id": None, "regrind_work_order_id": None})

        scrap_product_id = RegrindDefaultsService(self._connection).resolve_output_product(
            tenant_id=tenant_id, input_product_id=None
        )
        if scrap_product_id is None:
            return Err(
                "REGRIND_DEFAULT_MISSING",
                "no regrind output product is configured — set one in Production Settings before regrinding",
            )

        work_center_id = regrind_work_center_id or run.get("work_center_id")
        if work_center_id is None:
            row = self._connection.execute(
                "SELECT work_center_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (run["of_id"], tenant_id),
            ).fetchone()
            work_center_id = row[0] if row is not None else None
        if work_center_id is None:
            return Err("MISSING_WORK_CENTER", "cannot open a regrind order without a work center")

        scrap = ScrapService(self._connection).record_scrap(
            tenant_id=tenant_id, actor_id=actor_id, work_order_id=run["of_id"], work_center_id=work_center_id,
            scrap_type="shift_run", product_id=scrap_product_id, quantity=quantity,
            source_note=f"shift run {run['id']}",
        )
        if isinstance(scrap, Err):
            return scrap

        batch = RegrindService(self._connection).create_regrind_batch(
            tenant_id=tenant_id, actor_id=actor_id, scrap_record_ids=[scrap.value.id], work_center_id=work_center_id,
        )
        if isinstance(batch, Err):
            return batch
        return Ok({"scrap_record_id": scrap.value.id, "regrind_work_order_id": batch.value["work_order"].id})
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 9: Commit**

```bash
git add backend/modules/production/api/shift_stock_service.py backend/modules/production/api/test_shift_stock_service_integration.py
git commit -m "feat(production): add ShiftStockService.post_run/run_shortfalls/record_regrind on shift tables

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `ShiftStockService` — packing-side posting, DLC lot, packaging freeze, and reversal

**Files:**
- Modify: `backend/modules/production/api/shift_stock_service.py`
- Test: `backend/modules/production/api/test_shift_stock_service_integration.py`

**Interfaces:**
- Consumes: `Task 1`'s `ShiftStockService.__init__`, `_run_lines` pattern (mirror for packing).
- Consumes: `modules.production.domain.packaging_estimate.finished_quantity_from_count(*, packets_per_carton, carton_quantity, packets_counted, waste_carton_quantity) -> float` and `tonnage_from_count(*, net_weight_grams, packets_per_carton, carton_quantity, packets_counted, waste_carton_quantity) -> float` (both already exist, unchanged).
- Consumes: `core.api.service.CoreService(connection).get_product(tenant_id, product_id) -> Product | None` (has `.net_weight_grams`, `.packets_per_carton`).
- Consumes: `modules.warehouse.api.lot_service` (grep for the exact class — `report_product`'s research called it `LotService`; confirm `register_lot` signature by reading `warehouse/api/lot_service.py` before writing this task's code) `LotService(connection).register_lot(*, tenant_id, product_id, lot_number, actor_id, expiry_date, produced_at, source_type, source_id) -> Result[Lot]`.
- Produces: `ShiftStockService.freeze_packing_snapshot(self, *, tenant_id: str, packing_row: dict) -> dict` — returns `{"net_weight_grams": float | None, "packets_per_carton": float | None}`, writes those plus a computed tonnage onto `production.shift_packing_rows.snapshot_net_weight_grams`/`snapshot_packets_per_carton`/`finished_product_quantity` for that row id. Ports `conditionnement_service.freeze_packaging_parameters`.
- Produces: `ShiftStockService.packing_shortfalls(self, *, tenant_id: str, packing_row: dict) -> list[dict]`.
- Produces: `ShiftStockService.post_packing(self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, correlation_id: str, reverse: bool = False) -> Result[dict]` — returns `Ok({"movements": [...]})`, same shape as Task 1's `post_run`.
- Produces: `ShiftStockService.register_lot(self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, report_date) -> Result[str | None]` — returns `Ok(lot_id_or_None)`.
- Produces: `ShiftStockService.reverse_run(self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, force: bool = False, new_regrind_quantity: float | None = None, reason: str | None = None) -> Result[dict]` — combines `post_run(reverse=True)` + regrind unwind (ports `ProductionReportService._reverse_validated_effects` daily branch + `_unwind_regrind` + `_reconcile_closed_regrind_batch`, keyed on `run["id"]`/`scrap_type="shift_run"`/`source_note LIKE 'shift run {run.id}%'` instead of the old `daily_report {id}` pattern). Returns `Ok({"reversed_movements": [...], "removed_scrap_records": int, "reversed_regrind_stock": [...], "skip_regrind_rebuild": bool})`.
- Produces: `ShiftStockService.reverse_packing(self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, correlation_id: str) -> Result[dict]` — `post_packing(reverse=True)` only; packing rows have no regrind chain to unwind.
- Later tasks consume: all of the above from `ShiftValidationService` (Task 3).

- [ ] **Step 1: Write the failing test for packing-row posting and lot registration**

```python
def test_post_packing_receives_finished_and_issues_packaging_and_registers_lot():
    with get_connection() as conn:
        with conn.transaction(force_rollback=True):
            tenant_id = make_tenant(conn)
            actor_id = make_user(conn, tenant_id)
            wc = make_work_center(conn, tenant_id)
            finished = make_product(conn, tenant_id, name="Produit fini test", net_weight_grams=500, packets_per_carton=20)
            film = make_product(conn, tenant_id, name="Film test")
            fg_store = make_location(conn, tenant_id)
            pack_store = make_location(conn, tenant_id)
            of_id = make_work_order(conn, tenant_id, product_id=finished, work_center_id=wc)

            StockService(conn).receive_stock(
                tenant_id=tenant_id, product_id=film, location_id=pack_store, quantity=1000,
                correlation_id="seed", reference="test-seed", actor_id=actor_id,
            )

            packing_row = {
                "id": "pack-test-1", "of_id": of_id, "carton_quantity": 10, "packets_counted": 200,
                "waste_carton_quantity": 0, "film_quantity": 5, "carton_product_id": None,
                "film_product_id": film, "scotch_product_id": None, "ruban_product_id": None,
                "scotch_quantity": 0, "ruban_quantity": 0,
                "packaging_location_id": pack_store, "finished_goods_location_id": fg_store,
                "lot_number": "LOT-TEST-1", "dlc_date": None,
            }

            service = ShiftStockService(conn)
            snapshot = service.freeze_packing_snapshot(tenant_id=tenant_id, packing_row=packing_row)
            packing_row["snapshot_net_weight_grams"] = snapshot["net_weight_grams"]
            packing_row["snapshot_packets_per_carton"] = snapshot["packets_per_carton"]

            result = service.post_packing(
                tenant_id=tenant_id, actor_id=actor_id, packing_row=packing_row,
                finished_product_id=finished, correlation_id="corr-2",
            )
            assert result.value is not None, result
            movements = {m["product_id"]: m for m in result.value["movements"]}
            # carton tier present (packets_per_carton=20) -> carton_quantity(10)*20 = 200 packets = 100kg = 0.1t
            assert movements[finished]["direction"] == "in"
            assert movements[film]["direction"] == "out"
            assert movements[film]["quantity"] == 5

            lot = service.register_lot(
                tenant_id=tenant_id, actor_id=actor_id, packing_row=packing_row,
                finished_product_id=finished, report_date=datetime.date(2026, 9, 1),
            )
            assert lot.value is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v -k packing`
Expected: FAIL with `AttributeError: 'ShiftStockService' object has no attribute 'freeze_packing_snapshot'`

- [ ] **Step 3: Read `warehouse/api/lot_service.py` to confirm the exact `register_lot` signature**

Run: open `backend/modules/warehouse/api/lot_service.py` (or wherever `report_product.py`'s earlier research located it) and confirm the class name and exact keyword-argument names before writing Step 4 — the research pass named it `LotService.register_lot` but did not paste its exact signature. Adjust the Step 4 code below if the real signature differs (e.g. different param name for `produced_at`).

- [ ] **Step 4: Implement packing-side methods**

```python
    @staticmethod
    def _packing_lines(packing_row: dict) -> list[tuple[float, str]]:
        lines = [
            (float(packing_row.get("film_quantity") or 0), packing_row.get("film_product_id")),
            (float(packing_row.get("carton_quantity") or 0), packing_row.get("carton_product_id")),
            (float(packing_row.get("scotch_quantity") or 0), packing_row.get("scotch_product_id")),
            (float(packing_row.get("ruban_quantity") or 0), packing_row.get("ruban_product_id")),
        ]
        return [(quantity, product_id) for quantity, product_id in lines if quantity > 0 and product_id]

    def packing_shortfalls(self, *, tenant_id: str, packing_row: dict) -> list[dict]:
        shortfalls: list[dict] = []
        for quantity, product_id in self._packing_lines(packing_row):
            if self._stock.would_go_negative(
                tenant_id=tenant_id, product_id=product_id,
                location_id=packing_row["packaging_location_id"], quantity=quantity,
            ):
                shortfalls.append({"product_id": product_id, "location_id": packing_row["packaging_location_id"], "quantity": quantity})
        return shortfalls

    def freeze_packing_snapshot(self, *, tenant_id: str, packing_row: dict) -> dict:
        """Pin the packaging parameters a packing row is judged on, once, at
        validation. Ports conditionnement_service.freeze_packaging_parameters.
        """
        from core.api.service import CoreService
        from modules.production.domain.packaging_estimate import tonnage_from_count

        product = CoreService(self._connection).get_product(tenant_id, packing_row["of_id"] and packing_row.get("_finished_product_id") or None)
        # The caller resolves finished_product_id itself (see post_packing); here we
        # accept it explicitly to avoid a second product lookup ambiguity.
        raise NotImplementedError  # placeholder removed in the real implementation below
```

Discard that last `NotImplementedError` stub — it is a placeholder to signal that `freeze_packing_snapshot` needs `finished_product_id` as an explicit parameter, not inferred. Replace the whole method with:

```python
    def freeze_packing_snapshot(self, *, tenant_id: str, packing_row: dict, finished_product_id: str) -> dict:
        """Pin the packaging parameters a packing row is judged on, once, at
        validation. Ports conditionnement_service.freeze_packaging_parameters.
        """
        from core.api.service import CoreService
        from modules.production.domain.packaging_estimate import tonnage_from_count

        product = CoreService(self._connection).get_product(tenant_id, finished_product_id)
        net_weight_grams = product.net_weight_grams if product else None
        packets_per_carton = product.packets_per_carton if product else None
        finished_product_quantity = tonnage_from_count(
            net_weight_grams=net_weight_grams, packets_per_carton=packets_per_carton,
            carton_quantity=float(packing_row.get("carton_quantity") or 0),
            packets_counted=float(packing_row.get("packets_counted") or 0),
            waste_carton_quantity=float(packing_row.get("waste_carton_quantity") or 0),
        )
        self._connection.execute(
            "UPDATE production.shift_packing_rows SET snapshot_net_weight_grams = %s, "
            "snapshot_packets_per_carton = %s, finished_product_quantity = %s WHERE id = %s AND tenant_id = %s",
            (net_weight_grams, packets_per_carton, finished_product_quantity, packing_row["id"], tenant_id),
        )
        return {"net_weight_grams": net_weight_grams, "packets_per_carton": packets_per_carton}

    def post_packing(
        self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str,
        correlation_id: str, reverse: bool = False,
    ) -> Result[dict]:
        """Finished product in, packaging out. Ports ReportStockService.post_conditionnement_report.

        packets_per_carton comes from the row's own frozen snapshot (set by
        freeze_packing_snapshot at validation), never the product's current
        value, so reversing or correcting an old row always posts the same
        quantity it originally did.
        """
        from modules.production.domain.packaging_estimate import finished_quantity_from_count

        direction_in = "in" if not reverse else "out"
        direction_out = "out" if not reverse else "in"
        movements: list[dict] = []

        finished_quantity = finished_quantity_from_count(
            packets_per_carton=packing_row.get("snapshot_packets_per_carton"),
            carton_quantity=float(packing_row.get("carton_quantity") or 0),
            packets_counted=float(packing_row.get("packets_counted") or 0),
            waste_carton_quantity=float(packing_row.get("waste_carton_quantity") or 0),
        )
        if finished_quantity > 0:
            received = self._stock.post_production_movement(
                tenant_id=tenant_id, product_id=finished_product_id,
                location_id=packing_row["finished_goods_location_id"], quantity=finished_quantity,
                direction=direction_in, correlation_id=correlation_id,
                reference=f"shift_packing_row:{packing_row['id']}", move_type="production", actor_id=actor_id,
                source_type="production.shift_packing_row", source_id=packing_row["id"], of_id=packing_row["of_id"],
            )
            if isinstance(received, Err):
                return received
            movements.append({"direction": direction_in, "product_id": finished_product_id, "location_id": packing_row["finished_goods_location_id"], "quantity": finished_quantity})

        for quantity, product_id in self._packing_lines(packing_row):
            issued = self._stock.post_production_movement(
                tenant_id=tenant_id, product_id=product_id, location_id=packing_row["packaging_location_id"],
                quantity=quantity, direction=direction_out, correlation_id=correlation_id,
                reference=f"shift_packing_row:{packing_row['id']}", move_type="production_consumption", actor_id=actor_id,
                source_type="production.shift_packing_row", source_id=packing_row["id"], of_id=packing_row["of_id"],
            )
            if isinstance(issued, Err):
                return issued
            movements.append({"direction": direction_out, "product_id": product_id, "location_id": packing_row["packaging_location_id"], "quantity": quantity})

        return Ok({"movements": movements})

    def register_lot(
        self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, report_date,
    ) -> Result[str | None]:
        """Ports conditionnement_service.register_dlc_lot. Confirm LotService's
        real import path/signature (Step 3) before trusting this body verbatim."""
        import datetime as _dt
        from modules.warehouse.api.lot_service import LotService  # adjust path per Step 3 findings

        lot_number = packing_row.get("lot_number")
        if not lot_number:
            return Ok(None)
        lot = LotService(self._connection).register_lot(
            tenant_id=tenant_id, product_id=finished_product_id, lot_number=lot_number, actor_id=actor_id,
            expiry_date=packing_row.get("dlc_date"), produced_at=_dt.datetime.combine(report_date, _dt.time.min),
            source_type="production.shift_packing_row", source_id=packing_row["id"],
        )
        if isinstance(lot, Err):
            return lot
        return Ok(lot.value.id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v`
Expected: PASS

- [ ] **Step 6: Write the failing test for `reverse_run` unwinding an open (non-closed) regrind batch**

```python
def test_reverse_run_undoes_stock_and_removes_open_regrind_batch():
    with get_connection() as conn:
        with conn.transaction(force_rollback=True):
            tenant_id = make_tenant(conn)
            actor_id = make_user(conn, tenant_id)
            wc = make_work_center(conn, tenant_id)
            finished = make_product(conn, tenant_id, name="Produit fini test")
            regrind_output = make_product(conn, tenant_id, name="Rebroyat test")
            raw_store = make_location(conn, tenant_id)
            of_id = make_work_order(conn, tenant_id, product_id=finished, work_center_id=wc)
            conn.execute(
                "INSERT INTO production.regrind_defaults (tenant_id, input_product_id, output_product_id) VALUES (%s, NULL, %s)",
                (tenant_id, regrind_output),
            )
            StockService(conn).receive_stock(
                tenant_id=tenant_id, product_id=regrind_output, location_id=raw_store, quantity=0,
                correlation_id="seed2", reference="test-seed2", actor_id=actor_id,
            )

            run = {
                "id": "run-test-3", "of_id": of_id, "work_center_id": wc, "regrind_quantity": 8.0,
                "semolina_lines": [], "raw_material_location_id": None,
            }
            service = ShiftStockService(conn)
            posted = service.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id="corr-3")
            assert posted.value is not None
            regrind = service.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=None)
            assert regrind.value["regrind_work_order_id"] is not None

            reversed_result = service.reverse_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id="corr-3-rev")
            assert reversed_result.value is not None, reversed_result
            assert reversed_result.value["removed_scrap_records"] == 1

            remaining_order = conn.execute(
                "SELECT 1 FROM production.work_orders WHERE id = %s", (regrind.value["regrind_work_order_id"],)
            ).fetchone()
            assert remaining_order is None
```

- [ ] **Step 7: Run test to verify it fails**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v -k reverse_run`
Expected: FAIL with `AttributeError: 'ShiftStockService' object has no attribute 'reverse_run'`

- [ ] **Step 8: Implement `reverse_run` and `reverse_packing`**

Port `ProductionReportService._reverse_validated_effects` (daily branch only), `_unwind_regrind`, and `_reconcile_closed_regrind_batch` verbatim, with these substitutions throughout: `header.id` → `run["id"]`, `header.of_id` → `run["of_id"]`, the `scrap_type = 'daily_report'` filter → `scrap_type = 'shift_run'`, and the `source_note LIKE 'daily report {id}%'` filter → `source_note LIKE 'shift run {id}%'`. Keep every comment from the original (the rebroyat-chain docstrings explaining `force`, the closed-batch reconciliation three-way split) — these encode invariants, not just narration.

```python
    def reverse_run(
        self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, force: bool = False,
        new_regrind_quantity: float | None = None, reason: str | None = None,
    ) -> Result[dict]:
        """Undo everything validating this run caused. Ports
        ProductionReportService._reverse_validated_effects (daily branch).
        """
        undone = self.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, reverse=True)
        if isinstance(undone, Err):
            return undone

        unwound = self._unwind_regrind(
            tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, force=force,
            new_regrind_quantity=new_regrind_quantity, reason=reason,
        )
        if isinstance(unwound, Err):
            return unwound

        return Ok({
            "reversed_movements": undone.value,
            "removed_scrap_records": unwound.value["removed_scrap_records"],
            "reversed_regrind_stock": unwound.value["reversed_regrind_stock"],
            "skip_regrind_rebuild": unwound.value.get("skip_regrind_rebuild", False),
        })

    def reverse_packing(
        self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, correlation_id: str,
    ) -> Result[dict]:
        undone = self.post_packing(
            tenant_id=tenant_id, actor_id=actor_id, packing_row=packing_row,
            finished_product_id=finished_product_id, correlation_id=correlation_id, reverse=True,
        )
        if isinstance(undone, Err):
            return undone
        return Ok({"reversed_movements": undone.value})

    def _unwind_regrind(
        self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, force: bool = False,
        new_regrind_quantity: float | None = None, reason: str | None = None,
    ) -> Result[dict]:
        """Remove the scrap and regrind OF this run's validation created.

        A batch already ground and received into stock is refused unless force
        is set -- its output physically exists, so silently deleting the order
        underneath it would leave stock nobody can explain. force posts the
        mirror movement that undoes the receipt before removing the batch, its
        inputs and the work order itself.

        new_regrind_quantity marks the "correct a validated run" caller: there,
        a closed batch isn't refused outright -- it's reconciled against the
        corrected figure instead. reverse_run never passes it, so its behavior
        here is unchanged from a plain reversal.
        """
        scrap_rows = self._connection.execute(
            """
            SELECT id FROM production.scrap_records
            WHERE tenant_id = %s AND work_order_id = %s AND scrap_type = 'shift_run'
              AND source_note LIKE %s
            """,
            (tenant_id, run["of_id"], f"shift run {run['id']}%"),
        ).fetchall()
        if not scrap_rows:
            return Ok({"removed_scrap_records": 0, "reversed_regrind_stock": [], "skip_regrind_rebuild": False})
        scrap_ids = [row[0] for row in scrap_rows]

        batch_rows = self._connection.execute(
            """
            SELECT DISTINCT rbi.regrind_batch_work_order_id, wo.status, wo.product_id, rb.actual_output_quantity,
                   rb.input_quantity_total
            FROM production.regrind_batch_inputs rbi
            JOIN production.work_orders wo ON wo.id = rbi.regrind_batch_work_order_id
            JOIN production.regrind_batches rb ON rb.work_order_id = rbi.regrind_batch_work_order_id
            WHERE rbi.scrap_record_id = ANY(%s)
            """,
            (scrap_ids,),
        ).fetchall()

        if new_regrind_quantity is not None:
            return self._reconcile_closed_regrind_batch(
                tenant_id=tenant_id, actor_id=actor_id, run=run, force=force, reason=reason,
                new_regrind_quantity=new_regrind_quantity, batch_rows=batch_rows,
            )

        if not force:
            for _, batch_status, _, _, _ in batch_rows:
                if batch_status == "closed":
                    return Err(
                        "REGRIND_ALREADY_COMPLETED",
                        "the rebroyat order this run opened has already been ground and received into stock;"
                        " it cannot be unwound automatically",
                    )

        from modules.warehouse.api.service import StockService as _StockService

        stock = _StockService(self._connection)
        reversed_regrind_stock: list[dict] = []
        for batch_of_id, batch_status, product_id, actual_output_quantity, _ in batch_rows:
            if batch_status != "closed" or actual_output_quantity is None or float(actual_output_quantity) <= 0:
                continue
            receipt = stock.list_stock_moves(
                tenant_id=tenant_id, product_id=product_id, move_type="production",
                reference=f"work_order:{batch_of_id}", limit=1,
            )
            if not receipt:
                return Err(
                    "REGRIND_STOCK_MOVE_NOT_FOUND",
                    f"no stock receipt found for regrind order {batch_of_id}; refusing to force-delete blind",
                )
            location_id = receipt[0]["location_id"]
            quantity = float(actual_output_quantity)
            reversed_move = stock.post_production_movement(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id, quantity=quantity,
                direction="out", correlation_id=correlation_id, reference=f"work_order:{batch_of_id}:reversed",
                move_type="production_reversal", actor_id=actor_id,
                source_type="production.regrind_batch", source_id=batch_of_id, of_id=batch_of_id,
            )
            if isinstance(reversed_move, Err):
                return reversed_move
            reversed_regrind_stock.append({"work_order_id": batch_of_id, "product_id": product_id, "location_id": location_id, "quantity": quantity})

        for batch_of_id, _, _, _, _ in batch_rows:
            self._connection.execute("DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s", (batch_of_id,))
            self._connection.execute("DELETE FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s", (batch_of_id, tenant_id))
            self._connection.execute("DELETE FROM production.work_orders WHERE id = %s AND tenant_id = %s", (batch_of_id, tenant_id))

        self._connection.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (scrap_ids,))
        return Ok({"removed_scrap_records": len(scrap_ids), "reversed_regrind_stock": reversed_regrind_stock, "skip_regrind_rebuild": False})

    def _reconcile_closed_regrind_batch(
        self, *, tenant_id: str, actor_id: str, run: dict, force: bool, reason: str | None,
        new_regrind_quantity: float, batch_rows: list,
    ) -> Result[dict]:
        """Compare a correction's rebroyat figure against a closed batch instead
        of refusing it outright. Only a closed batch needs this: an open one
        never received stock, so it can still be unwound and rebuilt exactly
        like the normal path. A closed one's output physically exists, so the
        three ways the figure can move are handled instead of blocked:
          - unchanged: leave the batch alone.
          - higher: a second, independent order is opened for just the
            difference -- confirmed first via force.
          - lower: on-hand is reduced by the difference instead, carrying the
            correction's own reason for the audit trail.
        """
        closed = [row for row in batch_rows if row[1] == "closed"]
        other = [row for row in batch_rows if row[1] != "closed"]

        if len(closed) > 1:
            return Err("REGRIND_MULTIPLE_CLOSED_BATCHES", "more than one closed rebroyat order is tied to this run; resolve manually")

        removed_scrap = 0
        if other:
            other_scrap_rows = self._connection.execute(
                "SELECT scrap_record_id FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = ANY(%s)",
                ([row[0] for row in other],),
            ).fetchall()
            other_scrap_ids = [row[0] for row in other_scrap_rows]
            for batch_of_id, _, _, _, _ in other:
                self._connection.execute("DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s", (batch_of_id,))
                self._connection.execute("DELETE FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s", (batch_of_id, tenant_id))
                self._connection.execute("DELETE FROM production.work_orders WHERE id = %s AND tenant_id = %s", (batch_of_id, tenant_id))
            if other_scrap_ids:
                self._connection.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (other_scrap_ids,))
            removed_scrap = len(other_scrap_ids)

        if not closed:
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": False})

        batch_of_id, _, product_id, _, input_quantity_total = closed[0]
        input_quantity_total = float(input_quantity_total)
        delta = new_regrind_quantity - input_quantity_total

        if abs(delta) < 1e-6:
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": True})

        if delta > 0:
            if not force:
                return Err(
                    "REGRIND_DELTA_REQUIRES_NEW_ORDER",
                    f"the rebroyat order this run opened already ground {input_quantity_total:g} kg and is"
                    f" closed; the corrected {new_regrind_quantity:g} kg is {delta:g} kg more — confirm to open a"
                    " new rebroyat order for the difference",
                )
            scrap = self.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=None, quantity_override=delta)
            if isinstance(scrap, Err):
                return scrap
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": True})

        from modules.warehouse.api.service import StockService as _StockService

        stock = _StockService(self._connection)
        receipt = stock.list_stock_moves(tenant_id=tenant_id, product_id=product_id, move_type="production", reference=f"work_order:{batch_of_id}", limit=1)
        if not receipt:
            return Err("REGRIND_STOCK_MOVE_NOT_FOUND", f"no stock receipt found for regrind order {batch_of_id}; refusing to adjust stock blind")
        location_id = receipt[0]["location_id"]
        adjusted = stock.adjust_stock(
            tenant_id=tenant_id, product_id=product_id, location_id=location_id, delta=delta,
            reason=reason or "shift run correction", actor_id=actor_id,
            reference=f"work_order:{batch_of_id}:shift_run_correction:{run['id']}",
        )
        if isinstance(adjusted, Err):
            return adjusted
        return Ok({
            "removed_scrap_records": removed_scrap,
            "reversed_regrind_stock": [{"work_order_id": batch_of_id, "product_id": product_id, "location_id": location_id, "quantity": delta}],
            "skip_regrind_rebuild": True,
        })
```

Note: `record_regrind` needs a `quantity_override` parameter added (Task 1 did not include it) — add `quantity_override: float | None = None` to its signature from Task 1 and use `quantity_override if quantity_override is not None else float(run.get("regrind_quantity") or 0)` (this was already written that way in Task 1 Step 7 — just confirm it's there).

- [ ] **Step 9: Run all tests to verify they pass**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_stock_service_integration.py -v`
Expected: PASS (all tests)

- [ ] **Step 10: Commit**

```bash
git add backend/modules/production/api/shift_stock_service.py backend/modules/production/api/test_shift_stock_service_integration.py
git commit -m "feat(production): add packing-side posting, DLC lot registration, and reversal to ShiftStockService

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Rewire `ShiftValidationService` onto `ShiftStockService`

**Files:**
- Modify: `backend/modules/production/api/shift_validation_service.py`
- Existing test (must stay green, do not modify its assertions): `backend/modules/production/api/test_shift_validation_integration.py`

**Interfaces:**
- Consumes: everything produced in Task 1 + Task 2 (`ShiftStockService.post_run`, `run_shortfalls`, `record_regrind`, `freeze_packing_snapshot`, `post_packing`, `register_lot`, `packing_shortfalls`, `reverse_run`, `reverse_packing`).
- Consumes: `modules.production.api.report_product.stamp_order_products` (unchanged, already shift-native).
- Produces: `ShiftValidationService.validate_shift` and `reverse_shift` keep their exact existing signatures and `Result[dict]` return shape (`self._shifts.get_shift(...)` on success) — this task changes internals only, not the public contract, so `test_shift_validation_integration.py` needs zero changes to its assertions, only possibly to its fixtures if they inspected `production_reports` rows directly (check for that; if found, update those specific assertions to inspect `shift_runs`/`shift_packing_rows` and stock moves by `source_type = 'production.shift_run'` instead).

- [ ] **Step 1: Read the current `test_shift_validation_integration.py` in full**

Before changing anything, read `backend/modules/production/api/test_shift_validation_integration.py` completely and note every place it queries `production.production_reports`, `daily_reports`, or `conditionnement_reports` directly (as opposed to calling `ShiftValidationService`/`ShiftReportService` methods). List those line numbers — you will need to update just those specific assertions in Step 5, nothing else in the file.

- [ ] **Step 2: Run the existing suite to confirm it is currently green (baseline)**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_validation_integration.py -v`
Expected: PASS (all tests) — this is your baseline; every test must still pass after this task, possibly with the direct-old-table assertions from Step 1 rewritten to check shift tables/stock moves instead.

- [ ] **Step 3: Rewrite `validate_shift`'s posting loop**

Replace the body from `materialised = materialize_shift(...)` through the `for report_id, _report_type in materialised.value:` loop with:

```python
        correlation_id = correlation_id or str(ULID())
        try:
            with self._connection.transaction():
                stamp_order_products(self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id)

                runs = _rows(self._connection, tenant_id, shift_report_id, "shift_runs")
                packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
                if not runs and not packing:
                    raise _Abort(Err("NOTHING_TO_VALIDATE", "the shift has no production run and no packing row to validate"))

                open_stop = self._connection.execute(
                    "SELECT 1 FROM production.machine_stops WHERE shift_report_id = %s AND tenant_id = %s AND ended_at IS NULL LIMIT 1",
                    (shift_report_id, tenant_id),
                ).fetchone()
                if open_stop is not None:
                    raise _Abort(Err("OPEN_STOP", "a machine stop is still ongoing; end it before validating the shift"))

                stock = ShiftStockService(self._connection)
                shortfalls: list[dict] = []
                for run in runs:
                    run["semolina_lines"] = _rows(self._connection, tenant_id, run["id"], "shift_run_semolina_lines", by="run_id")
                    shortfalls += stock.run_shortfalls(tenant_id=tenant_id, run=run)
                for row in packing:
                    shortfalls += stock.packing_shortfalls(tenant_id=tenant_id, packing_row=row)
                if shortfalls and not (shortfall_comment or "").strip():
                    raise _Abort(Err(
                        "SHORTFALL_COMMENT_REQUIRED",
                        "this shift consumes more than the stock figure holds; validating it needs a comment explaining why",
                    ))

                for run in runs:
                    posted = stock.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id)
                    if isinstance(posted, Err):
                        raise _Abort(posted)
                    regrind = stock.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=regrind_work_center_id)
                    if isinstance(regrind, Err):
                        raise _Abort(regrind)

                order_products = {
                    row[0]: row[1]
                    for row in self._connection.execute(
                        "SELECT id, product_id FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
                        (tenant_id, list({p["of_id"] for p in packing})),
                    ).fetchall()
                } if packing else {}
                for row in packing:
                    finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
                    if finished_product_id is None:
                        raise _Abort(Err("NOT_FOUND", f"work order {row['of_id']} has no product to pack"))
                    stock.freeze_packing_snapshot(tenant_id=tenant_id, packing_row=row, finished_product_id=finished_product_id)
                    row["snapshot_packets_per_carton"] = stock.freeze_packing_snapshot(tenant_id=tenant_id, packing_row=row, finished_product_id=finished_product_id)["packets_per_carton"]
                    posted = stock.post_packing(tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id, correlation_id=correlation_id)
                    if isinstance(posted, Err):
                        raise _Abort(posted)
                    lot = stock.register_lot(tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id, report_date=shift_date)
                    if isinstance(lot, Err):
                        raise _Abort(lot)
```

Fix the double-call bug visible above before committing: `freeze_packing_snapshot` is called twice in that draft (once for its return value, once assigning `row["snapshot_packets_per_carton"]`). Call it once, capture the dict, and read both keys off the single result:

```python
                for row in packing:
                    finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
                    if finished_product_id is None:
                        raise _Abort(Err("NOT_FOUND", f"work order {row['of_id']} has no product to pack"))
                    snapshot = stock.freeze_packing_snapshot(tenant_id=tenant_id, packing_row=row, finished_product_id=finished_product_id)
                    row["snapshot_packets_per_carton"] = snapshot["packets_per_carton"]
                    posted = stock.post_packing(tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id, correlation_id=correlation_id)
                    if isinstance(posted, Err):
                        raise _Abort(posted)
                    lot = stock.register_lot(tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id, report_date=shift_date)
                    if isinstance(lot, Err):
                        raise _Abort(lot)
```

You need `shift_date` in scope: fetch it alongside the shift's status lock at the top of `validate_shift` (`SELECT status, report_date FROM production.shift_reports WHERE id = %s AND tenant_id = %s FOR UPDATE`) instead of the current status-only query, and unpack both.

Add the module-level helper `_rows` (a thin wrapper the same shape as `legacy_report_ledger._rows`, since this file no longer imports that module):

```python
def _rows(connection: psycopg.Connection, tenant_id: str, key: str, table: str, by: str = "shift_report_id") -> list[dict]:
    cursor = connection.execute(
        f"SELECT * FROM production.{table} WHERE {by} = %s AND tenant_id = %s ORDER BY line_order, id", (key, tenant_id)
    )
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]
```

Then delete the now-dead block that copied `conditionnement_reports` snapshot fields back onto `shift_packing_rows` (the `UPDATE production.shift_packing_rows p ... FROM production.conditionnement_reports c ...` statement) — `freeze_packing_snapshot` now writes those columns directly on `shift_packing_rows`, so that copy-back is redundant and references a table this task is phasing out.

Update the imports at the top of the file: remove `from modules.production.api.legacy_report_ledger import materialize_shift` and `from modules.production.api.production_report_service import ProductionReportService`; add `from modules.production.api.shift_stock_service import ShiftStockService`.

- [ ] **Step 4: Rewrite `reverse_shift`'s undo loop**

Replace the body from `reports = ProductionReportService(self._connection)` through the `for report_id in [*packing, *runs]:` loop with:

```python
                stock = ShiftStockService(self._connection)
                packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
                runs = _rows(self._connection, tenant_id, shift_report_id, "shift_runs")
                order_products = {
                    row[0]: row[1]
                    for row in self._connection.execute(
                        "SELECT id, product_id FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
                        (tenant_id, list({p["of_id"] for p in packing})),
                    ).fetchall()
                } if packing else {}
                # Packing first: mirrors the old ordering ("a packing report points at the daily report it drew from").
                for row in packing:
                    finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
                    result = stock.reverse_packing(
                        tenant_id=tenant_id, actor_id=actor_id, packing_row=row,
                        finished_product_id=finished_product_id, correlation_id=correlation_id,
                    )
                    if isinstance(result, Err):
                        raise _Abort(result)
                for run in runs:
                    result = stock.reverse_run(
                        tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, force=force,
                    )
                    if isinstance(result, Err):
                        raise _Abort(result)
```

Drop the `runs, packing = self._report_ids(tenant_id, shift_report_id)` line above the `try:` block (no longer needed — rows are fetched inline now) and drop the now-unused `_report_ids` method entirely if nothing else in the file calls it (grep the file first to confirm).

- [ ] **Step 5: Update any test assertions found in Step 1 that queried old tables directly**

For each line noted in Step 1, replace `production.production_reports`/`daily_reports`/`conditionnement_reports` queries with the shift-table or stock-move equivalent — e.g. a check that once did `SELECT status FROM production.production_reports WHERE id = %s` (a run's old-shaped id) becomes a check against `warehouse.stock_moves WHERE source_type = 'production.shift_run' AND source_id = %s` for "did this run post stock", or simply relies on `ShiftValidationService.validate_shift`'s returned dict, whichever the original assertion was actually testing for.

- [ ] **Step 6: Run the full existing suite**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_validation_integration.py -v`
Expected: PASS (all tests, same count as the Step 2 baseline)

- [ ] **Step 7: Run the five Review Focus scenarios explicitly**

If `test_shift_validation_integration.py` does not already cover all five bullets in this plan's **Review Focus** section, add one test per uncovered bullet now (two-run mold-change reversal, closed-regrind-batch force-refusal, shortfall-comment gate, carton-count-wins packing quantity, empty-shift day-sheet — this last one belongs in Task 4, skip it here). Run the suite again and confirm all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/production/api/shift_validation_service.py backend/modules/production/api/test_shift_validation_integration.py
git commit -m "refactor(production): validate/reverse shift via ShiftStockService instead of legacy_report_ledger bridge

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Port `DaySheetService` off the old tables

**Files:**
- Modify: `backend/modules/production/api/day_sheet_service.py`
- Existing test (must stay green): `backend/modules/production/api/test_day_sheet_integration.py`

**Interfaces:**
- Consumes: `modules.production.domain.day_sheet.DailyFact`, `PackingFact`, `build_rows` — **unchanged**, this task only changes what SQL builds these dataclasses, not the dataclasses or `build_rows` itself.
- Produces: `DaySheetService.get_day_sheet` and `get_month_recap` keep their exact existing signatures and return shapes.

- [ ] **Step 1: Read the current `test_day_sheet_integration.py` in full**

Note every fixture that seeds data via `ProductionReportService`/old tables directly rather than through `ShiftReportService` + `ShiftValidationService` — these fixtures must be switched to seed shift reports and validate them through the real Task 3 path instead, since `DaySheetService` will no longer see old-table rows at all.

- [ ] **Step 2: Run the existing suite to confirm baseline green**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_day_sheet_integration.py -v`
Expected: PASS (baseline)

- [ ] **Step 3: Rewrite `_reports` to read shift tables**

```python
    def _reports(
        self, tenant_id: str, date_from: datetime.date, date_to: datetime.date, work_center_id: str
    ) -> list[dict]:
        """One row per shift_run or shift_packing_row in range, in the shape the
        rest of this file already expects ('type' 'daily'|'conditionnement',
        matching the old report_type vocabulary so build_rows and its callers
        need no changes).
        """
        rows = self._connection.execute(
            """
            SELECT r.id, 'daily' AS type, sr.shift, sr.team, sr.status, r.of_id, o.product_id, r.id AS run_id
            FROM production.shift_runs r
            JOIN production.shift_reports sr ON sr.id = r.shift_report_id AND sr.tenant_id = r.tenant_id
            LEFT JOIN production.work_orders o ON o.id = r.of_id AND o.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND sr.report_date BETWEEN %s AND %s
              AND sr.work_center_id = %s AND sr.status = ANY(%s)
            UNION ALL
            SELECT p.id, 'conditionnement' AS type, sr.shift, sr.team, sr.status, p.of_id,
                   COALESCE(p.product_id, o.product_id), p.id AS run_id
            FROM production.shift_packing_rows p
            JOIN production.shift_reports sr ON sr.id = p.shift_report_id AND sr.tenant_id = p.tenant_id
            LEFT JOIN production.work_orders o ON o.id = p.of_id AND o.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND sr.report_date BETWEEN %s AND %s
              AND sr.work_center_id = %s AND sr.status = ANY(%s)
            ORDER BY 1
            """,
            (
                tenant_id, date_from, date_to, work_center_id, list(_WITH_PENDING),
                tenant_id, date_from, date_to, work_center_id, list(_WITH_PENDING),
            ),
        ).fetchall()
        return [
            {"id": i, "type": kind, "shift": shift, "team": team, "status": state, "of_id": of_id, "of_product_id": product_id}
            for i, kind, shift, team, state, of_id, product_id, _run_id in rows
        ]
```

Check `production.shift_packing_rows` has a `product_id` column (the earlier research on `shift_packing_rows` schema and the M1 memory note "OF product from shift... packing rows name their product" both suggest it does — confirm with `grep -n "product_id" backend/modules/production/migrations/0055_production_packing_product.sql` before trusting the `COALESCE(p.product_id, o.product_id)` above; adjust column name if the migration used a different one).

- [ ] **Step 4: Rewrite `_read_sheet`'s data-fetch section**

Replace the `daily_rows`, `semolina_rows`, `downtime_rows`, `waste_rows`, `packing_rows` queries (the block from `daily_rows = self._rows_for(...)` through `packing_rows = self._rows_for(...)`) with shift-table equivalents. Keep every downstream line (`wanted = {...}`, `tonnes(...)`, `in_base_unit(...)`, the `daily_facts`/`packing_facts` construction, `build_rows(...)`) **completely unchanged** — they operate on the same tuple shapes, just sourced differently:

```python
        daily_rows = self._rows_for(
            """
            SELECT r.id, r.water_quantity, r.production_minutes,
                   COALESCE(e.fuel_quantity, 0), COALESCE(e.gasoil_quantity, 0),
                   COALESCE(e.electricity_quantity, 0), COALESCE(e.generator_hours, 0),
                   r.regrind_input_quantity, r.regrind_input_product_id
            FROM production.shift_runs r
            LEFT JOIN production.shift_energy e ON e.shift_report_id = r.shift_report_id
            WHERE r.tenant_id = %s AND r.id = ANY(%s)
            """,
            tenant_id, daily_ids,
        )
        semolina_rows = self._rows_for(
            "SELECT run_id, product_id, quantity FROM production.shift_run_semolina_lines "
            "WHERE tenant_id = %s AND run_id = ANY(%s) ORDER BY run_id, line_order",
            tenant_id, daily_ids,
        )
        downtime_rows = self._rows_for(
            """
            SELECT COALESCE(run_id, packing_row_id) AS report_id, SUM(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60)
            FROM production.machine_stops
            WHERE tenant_id = %s AND run_id = ANY(%s) AND ended_at IS NOT NULL
            GROUP BY run_id, packing_row_id
            """,
            tenant_id, daily_ids,
        )
        waste_rows = self._rows_for(
            """
            SELECT COALESCE(run_id, packing_row_id) AS report_id, category, product_id, quantity
            FROM production.shift_waste_lines
            WHERE tenant_id = %s AND COALESCE(run_id, packing_row_id) = ANY(%s)
            ORDER BY report_id, line_order
            """,
            tenant_id, daily_ids + packing_ids,
        )
        packing_rows = self._rows_for(
            """
            SELECT id, finished_product_quantity, packets_counted, film_quantity, carton_quantity,
                   waste_carton_quantity, scotch_quantity, ruban_quantity, lot_number,
                   film_product_id, carton_product_id, scotch_product_id, ruban_product_id
            FROM production.shift_packing_rows WHERE tenant_id = %s AND id = ANY(%s)
            """,
            tenant_id, packing_ids,
        )
```

Note the `downtime_rows` query is a semantic change from the old per-report `report_downtime_lines.minutes` sum to computing minutes from `machine_stops.started_at`/`ended_at` directly — this is correct (shift tables never stored a precomputed minutes column, `machine_stops` is the source of truth), but double check the `GROUP BY run_id, packing_row_id` / `SELECT COALESCE(...)` combination is valid Postgres (it is, since both grouping columns are selected via the `COALESCE` in the SELECT list only — Postgres requires the grouping columns themselves in GROUP BY, which this has). Also note `waste_rows`' `report_id` column name is kept identical to the old query's output shape (`report_id`) even though it is now `COALESCE(run_id, packing_row_id)` — downstream code at `for report_id, category, product_id, quantity in waste_rows:` depends on this exact column order and name being unchanged.

Also change `daily_ids`/`packing_ids` construction just above this block from `[r["id"] for r in figures if r["type"] == "daily"]` — no change needed there, `_reports` already returns `"type": "daily"|"conditionnement"` in the new query, so this line is untouched.

- [ ] **Step 5: Rewrite `_present_pending_shifts` to drop the `materialize_shift` call**

Since `_reports` now reads shift tables directly (open/submitted/validated all live natively in `shift_runs`/`shift_packing_rows`, no materialization needed to "present" them), delete `_present_pending_shifts` entirely and delete its call site in `read_sheet` (the `with self._connection.transaction(force_rollback=True): self._present_pending_shifts(...)` wrapper collapses to just calling `_read_sheet` directly — no savepoint needed either, since nothing is being written provisionally anymore):

```python
    def read_sheet(
        self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date, work_center_id: str,
        include_pending: bool, column_of: Callable[[dict], str], yield_by_column: bool = False,
    ) -> dict:
        return self._read_sheet(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to, work_center_id=work_center_id,
            include_pending=include_pending, column_of=column_of, yield_by_column=yield_by_column,
        )
```

Remove the now-unused imports `from modules.production.api.legacy_report_ledger import materialize_shift`.

- [ ] **Step 6: Handle the "empty shift, no runs/packing yet" case (Review Focus item)**

Confirm the new `_reports` query naturally returns zero rows for a shift with nothing filed yet (it will, since it's a plain join with no `materialize_shift` side effects to skip) — this means the Review Focus concern ("must not crash building a DailyFact/PackingFact from zero rows") is satisfied by construction, since `figures` will simply have no entry for that shift and no `DailyFact`/`PackingFact` is built for it at all. Add a test confirming this explicitly:

```python
def test_open_shift_with_no_runs_produces_no_phantom_column():
    with get_connection() as conn:
        with conn.transaction(force_rollback=True):
            tenant_id = make_tenant(conn)
            actor_id = make_user(conn, tenant_id)
            wc = make_work_center(conn, tenant_id)
            shifts = ShiftReportService(conn)
            shifts.open_shift(
                tenant_id=tenant_id, actor_id=actor_id, work_center_id=wc,
                report_date=datetime.date(2026, 9, 1), shift="morning", team="Équipe A",
            )
            result = DaySheetService(conn).get_day_sheet(
                tenant_id=tenant_id, date=datetime.date(2026, 9, 1), work_center_id=wc, include_pending=True,
            )
            assert result.value is not None
            morning_column = next(c for c in result.value["columns"] if c["key"] == "morning")
            assert morning_column["reports"]["daily"] == {"validated": 0, "pending": 0}
```

- [ ] **Step 7: Run the full test suite**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production/api/test_day_sheet_integration.py -v`
Expected: PASS (all tests including the new one)

- [ ] **Step 8: Commit**

```bash
git add backend/modules/production/api/day_sheet_service.py backend/modules/production/api/test_day_sheet_integration.py
git commit -m "refactor(production): read the day sheet from shift tables instead of legacy reports

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Remove old routes, permissions, and module registration

**Files:**
- Modify: `backend/modules/production/api/router.py`
- Modify: `backend/modules/production/module.json`
- Test: whichever router-level test file exercises `/reports/*` (find via `grep -rl "reports/daily\|reports/conditionnement" backend/modules/production/api/test_*.py`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `/reports/daily`, `/reports/conditionnement`, `/reports/{report_id}` (GET/DELETE), `/reports/{report_id}/submit|validate|reject|revise`, `/reports/{report_id}/packaging-variance` no longer exist as routes. `/reports/team-performance`, `/reports/machine-performance`, `/reports/downtime-reasons`, `/reports/downtime-breakdown`, `/reports/consumption-by-supplier(+/export)`, `/reports/daily-recap/*` (the analytics routes) **stay** — confirm in Task 6 whether their backing services (`*_analytics_service.py`) read old tables (if so, that is separate follow-up work out of this plan's scope; flag it, do not silently break analytics here).

- [ ] **Step 1: Grep for every route this task must remove and confirm no other file still calls them**

Run: `grep -n "reports/daily\|reports/conditionnement\|/reports/{report_id}" "d:\mahmoud repo\Sonalim_ERP\backend\modules\production\api\router.py"` and cross check against the frontend (`grep -rn "reports/daily\|reports/conditionnement" "d:\mahmoud repo\Sonalim_ERP\frontend\src"`) — the frontend grep must come back empty or only match files already slated for deletion in Task 9. If it finds a live caller outside `DailyReportsTab.tsx`/`ConditionnementTab.tsx`, stop and report back rather than removing the route out from under it.

- [ ] **Step 2: Remove the routes and their handler functions from `router.py`**

Delete the route decorators and handler bodies for the paths confirmed in Step 1. Keep the analytics routes (`team-performance`, `machine-performance`, `downtime-reasons`, `downtime-breakdown`, `consumption-by-supplier`, `daily-recap/*`) untouched for now.

- [ ] **Step 3: Remove old permissions and service registrations from `module.json`**

Remove `production.manage_reports`, `production.validate_reports`, `production.admin_reports` permission entries and the `ProductionReportService`/`ConditionnementReportService` service registrations, but only if nothing else in the module still references them — grep first: `grep -rn "production.manage_reports\|production.validate_reports\|production.admin_reports" "d:\mahmoud repo\Sonalim_ERP\backend"`. If the analytics routes kept in Step 2 are gated by `production.view_reports`, leave `production.view_reports` alone (it is not in the removal list).

- [ ] **Step 4: Update or remove the router-level test file(s) found via the Step 1 grep pattern**

Remove test cases that hit the deleted routes; keep any that test the surviving analytics routes.

- [ ] **Step 5: Run the production module's full backend test suite**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest modules/production -v 2>&1 | tail -60`
Expected: all tests referencing deleted routes are gone (not failing — gone); everything else still PASS. Some failures are expected here from files Task 7 will fix — note which ones and move on; do not fix them in this task.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/production/api/router.py backend/modules/production/module.json
git commit -m "feat(production): remove old /reports/daily and /reports/conditionnement routes and permissions

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Confirm and scope analytics services' dependency on old tables

**Files:**
- Read-only investigation, no changes in this task unless the finding is trivial (see Step 3).

**Interfaces:** none produced; this task's output is a decision recorded in the plan (Step 3) that Task 7/8 depend on.

**Amended during Task 3 execution (ledgered ruling):** `of_consolidation_service.py` was found reading `production.daily_reports` for per-run `fuel_quantity`/`gasoil_quantity`/`electricity_quantity`/`generator_hours` — a fourth file with the same class of gap as the three named below, missed by the original survey. Added to this task's scope. Concretely: `shift_energy` already holds the *whole-shift* totals (never split by run — the per-run split was `legacy_report_ledger.materialize_shift`'s own `split_proportionally` call, a presentation-time computation for the old reader, not stored anywhere on the shift tables themselves). Porting `of_consolidation_service.py` means either (a) it reads `shift_energy` directly and sums/uses whole-shift totals instead of a per-run split, if its consumers don't actually need the per-run granularity, or (b) `ShiftStockService`/`ShiftValidationService` needs to persist a per-run energy split onto `shift_runs` (e.g. new columns) if per-run granularity is a real product requirement. Step 1 below must determine which.

- [ ] **Step 1: Check whether `production_analytics_service.py`, `daily_recap_export.py`, `report_period_service.py`, `of_consolidation_service.py` read old tables**

Read `backend/modules/production/api/production_analytics_service.py`, `daily_recap_export.py`, `report_period_service.py`, `of_consolidation_service.py` in full. For each, note every SQL query's `FROM`/`JOIN` targets. For `of_consolidation_service.py` specifically, determine whether its per-OF energy rollup is read anywhere that would notice the difference between a per-run split and a whole-shift total divided evenly (or attributed to the OF's own runs by minutes, recomputed at read time rather than stored) — if nothing depends on run-level precision, option (a) above is far cheaper than (b).

- [ ] **Step 2: Decide scope based on findings**

If any of these three files query `production.production_reports`/`daily_reports`/`conditionnement_reports`, this plan has two options and the plan owner (the person running this plan) must pick one before Task 8 can drop the old tables:
  (a) extend this plan with a Task 6b to port that specific service to shift tables (write it the same way Task 4 was written, once the query shape is known), or
  (b) leave those specific analytics endpoints broken/removed and tell the user explicitly, since they were out of this plan's original scope.
Do not silently drop the old tables in Task 8 while one of these services still queries them — that produces a 500 error in production, not a clean removal.

- [ ] **Step 3: If no old-table dependency is found, record that and proceed**

If all three files already query shift tables or don't touch production reports at all (e.g. they're pure aggregation over `work_orders`/`scrap_records`), no further action is needed — note this finding in the commit message of Task 8 so the historical record shows it was checked, not missed.

This task has no code changes and no commit of its own — its finding feeds directly into Task 8's Step 1.

---

### Task 7: Remove/rewrite the 25 dependent backend test files

**Files:**
- Investigate and modify/delete as needed: `test_report_flow_integration.py`, `test_conditionnement_flow_integration.py`, `test_report_reversal_integration.py`, `test_shift_legacy_conversion_integration.py`, `test_downtime_lines_integration.py`, `test_waste_lines_integration.py`, `test_packaging_variance_integration.py`, `domain/test_production_report.py`, plus others found by the grep below. (`test_shift_validation_integration.py` and `test_day_sheet_integration.py` were already handled in Tasks 3–4 — skip them here.)

**Interfaces:** none new; this task only removes dead test surface and ensures the remaining suite is green.

- [ ] **Step 1: Get the authoritative current list**

Run: `grep -rl "daily_reports\|conditionnement_reports\|ProductionReportService\|ConditionnementReportService\|production_reports" "d:\mahmoud repo\Sonalim_ERP\backend" --include="test_*.py"` — this is the real list as of this task's execution (the earlier survey's count of 25 may have drifted after Tasks 1–5's edits). Work through every file this returns.

- [ ] **Step 2: For each file, classify it into one of three buckets**

  - **Pure old-system test** (e.g. `test_report_flow_integration.py`, `test_conditionnement_flow_integration.py`, `test_report_reversal_integration.py`, `domain/test_production_report.py`): the old system is gone, so **delete the file**. Its behavior is now covered by `test_shift_stock_service_integration.py` (Tasks 1–2) and `test_shift_validation_integration.py` (Task 3).
  - **Conversion/bridge test** (`test_shift_legacy_conversion_integration.py`): this tested `legacy_report_ledger.materialize_shift` and the `0049`/`0051` conversion migrations — **delete the file**, `legacy_report_ledger.py` is deleted in Task 8.
  - **Cross-cutting test that happens to touch old tables incidentally** (`test_downtime_lines_integration.py`, `test_waste_lines_integration.py`, `test_packaging_variance_integration.py`, and any cross-module hits like `qc/api/test_qc_flow_integration.py`, `warehouse/api/test_lot_expiry_integration.py`): read the file, find the specific fixture/assertion that references the old tables, and **rewrite just that part** to build its fixture via `ShiftReportService`/`ShiftValidationService` instead (following the same pattern used in Task 3 Step 1/Step 5 and Task 4 Step 1). Do not delete these files — they test real, still-needed behavior (downtime-line validation rules, waste-line validation rules, packaging variance calculation) that must keep being tested, just against the new fixture path.

- [ ] **Step 3: Check `test_packaging_variance_integration.py`'s backing service**

`PackagingVarianceService.for_report` (routed at `/reports/{report_id}/packaging-variance`, kept per Task 5 Step 2's scope note — re-check: if Task 5 removed this route because it lived under the generic `/reports/{report_id}` prefix being deleted, this test needs the same treatment as Task 6's analytics services: read `packaging_variance_service.py`, determine if it reads old tables, and either port it (extend this task) or flag it for the user per Task 6's Step 2 decision rule.

- [ ] **Step 4: Run the full backend suite**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest . -v 2>&1 | tail -100`
Expected: PASS, zero references to deleted modules remain (no `ImportError`/`ModuleNotFoundError` anywhere in the run).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(production): remove or port the 25 backend tests that depended on the legacy report system

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Drop the old schema and delete the old backend service files

**Files:**
- Create: `backend/modules/production/migrations/0058_production_drop_legacy_reports.sql`
- Delete: `backend/modules/production/api/production_report_service.py`, `conditionnement_service.py`, `report_stock_service.py`, `legacy_report_ledger.py`, `downtime_line_store.py`, `waste_line_store.py`, `semolina_line_store.py`
- Delete: `backend/scripts/fix_daily_report_regrind_product.py`, `fix_daily_report_scrap_product.py`, `fix_daily_report_water_quantities.py`, `fix_daily_report_water_quantity_of34.py`

**Interfaces:** none; this is pure removal, gated on Tasks 3–7 all being green first.

- [ ] **Step 1: Confirm nothing still imports the files slated for deletion**

Run: `grep -rln "production_report_service\|conditionnement_service\|report_stock_service\|legacy_report_ledger\|downtime_line_store\|waste_line_store\|semolina_line_store" "d:\mahmoud repo\Sonalim_ERP\backend" --include="*.py"` — every hit must be inside one of the files this task is about to delete, or this task is not ready yet (go back and finish whichever earlier task left a dangling import).

- [ ] **Step 2: Delete the backend service and fix-script files**

```bash
cd "d:\mahmoud repo\Sonalim_ERP"
git rm backend/modules/production/api/production_report_service.py
git rm backend/modules/production/api/conditionnement_service.py
git rm backend/modules/production/api/report_stock_service.py
git rm backend/modules/production/api/legacy_report_ledger.py
git rm backend/modules/production/api/downtime_line_store.py
git rm backend/modules/production/api/waste_line_store.py
git rm backend/modules/production/api/semolina_line_store.py
git rm backend/scripts/fix_daily_report_regrind_product.py
git rm backend/scripts/fix_daily_report_scrap_product.py
git rm backend/scripts/fix_daily_report_water_quantities.py
git rm backend/scripts/fix_daily_report_water_quantity_of34.py
```

- [ ] **Step 3: Write the drop migration**

```sql
-- backend/modules/production/migrations/0058_production_drop_legacy_reports.sql
--
-- The old Daily/Conditionnement report system (production.production_reports and
-- its detail tables) is retired: every read and write path now runs on the shift
-- tables (shift_reports, shift_runs, shift_packing_rows, shift_waste_lines,
-- machine_stops). ShiftStockService replaced ReportStockService/
-- ProductionReportService's stock-posting, regrind and DLC-lot logic directly on
-- the shift tables; legacy_report_ledger.py (the bridge that faked old-shaped
-- rows to reuse the old logic) is deleted alongside this migration.
--
-- This is a genuine DROP, not a rename to a view: nothing reads these tables any
-- more (confirmed by Task 6/7's grep passes before this migration was written).
DROP TABLE IF EXISTS production.report_waste_lines;
DROP TABLE IF EXISTS production.report_semolina_lines;
DROP TABLE IF EXISTS production.report_downtime_lines;
DROP TABLE IF EXISTS production.conditionnement_reports;
DROP TABLE IF EXISTS production.daily_reports;
DROP TABLE IF EXISTS production.report_revisions;
DROP TABLE IF EXISTS production.production_reports;
```

Before finalizing this list, run `grep -n "CREATE TABLE" "d:\mahmoud repo\Sonalim_ERP\backend\modules\production\migrations\"0014*.sql 0015*.sql 0016*.sql 0022*.sql 0023*.sql 0027*.sql 0032*.sql` to confirm the complete list of tables created for the old system (the plan's earlier survey named these seven plus mentioned packaging reconciliation in `0023` — read that migration specifically to check if it created a separate table name not yet listed here, e.g. `packaging_reconciliation_lines` or similar, and add it to the DROP list if so).

- [ ] **Step 4: Run the migration against the dev database**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m core.migrate` (or whatever this repo's actual migration-runner command is — grep `backend/scripts` or the repo's README/CLAUDE.md for the exact invocation before running; do not guess a Django/Alembic-style command that doesn't exist here).

- [ ] **Step 5: Run the entire backend test suite one final time**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m pytest . -v 2>&1 | tail -100`
Expected: PASS, zero failures, zero errors, zero skips due to missing tables.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(production): drop the legacy Daily/Conditionnement report schema and services

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Remove the old frontend dialogs and their wiring

**Files:**
- Modify: `frontend/src/features/production/WorkOrderDetailsPage.tsx`
- Investigate and modify: `frontend/src/features/production/StageDetailsDialog.tsx` (confirm exact filename via `grep -rl "onOpenReport" frontend/src/features/production`)
- Delete: `frontend/src/features/production/DailyReportsTab.tsx`, `frontend/src/features/production/ConditionnementTab.tsx`

**Interfaces:**
- Consumes: nothing backend (backend routes are already gone as of Task 5/8, so any lingering frontend call would already be a 404 — this task removes the now-dead UI that would trigger those calls).
- Produces: `WorkOrderDetailsPage.tsx` compiles and renders with no reference to `DailyReportDialog`/`PackingReportDialog`.

- [ ] **Step 1: Find every caller of `StageDetailsDialog`'s `onOpenReport` prop and confirm what it's listing**

Run: `grep -n "onOpenReport\|openReport\b" "d:\mahmoud repo\Sonalim_ERP\frontend\src\features\production\StageDetailsDialog.tsx"` (adjust filename per the grep above if different) to see what triggers `onOpenReport` — almost certainly a list of an OF's past reports rendered inside the stage dialog, sourced from the now-deleted `/reports?of_id=...` endpoint (or similar). Read enough of that file to know exactly what UI element (a button, a row) calls `onOpenReport` and what data feeds it.

- [ ] **Step 2: Remove the report-opening affordance from `StageDetailsDialog.tsx`**

Since the old report list endpoint no longer exists (Task 5 removed `/reports` list routes under `production.view_reports` if they were among the deleted ones — recheck Task 5 Step 2's exact deletion list; if `GET /reports` survived because it's dual-purpose, this step may only need to stop querying old report types), remove the button/row that triggered `onOpenReport`, its prop from `StageDetailsDialog`'s props interface, and any now-unused state.

- [ ] **Step 3: Remove the dialog rendering and imports from `WorkOrderDetailsPage.tsx`**

Delete lines 53-54 (`import { DailyReportDialog } from "./DailyReportsTab";` and `import { PackingReportDialog } from "./ConditionnementTab";`), the `openReport`/`setOpenReport` state if it becomes unused after Step 2, and the JSX block at lines 767-795 (`{openReport && (openReport.report_type === "daily" ? <DailyReportDialog .../> : <PackingReportDialog .../>)}`).

- [ ] **Step 4: Delete the two tab files**

```bash
cd "d:\mahmoud repo\Sonalim_ERP"
git rm frontend/src/features/production/DailyReportsTab.tsx
git rm frontend/src/features/production/ConditionnementTab.tsx
```

- [ ] **Step 5: Check `ProductionPage.tsx` / nav config for any remaining references**

Per project memory, M6a already removed the old Daily/Conditionnement tabs from `ProductionPage` nav (redirecting to `?tab=shift-report`), so this should be a no-op check: `grep -rn "DailyReportsTab\|ConditionnementTab" "d:\mahmoud repo\Sonalim_ERP\frontend\src"` should return nothing after Step 4. If it does return something, read that file and remove the reference.

- [ ] **Step 6: Type-check the frontend**

Run: `cd "d:\mahmoud repo\Sonalim_ERP\frontend" && npx tsc -b --force`
Expected: zero errors. (Per project feedback memory, always use `--force` here.)

- [ ] **Step 7: Manually verify in a real browser**

Start the dev server, log in as the demo user, open a work order's details page, open a stage's details dialog, and confirm: no crash, no dead button, the shift-report screens are unaffected. This is a UI removal — a broken import or dangling prop will show as a blank page or console error, not a type error, so this manual check is required per this project's "verify frontend changes in the browser" standing feedback.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(production): remove the old Daily/Conditionnement report dialogs from the work order page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** Every piece the original survey inventoried is covered: backend services (Tasks 1–3, 8), `legacy_report_ledger` (Tasks 3, 8), `DaySheetService` (Task 4), routes/permissions (Task 5), analytics services (Task 6, deliberately deferred to a decision point rather than guessed at), 25 test files (Task 7), frontend dialogs (Task 9), migrations (Task 8). The `WorkOrderDetailsPage`/`StageDetailsDialog` coupling found during planning is handled in Task 9 Steps 1–2 rather than assumed away.

**Placeholder scan:** Two intentional "wrong code, corrected immediately after" blocks exist in Task 1 Step 1 and Task 2 Step 3/4 — each is explicitly flagged in its own step text as scaffolding to discard, with the real code given immediately after, per this plan's own instruction to the executor. These are not silent placeholders; every other step has real, runnable code or an exact grep/shell command.

**Type consistency:** `ShiftStockService` method names and return shapes (`Ok({"movements": [...]})`, `Ok({"scrap_record_id":, "regrind_work_order_id":})`, `Ok({"reversed_movements":, "removed_scrap_records":, "reversed_regrind_stock":, "skip_regrind_rebuild":})`) are declared once in Task 1/2's Interfaces blocks and used identically in Task 3's rewiring — checked for drift while writing Task 3.

**Review Focus:** all five items have an owning task and an explicit test (two-run reversal → Task 3 Step 7; closed-batch force-refusal → Task 2 Step 6 + Task 3 Step 7; shortfall gate → Task 3 Step 3's `shortfalls` check, test via Step 7; carton-count-wins → Task 2 Step 1's test asserts the carton-tier math; empty-shift day sheet → Task 4 Step 6's explicit test).

**Known open risk carried forward, not silently resolved:** Task 6 and Task 7 Step 3 both stop short of guaranteeing the analytics/packaging-variance services are shift-native — this is deliberate. The original research pass did not read those files in enough depth to know if they touch old tables, and guessing their query shape to write a port task now would violate "no placeholders." Task 6 makes this decision point explicit and blocks Task 8 on it rather than letting the schema drop silently break an unexamined endpoint.

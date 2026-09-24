# Analytics Shift Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regroup Analytics into Production vs. Cost & Pricing tabs, verify the 4 existing production tabs are correct against shift-era data, and add three new tabs (Downtime classification, Energy, Shift Health) plus a humidity panel and DLC-coverage stat — all backed by real recorded fields, no invented thresholds.

**Architecture:** Three new small backend services (`stops_analytics_service.py`, `energy_analytics_service.py`, `shift_health_service.py`) follow `team_performance_service.py`'s exact style: raw tenant-scoped SQL, `status = 'validated'` filtering, dict rows. Three new endpoints under `/production/analytics/...`, permission `production.view_reports` (same as every existing analytics endpoint). Frontend adds three new tab components + hooks following `useManufacturingOverview.ts`'s per-source react-query pattern, and `AnalyticsPage.tsx`'s tab list gains a `group` field for visual regrouping only.

**Tech Stack:** FastAPI + psycopg (backend, `backend/modules/production/api`), React + TanStack Query + Recharts + TypeScript (frontend, `frontend/src/features/analytics`).

**Spec:** `docs/superpowers/specs/2026-09-23-analytics-shift-rewrite-design.md` (Part B). Depends on Part A (`docs/superpowers/plans/2026-09-23-validator-edit-plan.md`) only for Task 6 (Shift Health's validator-edit-rate panel) — every other task here is independent of Part A and can ship first.

## Global Constraints

- Every new panel states a real recorded figure or compares direction-only against the previous equal-length period (`compareQuantity`/`compareRatio` from `manufacturing/metrics.ts`) — no invented thresholds, targets, or "healthy/unhealthy" bands anywhere in this plan.
- Only `status = 'validated'` shift reports (and their child rows) count in every new query, matching every existing analytics query in this module.
- Fuel (fioul) and gasoil are always shown as separate series, never merged (per [[project-analytics-data-constraints]]).
- Permission for every new endpoint is `production.view_reports`, identical to `list_team_performance`/`list_machine_performance`/`list_downtime_breakdown` (`router.py:1911`, `1935`, `1971`).
- No new hard-coded French/English copy skips the `T`/`L(en, fr)` pattern already used in `shiftText.ts`, or the flat `en`/`fr` dictionary pattern in `frontend/src/lib/i18n.tsx` for Analytics' own keys (`analytics.xxx.yyy` prefix, mirrored at the matching line offset in both dictionaries).
- Follow existing file/type patterns exactly: `Result`/`Err`/`Ok` are NOT used in these read-only analytics services (none of `team_performance_service.py`/`machine_performance_service.py` uses them — plain functions returning lists of dicts, matching that precedent, not the shift-write services' `Result` pattern).

## Review Focus

- A date range with **no validated shifts at all** (empty tenant, or a future date range) must render each new tab's existing `AnalyticsEmptyState`/`AnalyticsErrorState` pattern, not a blank chart or a divide-by-zero — every ratio in this plan (per-tonne, %, rate) must guard its denominator exactly like `ratioPct` already does.
- A `machine_stops` row with `equipment_id IS NULL` must appear in the Downtime tab's "unattributed" stat, never silently dropped from the classification/motif paretos' totals and never double-counted into some machine's row.
- A `shift_reports` row that is `open`/`returned` (not yet `submitted` or `validated`) must be excluded from Shift Health's time-to-validate and return-rate panels (both need a `submitted_at`), but **must** be counted in the submission funnel panel (which explicitly covers every status) — getting this filter wrong in one panel but not the other is an easy copy-paste bug across three SQL queries in one file.
- `shift_energy.gasoil_quantity` and `fuel_quantity` for a shift with **zero** of one but nonzero of the other must both still render as their own series point (0, not a gap) — a `LEFT JOIN`/`COALESCE` mistake could turn "recorded as zero" into "no data," which is a materially different claim per [[feedback_no_invented_thresholds]].
- The energy-per-tonne ratio must use the *same* date window's produced tonnage as the numerator's shifts (join on `shift_report_id`/`report_date`+`work_center_id`, not two independently-windowed aggregates that could silently drift apart if one query's window and the other's are edited separately later).

---

## Task 1: `StopsAnalyticsService` + `/production/analytics/stops` endpoint

**Files:**
- Create: `backend/modules/production/api/stops_analytics_service.py`
- Create: `backend/modules/production/api/test_stops_analytics_integration.py`
- Modify: `backend/modules/production/api/router.py`

**Interfaces:**
- Produces: `StopsAnalyticsService.list_stops(*, tenant_id: str, date_from: str | None, date_to: str | None) -> list[dict]`, each dict: `{equipment_id: str | None, work_center_id: str, team: str | None, report_date: str, started_at: str, ended_at: str, minutes: int, downtime_type: str | None, classification: str | None, motif: str | None, source: str}`. Endpoint `GET /production/analytics/stops?date_from=&date_to=`, permission `production.view_reports`. Consumed by Task 5 (frontend).

- [ ] **Step 1: Write the failing integration test**

Create `backend/modules/production/api/test_stops_analytics_integration.py`:

```python
"""Stops analytics reads production.machine_stops for validated shifts only."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.stops_analytics_service import StopsAnalyticsService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "stops-analytics-test"
DAY = datetime.date(2030, 7, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, semolina, location, fg_location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(8))
    film, carton, scotch, ruban = (str(ULID()) for _ in range(4))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((product, "SA-PASTA"), (semolina, "SA-SEMO"), (film, "SA-FILM"), (carton, "SA-CARTON"), (scotch, "SA-SCOTCH"), (ruban, "SA-RUBAN")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SA-LOC', 'Silo')", (location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SA-PACK', 'Packaging')", (packaging_location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SA-FG', 'Finished goods')", (fg_location, TENANT))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SA-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'SA-EQ', 'Press')", (equipment, TENANT, work_center))
    stock = StockService(db)
    stock.receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    for product_id in (film, carton, scotch, ruban):
        stock.receive_stock(tenant_id=TENANT, product_id=product_id, location_id=packaging_location, quantity=10_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {
        "actor": actor, "product": product, "semolina": semolina, "location": location, "fg_location": fg_location,
        "packaging_location": packaging_location, "work_center": work_center, "equipment": equipment,
        "film": film, "carton": carton, "scotch": scotch, "ruban": ruban,
    }


def _of(db, env) -> str:
    service = WorkOrderService(db)
    created = service.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000, work_center_id=env["work_center"], start_date=DAY)
    assert isinstance(created, Ok)
    assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok)
    return created.value.id


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _shift(db, shift_id) -> dict:
    return _ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id))


def _validated_shift_with_stop(db, env, *, equipment_id, classification=None, motif=None, source="manual") -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]

    stop = {
        "equipment_id": equipment_id, "started_at": "2030-07-01T08:00:00Z", "ended_at": "2030-07-01T08:30:00Z",
        "downtime_type": "unplanned", "classification": classification, "motif": motif, "run_id": run_ids[0], "source": source,
    }
    packing = {"of_id": of_id, "run_id": run_ids[0], "equipment_id": env["equipment"], "finished_product_quantity": 800,
               "packets_counted": 1600, "film_quantity": 40, "carton_quantity": 100, "scotch_quantity": 2, "ruban_quantity": 1,
               "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
               "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_location"],
               "finished_goods_location_id": env["fg_location"], "lot_number": "B7011SNL"}

    filled = {"runs": None, "stops": {"stops": [stop]}, "packing": {"rows": [packing]}}
    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_lists_stops_of_validated_shifts_with_classification_and_source(db, env):
    _validated_shift_with_stop(db, env, equipment_id=env["equipment"], classification="mechanical", motif="belt", source="live")

    rows = StopsAnalyticsService(db).list_stops(tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")

    assert len(rows) == 1
    row = rows[0]
    assert row["equipment_id"] == env["equipment"]
    assert row["classification"] == "mechanical"
    assert row["motif"] == "belt"
    assert row["source"] == "live"
    assert row["minutes"] == 30
    assert row["work_center_id"] == env["work_center"]


def test_stops_with_no_equipment_are_still_returned_unattributed(db, env):
    _validated_shift_with_stop(db, env, equipment_id=None)
    rows = StopsAnalyticsService(db).list_stops(tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")
    assert len(rows) == 1
    assert rows[0]["equipment_id"] is None


def test_stops_outside_the_date_range_are_excluded(db, env):
    _validated_shift_with_stop(db, env, equipment_id=env["equipment"])
    rows = StopsAnalyticsService(db).list_stops(tenant_id=TENANT, date_from="2030-01-01", date_to="2030-01-31")
    assert rows == []


def test_stops_scoped_to_tenant(db, env):
    _validated_shift_with_stop(db, env, equipment_id=env["equipment"])
    rows = StopsAnalyticsService(db).list_stops(tenant_id="a-different-tenant", date_from="2030-07-01", date_to="2030-07-01")
    assert rows == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_stops_analytics_integration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.production.api.stops_analytics_service'`.

- [ ] **Step 3: Implement `StopsAnalyticsService`**

Create `backend/modules/production/api/stops_analytics_service.py`:

```python
from __future__ import annotations

import psycopg


class StopsAnalyticsService:
    """Machine stops of validated shifts, at full detail -- classification, motif,
    and how the stop was captured (live / added after / manual / migrated).

    Unlike MachinePerformanceService (which sums minutes per machine+period for a
    productivity view), this returns one row per stop so the caller can pivot by
    classification, motif, or capture source -- none of which survive an
    aggregate sum. A stop with no equipment_id is still returned (equipment_id
    null), never dropped, so a caller can show it as its own "unattributed"
    figure instead of silently excluding it from every total.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_stops(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        clauses = ["s.tenant_id = %s", "s.status = 'validated'", "ms.ended_at IS NOT NULL"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("s.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("s.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT
                ms.equipment_id, s.work_center_id, s.team, s.report_date,
                ms.started_at, ms.ended_at,
                ROUND(EXTRACT(EPOCH FROM (ms.ended_at - ms.started_at)) / 60) AS minutes,
                ms.downtime_type, ms.classification, ms.motif, ms.source
            FROM production.machine_stops ms
            JOIN production.shift_reports s ON s.id = ms.shift_report_id AND s.tenant_id = ms.tenant_id
            WHERE {where}
            ORDER BY ms.started_at
            """,
            params,
        ).fetchall()
        return [
            {
                "equipment_id": equipment_id,
                "work_center_id": work_center_id,
                "team": team,
                "report_date": report_date.isoformat(),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "minutes": int(minutes),
                "downtime_type": downtime_type,
                "classification": classification,
                "motif": motif,
                "source": source,
            }
            for (
                equipment_id, work_center_id, team, report_date, started_at, ended_at,
                minutes, downtime_type, classification, motif, source,
            ) in rows
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_stops_analytics_integration.py -v`
Expected: all 4 PASS.

- [ ] **Step 5: Add the endpoint**

In `backend/modules/production/api/router.py`, add the import near the other analytics service imports and the endpoint near `list_downtime_breakdown` (after line ~1976):

```python
from modules.production.api.stops_analytics_service import StopsAnalyticsService


@router.get("/analytics/stops")
def list_stops_analytics(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Every stop of a validated shift, at full detail, for the Downtime analytics tab."""
    with get_connection() as connection:
        return StopsAnalyticsService(connection).list_stops(tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to)
```

- [ ] **Step 6: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/production/api/stops_analytics_service.py backend/modules/production/api/test_stops_analytics_integration.py backend/modules/production/api/router.py
git commit -m "Add stops analytics service and endpoint"
```

---

## Task 2: `EnergyAnalyticsService` + `/production/analytics/energy` endpoint

**Files:**
- Create: `backend/modules/production/api/energy_analytics_service.py`
- Create: `backend/modules/production/api/test_energy_analytics_integration.py`
- Modify: `backend/modules/production/api/router.py`

**Interfaces:**
- Produces: `EnergyAnalyticsService.list_energy(*, tenant_id: str, date_from: str | None, date_to: str | None, work_center_id: str | None = None) -> list[dict]`, each dict: `{report_date: str, work_center_id: str, team: str | None, fuel_quantity: float, gasoil_quantity: float, gasoil_flow_rate: float, generator_hours: float, electricity_quantity: float, produced_quantity: float}`. `produced_quantity` is that shift's total `finished_product_quantity` across its runs (same basis `TeamPerformanceService` uses), joined in so the frontend can compute energy-per-tonne without a second request. Endpoint `GET /production/analytics/energy?date_from=&date_to=&work_center_id=`. Consumed by Task 5.

- [ ] **Step 1: Write the failing integration test**

Create `backend/modules/production/api/test_energy_analytics_integration.py`. Reuse the same `env`/`_of`/`_ok`/`_shift` fixture bodies as Task 1's test file (copy them — these test files intentionally do not share fixtures across files, matching `test_shift_validation_integration.py`'s and other production test files' existing self-contained style), with tenant `TENANT = "energy-analytics-test"` and:

```python
def _validated_shift_with_energy(db, env, *, fuel=0, gasoil=0, generator_hours=0, electricity=0) -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]
    packing = {"of_id": of_id, "run_id": run_ids[0], "equipment_id": env["equipment"], "finished_product_quantity": 800,
               "packets_counted": 1600, "film_quantity": 40, "carton_quantity": 100, "scotch_quantity": 2, "ruban_quantity": 1,
               "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
               "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_location"],
               "finished_goods_location_id": env["fg_location"], "lot_number": "B7021SNL"}
    energy = {"fuel_quantity": fuel, "gasoil_quantity": gasoil, "generator_hours": generator_hours, "electricity_quantity": electricity}

    filled = {"runs": None, "packing": {"rows": [packing]}, "energy": {"energy": energy}}
    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_lists_energy_of_validated_shifts_including_zero_values(db, env):
    _validated_shift_with_energy(db, env, fuel=0, gasoil=120.5, generator_hours=3, electricity=450)

    rows = EnergyAnalyticsService(db).list_energy(tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")

    assert len(rows) == 1
    row = rows[0]
    assert row["fuel_quantity"] == 0.0  # recorded zero, not a missing row
    assert row["gasoil_quantity"] == 120.5
    assert row["generator_hours"] == 3.0
    assert row["electricity_quantity"] == 450.0
    assert row["produced_quantity"] == 900.0  # the run's finished_product_quantity
    assert row["work_center_id"] == env["work_center"]


def test_energy_filtered_by_work_center(db, env):
    _validated_shift_with_energy(db, env, fuel=10)
    rows = EnergyAnalyticsService(db).list_energy(tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01", work_center_id="not-this-line")
    assert rows == []


def test_energy_outside_date_range_excluded(db, env):
    _validated_shift_with_energy(db, env, fuel=10)
    rows = EnergyAnalyticsService(db).list_energy(tenant_id=TENANT, date_from="2030-01-01", date_to="2030-01-31")
    assert rows == []
```

(Add the necessary imports at the top of the new file — same set as Task 1's test file, plus `EnergyAnalyticsService` from `modules.production.api.energy_analytics_service`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_energy_analytics_integration.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `EnergyAnalyticsService`**

Create `backend/modules/production/api/energy_analytics_service.py`:

```python
from __future__ import annotations

import psycopg


class EnergyAnalyticsService:
    """Fuel, gasoil, generator and electricity, one row per validated shift.

    shift_energy is typed once per shift (not per run), so this stays at the
    shift grain -- no per-run/per-product energy split exists to read.
    produced_quantity is joined in from the shift's own runs (same basis
    TeamPerformanceService uses for produced_quantity) so a caller can divide
    without a second request, but the two figures are read from the same
    shift_report_id in one query, so they can never drift out of the same window.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_energy(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        work_center_id: str | None = None,
    ) -> list[dict]:
        clauses = ["s.tenant_id = %s", "s.status = 'validated'"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("s.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("s.report_date <= %s")
            params.append(date_to)
        if work_center_id is not None:
            clauses.append("s.work_center_id = %s")
            params.append(work_center_id)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT
                s.report_date, s.work_center_id, s.team,
                e.fuel_quantity, e.gasoil_quantity, e.gasoil_flow_rate, e.generator_hours, e.electricity_quantity,
                COALESCE(r.produced_quantity, 0) AS produced_quantity
            FROM production.shift_energy e
            JOIN production.shift_reports s ON s.id = e.shift_report_id AND s.tenant_id = e.tenant_id
            LEFT JOIN (
                SELECT shift_report_id, SUM(finished_product_quantity) AS produced_quantity
                FROM production.shift_runs
                GROUP BY shift_report_id
            ) r ON r.shift_report_id = s.id
            WHERE {where}
            ORDER BY s.report_date
            """,
            params,
        ).fetchall()
        return [
            {
                "report_date": report_date.isoformat(),
                "work_center_id": work_center_id,
                "team": team,
                "fuel_quantity": float(fuel_quantity),
                "gasoil_quantity": float(gasoil_quantity),
                "gasoil_flow_rate": float(gasoil_flow_rate),
                "generator_hours": float(generator_hours),
                "electricity_quantity": float(electricity_quantity),
                "produced_quantity": float(produced_quantity),
            }
            for (
                report_date, work_center_id, team, fuel_quantity, gasoil_quantity,
                gasoil_flow_rate, generator_hours, electricity_quantity, produced_quantity,
            ) in rows
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_energy_analytics_integration.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Add the endpoint**

In `router.py`, near the stops endpoint:

```python
from modules.production.api.energy_analytics_service import EnergyAnalyticsService


@router.get("/analytics/energy")
def list_energy_analytics(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    work_center_id: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """One row per validated shift's energy figures, for the Energy analytics tab."""
    with get_connection() as connection:
        return EnergyAnalyticsService(connection).list_energy(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to, work_center_id=work_center_id
        )
```

- [ ] **Step 6: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/production/api/energy_analytics_service.py backend/modules/production/api/test_energy_analytics_integration.py backend/modules/production/api/router.py
git commit -m "Add energy analytics service and endpoint"
```

---

## Task 3: `ShiftHealthService` (funnel, latency, return rate, completeness) + endpoint

**Files:**
- Create: `backend/modules/production/api/shift_health_service.py`
- Create: `backend/modules/production/api/test_shift_health_integration.py`
- Modify: `backend/modules/production/api/router.py`

**Interfaces:**
- Produces: `ShiftHealthService.get_shift_health(*, tenant_id: str, date_from: str | None, date_to: str | None) -> dict` shaped:
  ```python
  {
      "funnel": [{"status": str, "count": int}],  # every shift opened in range, whatever its current status
      "time_to_validate_minutes": {"median": float | None, "average": float | None, "sample_size": int},
      "return_rate_by_section": [{"section_key": str, "returned_count": int, "total_count": int, "return_rate_pct": float | None}],
      "completeness": {"average_sections_filled": float | None, "total_sections": int, "shift_count": int},
  }
  ```
  Endpoint `GET /production/analytics/shift-health?date_from=&date_to=`. Consumed by Task 5. (Task 6 later extends this same dict with a `validator_edit_rate_by_section` key once Part A has shipped — not built in this task.)

- [ ] **Step 1: Write the failing integration test**

Create `backend/modules/production/api/test_shift_health_integration.py`. Reuse the `env`/`_of`/`_ok` fixture style from Task 1 (tenant `TENANT = "shift-health-test"`), plus helpers to open shifts at different statuses without needing them fully validated (the funnel panel needs `open`/`submitted`/`returned`/`validated` shifts to exist side by side):

```python
"""Shift lifecycle health: submission funnel, time-to-validate, return rate, completeness."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.shift_health_service import ShiftHealthService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS

TENANT = "shift-health-test"
DAY = datetime.date(2030, 8, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    work_center = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SH-WC', 'Line')", (work_center, TENANT))
    return {"actor": actor, "work_center": work_center}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _open_shift(db, env, *, shift="morning", report_date=DAY) -> str:
    return _ok(ShiftReportService(db).open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=report_date, shift=shift,
    ))["id"]


def _submit_every_section_as_nothing_to_report(db, env, shift_id):
    service = ShiftReportService(db)
    for key in SECTION_KEYS:
        _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))


def test_funnel_counts_every_status_in_range(db, env):
    open_shift = _open_shift(db, env, shift="morning")

    submitted_shift = _open_shift(db, env, shift="afternoon")
    _submit_every_section_as_nothing_to_report(db, env, submitted_shift)

    validated_shift = _open_shift(db, env, shift="night")
    _submit_every_section_as_nothing_to_report(db, env, validated_shift)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=validated_shift))

    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-08-01", date_to="2030-08-01")

    by_status = {row["status"]: row["count"] for row in health["funnel"]}
    assert by_status.get("open") == 1
    assert by_status.get("submitted") == 1
    assert by_status.get("validated") == 1


def test_time_to_validate_only_counts_validated_shifts(db, env):
    shift_id = _open_shift(db, env)
    _submit_every_section_as_nothing_to_report(db, env, shift_id)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))

    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-08-01", date_to="2030-08-01")

    assert health["time_to_validate_minutes"]["sample_size"] == 1
    assert health["time_to_validate_minutes"]["average"] is not None
    assert health["time_to_validate_minutes"]["average"] >= 0


def test_time_to_validate_empty_when_nothing_validated(db, env):
    _open_shift(db, env)
    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-08-01", date_to="2030-08-01")
    assert health["time_to_validate_minutes"]["sample_size"] == 0
    assert health["time_to_validate_minutes"]["median"] is None
    assert health["time_to_validate_minutes"]["average"] is None


def test_return_rate_reflects_returned_sections(db, env):
    shift_id = _open_shift(db, env)
    _submit_every_section_as_nothing_to_report(db, env, shift_id)
    _ok(ShiftValidationService(db).reject_sections(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["runs"], reason="missing data",
    ))

    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-08-01", date_to="2030-08-01")

    by_key = {row["section_key"]: row for row in health["return_rate_by_section"]}
    assert by_key["runs"]["returned_count"] == 1
    assert by_key["runs"]["return_rate_pct"] == 100.0
    assert by_key["waste_production"]["returned_count"] == 0


def test_completeness_counts_non_empty_sections(db, env):
    shift_id = _open_shift(db, env)
    _submit_every_section_as_nothing_to_report(db, env, shift_id)  # all 9 sections now non-empty

    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-08-01", date_to="2030-08-01")

    assert health["completeness"]["total_sections"] == len(SECTION_KEYS)
    assert health["completeness"]["average_sections_filled"] == float(len(SECTION_KEYS))
    assert health["completeness"]["shift_count"] == 1


def test_empty_window_returns_zeroed_shape_not_an_error(db, env):
    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-01-01", date_to="2030-01-31")
    assert health["funnel"] == []
    assert health["time_to_validate_minutes"]["sample_size"] == 0
    assert health["completeness"]["shift_count"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_health_integration.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `ShiftHealthService`**

Create `backend/modules/production/api/shift_health_service.py`:

```python
from __future__ import annotations

import psycopg

from modules.production.domain.shift_report import SECTION_KEYS


class ShiftHealthService:
    """Health of the shift-reporting process itself: how many shifts are in
    each state, how long validation takes, which sections get sent back most,
    and how complete shifts are. Every figure here is a recorded fact or a
    direction-only comparison -- no target or "on time" threshold exists
    anywhere in the system for any of these, so none is invented here.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_shift_health(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        funnel = [
            {"status": status, "count": int(count)}
            for status, count in self._connection.execute(
                f"SELECT status, count(*) FROM production.shift_reports WHERE {where} GROUP BY status", params
            ).fetchall()
        ]

        ttv_row = self._connection.execute(
            f"""
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (validated_at - submitted_at)) / 60),
                AVG(EXTRACT(EPOCH FROM (validated_at - submitted_at)) / 60),
                count(*)
            FROM production.shift_reports
            WHERE {where} AND status = 'validated' AND submitted_at IS NOT NULL AND validated_at IS NOT NULL
            """,
            params,
        ).fetchone()
        median, average, sample_size = ttv_row
        time_to_validate_minutes = {
            "median": float(median) if median is not None else None,
            "average": float(average) if average is not None else None,
            "sample_size": int(sample_size),
        }

        # Every submitted-or-later revision of a section, tenant/date-scoped via the
        # parent shift; a section counts as "returned" if any of its revisions in
        # this window carries a return_reason (it was sent back at least once).
        returned_counts = dict(
            self._connection.execute(
                f"""
                SELECT r.section_key, count(DISTINCT r.shift_report_id)
                FROM production.shift_section_revisions r
                JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
                WHERE {where.replace('tenant_id', 's.tenant_id').replace('report_date', 's.report_date')}
                  AND r.section_key = ANY(%s) AND r.reason IS NOT NULL
                GROUP BY r.section_key
                """,
                [*params, list(SECTION_KEYS)],
            ).fetchall()
        )
        total_counts = dict(
            self._connection.execute(
                f"""
                SELECT sec.section_key, count(DISTINCT sec.shift_report_id)
                FROM production.shift_report_sections sec
                JOIN production.shift_reports s ON s.id = sec.shift_report_id AND s.tenant_id = sec.tenant_id
                WHERE {where.replace('tenant_id', 's.tenant_id').replace('report_date', 's.report_date')}
                  AND sec.section_key = ANY(%s)
                GROUP BY sec.section_key
                """,
                [*params, list(SECTION_KEYS)],
            ).fetchall()
        )
        return_rate_by_section = [
            {
                "section_key": key,
                "returned_count": returned_counts.get(key, 0),
                "total_count": total_counts.get(key, 0),
                "return_rate_pct": (
                    (returned_counts.get(key, 0) / total_counts[key]) * 100 if total_counts.get(key, 0) > 0 else None
                ),
            }
            for key in SECTION_KEYS
        ]

        completeness_row = self._connection.execute(
            f"""
            SELECT AVG(filled), count(*)
            FROM (
                SELECT s.id, count(*) FILTER (WHERE sec.status != 'empty') AS filled
                FROM production.shift_reports s
                LEFT JOIN production.shift_report_sections sec ON sec.shift_report_id = s.id AND sec.tenant_id = s.tenant_id
                WHERE {where}
                GROUP BY s.id
            ) per_shift
            """,
            params,
        ).fetchone()
        avg_filled, shift_count = completeness_row
        completeness = {
            "average_sections_filled": float(avg_filled) if avg_filled is not None else None,
            "total_sections": len(SECTION_KEYS),
            "shift_count": int(shift_count),
        }

        return {
            "funnel": funnel,
            "time_to_validate_minutes": time_to_validate_minutes,
            "return_rate_by_section": return_rate_by_section,
            "completeness": completeness,
        }
```

Note on the `where.replace(...)` calls: the base `where` clause is built against unqualified `tenant_id`/`report_date` (matching every other service in this file family, e.g. `TeamPerformanceService`'s `where`/`where2` split), and reused twice against a query that needs the `s.` prefix because the FROM table there is the child table, not `shift_reports` itself — this mirrors the exact same qualified-vs-unqualified `where`/`where2` pattern `team_performance_service.py` already uses for its `sem_ratio` CTE (see `team_performance_service.py:39-51`), just via string substitution instead of a second clause list, because here both queries share the same two filter columns. Verify this substitution produces valid SQL by running the tests in the next step — if `report_date`/`tenant_id` appear ambiguously elsewhere in the `where` string unexpectedly, build `where`/`params` twice (once unqualified for the funnel/ttv/completeness queries against `shift_reports` directly, once as `s.tenant_id`/`s.report_date` for the two section-revision queries) instead of using `.replace()`, which is safer against accidental substring matches — prefer that dual-list approach if `.replace()` proves fragile.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_health_integration.py -v`
Expected: all 6 PASS. If the `.replace()` substitution in Step 3 produces incorrect SQL (test failure with a column-ambiguity or syntax error), switch to the dual explicit clause-list approach described in Step 3's note and re-run.

- [ ] **Step 5: Add the endpoint**

In `router.py`:

```python
from modules.production.api.shift_health_service import ShiftHealthService


@router.get("/analytics/shift-health")
def get_shift_health_analytics(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """Submission funnel, time-to-validate, return rate and completeness, for the Shift Health tab."""
    with get_connection() as connection:
        return ShiftHealthService(connection).get_shift_health(tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to)
```

- [ ] **Step 6: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/production/api/shift_health_service.py backend/modules/production/api/test_shift_health_integration.py backend/modules/production/api/router.py
git commit -m "Add shift health analytics service and endpoint"
```

---

## Task 4: Frontend API clients for the three new endpoints

**Files:**
- Modify: `frontend/src/features/production/api.ts`

**Interfaces:**
- Produces: `listStopsAnalytics`, `listEnergyAnalytics`, `getShiftHealth` functions + their row/response types, matching Tasks 1-3's response shapes exactly. Consumed by Task 5's hooks.

- [ ] **Step 1: Add types and functions**

In `frontend/src/features/production/api.ts`, near `listDowntimeBreakdown` (end of file's analytics section), add:

```typescript
export interface StopAnalyticsRow {
  equipment_id: string | null;
  work_center_id: string;
  team: string | null;
  report_date: string;
  started_at: string;
  ended_at: string;
  minutes: number;
  downtime_type: string | null;
  classification: string | null;
  motif: string | null;
  source: "live" | "added_after" | "manual" | "migrated";
}

export function listStopsAnalytics(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<StopAnalyticsRow[]>(`/production/analytics/stops${suffix}`, { token });
}

export interface EnergyAnalyticsRow {
  report_date: string;
  work_center_id: string;
  team: string | null;
  fuel_quantity: number;
  gasoil_quantity: number;
  gasoil_flow_rate: number;
  generator_hours: number;
  electricity_quantity: number;
  produced_quantity: number;
}

export function listEnergyAnalytics(
  token: string,
  params: { date_from?: string; date_to?: string; work_center_id?: string } = {},
) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  if (params.work_center_id) query.set("work_center_id", params.work_center_id);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<EnergyAnalyticsRow[]>(`/production/analytics/energy${suffix}`, { token });
}

export interface ShiftHealth {
  funnel: { status: string; count: number }[];
  time_to_validate_minutes: { median: number | null; average: number | null; sample_size: number };
  return_rate_by_section: { section_key: string; returned_count: number; total_count: number; return_rate_pct: number | null }[];
  completeness: { average_sections_filled: number | null; total_sections: number; shift_count: number };
}

export function getShiftHealth(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ShiftHealth>(`/production/analytics/shift-health${suffix}`, { token });
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean (additive, unused exports at this point).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/production/api.ts
git commit -m "Add frontend API clients for stops, energy and shift-health analytics"
```

---

## Task 5: Three new analytics tabs (Downtime, Energy, Shift Health) + tab regrouping

**Files:**
- Create: `frontend/src/features/analytics/manufacturing/useStopsAnalytics.ts`
- Create: `frontend/src/features/analytics/manufacturing/useEnergyAnalytics.ts`
- Create: `frontend/src/features/analytics/manufacturing/useShiftHealth.ts`
- Create: `frontend/src/features/analytics/DowntimeAnalyticsTab.tsx`
- Create: `frontend/src/features/analytics/EnergyAnalyticsTab.tsx`
- Create: `frontend/src/features/analytics/ShiftHealthTab.tsx`
- Modify: `frontend/src/features/analytics/AnalyticsPage.tsx`
- Modify: `frontend/src/features/analytics/manufacturing/format.ts` (add `classification`/`downtimeType` formatters)
- Modify: `frontend/src/lib/i18n.tsx` (new keys, both `en` and `fr`)

**Interfaces:**
- Consumes: Task 4's `listStopsAnalytics`, `listEnergyAnalytics`, `getShiftHealth`; `compareQuantity`/`compareRatio`/`buildWindows`/`localTodayIso` from `manufacturing/metrics.ts`; `PeriodFilter`/`PERIOD_DAYS` from `PeriodFilter.tsx`; `AnalyticsEmptyState`/`AnalyticsErrorState`/`AnalyticsLoadingState` from `AnalyticsStates.tsx`; `useMinimumLoading`; `downtimeLabel` from `../production/downtimeOptions`.
- Produces: three new tab components mounted in `AnalyticsPage.tsx`'s `TABS` array under a `group: "production"` field.

- [ ] **Step 1: Add `classification`/`downtimeType` formatters**

In `frontend/src/features/analytics/manufacturing/format.ts`, extend `useFormatters`' returned object (the `Formatters` type is defined in `./insights.ts` — read it first and add the two new fields there too):

```bash
grep -n "export interface Formatters" -A 15 frontend/src/features/analytics/manufacturing/insights.ts
```

Add `classification: (value: string) => string` and `downtimeType: (value: string) => string` to the `Formatters` interface in `insights.ts`, then in `format.ts`'s `useFormatters`:

```typescript
      classification: (value: string) => downtimeLabel(t, "classification", value),
      downtimeType: (value: string) => downtimeLabel(t, "type", value),
```

(added alongside the existing `motif: (motif: string) => downtimeLabel(t, "motif", motif),` line — same function, different `field` argument, per `downtimeOptions.tsx`'s `DowntimeField` union already covering all three.)

- [ ] **Step 2: Type-check after the formatter change**

Run: `cd frontend && npx tsc -b --force`
Expected: clean (both call sites of `useFormatters`'s return value are additive fields, not a breaking change to existing callers).

- [ ] **Step 3: Write `useStopsAnalytics.ts`**

Create `frontend/src/features/analytics/manufacturing/useStopsAnalytics.ts`:

```typescript
import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { listStopsAnalytics, type StopAnalyticsRow } from "../../production/api";
import { buildWindows, localTodayIso, type DateWindow } from "./metrics";
import type { PeriodDays } from "../PeriodFilter";

export interface ClassificationBucket {
  classification: string | null;
  minutes: number;
  stopCount: number;
}

export interface MotifBucket {
  motif: string | null;
  minutes: number;
  stopCount: number;
}

export interface SourceBucket {
  source: StopAnalyticsRow["source"];
  minutes: number;
  sharePct: number;
}

export interface StopsSummary {
  totalMinutes: number;
  byClassification: ClassificationBucket[];
  byMotif: (classification: string | null) => MotifBucket[];
  bySource: SourceBucket[];
  unattributedMinutes: number;
  unattributedCount: number;
}

export function summarizeStops(rows: StopAnalyticsRow[]): StopsSummary {
  const totalMinutes = rows.reduce((sum, row) => sum + row.minutes, 0);

  const classificationMap = new Map<string | null, { minutes: number; stopCount: number }>();
  const motifByClassification = new Map<string | null, Map<string | null, { minutes: number; stopCount: number }>>();
  const sourceMap = new Map<StopAnalyticsRow["source"], number>();
  let unattributedMinutes = 0;
  let unattributedCount = 0;

  for (const row of rows) {
    const c = classificationMap.get(row.classification) ?? { minutes: 0, stopCount: 0 };
    c.minutes += row.minutes;
    c.stopCount += 1;
    classificationMap.set(row.classification, c);

    const motifMap = motifByClassification.get(row.classification) ?? new Map();
    const m = motifMap.get(row.motif) ?? { minutes: 0, stopCount: 0 };
    m.minutes += row.minutes;
    m.stopCount += 1;
    motifMap.set(row.motif, m);
    motifByClassification.set(row.classification, motifMap);

    sourceMap.set(row.source, (sourceMap.get(row.source) ?? 0) + row.minutes);

    if (row.equipment_id === null) {
      unattributedMinutes += row.minutes;
      unattributedCount += 1;
    }
  }

  const byClassification = [...classificationMap.entries()]
    .map(([classification, v]) => ({ classification, ...v }))
    .sort((a, b) => b.minutes - a.minutes);

  const bySource = [...sourceMap.entries()]
    .map(([source, minutes]) => ({ source, minutes, sharePct: totalMinutes > 0 ? (minutes / totalMinutes) * 100 : 0 }))
    .sort((a, b) => b.minutes - a.minutes);

  return {
    totalMinutes,
    byClassification,
    byMotif: (classification) =>
      [...(motifByClassification.get(classification) ?? new Map()).entries()]
        .map(([motif, v]) => ({ motif, ...v }))
        .sort((a, b) => b.minutes - a.minutes),
    bySource,
    unattributedMinutes,
    unattributedCount,
  };
}

export function useStopsAnalytics(days: PeriodDays) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);

  const stops = useQuery({
    queryKey: ["analytics", "stops", windows.current.from, windows.current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listStopsAnalytics(token, { date_from: windows.current.from, date_to: windows.current.to }),
  });

  const summary = useMemo(() => summarizeStops(stops.data ?? []), [stops.data]);

  return { windows, stops, summary };
}

export type { DateWindow };
```

- [ ] **Step 4: Write `useEnergyAnalytics.ts`**

Create `frontend/src/features/analytics/manufacturing/useEnergyAnalytics.ts`:

```typescript
import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { listEnergyAnalytics, type EnergyAnalyticsRow } from "../../production/api";
import { buildWindows, localTodayIso } from "./metrics";
import type { PeriodDays } from "../PeriodFilter";

export interface EnergyTotals {
  fuel: number;
  gasoil: number;
  generatorHours: number;
  electricity: number;
  produced: number;
}

export interface EnergyByLine {
  workCenterId: string;
  totals: EnergyTotals;
  fuelPerTonne: number | null;
  gasoilPerTonne: number | null;
  electricityPerTonne: number | null;
}

export interface EnergySummary {
  totals: EnergyTotals;
  fuelPerTonne: number | null;
  gasoilPerTonne: number | null;
  electricityPerTonne: number | null;
  byDate: { date: string; fuel: number; gasoil: number; electricity: number }[];
  byLine: EnergyByLine[];
}

function emptyTotals(): EnergyTotals {
  return { fuel: 0, gasoil: 0, generatorHours: 0, electricity: 0, produced: 0 };
}

function addRow(target: EnergyTotals, row: EnergyAnalyticsRow) {
  target.fuel += row.fuel_quantity;
  target.gasoil += row.gasoil_quantity;
  target.generatorHours += row.generator_hours;
  target.electricity += row.electricity_quantity;
  target.produced += row.produced_quantity;
}

/** Tonnes per KG_PER_TONNE-scale conversion is not needed here: produced_quantity is
 * already in the semolina's own unit (tonnes for this tenant, same basis every other
 * per-tonne figure in this module uses -- see wasteRate's own comment in metrics.ts). */
export function summarizeEnergy(rows: EnergyAnalyticsRow[]): EnergySummary {
  const totals = emptyTotals();
  const byDateMap = new Map<string, { fuel: number; gasoil: number; electricity: number }>();
  const byLineMap = new Map<string, EnergyTotals>();

  for (const row of rows) {
    addRow(totals, row);

    const d = byDateMap.get(row.report_date) ?? { fuel: 0, gasoil: 0, electricity: 0 };
    d.fuel += row.fuel_quantity;
    d.gasoil += row.gasoil_quantity;
    d.electricity += row.electricity_quantity;
    byDateMap.set(row.report_date, d);

    const l = byLineMap.get(row.work_center_id) ?? emptyTotals();
    addRow(l, row);
    byLineMap.set(row.work_center_id, l);
  }

  const byLine = [...byLineMap.entries()]
    .map(([workCenterId, t]) => ({
      workCenterId,
      totals: t,
      fuelPerTonne: t.produced > 0 ? t.fuel / t.produced : null,
      gasoilPerTonne: t.produced > 0 ? t.gasoil / t.produced : null,
      electricityPerTonne: t.produced > 0 ? t.electricity / t.produced : null,
    }))
    .sort((a, b) => a.workCenterId.localeCompare(b.workCenterId));

  return {
    totals,
    fuelPerTonne: totals.produced > 0 ? totals.fuel / totals.produced : null,
    gasoilPerTonne: totals.produced > 0 ? totals.gasoil / totals.produced : null,
    electricityPerTonne: totals.produced > 0 ? totals.electricity / totals.produced : null,
    byDate: [...byDateMap.entries()].map(([date, v]) => ({ date, ...v })).sort((a, b) => a.date.localeCompare(b.date)),
    byLine,
  };
}

export function useEnergyAnalytics(days: PeriodDays) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);
  const { current, previous } = windows;

  const energyCurrent = useQuery({
    queryKey: ["analytics", "energy", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listEnergyAnalytics(token, { date_from: current.from, date_to: current.to }),
  });
  const energyPrevious = useQuery({
    queryKey: ["analytics", "energy", previous.from, previous.to],
    placeholderData: keepPreviousData,
    queryFn: () => listEnergyAnalytics(token, { date_from: previous.from, date_to: previous.to }),
  });

  const summary = useMemo(() => summarizeEnergy(energyCurrent.data ?? []), [energyCurrent.data]);
  const previousSummary = useMemo(() => summarizeEnergy(energyPrevious.data ?? []), [energyPrevious.data]);

  return { windows, energyCurrent, energyPrevious, summary, previousSummary };
}
```

`ratioPct` is not imported into this file — only `buildWindows`/`localTodayIso` are needed from `metrics.ts`, since every per-tonne guard above is a direct `> 0` check, not a percentage.

- [ ] **Step 5: Write `useShiftHealth.ts`**

Create `frontend/src/features/analytics/manufacturing/useShiftHealth.ts`:

```typescript
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { getShiftHealth } from "../../production/api";
import { buildWindows, localTodayIso } from "./metrics";
import type { PeriodDays } from "../PeriodFilter";

export function useShiftHealth(days: PeriodDays) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);

  const health = useQuery({
    queryKey: ["analytics", "shift-health", windows.current.from, windows.current.to],
    queryFn: () => getShiftHealth(token, { date_from: windows.current.from, date_to: windows.current.to }),
  });

  return { windows, health };
}
```

- [ ] **Step 6: Add i18n keys**

In `frontend/src/lib/i18n.tsx`, find the `analytics.tabs.*` block in the `en` dict (around line 1187) and add three new tab labels plus each tab's own content keys. Search for the exact insertion point:

```bash
grep -n '"analytics.tabs.priceHistory"' frontend/src/lib/i18n.tsx
```

Add immediately after that line in the `en` object:

```typescript
  "analytics.tabs.downtime": "Downtime",
  "analytics.tabs.energy": "Energy",
  "analytics.tabs.shiftHealth": "Shift health",

  "analytics.downtime.classification.title": "Downtime by classification",
  "analytics.downtime.classification.subtitle": "Minutes lost, grouped by how the stop was classified.",
  "analytics.downtime.motif.title": "Reasons",
  "analytics.downtime.motif.subtitle": "Click a classification above to see its reasons.",
  "analytics.downtime.captureQuality.title": "How stops were captured",
  "analytics.downtime.captureQuality.live": "Live",
  "analytics.downtime.captureQuality.addedAfter": "Added after",
  "analytics.downtime.captureQuality.manual": "Manual",
  "analytics.downtime.captureQuality.migrated": "Migrated",
  "analytics.downtime.unattributed.title": "Unattributed downtime",
  "analytics.downtime.unattributed.subtitle": "Stops with no machine recorded — {count} stop(s), {minutes}.",
  "analytics.downtime.unclassified": "Unclassified",
  "analytics.downtime.noReason": "No reason given",

  "analytics.energy.trend.title": "Energy consumption",
  "analytics.energy.trend.subtitle": "Fuel, gasoil and electricity, by day.",
  "analytics.energy.perTonne.title": "Energy per tonne produced",
  "analytics.energy.byLine.title": "By line",
  "analytics.energy.generator.title": "Generator usage",
  "analytics.energy.generator.subtitle": "Hours the generator ran.",
  "analytics.energy.fuel": "Fuel",
  "analytics.energy.gasoil": "Gasoil",
  "analytics.energy.electricity": "Electricity",
  "analytics.energy.empty.title": "No energy recorded yet",
  "analytics.energy.empty.description": "No shift in this period recorded energy figures.",

  "analytics.shiftHealth.funnel.title": "Submission funnel",
  "analytics.shiftHealth.funnel.subtitle": "Every shift opened in this period, by current status.",
  "analytics.shiftHealth.status.open": "Open",
  "analytics.shiftHealth.status.submitted": "Submitted",
  "analytics.shiftHealth.status.validated": "Validated",
  "analytics.shiftHealth.status.returned": "Returned",
  "analytics.shiftHealth.timeToValidate.title": "Time to validate",
  "analytics.shiftHealth.timeToValidate.subtitle": "From submission to approval.",
  "analytics.shiftHealth.timeToValidate.median": "Median",
  "analytics.shiftHealth.timeToValidate.average": "Average",
  "analytics.shiftHealth.timeToValidate.empty": "No shift validated in this period yet.",
  "analytics.shiftHealth.returnRate.title": "Sections sent back",
  "analytics.shiftHealth.returnRate.subtitle": "Share of each section that was returned to the team at least once.",
  "analytics.shiftHealth.completeness.title": "Section completeness",
  "analytics.shiftHealth.completeness.subtitle": "Average sections filled per shift, out of {total}.",
  "analytics.shiftHealth.section.runs": "Production",
  "analytics.shiftHealth.section.waste_production": "Production waste",
  "analytics.shiftHealth.section.stops": "Stops",
  "analytics.shiftHealth.section.silo": "Silo",
  "analytics.shiftHealth.section.staffing": "Staffing",
  "analytics.shiftHealth.section.packing": "Packing",
  "analytics.shiftHealth.section.packet_checks": "Packet checks",
  "analytics.shiftHealth.section.waste_packing": "Packing waste",
  "analytics.shiftHealth.section.energy": "Energy",
```

Then find the matching `fr` block (search `grep -n '"analytics.tabs.priceHistory"' frontend/src/lib/i18n.tsx` will show two line numbers — the second is the `fr` dict) and add the French mirror at the equivalent position, same keys, French text:

```typescript
  "analytics.tabs.downtime": "Arrêts",
  "analytics.tabs.energy": "Énergie",
  "analytics.tabs.shiftHealth": "Santé des shifts",

  "analytics.downtime.classification.title": "Arrêts par classification",
  "analytics.downtime.classification.subtitle": "Minutes perdues, groupées par la façon dont l'arrêt a été classé.",
  "analytics.downtime.motif.title": "Motifs",
  "analytics.downtime.motif.subtitle": "Cliquez une classification ci-dessus pour voir ses motifs.",
  "analytics.downtime.captureQuality.title": "Comment les arrêts ont été saisis",
  "analytics.downtime.captureQuality.live": "En direct",
  "analytics.downtime.captureQuality.addedAfter": "Ajouté après coup",
  "analytics.downtime.captureQuality.manual": "Manuel",
  "analytics.downtime.captureQuality.migrated": "Migré",
  "analytics.downtime.unattributed.title": "Arrêts non attribués",
  "analytics.downtime.unattributed.subtitle": "Arrêts sans machine enregistrée — {count} arrêt(s), {minutes}.",
  "analytics.downtime.unclassified": "Non classé",
  "analytics.downtime.noReason": "Aucun motif indiqué",

  "analytics.energy.trend.title": "Consommation d'énergie",
  "analytics.energy.trend.subtitle": "Fioul, gasoil et électricité, par jour.",
  "analytics.energy.perTonne.title": "Énergie par tonne produite",
  "analytics.energy.byLine.title": "Par ligne",
  "analytics.energy.generator.title": "Utilisation du groupe électrogène",
  "analytics.energy.generator.subtitle": "Heures de fonctionnement du groupe.",
  "analytics.energy.fuel": "Fioul",
  "analytics.energy.gasoil": "Gasoil",
  "analytics.energy.electricity": "Électricité",
  "analytics.energy.empty.title": "Aucune énergie enregistrée",
  "analytics.energy.empty.description": "Aucun shift de cette période n'a enregistré de données d'énergie.",

  "analytics.shiftHealth.funnel.title": "Entonnoir de soumission",
  "analytics.shiftHealth.funnel.subtitle": "Chaque shift ouvert sur cette période, par statut actuel.",
  "analytics.shiftHealth.status.open": "Ouvert",
  "analytics.shiftHealth.status.submitted": "Soumis",
  "analytics.shiftHealth.status.validated": "Validé",
  "analytics.shiftHealth.status.returned": "Renvoyé",
  "analytics.shiftHealth.timeToValidate.title": "Délai de validation",
  "analytics.shiftHealth.timeToValidate.subtitle": "De la soumission à l'approbation.",
  "analytics.shiftHealth.timeToValidate.median": "Médiane",
  "analytics.shiftHealth.timeToValidate.average": "Moyenne",
  "analytics.shiftHealth.timeToValidate.empty": "Aucun shift validé sur cette période.",
  "analytics.shiftHealth.returnRate.title": "Sections renvoyées",
  "analytics.shiftHealth.returnRate.subtitle": "Part de chaque section renvoyée à l'équipe au moins une fois.",
  "analytics.shiftHealth.completeness.title": "Complétude des sections",
  "analytics.shiftHealth.completeness.subtitle": "Sections remplies en moyenne par shift, sur {total}.",
  "analytics.shiftHealth.section.runs": "Production",
  "analytics.shiftHealth.section.waste_production": "Déchets production",
  "analytics.shiftHealth.section.stops": "Arrêts",
  "analytics.shiftHealth.section.silo": "Silo",
  "analytics.shiftHealth.section.staffing": "Effectifs",
  "analytics.shiftHealth.section.packing": "Conditionnement",
  "analytics.shiftHealth.section.packet_checks": "Contrôles paquets",
  "analytics.shiftHealth.section.waste_packing": "Déchets conditionnement",
  "analytics.shiftHealth.section.energy": "Énergie",
```

- [ ] **Step 7: Write `DowntimeAnalyticsTab.tsx`**

Create `frontend/src/features/analytics/DowntimeAnalyticsTab.tsx`:

```tsx
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useI18n } from "../../lib/i18n";
import { fill } from "./manufacturing/format";
import { useFormatters } from "./manufacturing/format";
import { useStopsAnalytics } from "./manufacturing/useStopsAnalytics";
import { useMinimumLoading } from "./useMinimumLoading";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import YieldWasteIllustration from "../../assets/illustrations/yield-waste.svg?react";

const BAR = "hsl(217 91% 45%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };
const SOURCE_LABEL_KEY = {
  live: "analytics.downtime.captureQuality.live",
  added_after: "analytics.downtime.captureQuality.addedAfter",
  manual: "analytics.downtime.captureQuality.manual",
  migrated: "analytics.downtime.captureQuality.migrated",
} as const;

export function DowntimeAnalyticsTab() {
  const { t } = useI18n();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, stops, summary } = useStopsAnalytics(days);
  const showLoader = useMinimumLoading(stops.isLoading);
  const fmt = useFormatters(useMemo(() => (id: string) => id, []));
  const [selectedClassification, setSelectedClassification] = useState<string | null | undefined>(undefined);

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (stops.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => stops.refetch()} />
        </Card>
      </div>
    );
  }
  if (summary.totalMinutes === 0 && (stops.data ?? []).length === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={YieldWasteIllustration} title={t("analytics.empty.production.title")} description={t("analytics.empty.production.description")} />
        </Card>
      </div>
    );
  }

  // React state can hold `null` as a real, distinct value (the "unclassified" bucket),
  // so `undefined` is reserved for "nothing picked yet -- default to the biggest bucket".
  const classificationData = summary.byClassification.map((c) => ({
    classification: c.classification,
    label: c.classification ? fmt.classification(c.classification) : t("analytics.downtime.unclassified"),
    minutes: c.minutes,
  }));
  const activeClassification = selectedClassification === undefined ? summary.byClassification[0]?.classification ?? null : selectedClassification;
  const motifData = summary
    .byMotif(activeClassification)
    .map((m) => ({ key: m.motif ?? "__none__", label: m.motif ? fmt.motif(m.motif) : t("analytics.downtime.noReason"), minutes: m.minutes }));

  return (
    <div className="space-y-5">
      {header}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("analytics.downtime.classification.title")}</CardTitle>
              <CardDescription>{t("analytics.downtime.classification.subtitle")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={classificationData}
                  margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
                  onClick={(state) => {
                    const clicked = state?.activePayload?.[0]?.payload as (typeof classificationData)[number] | undefined;
                    if (clicked) setSelectedClassification(clicked.classification);
                  }}
                >
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={false} />
                  <YAxis tick={TICK} tickLine={false} axisLine={false} width={44} />
                  <Tooltip formatter={(value) => [fmt.duration(Number(value)), t("analytics.machines.rate")]} />
                  <Bar dataKey="minutes" fill={BAR} radius={[4, 4, 0, 0]} cursor="pointer" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("analytics.downtime.motif.title")}</CardTitle>
              <CardDescription>{t("analytics.downtime.motif.subtitle")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {motifData.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("analytics.yieldWasteTab.drivers.none")}</p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {motifData.map((m) => (
                  <li key={m.key} className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs">
                    {m.label} <span className="tabular-nums text-muted-foreground">· {fmt.duration(m.minutes)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.downtime.captureQuality.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {summary.bySource.map((s) => (
              <div key={s.source} className="flex items-center gap-3">
                <span className="w-28 shrink-0 text-sm">{t(SOURCE_LABEL_KEY[s.source])}</span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted" role="presentation">
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${s.sharePct}%` }} />
                </span>
                <span className="w-16 shrink-0 text-right text-sm tabular-nums">{s.sharePct.toFixed(0)}%</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.downtime.unattributed.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              {fill(t("analytics.downtime.unattributed.subtitle"), {
                count: String(summary.unattributedCount),
                minutes: fmt.duration(summary.unattributedMinutes),
              })}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Write `EnergyAnalyticsTab.tsx`**

Create `frontend/src/features/analytics/EnergyAnalyticsTab.tsx`:

```tsx
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend, Bar, BarChart } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useI18n } from "../../lib/i18n";
import { formatNumber } from "./manufacturing/format";
import { useEnergyAnalytics } from "./manufacturing/useEnergyAnalytics";
import { useMinimumLoading } from "./useMinimumLoading";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import YieldWasteIllustration from "../../assets/illustrations/yield-waste.svg?react";

const FUEL_COLOR = "hsl(38 92% 42%)";
const GASOIL_COLOR = "hsl(217 91% 45%)";
const ELECTRICITY_COLOR = "hsl(152 69% 31%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };

export function EnergyAnalyticsTab() {
  const { t } = useI18n();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, energyCurrent, summary } = useEnergyAnalytics(days);
  const showLoader = useMinimumLoading(energyCurrent.isLoading);

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (energyCurrent.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => energyCurrent.refetch()} />
        </Card>
      </div>
    );
  }
  if ((energyCurrent.data ?? []).length === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={YieldWasteIllustration} title={t("analytics.energy.empty.title")} description={t("analytics.energy.empty.description")} />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {header}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("analytics.energy.trend.title")}</CardTitle>
            <CardDescription>{t("analytics.energy.trend.subtitle")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={summary.byDate} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="date" tick={TICK} tickLine={false} axisLine={false} minTickGap={32} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} width={44} />
                <Tooltip />
                <Legend />
                <Line type="linear" dataKey="fuel" name={t("analytics.energy.fuel")} stroke={FUEL_COLOR} strokeWidth={2} dot={false} />
                <Line type="linear" dataKey="gasoil" name={t("analytics.energy.gasoil")} stroke={GASOIL_COLOR} strokeWidth={2} dot={false} />
                <Line type="linear" dataKey="electricity" name={t("analytics.energy.electricity")} stroke={ELECTRICITY_COLOR} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.energy.perTonne.title")}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-3 text-center">
            <div>
              <p className="text-2xl font-semibold tabular-nums">{summary.fuelPerTonne === null ? "—" : formatNumber(summary.fuelPerTonne, 2)}</p>
              <p className="text-xs text-muted-foreground">{t("analytics.energy.fuel")}</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums">{summary.gasoilPerTonne === null ? "—" : formatNumber(summary.gasoilPerTonne, 2)}</p>
              <p className="text-xs text-muted-foreground">{t("analytics.energy.gasoil")}</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums">{summary.electricityPerTonne === null ? "—" : formatNumber(summary.electricityPerTonne, 2)}</p>
              <p className="text-xs text-muted-foreground">{t("analytics.energy.electricity")}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.energy.generator.title")}</CardTitle>
            <CardDescription>{t("analytics.energy.generator.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">{formatNumber(summary.totals.generatorHours, 1)} h</p>
          </CardContent>
        </Card>
      </div>

      {summary.byLine.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.energy.byLine.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={summary.byLine.map((l) => ({ line: l.workCenterId, gasoil: l.gasoilPerTonne ?? 0 }))} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="line" tick={TICK} tickLine={false} axisLine={false} />
                  <YAxis tick={TICK} tickLine={false} axisLine={false} width={44} />
                  <Tooltip />
                  <Bar dataKey="gasoil" name={t("analytics.energy.gasoil")} fill={GASOIL_COLOR} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
```

Note: `EnergyByLine`'s work_center_id is shown raw (no line-name resolution) — this matches the plan's scope (no new line-name-lookup plumbing); if a future pass wants line names instead of ids, that's a follow-up, not part of this task.

- [ ] **Step 9: Write `ShiftHealthTab.tsx`**

Create `frontend/src/features/analytics/ShiftHealthTab.tsx`:

```tsx
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { fill, formatNumber, formatPercent } from "./manufacturing/format";
import { useShiftHealth } from "./manufacturing/useShiftHealth";
import { useMinimumLoading } from "./useMinimumLoading";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import YieldWasteIllustration from "../../assets/illustrations/yield-waste.svg?react";

const BAR = "hsl(217 91% 45%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };

function statusLabel(t: (key: TranslationKey) => string, status: string): string {
  const key = `analytics.shiftHealth.status.${status}` as TranslationKey;
  return t(key);
}

function sectionLabel(t: (key: TranslationKey) => string, key: string): string {
  return t(`analytics.shiftHealth.section.${key}` as TranslationKey);
}

export function ShiftHealthTab() {
  const { t } = useI18n();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, health } = useShiftHealth(days);
  const showLoader = useMinimumLoading(health.isLoading);

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (health.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => health.refetch()} />
        </Card>
      </div>
    );
  }
  const data = health.data;
  if (!data || data.completeness.shift_count === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={YieldWasteIllustration} title={t("analytics.empty.production.title")} description={t("analytics.empty.production.description")} />
        </Card>
      </div>
    );
  }

  const funnelData = data.funnel.map((f) => ({ status: statusLabel(t, f.status), count: f.count }));

  return (
    <div className="space-y-5">
      {header}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("analytics.shiftHealth.funnel.title")}</CardTitle>
            <CardDescription>{t("analytics.shiftHealth.funnel.subtitle")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnelData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="status" tick={TICK} tickLine={false} axisLine={false} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill={BAR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("analytics.shiftHealth.timeToValidate.title")}</CardTitle>
              <CardDescription>{t("analytics.shiftHealth.timeToValidate.subtitle")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {data.time_to_validate_minutes.sample_size === 0 ? (
              <p className="text-sm text-muted-foreground">{t("analytics.shiftHealth.timeToValidate.empty")}</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 text-center">
                <div>
                  <p className="text-2xl font-semibold tabular-nums">{formatNumber(data.time_to_validate_minutes.median ?? 0, 0)} min</p>
                  <p className="text-xs text-muted-foreground">{t("analytics.shiftHealth.timeToValidate.median")}</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold tabular-nums">{formatNumber(data.time_to_validate_minutes.average ?? 0, 0)} min</p>
                  <p className="text-xs text-muted-foreground">{t("analytics.shiftHealth.timeToValidate.average")}</p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.shiftHealth.completeness.title")}</CardTitle>
            <CardDescription>{fill(t("analytics.shiftHealth.completeness.subtitle"), { total: String(data.completeness.total_sections) })}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">
              {data.completeness.average_sections_filled === null ? "—" : formatNumber(data.completeness.average_sections_filled, 1)} / {data.completeness.total_sections}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("analytics.shiftHealth.returnRate.title")}</CardTitle>
            <CardDescription>{t("analytics.shiftHealth.returnRate.subtitle")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("analytics.teams.column.team")}</TableHead>
                <TableHead className="text-right">{t("analytics.shiftHealth.returnRate.title")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.return_rate_by_section.map((row) => (
                <TableRow key={row.section_key}>
                  <TableCell className="font-medium">{sectionLabel(t, row.section_key)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatPercent(row.return_rate_pct)} ({row.returned_count}/{row.total_count})
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 10: Regroup `AnalyticsPage.tsx`'s tabs**

Read the current file first (it was already read earlier in this session — the `TABS` array is lines 23-41). Replace it:

```tsx
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { Cog, Factory, FileSpreadsheet, Gauge, HeartPulse, PackageSearch, Recycle, TrendingUp, Users, Zap } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useI18n } from "../../lib/i18n";
import { AnalyticsOverviewSection } from "./AnalyticsOverviewSection";
import { YieldWasteTab } from "./YieldWasteTab";
import { TeamPerformanceTab } from "./TeamPerformanceTab";
import { MachinePerformanceTab } from "./MachinePerformanceTab";
import { DowntimeAnalyticsTab } from "./DowntimeAnalyticsTab";
import { EnergyAnalyticsTab } from "./EnergyAnalyticsTab";
import { ShiftHealthTab } from "./ShiftHealthTab";
import { ConsumptionReportTab } from "./ConsumptionReportTab";
import { ProductionRecapExportTab } from "./ProductionRecapExportTab";
import { PriceHistoryTab } from "./PriceHistoryTab";

// Cross-module KPIs — anything that reads more than one module's data to answer
// one question (here: production's reports and qc's quality reports, by team)
// lives here rather than inside the module whose tables happen to back it, so
// Production's tabs stay about the OF and Quality's about the report/NC record.
// Machine performance is single-module (production only), but sits beside team
// performance rather than inside a Production tab because it answers the same
// kind of cross-cutting "who/what is producing well" question, at a different grain.
// Consumption-by-supplier reads production's report tables *and* procurement's
// order history (for costing), so it belongs here for the same reason.
//
// Two visual groups: "production" (how is the plant running) and "cost" (what
// does it cost) — same tab bar, same ?tab= param, grouped only for the reader's
// sake as the list has grown past what a flat row reads well at.
const TABS = [
  { value: "overview", labelKey: "analytics.tabs.overview", icon: Factory, Component: AnalyticsOverviewSection, group: "production" },
  { value: "yield-waste", labelKey: "analytics.tabs.yieldWaste", icon: Recycle, Component: YieldWasteTab, group: "production" },
  { value: "team-performance", labelKey: "analytics.tabs.teamPerformance", icon: Users, Component: TeamPerformanceTab, group: "production" },
  { value: "machine-performance", labelKey: "analytics.tabs.machinePerformance", icon: Cog, Component: MachinePerformanceTab, group: "production" },
  { value: "downtime", labelKey: "analytics.tabs.downtime", icon: Gauge, Component: DowntimeAnalyticsTab, group: "production" },
  { value: "energy", labelKey: "analytics.tabs.energy", icon: Zap, Component: EnergyAnalyticsTab, group: "production" },
  { value: "shift-health", labelKey: "analytics.tabs.shiftHealth", icon: HeartPulse, Component: ShiftHealthTab, group: "production" },
  {
    value: "consumption-report",
    labelKey: "analytics.tabs.consumptionReport",
    icon: PackageSearch,
    Component: ConsumptionReportTab,
    group: "cost",
  },
  {
    value: "production-recap",
    labelKey: "analytics.tabs.productionRecap",
    icon: FileSpreadsheet,
    Component: ProductionRecapExportTab,
    group: "cost",
  },
  { value: "price-history", labelKey: "analytics.tabs.priceHistory", icon: TrendingUp, Component: PriceHistoryTab, group: "cost" },
] as const;

type TabValue = (typeof TABS)[number]["value"];
type TabGroup = (typeof TABS)[number]["group"];
const GROUP_LABEL_KEY: Record<TabGroup, "analytics.group.production" | "analytics.group.cost"> = {
  production: "analytics.group.production",
  cost: "analytics.group.cost",
};

export function AnalyticsPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = TABS.some((entry) => entry.value === requested) ? requested! : "overview";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
  const ActiveTab = TABS.find((entry) => entry.value === tab)!.Component;
  const groups: TabGroup[] = ["production", "cost"];

  return (
    <MotionConfig reducedMotion="user">
      <div className="space-y-6">
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <h1 className="text-xl font-semibold tracking-tight">{t("analytics.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("analytics.subtitle")}</p>
        </motion.div>

        {TABS.length > 1 && (
          <div className="space-y-2">
            {groups.map((group) => (
              <div key={group} className="space-y-1.5">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t(GROUP_LABEL_KEY[group])}</p>
                <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
                  <TabsList>
                    {TABS.filter((entry) => entry.group === group).map((tabDef) => (
                      <TabsTrigger key={tabDef.value} value={tabDef.value} active={tab === tabDef.value} layoutId="analytics-tab-indicator">
                        <span className="flex items-center gap-1.5">
                          <tabDef.icon className="h-4 w-4" />
                          {t(tabDef.labelKey)}
                        </span>
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
              </div>
            ))}
          </div>
        )}

        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            <ActiveTab />
          </motion.div>
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}
```

Add the two new group-label i18n keys alongside Step 6's additions (`en`: `"analytics.group.production": "Production"`, `"analytics.group.cost": "Cost & pricing"`; `fr`: `"analytics.group.production": "Production"`, `"analytics.group.cost": "Coûts et prix"`).

Note: rendering two separate `<Tabs>` instances (one per group) sharing one `value`/`onValueChange` means the `layoutId="analytics-tab-indicator"` animated underline will not slide between groups smoothly (framer-motion's shared layout animation works within one animated tree per group here, not across two `<Tabs>` trees) — verify this visually in Step 12's browser pass; if the cross-group transition looks broken, drop `layoutId` from the second group's `TabsTrigger`s (each group keeps its own independent indicator, which is a fine tradeoff for a purely visual grouping) rather than restructuring `Tabs`/`TabsList` to accept a flat list with visual dividers.

- [ ] **Step 11: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean.

- [ ] **Step 12: Browser verification**

Use the `run` skill or drive manually against the seeded shift month (2026-08-20..2026-09-20): open Analytics, confirm the two-group tab bar renders and both groups' tabs are clickable and keep the URL `?tab=` in sync; open Downtime and confirm the classification pareto renders, click a bar and confirm the motif list below updates, confirm the capture-quality bars and the unattributed-downtime line show real numbers; open Energy and confirm the three-series trend, per-tonne stats, and generator hours render with real seeded data; open Shift Health and confirm the funnel, time-to-validate, return-rate table and completeness stat all render with real numbers (the seeded month has submitted/validated/returned shifts per memory, so every panel should have non-empty data). Take note of the `layoutId` animation issue flagged in Step 10 and fix if visibly broken.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/features/analytics/manufacturing/useStopsAnalytics.ts frontend/src/features/analytics/manufacturing/useEnergyAnalytics.ts frontend/src/features/analytics/manufacturing/useShiftHealth.ts frontend/src/features/analytics/DowntimeAnalyticsTab.tsx frontend/src/features/analytics/EnergyAnalyticsTab.tsx frontend/src/features/analytics/ShiftHealthTab.tsx frontend/src/features/analytics/AnalyticsPage.tsx frontend/src/features/analytics/manufacturing/format.ts frontend/src/features/analytics/manufacturing/insights.ts frontend/src/lib/i18n.tsx
git commit -m "Add Downtime, Energy and Shift Health analytics tabs; regroup Analytics tab bar"
```

---

## Task 6: Validator-edit-rate panel on Shift Health (depends on Part A)

**Files:**
- Modify: `backend/modules/production/api/shift_health_service.py`
- Modify: `backend/modules/production/api/test_shift_health_integration.py`
- Modify: `frontend/src/features/production/api.ts` (extend `ShiftHealth` type)
- Modify: `frontend/src/features/analytics/ShiftHealthTab.tsx`
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `edited_by_validator` column from Part A's migration `0058` (`docs/superpowers/plans/2026-09-23-validator-edit-plan.md`, Task 1) — **do not start this task until Part A Task 1 (the migration) has been applied to the dev DB**, since `shift_section_revisions.edited_by_validator` must exist for this query to run at all.
- Produces: extends `get_shift_health`'s return dict with `"validator_edit_rate_by_section": [{"section_key": str, "edited_count": int, "total_count": int, "edit_rate_pct": float | None}]`.

- [ ] **Step 1: Confirm the prerequisite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "import psycopg; c = psycopg.connect('postgresql://erp:erp@localhost:5432/erp'); print(c.execute(\"SELECT column_name FROM information_schema.columns WHERE table_schema='production' AND table_name='shift_section_revisions' AND column_name='edited_by_validator'\").fetchone())"`
Expected: prints a row (the column exists). If it prints `None`, stop and complete Part A's Task 1 first.

- [ ] **Step 2: Write the failing test**

Add to `test_shift_health_integration.py`:

```python
def test_validator_edit_rate_by_section(db, env):
    from modules.production.api.shift_validation_service import ShiftValidationService as SVS

    shift_id = _open_shift(db, env)
    _submit_every_section_as_nothing_to_report(db, env, shift_id)
    # "nothing to report" sections have no rows to edit; declare_nothing already put
    # every section at 'nothing_to_report' -- edit one via the validator path, which
    # writes real rows into it regardless of its prior emptiness.
    edited = SVS(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="staffing",
        payload={}, reason="test edit",
    )
    assert isinstance(edited, Ok), getattr(edited, "message", "")

    health = ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from="2030-08-01", date_to="2030-08-01")

    by_key = {row["section_key"]: row for row in health["validator_edit_rate_by_section"]}
    assert by_key["staffing"]["edited_count"] == 1
    assert by_key["runs"]["edited_count"] == 0
```

(Import `ShiftValidationService` normally at the top of the file instead of inline if preferred — the inline import above only avoids reordering the file's existing import block; either is fine.)

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_health_integration.py -k validator_edit_rate -v`
Expected: FAIL — `KeyError: 'validator_edit_rate_by_section'`.

- [ ] **Step 4: Extend `get_shift_health`**

In `shift_health_service.py`, add after the `return_rate_by_section` block (before `completeness_row`):

```python
        edited_counts = dict(
            self._connection.execute(
                f"""
                SELECT r.section_key, count(DISTINCT r.shift_report_id)
                FROM production.shift_section_revisions r
                JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
                WHERE {where.replace('tenant_id', 's.tenant_id').replace('report_date', 's.report_date')}
                  AND r.section_key = ANY(%s) AND r.edited_by_validator = TRUE
                GROUP BY r.section_key
                """,
                [*params, list(SECTION_KEYS)],
            ).fetchall()
        )
        validator_edit_rate_by_section = [
            {
                "section_key": key,
                "edited_count": edited_counts.get(key, 0),
                "total_count": total_counts.get(key, 0),
                "edit_rate_pct": (
                    (edited_counts.get(key, 0) / total_counts[key]) * 100 if total_counts.get(key, 0) > 0 else None
                ),
            }
            for key in SECTION_KEYS
        ]
```

And add `"validator_edit_rate_by_section": validator_edit_rate_by_section,` to the final returned dict.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_health_integration.py -v`
Expected: all pass, including the new test.

- [ ] **Step 6: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -v`
Expected: all pass.

- [ ] **Step 7: Extend the frontend type and render the panel**

In `frontend/src/features/production/api.ts`, add to the `ShiftHealth` interface:

```typescript
  validator_edit_rate_by_section: { section_key: string; edited_count: number; total_count: number; edit_rate_pct: number | null }[];
```

In `ShiftHealthTab.tsx`, add a new `Card` after the return-rate table (same `Table`/`TableHeader`/`TableRow` pattern), reading `data.validator_edit_rate_by_section`. Add i18n keys `analytics.shiftHealth.validatorEditRate.title`/`.subtitle` to both `en` and `fr` in `i18n.tsx`, mirroring the pattern used for `returnRate` in Task 5 Step 6.

- [ ] **Step 8: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean.

- [ ] **Step 9: Browser verification**

After using Part A's validator-edit UI on a real submitted shift in the browser (per Part A's own Task 5 verification step), open the Shift Health tab and confirm the new panel shows a non-zero edit count for the section that was edited.

- [ ] **Step 10: Commit**

```bash
git add backend/modules/production/api/shift_health_service.py backend/modules/production/api/test_shift_health_integration.py frontend/src/features/production/api.ts frontend/src/features/analytics/ShiftHealthTab.tsx frontend/src/lib/i18n.tsx
git commit -m "Add validator-edit-rate panel to Shift Health tab"
```

---

## Task 7: Humidity trend on Yield & Waste + DLC-coverage stat

**Files:**
- Create: `backend/modules/production/api/humidity_analytics_service.py`
- Create: `backend/modules/production/api/test_humidity_analytics_integration.py`
- Modify: `backend/modules/production/api/router.py`
- Modify: `frontend/src/features/production/api.ts`
- Modify: `frontend/src/features/analytics/YieldWasteTab.tsx`
- Modify: `frontend/src/features/analytics/manufacturing/metrics.ts`
- Modify: `frontend/src/features/analytics/manufacturing/useManufacturingOverview.ts`
- Modify: `frontend/src/features/analytics/AnalyticsOverviewSection.tsx`
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Produces: `list_humidity(connection, *, tenant_id, date_from, date_to) -> list[dict]` (new file, kept separate from `team_performance_service.py` because humidity is per-run, not per-team-period, and doesn't fit that query's grain), exposed as `GET /production/analytics/humidity?date_from=&date_to=` returning `[{report_date: str, work_center_id: str, humidity_percentage: float}]`. DLC coverage reuses the **existing** `LotService.list_lots(source_type=..., without_expiry=True)` (`backend/modules/warehouse/api/lot_service.py:45`) directly — no new backend code for it, just a frontend count of an existing response, per Step 6 below.

- [ ] **Step 1: Confirm the source_type value packing rows' lots use**

```bash
grep -n "source_type" backend/modules/production/api/legacy_report_ledger.py backend/modules/warehouse/api/lot_service.py | head -10
```

Confirm the string `LotService.register_lot` writes as `source_type` for a packing-row-registered lot (per memory, this is the existing finished-goods lot path QC's `LotDlcTab` already queries). Use that exact string as `source_type` in Step 6's frontend call — do not guess a value.

- [ ] **Step 2: Write the failing test for the humidity endpoint**

Create `backend/modules/production/api/test_humidity_analytics_integration.py`, reusing the exact `env`/`_of`/`_ok`/`_shift` fixture bodies from Task 1's test file (tenant `TENANT = "humidity-analytics-test"`), plus:

```python
def _validated_shift_with_humidity(db, env, *, humidity) -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900, "humidity_percentage": humidity,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]
    packing = {"of_id": of_id, "run_id": run_ids[0], "equipment_id": env["equipment"], "finished_product_quantity": 800,
               "packets_counted": 1600, "film_quantity": 40, "carton_quantity": 100, "scotch_quantity": 2, "ruban_quantity": 1,
               "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
               "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_location"],
               "finished_goods_location_id": env["fg_location"], "lot_number": "B7031SNL"}

    filled = {"runs": None, "packing": {"rows": [packing]}}
    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_humidity_endpoint_returns_run_level_readings(db, env):
    _validated_shift_with_humidity(db, env, humidity=14.2)

    rows = list_humidity(db, tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")

    assert len(rows) == 1
    assert rows[0]["humidity_percentage"] == 14.2
    assert rows[0]["work_center_id"] == env["work_center"]
```

Add a second test in the same file:

```python
def test_runs_with_no_humidity_are_skipped_not_zeroed(db, env):
    """humidity_percentage defaults to NULL on shift_runs when never typed
    (migration 0048's column has no DEFAULT) -- Step 3's WHERE clause must
    exclude those runs, not report them as 0%."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))

    for key in SECTION_KEYS:
        if key != "runs":
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs"))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))

    rows = list_humidity(db, tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")
    assert rows == []
```

(Note: this second test omits a packing row entirely and declares `packing` nothing-to-report, unlike `_validated_shift_with_humidity` — `SECTION_KEYS` includes `packing` in its loop, so declaring it empty here is required for `submit_every_section`-style validation to reach `validated`; this mirrors `_submitted_shift`'s own `packing: True/False` flag from `test_shift_validation_integration.py`, just inlined for a single case instead of parameterized.)

Add imports at the top: same set as Task 1's test file, plus `from modules.production.api.humidity_analytics_service import list_humidity`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_humidity_analytics_integration.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `list_humidity`**

Create `backend/modules/production/api/humidity_analytics_service.py`:

```python
from __future__ import annotations

import psycopg


def list_humidity(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Dough humidity per validated run, for the Yield & Waste humidity trend.

    Skips runs with no recorded humidity_percentage -- not every run's team
    measures it, and a null is "not measured," never treated as 0.
    """
    clauses = ["s.tenant_id = %s", "s.status = 'validated'", "r.humidity_percentage IS NOT NULL"]
    params: list[object] = [tenant_id]
    if date_from is not None:
        clauses.append("s.report_date >= %s")
        params.append(date_from)
    if date_to is not None:
        clauses.append("s.report_date <= %s")
        params.append(date_to)
    where = " AND ".join(clauses)
    rows = connection.execute(
        f"""
        SELECT s.report_date, s.work_center_id, r.humidity_percentage
        FROM production.shift_runs r
        JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
        WHERE {where}
        ORDER BY s.report_date
        """,
        params,
    ).fetchall()
    return [
        {"report_date": report_date.isoformat(), "work_center_id": work_center_id, "humidity_percentage": float(humidity)}
        for report_date, work_center_id, humidity in rows
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_humidity_analytics_integration.py -v`
Expected: both PASS.

- [ ] **Step 6: Add the endpoint**

In `router.py`:

```python
from modules.production.api.humidity_analytics_service import list_humidity


@router.get("/analytics/humidity")
def list_humidity_analytics(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    with get_connection() as connection:
        return list_humidity(connection, tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to)
```

- [ ] **Step 7: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -v`
Expected: all pass.

- [ ] **Step 8: Commit the backend piece**

```bash
git add backend/modules/production/api/humidity_analytics_service.py backend/modules/production/api/test_humidity_analytics_integration.py backend/modules/production/api/router.py
git commit -m "Add humidity analytics endpoint"
```

- [ ] **Step 9: Frontend — API client, hook wiring, and the Yield & Waste panel**

In `frontend/src/features/production/api.ts`, add:

```typescript
export interface HumidityRow {
  report_date: string;
  work_center_id: string;
  humidity_percentage: number;
}

export function listHumidity(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<HumidityRow[]>(`/production/analytics/humidity${suffix}`, { token });
}
```

In `frontend/src/features/analytics/manufacturing/metrics.ts`, add a small aggregation next to `summarizeOperations` (same file, same style — this is a genuinely reused shape, not a one-off, since both `useManufacturingOverview.ts` and `YieldWasteTab.tsx` will read it):

```typescript
export interface HumidityPoint {
  date: string;
  averageHumidityPct: number;
}

/** Average humidity per day, across every line -- skips nothing (every row already
 * has a non-null humidity_percentage per list_humidity's own filter). */
export function summarizeHumidity(rows: { report_date: string; humidity_percentage: number }[]): HumidityPoint[] {
  const byDate = new Map<string, { sum: number; count: number }>();
  for (const row of rows) {
    const bucket = byDate.get(row.report_date) ?? { sum: 0, count: 0 };
    bucket.sum += row.humidity_percentage;
    bucket.count += 1;
    byDate.set(row.report_date, bucket);
  }
  return [...byDate.entries()]
    .map(([date, { sum, count }]) => ({ date, averageHumidityPct: sum / count }))
    .sort((a, b) => a.date.localeCompare(b.date));
}
```

In `frontend/src/features/analytics/manufacturing/useManufacturingOverview.ts`, add to `useOperationsData` (alongside the existing `teamCurrent` query):

```typescript
  const humidityCurrent = useQuery({
    queryKey: [...ROOT, "humidity", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listHumidity(token, { date_from: current.from, date_to: current.to }),
  });
  const humidity = useMemo(() => summarizeHumidity(humidityCurrent.data ?? []), [humidityCurrent.data]);
```

Add `listHumidity` to the existing import from `../../production/api` and `summarizeHumidity` to the existing import from `./metrics`. Add `humidityCurrent, humidity` to `useOperationsData`'s returned object.

In `YieldWasteTab.tsx`, destructure `humidity` alongside the existing `{ windows, teamCurrent, ops, previousOps }` from `useOperationsData(days)`, and add a new `Card` after the existing trend/drivers grid (same `LineChart`/`CartesianGrid`/`XAxis`/`YAxis`/`Tooltip`/`Line` structure as the yield trend chart already in that file, reading `humidity.map(p => ({ date: p.date, humidity: p.averageHumidityPct }))` as its data, `dataKey="humidity"`, y-axis formatted as `${formatNumber(value, 1)}%`). Render the card only `{humidity.length > 0 && (...)}` — no card, no empty state, when nothing in the window recorded humidity (this is additive information, not a primary metric the tab depends on, so it should not force a loading/error branch of its own; it rides on `teamCurrent`'s existing loading/error states since both queries share the same window).

- [ ] **Step 10: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean.

- [ ] **Step 11: Commit the humidity frontend piece**

```bash
git add frontend/src/features/production/api.ts frontend/src/features/analytics/manufacturing/metrics.ts frontend/src/features/analytics/manufacturing/useManufacturingOverview.ts frontend/src/features/analytics/YieldWasteTab.tsx
git commit -m "Add humidity trend panel to Yield & Waste tab"
```

- [ ] **Step 12: DLC-coverage stat on `AnalyticsOverviewSection.tsx`**

Read the file first:

```bash
grep -n "quality\|conformity\|Card" frontend/src/features/analytics/AnalyticsOverviewSection.tsx | head -20
```

Find the existing quality/conformity card in that file (the Overview already renders QC conformity figures per `useManufacturingOverview`'s `quality` field). Add a small stat line inside that same card (not a new `Card` — this is one number riding alongside an existing quality figure, matching the "don't add a whole new tab for one number" decision from the spec): `listLots(token, { source_type: <value confirmed in Step 1>, without_expiry: true })` from `frontend/src/features/warehouse/api.ts` (check that file's existing `listLots` export signature first with `grep -n "export function listLots" frontend/src/features/warehouse/api.ts` and match its exact parameter names), rendered as `{count} lots awaiting DLC` with a `Link to="/quality?tab=lot-dlc"` (import `Link` from `react-router-dom`, matching how `react-router-dom` is already imported in this codebase's other cross-module links — confirm the import path with `grep -rn 'from "react-router-dom"' frontend/src/features/analytics/`). Add i18n keys `analytics.overview.dlcAwaiting` (`en`: `"{count} lot(s) awaiting DLC"`, `fr`: `"{count} lot(s) en attente de DLC"`) to both dictionaries.

- [ ] **Step 13: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean.

- [ ] **Step 14: Browser verification**

Confirm the humidity trend renders on Yield & Waste against the seeded shift month (or confirm it correctly shows nothing if the seed month never recorded humidity — verify which is true with a direct query before assuming either is a bug: `SELECT count(*) FROM production.shift_runs WHERE humidity_percentage IS NOT NULL;` against the dev DB). Confirm the DLC-awaiting stat on the Overview shows a real count and its link lands on QC's Lot DLC queue.

- [ ] **Step 15: Commit**

```bash
git add frontend/src/features/analytics/AnalyticsOverviewSection.tsx frontend/src/lib/i18n.tsx
git commit -m "Add DLC-coverage stat to Analytics Overview"
```

---

## Task 8: Full-branch verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest -v`
Expected: 100% green across every module, not just `production`.

- [ ] **Step 2: Full frontend type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean.

- [ ] **Step 3: Re-drive the 4 existing production tabs against the seeded month**

Per the spec's B.2, confirm Overview/Yield & Waste/Team Performance/Machine Performance still render sane figures against `backend/scripts/seed_shift_month.py`'s data, and confirm the "unattributed downtime" addition (if a small addition to `MachineDowntimePanel` was made per B.2 — check whether that sub-task was actually done; if it was scoped out of this plan's tasks, note that as a follow-up rather than silently skipping it) is visible.

- [ ] **Step 4: Update memory**

Note for whoever executes: update `project-shift-report-program` or add a linked `project-analytics-shift-rewrite` memory recording what shipped — 3 new tabs, tab regrouping, humidity/DLC additions, and the dependency on Part A for Task 6's panel.

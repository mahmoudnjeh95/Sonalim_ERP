# Milestone 2: OF List and OF Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The OF list shows compact PC | PL cards with real progress, the OF's products, and its shift status (official validated figures with pending shifts beside them); the OF page lists the OF's real shifts and opens them in the shift screen.

**Architecture:** One light read `GET /production/work-orders/overview` (SQL aggregates, no per-OF consolidation) feeds the list. `GET /production/shift-reports` gains an `of_id` filter for the OF page. The 1,300-line `WorkOrdersTab.tsx` is split into a tab, a card, one set of dialogs mounted once, and an actions hook. `ShiftReportTab` learns to open a specific line/date/shift from the URL.

**Tech Stack:** as Milestone 1.

**Spec:** `docs/superpowers/specs/2026-09-21-work-orders-product-from-shift-design.md` (Milestone 2: 2.1 to 2.3). Milestone 1 is built (`2026-09-21-work-orders-m1-packing-product.md`).

## Global Constraints

- Backend tests: from `backend/`, `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest <path> -q -p no:cacheprovider`. Frontend: `cd frontend && npx tsc -b --force` must exit 0.
- No commits (none requested). Validated is the official figure; pending is shown beside it and never added to it.
- Every user-facing string goes through `t(...)` with an English and a French entry in `frontend/src/lib/i18n.tsx`. `t` takes no parameters: build sentences by concatenation.
- No invented thresholds: progress is produced / planned tonnes, and there is no bar and no percentage when the OF has no planned quantity; yield is "—" until a shift is validated (never 0.0%).
- Regrind OFs (a row in `production.regrind_batches`) are not listed.

## File Structure

| File | Change |
|---|---|
| `backend/modules/production/api/work_order_overview_service.py` | new |
| `backend/modules/production/api/test_work_order_overview_integration.py` | new |
| `backend/modules/production/api/shift_report_service.py` | `list_shifts(of_id=...)` |
| `backend/modules/production/api/router.py` | `GET /work-orders/overview`; `of_id` on `GET /shift-reports` |
| `frontend/src/features/production/api.ts` | overview type + fetch |
| `frontend/src/features/production/shift/shiftApi.ts` | `of_id` filter |
| `frontend/src/features/production/WorkOrdersTab.tsx` | rewritten (tab) |
| `frontend/src/features/production/WorkOrderCard.tsx` | new |
| `frontend/src/features/production/WorkOrderDialogs.tsx` | new (edit + close dialogs, mounted once) |
| `frontend/src/features/production/useWorkOrderActions.ts` | new (mutations) |
| `frontend/src/features/production/WorkOrderDetailsPage.tsx` | shifts list, pending line |
| `frontend/src/features/production/shift/ShiftReportTab.tsx` | read `line`, `date`, `shift` from the URL |
| `frontend/src/lib/i18n.tsx` | new keys (en + fr) |

---

### Task 1: The overview read

**Files:** create `work_order_overview_service.py`, `test_work_order_overview_integration.py`; modify `router.py` (next to `GET /work-orders/yields`).

**Interfaces:**
- Produces: `WorkOrderOverviewService(connection).overview(*, tenant_id: str, date: datetime.date, at: datetime.time) -> list[dict]`, one dict per non-regrind OF:
  `{"of_id", "products": [str], "produced_quantity": float, "completion_ratio": float|None, "yield_ratio": float|None, "shifts": {"validated","submitted","in_progress","returned"}, "last_shift_date": str|None, "pending_quantity": float, "live": bool}`.
  `products` = distinct products of the OF's validated packing reports (earliest first), else `[OF.product_id]` when it has one, else `[]`. `produced_quantity` = validated conditionnement tonnage (what OF consolidation calls produced). `completion_ratio` = produced / planned, `None` without a positive planned quantity. `yield_ratio` from `WorkOrderYieldService`, `None` when it has no entry. `pending_quantity` = tonnes on packing rows of `open` and `submitted` shifts (`tonnage_from_count` per row with its product's parameters). `live` = an `open` or `submitted` shift for the shift window containing `at` (the board's `current_shift`; a night shift after midnight belongs to its start day) holds a run of the OF.
- HTTP: `GET /production/work-orders/overview?date=YYYY-MM-DD&at=HH:MM` (both default to the server's now), permission `production.view_work_orders`.

- [ ] **Step 1: Write the failing tests**

```python
"""One row per OF for the list: official figures from validated shifts, pending ones beside them."""
from __future__ import annotations

import datetime

import pytest

from modules.production.api.service import WorkOrderService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.test_packing_product_validation_integration import (  # noqa: F401  (env is a fixture)
    DAY,
    TENANT,
    _ok,
    _two_product_shift,
    env,
)
from modules.production.api.work_order_overview_service import WorkOrderOverviewService

MORNING = datetime.time(9, 0)


def _row(db, of_id, at=MORNING):
    rows = WorkOrderOverviewService(db).overview(tenant_id=TENANT, date=DAY, at=at)
    return next(r for r in rows if r["of_id"] == of_id)


def _bare_order(db, env):
    orders = WorkOrderService(db)
    return _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id


def test_an_order_with_no_shift_has_nothing_to_show(db, env):
    row = _row(db, _bare_order(db, env))
    assert row["products"] == [] and row["produced_quantity"] == 0
    assert row["completion_ratio"] is None or row["completion_ratio"] == 0
    assert row["yield_ratio"] is None and row["last_shift_date"] is None
    assert row["shifts"] == {"validated": 0, "submitted": 0, "in_progress": 0, "returned": 0}
    assert row["pending_quantity"] == 0 and row["live"] is False


def test_a_handed_in_shift_is_pending_and_never_official(db, env):
    _, of_id = _two_product_shift(db, env)
    row = _row(db, of_id)
    assert row["shifts"]["submitted"] == 1 and row["shifts"]["validated"] == 0
    assert row["produced_quantity"] == 0 and row["products"] == [] and row["yield_ratio"] is None
    assert row["pending_quantity"] == pytest.approx(0.108)  # 120 x 500 g + 240 x 200 g


def test_a_validated_shift_counts_officially(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    row = _row(db, of_id)
    assert row["shifts"]["validated"] == 1 and row["pending_quantity"] == 0
    assert row["products"] == [env["big"], env["small"]]
    assert row["produced_quantity"] == pytest.approx(0.108)
    assert row["completion_ratio"] == pytest.approx(0.108 / 1000)
    assert row["yield_ratio"] == pytest.approx(0.9)
    assert row["last_shift_date"] == DAY.isoformat()


def test_an_order_is_live_while_its_shift_is_running(db, env):
    db.execute("INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, 'morning', '07:00', '15:00')", (TENANT,))
    _, of_id = _two_product_shift(db, env)
    assert _row(db, of_id, at=MORNING)["live"] is True
    assert _row(db, of_id, at=datetime.time(16, 0))["live"] is False


def test_regrind_orders_are_not_listed(db, env):
    of_id = _bare_order(db, env)
    db.execute("INSERT INTO production.regrind_batches (work_order_id, tenant_id) VALUES (%s, %s)", (of_id, TENANT))
    assert of_id not in {r["of_id"] for r in WorkOrderOverviewService(db).overview(tenant_id=TENANT, date=DAY, at=MORNING)}


def test_another_tenants_orders_are_not_listed(db, env):
    _bare_order(db, env)
    assert WorkOrderOverviewService(db).overview(tenant_id="somebody-else", date=DAY, at=MORNING) == []
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: work_order_overview_service`).

- [ ] **Step 3: Implement `work_order_overview_service.py`**

```python
"""One row per OF for the list: what it made, in which products, and where its shifts stand.

Official figures come from validated shifts only. What is waiting (handed in or still being typed)
is reported apart as `pending_quantity` and `shifts`, and is never added to a validated figure.
SQL aggregates only: nothing here runs an OF's full consolidation.
"""
from __future__ import annotations

import datetime

import psycopg

from core.api.service import CoreService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.domain.dashboard import current_shift
from modules.production.domain.packaging_estimate import tonnage_from_count

_SHIFT_STATUS_KEY = {"validated": "validated", "submitted": "submitted", "open": "in_progress", "returned": "returned"}


class WorkOrderOverviewService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def overview(self, *, tenant_id: str, date: datetime.date, at: datetime.time) -> list[dict]:
        orders = self._connection.execute(
            """
            SELECT w.id, w.planned_quantity, w.product_id
            FROM production.work_orders w
            WHERE w.tenant_id = %s
              AND NOT EXISTS (SELECT 1 FROM production.regrind_batches rb WHERE rb.work_order_id = w.id)
            ORDER BY w.created_at DESC, w.id
            """,
            (tenant_id,),
        ).fetchall()
        if not orders:
            return []

        products = self._validated_products(tenant_id)
        produced = self._produced(tenant_id)
        shifts, last_shift = self._shift_counts(tenant_id)
        pending = self._pending_tonnage(tenant_id)
        live = self._live_orders(tenant_id, date, at)
        yields = {y["work_order_id"]: y["yield_ratio"] for y in WorkOrderYieldService(self._connection).list_work_order_yields(tenant_id)}

        rows = []
        for of_id, planned, own_product in orders:
            made = produced.get(of_id, 0.0)
            rows.append(
                {
                    "of_id": of_id,
                    "products": products.get(of_id) or ([own_product] if own_product else []),
                    "produced_quantity": made,
                    "completion_ratio": made / float(planned) if planned is not None and float(planned) > 0 else None,
                    "yield_ratio": yields.get(of_id),
                    "shifts": shifts.get(of_id, {"validated": 0, "submitted": 0, "in_progress": 0, "returned": 0}),
                    "last_shift_date": last_shift[of_id].isoformat() if of_id in last_shift else None,
                    "pending_quantity": pending.get(of_id, 0.0),
                    "live": of_id in live,
                }
            )
        return rows

    def _validated_products(self, tenant_id: str) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for of_id, product_id in self._connection.execute(
            """
            SELECT r.of_id, COALESCE(c.product_id, w.product_id) AS product_id
            FROM production.production_reports r
            JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            LEFT JOIN production.shift_packing_rows p ON p.id = r.id AND p.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.report_type = 'conditionnement' AND r.status = 'validated'
            GROUP BY r.of_id, COALESCE(c.product_id, w.product_id)
            HAVING COALESCE(c.product_id, w.product_id) IS NOT NULL
            ORDER BY r.of_id, MIN(r.report_date), MIN(p.line_order) NULLS LAST, MIN(r.created_at), 2
            """,
            (tenant_id,),
        ).fetchall():
            found.setdefault(of_id, []).append(product_id)
        return found

    def _produced(self, tenant_id: str) -> dict[str, float]:
        return {
            of_id: float(total)
            for of_id, total in self._connection.execute(
                """
                SELECT r.of_id, COALESCE(SUM(c.finished_product_quantity), 0)
                FROM production.production_reports r
                JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
                WHERE r.tenant_id = %s AND r.report_type = 'conditionnement' AND r.status = 'validated'
                GROUP BY r.of_id
                """,
                (tenant_id,),
            ).fetchall()
        }

    def _shift_counts(self, tenant_id: str) -> tuple[dict[str, dict[str, int]], dict[str, datetime.date]]:
        counts: dict[str, dict[str, int]] = {}
        last: dict[str, datetime.date] = {}
        for of_id, status, n, latest in self._connection.execute(
            """
            SELECT x.of_id, s.status, COUNT(DISTINCT s.id), MAX(s.report_date)
            FROM (
                SELECT of_id, shift_report_id FROM production.shift_runs WHERE tenant_id = %s
                UNION
                SELECT of_id, shift_report_id FROM production.shift_packing_rows WHERE tenant_id = %s
            ) x
            JOIN production.shift_reports s ON s.id = x.shift_report_id AND s.tenant_id = %s
            GROUP BY x.of_id, s.status
            """,
            (tenant_id, tenant_id, tenant_id),
        ).fetchall():
            bucket = counts.setdefault(of_id, {"validated": 0, "submitted": 0, "in_progress": 0, "returned": 0})
            bucket[_SHIFT_STATUS_KEY[status]] = int(n)
            if of_id not in last or latest > last[of_id]:
                last[of_id] = latest
        return counts, last

    def _pending_tonnage(self, tenant_id: str) -> dict[str, float]:
        core = CoreService(self._connection)
        parameters: dict[str, tuple[float | None, float | None]] = {}
        totals: dict[str, float] = {}
        for of_id, product_id, cartons, packets, waste in self._connection.execute(
            """
            SELECT p.of_id, p.product_id, p.carton_quantity, p.packets_counted, p.waste_carton_quantity
            FROM production.shift_packing_rows p
            JOIN production.shift_reports s ON s.id = p.shift_report_id AND s.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND s.status IN ('open', 'submitted')
            """,
            (tenant_id,),
        ).fetchall():
            if not product_id:
                continue
            if product_id not in parameters:
                product = core.get_product(tenant_id, product_id)
                parameters[product_id] = (product.net_weight_grams, product.packets_per_carton) if product else (None, None)
            weight, per_carton = parameters[product_id]
            totals[of_id] = totals.get(of_id, 0.0) + tonnage_from_count(
                net_weight_grams=weight,
                packets_per_carton=per_carton,
                carton_quantity=float(cartons),
                packets_counted=float(packets),
                waste_carton_quantity=float(waste),
            )
        return totals

    def _live_orders(self, tenant_id: str, date: datetime.date, at: datetime.time) -> set[str]:
        running = current_shift(DashboardSettingsService(self._connection).list_shift_windows(tenant_id=tenant_id), at)
        if running is None:
            return set()
        # A night shift that runs through midnight belongs to the day it started.
        report_date = date - datetime.timedelta(days=1) if running.start > running.end and at < running.end else date
        return {
            row[0]
            for row in self._connection.execute(
                """
                SELECT DISTINCT r.of_id
                FROM production.shift_runs r
                JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
                WHERE s.tenant_id = %s AND s.report_date = %s AND lower(s.shift) = lower(%s) AND s.status IN ('open', 'submitted')
                """,
                (tenant_id, report_date, running.shift),
            ).fetchall()
        }
```

- [ ] **Step 4: The route.** In `router.py`, directly after the `GET /work-orders/yields` handler add (import `WorkOrderOverviewService`; `datetime` is already imported):

```python
@router.get("/work-orders/overview")
def get_work_orders_overview(
    date: datetime.date | None = Query(default=None, description="Plant-local date. Defaults to the server's."),
    at: datetime.time | None = Query(default=None, description="Plant-local clock time, HH:MM. Defaults to the server's."),
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """One light row per OF for the list: products, produced tonnes, shift counts, pending tonnes, live."""
    now = datetime.datetime.now()
    with get_connection() as connection:
        return WorkOrderOverviewService(connection).overview(
            tenant_id=tenant.tenant_id, date=date or now.date(), at=at or now.time().replace(second=0, microsecond=0)
        )
```

- [ ] **Step 5: Run the new tests, expect PASS.** Fix expectations only where the test guessed wrong about existing behaviour (for example how the yield service reports an OF), never the rule.

### Task 2: `of_id` filter on shift reports

**Files:** modify `shift_report_service.py` (`list_shifts`), `router.py` (`GET /shift-reports`), `test_work_order_overview_integration.py`.

- [ ] **Step 1: Failing test** (append):

```python
def test_shifts_can_be_listed_for_one_order(db, env):
    from modules.production.api.shift_report_service import ShiftReportService

    shift_id, of_id = _two_product_shift(db, env)
    service = ShiftReportService(db)
    assert [s["id"] for s in service.list_shifts(tenant_id=TENANT, of_id=of_id)] == [shift_id]
    assert service.list_shifts(tenant_id=TENANT, of_id=_bare_order(db, env)) == []
```

- [ ] **Step 2: Implement.** `list_shifts` gains `of_id: str | None = None`; after the loop that builds `clauses` from date/line/status add:

```python
        if of_id is not None:
            clauses.append(
                "id IN (SELECT shift_report_id FROM production.shift_runs WHERE tenant_id = %s AND of_id = %s "
                "UNION SELECT shift_report_id FROM production.shift_packing_rows WHERE tenant_id = %s AND of_id = %s)"
            )
            params.extend([tenant_id, of_id, tenant_id, of_id])
```

In `router.py` the `GET /shift-reports` handler takes `of_id: str | None = Query(default=None)` and passes `of_id=of_id`.

- [ ] **Step 3: Run, expect PASS; then run `modules/production` to check nothing else moved.**

### Task 3: Frontend data layer and strings

**Files:** `frontend/src/features/production/api.ts`, `shift/shiftApi.ts`, `frontend/src/lib/i18n.tsx`.

- [ ] `api.ts`:

```ts
/** What the OF list needs per order, from one light read: official figures from validated shifts, pending ones apart. */
export interface WorkOrderOverview {
  of_id: string;
  /** Products of the validated packing reports (earliest first), else the order's own; empty until either exists. */
  products: string[];
  /** Tonnes packed in validated shifts. */
  produced_quantity: number;
  /** produced / planned; null when the order has no planned quantity. */
  completion_ratio: number | null;
  /** Null until a shift is validated. */
  yield_ratio: number | null;
  shifts: { validated: number; submitted: number; in_progress: number; returned: number };
  last_shift_date: string | null;
  /** Tonnes on shifts handed in or still being typed; never part of the official figure. */
  pending_quantity: number;
  live: boolean;
}

export const WORK_ORDER_OVERVIEW_QUERY_KEY = ["production", "work-orders", "overview"] as const;

export function getWorkOrdersOverview(token: string, params: { date: string; at: string }) {
  return apiFetch<WorkOrderOverview[]>(`/production/work-orders/overview?date=${params.date}&at=${params.at}`, { token });
}
```

- [ ] `shiftApi.ts`: `listShiftReports` filters type gains `of_id?: string`.
- [ ] `i18n.tsx`: add these keys (English then French), next to `production.workOrders.card.open`:

| key | en | fr |
|---|---|---|
| `production.workOrders.card.noProduct` | Product set at the first validated report | Produit défini au 1er rapport validé |
| `production.workOrders.card.noPlan` | No planned quantity | Pas de quantité prévue |
| `production.workOrders.card.planned` | planned | prévu |
| `production.workOrders.card.yieldNone` | — | — |
| `production.workOrders.card.validated` | validated | validé(s) |
| `production.workOrders.card.waiting` | waiting | en attente |
| `production.workOrders.card.inProgress` | in progress | en saisie |
| `production.workOrders.card.returned` | returned | renvoyé(s) |
| `production.workOrders.card.live` | Live now | En cours |
| `production.workOrders.card.noShift` | No shift yet | Aucun shift |
| `production.workOrders.card.pending` | waiting validation | en attente de validation |
| `production.workOrders.card.lastShift` | Last shift | Dernier shift |
| `production.workOrders.group.empty` | No order for these filters | Aucun ordre pour ces filtres |
| `production.workOrders.group.active` | Active | Actifs |
| `production.workOrders.group.showClosed` | Show closed and cancelled | Afficher clôturés et annulés |
| `production.workOrders.group.hideClosed` | Hide closed and cancelled | Masquer clôturés et annulés |
| `production.workOrders.search` | Search reference, line, product, supervisor | Rechercher référence, poste, produit, superviseur |
| `production.workOrders.empty.filtered` | No work order matches these filters | Aucun ordre ne correspond à ces filtres |
| `production.ofDetails.shifts.title` | Shifts | Shifts |
| `production.ofDetails.shifts.subtitle` | Every shift that worked on this order, validated or not. | Chaque shift qui a travaillé sur cet ordre, validé ou non. |
| `production.ofDetails.shifts.empty` | No shift has worked on this order yet. | Aucun shift n'a encore travaillé sur cet ordre. |
| `production.ofDetails.shifts.open` | Open the shift | Ouvrir le shift |
| `production.ofDetails.pending` | waiting validation | en attente de validation |

Also replace the value of `production.workOrders.productHint` with "The product appears here after the first validated report." / "Le produit apparaît ici après le premier rapport validé.".

- [ ] `npx tsc -b --force` exits 0.

### Task 4: The OF list

**Files:** rewrite `WorkOrdersTab.tsx`; create `WorkOrderCard.tsx`, `WorkOrderDialogs.tsx`, `useWorkOrderActions.ts`.

**Interfaces:**
- `useWorkOrderActions(token)` returns `{ start, suspend, resume, cancel, close, update }`, each a react-query mutation whose `onSuccess` invalidates `["production","work-orders"]` (which also refreshes the overview key) and toasts with the existing `production.workOrders.*Toast` and `*Error` strings.
- `WorkOrderCard` props: `{ order: WorkOrder; overview?: WorkOrderOverview; productNames: string[]; workCenterName: string; supervisorName: string; unit: string | null; highlighted: boolean; actions: RowAction[] }`. It renders: reference (link to `/production/work-orders/{id}`) with status badge and the row-actions menu; line, start date, supervisor; product names (or the `noProduct` note); a progress block (`completion_ratio` bar with produced / planned tonnes, or produced tonnes only and the `noPlan` note when `completion_ratio` is null); yield ("—" when null); shift line (`n validated · n waiting · n in progress`, `Live now` badge when `live`, `noShift` when all zero, last shift date); pending tonnes muted with the `pending` label when above zero. No looping animation; one entrance animation via the existing `rowEnterProps`.
- `WorkOrderDialogs` props: `{ editing: WorkOrder | null; closing: WorkOrder | null; onCloseEdit(); onCloseClose(); ... }` holds the edit form (work center, supervisor, PC/PL, recipe, packaging BOM) and the close dialog, moved unchanged from `OrderActions`.
- `WorkOrdersTab`: queries (`listWorkOrders`, overview, work centers, products, supervisors, regrind batches for the guard), status and type filter tabs, a search box, PC | PL groups; closed and cancelled OFs are folded under a toggle; empty state through `EmptyState`. Search matches reference, work-center code, supervisor label and product names.

- [ ] Steps: write the four files as above reusing the current create dialog and row-action logic, then `npx tsc -b --force` (exit 0) and the browser check in Task 6.

### Task 5: The OF page and the deep link

**Files:** `WorkOrderDetailsPage.tsx`, `shift/ShiftReportTab.tsx`.

- [ ] `ShiftReportTab.tsx`: read `line`, `date`, `shift` from `useSearchParams()` as the initial values of `workCenterId`, `date`, `shiftName` (falling back to today, the first usable line and the current window as today).
- [ ] `WorkOrderDetailsPage.tsx`: replace the "Rapports" card (old report rows, legacy dialogs) with a **Shifts** card built from `listShiftReports(token, { of_id })`: date, shift, line name, status badge, section count; each row links to `/production?tab=shift-report&line={work_center_id}&date={report_date}&shift={shift}`. Remove the now-unused legacy dialog imports and state (`DailyReportDialog`, `PackingReportDialog`, `openReport`) only if nothing else on the page uses them. Add the pending line under the progress bar: when the overview row's `pending_quantity > 0`, "+ {tonnes} t {pending}".
- [ ] `npx tsc -b --force` exits 0.

### Task 6: Verify

- [ ] `modules core` backend suites all pass (report the counts).
- [ ] `npx tsc -b --force` exits 0.
- [ ] Headless Chrome (CDP recipe from memory): open `/production` (OF tab), confirm compact cards render for the 28 dev OFs, PC | PL columns, a card with several products lists them, a suspended OF with no validated shift shows "—" for yield, closed OFs are folded; open an OF page and confirm the Shifts card lists real shifts and a row link opens the shift screen on that line, date and shift. Screenshots for the client. Read-only: nothing is saved.

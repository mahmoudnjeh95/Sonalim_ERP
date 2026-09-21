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


def _no_shifts() -> dict[str, int]:
    return {"validated": 0, "submitted": 0, "in_progress": 0, "returned": 0}


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
            ORDER BY w.id DESC
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
        yields = {
            y["work_order_id"]: y["yield_ratio"]
            for y in WorkOrderYieldService(self._connection).list_work_order_yields(tenant_id)
        }

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
                    "shifts": shifts.get(of_id, _no_shifts()),
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
            counts.setdefault(of_id, _no_shifts())[_SHIFT_STATUS_KEY[status]] = int(n)
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
                WHERE s.tenant_id = %s AND s.report_date = %s AND lower(s.shift) = lower(%s)
                  AND s.status IN ('open', 'submitted')
                """,
                (tenant_id, report_date, running.shift),
            ).fetchall()
        }

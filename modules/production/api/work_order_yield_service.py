from __future__ import annotations

import psycopg


class WorkOrderYieldService:
    """Rendement (yield) = (actual output tons + rebroyat generated) / semoule tons
    poured, computed live from work_order_inputs + product_classifications +
    scrap_records — never persisted, matching the codebase's existing convention for
    derived values (see regrind's loss_quantity).

    "Rebroyat generated" is this OF's own scrap (versement/filling_dosing +
    découpe/cutting stages, production.scrap_records.work_order_id) — that scrap is
    recoverable material, later ground back into raw material via RegrindService, so
    it counts as usable output for yield purposes even though it isn't part of
    actual_output_quantity. Water is excluded from the denominator; rebroyat (as an
    input, i.e. is_regrind=True poured lines) is excluded too, since the denominator
    is fresh semoule only.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _semoule_total_by_work_order(self, tenant_id: str, work_order_ids: list[str] | None = None) -> dict[str, float]:
        clauses = ["wo.tenant_id = %s", "wo.status = 'completed'", "wo.actual_output_quantity IS NOT NULL"]
        params: list[object] = [tenant_id]
        if work_order_ids is not None:
            if not work_order_ids:
                return {}
            clauses.append("wo.id = ANY(%s)")
            params.append(work_order_ids)
        rows = self._connection.execute(
            f"""
            SELECT wo.id,
                   COALESCE(SUM(woi.quantity) FILTER (
                       WHERE pc.category = 'raw_material' AND pc.is_regrind = FALSE AND pc.is_water = FALSE
                   ), 0)
            FROM production.work_orders wo
            LEFT JOIN production.work_order_inputs woi ON woi.work_order_id = wo.id AND woi.tenant_id = wo.tenant_id
            LEFT JOIN core.products cp ON cp.tenant_id = wo.tenant_id AND cp.id = woi.product_id
            LEFT JOIN production.product_classifications pc ON pc.tenant_id = wo.tenant_id AND pc.product_id = cp.sku
            WHERE {' AND '.join(clauses)}
            GROUP BY wo.id
            """,
            params,
        ).fetchall()
        return {work_order_id: float(total) for work_order_id, total in rows}

    def _scrap_total_by_work_order(self, tenant_id: str, work_order_ids: list[str] | None = None) -> dict[str, float]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if work_order_ids is not None:
            if not work_order_ids:
                return {}
            clauses.append("work_order_id = ANY(%s)")
            params.append(work_order_ids)
        rows = self._connection.execute(
            f"""
            SELECT work_order_id, SUM(quantity)
            FROM production.scrap_records
            WHERE {' AND '.join(clauses)} AND work_order_id IS NOT NULL
            GROUP BY work_order_id
            """,
            params,
        ).fetchall()
        return {work_order_id: float(total) for work_order_id, total in rows}

    def _yield_ratio(self, actual_output_quantity: float, semoule_total: float, scrap_total: float) -> float:
        return (actual_output_quantity + scrap_total) / semoule_total

    def get_work_order_yield(self, *, tenant_id: str, work_order_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT actual_output_quantity FROM production.work_orders WHERE id = %s AND tenant_id = %s AND status = 'completed'",
            (work_order_id, tenant_id),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        actual_output_quantity = float(row[0])
        semoule_total = self._semoule_total_by_work_order(tenant_id, [work_order_id]).get(work_order_id, 0.0)
        if semoule_total <= 0:
            return None
        scrap_total = self._scrap_total_by_work_order(tenant_id, [work_order_id]).get(work_order_id, 0.0)
        return {
            "work_order_id": work_order_id,
            "actual_output_quantity": actual_output_quantity,
            "rebroyat_quantity": scrap_total,
            "semoule_quantity_total": semoule_total,
            "yield_ratio": self._yield_ratio(actual_output_quantity, semoule_total, scrap_total),
        }

    def list_work_order_yields(self, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT id, actual_output_quantity FROM production.work_orders WHERE tenant_id = %s AND status = 'completed' AND actual_output_quantity IS NOT NULL",
            (tenant_id,),
        ).fetchall()
        semoule_by_id = self._semoule_total_by_work_order(tenant_id)
        scrap_by_id = self._scrap_total_by_work_order(tenant_id)
        results = []
        for work_order_id, actual_output_quantity in rows:
            semoule_total = semoule_by_id.get(work_order_id, 0.0)
            if semoule_total <= 0:
                continue
            scrap_total = scrap_by_id.get(work_order_id, 0.0)
            results.append(
                {
                    "work_order_id": work_order_id,
                    "actual_output_quantity": float(actual_output_quantity),
                    "rebroyat_quantity": scrap_total,
                    "semoule_quantity_total": semoule_total,
                    "yield_ratio": self._yield_ratio(float(actual_output_quantity), semoule_total, scrap_total),
                }
            )
        return results

    def get_recipe_yield_summary(self, *, tenant_id: str, recipe_id: str) -> dict:
        rows = self._connection.execute(
            "SELECT id, actual_output_quantity FROM production.work_orders WHERE tenant_id = %s AND recipe_id = %s AND status = 'completed' AND actual_output_quantity IS NOT NULL",
            (tenant_id, recipe_id),
        ).fetchall()
        work_order_ids = [r[0] for r in rows]
        semoule_by_id = self._semoule_total_by_work_order(tenant_id, work_order_ids)
        scrap_by_id = self._scrap_total_by_work_order(tenant_id, work_order_ids)
        ratios = []
        for work_order_id, actual_output_quantity in rows:
            semoule_total = semoule_by_id.get(work_order_id, 0.0)
            if semoule_total > 0:
                scrap_total = scrap_by_id.get(work_order_id, 0.0)
                ratios.append(self._yield_ratio(float(actual_output_quantity), semoule_total, scrap_total))
        return {
            "recipe_id": recipe_id,
            "work_order_count": len(ratios),
            "average_yield_ratio": sum(ratios) / len(ratios) if ratios else None,
        }

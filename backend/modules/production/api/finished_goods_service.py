from __future__ import annotations

import psycopg


class FinishedGoodsService:
    """Finished pasta actually packed in a period, by product -- the plant's
    "Produit Fini" sheet: tonnage off the scale (finished_product_quantity)
    and the packet tally (packets_counted) that Phase 5 actually posts to
    stock, per product and per PC/PL line.

    Sourced from production.conditionnement_reports, the same table and the
    same validated-only convention as ConsumptionReportService and
    of_consolidation_service.OfConsolidationService -- this is that same
    figure grouped by product and by date range instead of by one OF.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_finished_goods(
        self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        clauses = ["r.tenant_id = %s", "r.status = 'validated'", "COALESCE(c.product_id, w.product_id) IS NOT NULL"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT
                COALESCE(c.product_id, w.product_id) AS product_id,
                w.product_type AS pc_pl,
                SUM(c.finished_product_quantity) AS quantity,
                SUM(c.packets_counted) AS packets_counted
            FROM production.conditionnement_reports c
            JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE {where}
            GROUP BY COALESCE(c.product_id, w.product_id), w.product_type
            HAVING SUM(c.finished_product_quantity) > 0 OR SUM(c.packets_counted) > 0
            """,
            params,
        ).fetchall()

        return [
            {
                "product_id": product_id,
                "pc_pl": pc_pl,
                "quantity": float(quantity or 0),
                "packets_counted": float(packets_counted or 0),
            }
            for product_id, pc_pl, quantity, packets_counted in rows
        ]

from __future__ import annotations

import psycopg

from modules.procurement.api.service import PurchaseOrderService
from modules.production.api.landed_cost import average_landed_cost_by_product


class MaterialConsumptionService:
    """Semoule consumption for a period, costed from procurement's own
    landed-cost purchase history rather than the last-price-paid convention
    ConsumptionReportService uses for packaging -- this mirrors the plant's
    own "BD MP" tracking sheet, where a raw material's cost/tonne is its
    purchases' total landed cost (achat + transport + transit + assurance +
    license + diwan + manutention) averaged over everything bought, not just
    the latest order.

    Sourced from production.report_semolina_lines (0027) -- the semoule a
    shift actually poured, one line per quality. Rebroyat poured back into
    the mix is deliberately excluded: it was never purchased, so it has no
    landed cost to price it against, and the plant's own MP sheet does not
    list it either (see of_consolidation_service.py for where rebroyat is
    accounted for instead, alongside fresh semoule, as "what the line was
    given to work with").

    Only validated reports count, same as every other aggregate in this
    module (see ConsumptionReportService) -- a draft is a team's working
    notes, not a result to report a material consumption figure against.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_consumption(
        self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None,
        receipt_lines: list[dict] | None = None,
    ) -> list[dict]:
        clauses = ["r.tenant_id = %s", "r.status = 'validated'", "sl.product_id IS NOT NULL", "sl.quantity > 0"]
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
            SELECT sl.product_id, SUM(sl.quantity) AS quantity
            FROM production.report_semolina_lines sl
            JOIN production.production_reports r ON r.id = sl.report_id AND r.tenant_id = sl.tenant_id
            WHERE {where}
            GROUP BY sl.product_id
            """,
            params,
        ).fetchall()

        result = [{"product_id": product_id, "quantity": float(quantity)} for product_id, quantity in rows]
        self._apply_landed_cost(tenant_id, result, receipt_lines=receipt_lines)
        return result

    def _apply_landed_cost(self, tenant_id: str, rows: list[dict], *, receipt_lines: list[dict] | None = None) -> None:
        """Fills unit_cost/cost from the weighted-average landed cost/unit
        across every confirmed receipt for that product -- see
        PurchaseOrderService.list_confirmed_receipt_line_details for what a
        landed cost is built from. A product with no confirmed receipt is
        left unpriced rather than guessed at, matching ConsumptionReportService's
        own convention for packaging with no order history.

        `receipt_lines` isn't date-scoped by this call's own date_from/date_to --
        it's every confirmed receipt, tenant-wide, same set regardless of which
        period is being costed. A caller already holding that list (e.g. one
        pricing several periods in the same request) can pass it through instead
        of paying for this tenant-wide query again on every call."""
        if receipt_lines is None:
            receipt_lines = PurchaseOrderService(self._connection).list_confirmed_receipt_line_details(tenant_id=tenant_id)
        unit_costs = average_landed_cost_by_product(receipt_lines)

        for row in rows:
            unit_cost = unit_costs.get(row["product_id"])
            if unit_cost is None:
                row.update(unit_cost=None, cost=None, priced=False)
                continue
            row.update(unit_cost=unit_cost, cost=row["quantity"] * unit_cost, priced=True)

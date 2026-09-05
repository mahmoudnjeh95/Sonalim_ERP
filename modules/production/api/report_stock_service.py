from __future__ import annotations

import psycopg

from core.domain.result import Err, Ok, Result
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    ProductionReport,
)
from modules.warehouse.api.service import StockService


class ReportStockService:
    """What each validated report moves.

    This is the door the whole rebuild was for. Stock changes here and nowhere
    else in production, except regrind completion — so the rules are worth stating
    plainly:

    * **The daily report deducts raw material only.** Its finished-product figure
      is recorded for yield and consolidation and posts nothing, because the
      conditionnement report owns that tonnage. Counting both would double the
      same pasta.
    * **The conditionnement report brings the finished product in** and takes
      film, cartons and tape out. This is the only place packaging is deducted —
      when quality later strips a rejected packet back down, those components are
      recorded as déchet and never deducted a second time. What comes in is the
      **packets the line counted**, never the packet count derived from the
      tonnage (Phase 9, decision 18): if validation posted the estimate, stock
      would always *be* the estimate and the écart could never appear in it.
    * **The quality report moves nothing.** Quality only touches inventory through
      a non-conformity.
    * **A shortfall posts anyway.** A validated report says what the line actually
      consumed; refusing it because the stock figure disagrees would make the
      record follow inventory rather than the other way round. The validator
      explains it instead, and the variance is surfaced.

    Only validated reports reach this service — the report service refuses every
    other status before calling it, so "draft and rejected never post" is enforced
    rather than assumed.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    @staticmethod
    def _direction(base: str, reverse: bool) -> str:
        """Reversing a report is the same movements with the arrows turned round.

        Correcting or deleting a validated report has to undo what it posted, and
        posting the mirror image is honest in a way that editing history is not:
        the original movement stays on the ledger, and the correction stands
        beside it with its own reason.
        """
        if not reverse:
            return base
        return "in" if base == "out" else "out"

    # ---- shortfall detection --------------------------------------------

    @staticmethod
    def _daily_lines(detail: DailyReportDetail) -> list[tuple[float, str, str]]:
        """Everything a daily report takes out of stock: semoule and rebroyat alike.

        Each semoule line carries its own location; rebroyat still draws from
        the report's one `raw_material_location_id` — see the domain comment on
        why rebroyat stays a single field while semoule became a list.
        """
        lines = [(line.quantity, line.product_id, line.location_id) for line in detail.semolina_lines]
        if detail.raw_material_location_id:
            lines.append(
                (detail.regrind_input_quantity, detail.regrind_input_product_id, detail.raw_material_location_id)
            )
        return [
            (quantity, product_id, location_id)
            for quantity, product_id, location_id in lines
            if quantity > 0 and product_id and location_id
        ]

    def daily_shortfalls(self, *, tenant_id: str, detail: DailyReportDetail) -> list[dict]:
        """Withdrawals on this report that would drive a balance below zero."""
        shortfalls: list[dict] = []
        for quantity, product_id, location_id in self._daily_lines(detail):
            if self._stock.would_go_negative(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=location_id,
                quantity=quantity,
            ):
                shortfalls.append(
                    {
                        "product_id": product_id,
                        "location_id": location_id,
                        "quantity": quantity,
                    }
                )
        return shortfalls

    def conditionnement_shortfalls(
        self, *, tenant_id: str, detail: ConditionnementReportDetail
    ) -> list[dict]:
        shortfalls: list[dict] = []
        for quantity, product_id in self._packaging_lines(detail):
            if self._stock.would_go_negative(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=detail.packaging_location_id,  # type: ignore[arg-type]
                quantity=quantity,
            ):
                shortfalls.append(
                    {
                        "product_id": product_id,
                        "location_id": detail.packaging_location_id,
                        "quantity": quantity,
                    }
                )
        return shortfalls

    @staticmethod
    def _packaging_lines(detail: ConditionnementReportDetail) -> list[tuple[float, str]]:
        lines = [
            (detail.film_quantity, detail.film_product_id),
            (detail.carton_quantity, detail.carton_product_id),
            (detail.tape_quantity, detail.tape_product_id),
        ]
        return [(quantity, product_id) for quantity, product_id in lines if quantity > 0 and product_id]

    # ---- posting ---------------------------------------------------------

    def post_daily_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        header: ProductionReport,
        detail: DailyReportDetail,
        correlation_id: str,
        reverse: bool = False,
    ) -> Result[list[dict]]:
        """Raw material out. Nothing else — see the class docstring.

        With `reverse`, the same lines post inward instead: that is how a
        validated report's effect is undone before it is corrected or deleted.
        """
        movements: list[dict] = []
        for quantity, product_id, location_id in self._daily_lines(detail):
            posted = self._stock.post_production_movement(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=location_id,
                quantity=quantity,
                direction=self._direction("out", reverse),
                correlation_id=correlation_id,
                reference=f"production_report:{header.id}",
                move_type="production_consumption",
                actor_id=actor_id,
                source_type="production.daily_report",
                source_id=header.id,
                of_id=header.of_id,
            )
            if isinstance(posted, Err):
                return posted
            movements.append(
                {
                    "direction": self._direction("out", reverse),
                    "product_id": product_id,
                    "location_id": location_id,
                    "quantity": quantity,
                }
            )
        return Ok(movements)

    def post_conditionnement_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        header: ProductionReport,
        detail: ConditionnementReportDetail,
        finished_product_id: str,
        correlation_id: str,
        reverse: bool = False,
    ) -> Result[list[dict]]:
        """Finished product in, packaging out.

        `finished_product_id` is the OF's product, resolved by the caller — the
        report deliberately does not restate it, so it cannot contradict the order
        it belongs to.

        The quantity received is `packets_counted`, in the product's own unit.
        `finished_product_quantity` is a tonnage from Phase 9 and moves nothing;
        it feeds yield and consolidation, exactly as the daily report's own
        finished-product figure does.
        """
        movements: list[dict] = []

        if detail.packets_counted > 0:
            received = self._stock.post_production_movement(
                tenant_id=tenant_id,
                product_id=finished_product_id,
                location_id=detail.finished_goods_location_id,  # type: ignore[arg-type]
                quantity=detail.packets_counted,
                direction=self._direction("in", reverse),
                correlation_id=correlation_id,
                reference=f"production_report:{header.id}",
                move_type="production",
                actor_id=actor_id,
                source_type="production.conditionnement_report",
                source_id=header.id,
                of_id=header.of_id,
            )
            if isinstance(received, Err):
                return received
            movements.append(
                {
                    "direction": self._direction("in", reverse),
                    "product_id": finished_product_id,
                    "location_id": detail.finished_goods_location_id,
                    "quantity": detail.packets_counted,
                }
            )

        for quantity, product_id in self._packaging_lines(detail):
            issued = self._stock.post_production_movement(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=detail.packaging_location_id,  # type: ignore[arg-type]
                quantity=quantity,
                direction=self._direction("out", reverse),
                correlation_id=correlation_id,
                reference=f"production_report:{header.id}",
                move_type="production_consumption",
                actor_id=actor_id,
                source_type="production.conditionnement_report",
                source_id=header.id,
                of_id=header.of_id,
            )
            if isinstance(issued, Err):
                return issued
            movements.append(
                {
                    "direction": self._direction("out", reverse),
                    "product_id": product_id,
                    "location_id": detail.packaging_location_id,
                    "quantity": quantity,
                }
            )

        return Ok(movements)

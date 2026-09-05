from __future__ import annotations

import psycopg

from core.domain.result import Err, Ok, Result

# Only validated reports count. A draft is a team's working notes and a rejected
# report has been refused — consolidating either would let figures nobody approved
# into the OF's official result, and from Phase 5 those are the same figures that
# moved stock.
_VALIDATED = "status = 'validated'"


class OfConsolidationService:
    """What an OF actually produced, summed live from its validated reports.

    Nothing here is stored. The OF used to carry `actual_output_quantity` as a
    cached answer; that column is gone, because a stored total and the reports it
    was derived from can disagree, and when they do there is no way to tell which
    one is wrong. Computing it on demand means the answer always matches the
    reports that justify it.

    A consolidation is available at any point in an OF's life — an order still
    running simply shows what has been validated so far, which is what a cockpit
    wants. Closure changes nothing about how it is computed.

    Quality comes from the qc module through its service, never from a join: qc
    owns those tables and production may not read them.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def consolidate(self, *, tenant_id: str, of_id: str) -> Result[dict]:
        work_order = self._connection.execute(
            """
            SELECT reference, product_id, planned_quantity, status, work_center_id, start_date, closed_at
            FROM production.work_orders WHERE id = %s AND tenant_id = %s
            """,
            (of_id, tenant_id),
        ).fetchone()
        if work_order is None:
            return Err("NOT_FOUND", f"work order {of_id} not found")
        reference, product_id, planned_quantity, status, work_center_id, start_date, closed_at = work_order

        daily = self._daily_totals(tenant_id=tenant_id, of_id=of_id)
        packing = self._conditionnement_totals(tenant_id=tenant_id, of_id=of_id)
        quality = self._quality_summary(tenant_id=tenant_id, of_id=of_id)
        waste = self._waste_totals(tenant_id=tenant_id, of_id=of_id)

        produced = packing["finished_product_quantity"]
        semolina = daily["semolina_quantity"]
        # What actually went into the mix: fresh semoule plus any rebroyat poured
        # back in. This is the basis the plant judges a run against — the planned
        # figure says what was scheduled, not what the line was given to work with.
        material_input = semolina + daily["regrind_input_quantity"]

        return Ok(
            {
                "of_id": of_id,
                "reference": reference,
                "product_id": product_id,
                "status": status,
                "work_center_id": work_center_id,
                "start_date": start_date.isoformat() if start_date is not None else None,
                "closed_at": closed_at.isoformat() if closed_at is not None else None,
                # Nullable since molds (0024): a lightweight OF is created before its
                # tonnage is known, and assigns it later via the edit form.
                "planned_quantity": float(planned_quantity) if planned_quantity is not None else None,
                # The finished tonnage is the conditionnement reports' figure. The
                # daily report's own finished-product number is recorded for yield
                # and deliberately not added here — it is the same pasta.
                "produced_quantity": produced,
                # What the line counted into stock, in the product's own unit.
                "packets_counted": packing["packets_counted"],
                "completion_ratio": (
                    (produced / float(planned_quantity))
                    if planned_quantity is not None and float(planned_quantity) > 0
                    else None
                ),
                # Produced against what was poured in, not against the plan.
                "material_input_quantity": material_input,
                "transformation_ratio": (produced / material_input) if material_input > 0 else None,
                "raw_material": {
                    "semolina_quantity": semolina,
                    "semolina_product_id": daily["semolina_product_id"],
                    # Per quality, sorted worst-... largest first, same shape as
                    # waste.by_product below. Null semolina_product_id above just
                    # means more than one quality was poured — this is where to
                    # see the breakdown.
                    "semolina_by_product": daily["semolina_by_product"],
                    "regrind_input_quantity": daily["regrind_input_quantity"],
                    "regrind_input_product_id": daily["regrind_input_product_id"],
                    "dough_quantity": daily["dough_quantity"],
                },
                "packaging": {
                    "film_quantity": packing["film_quantity"],
                    "film_product_id": packing["film_product_id"],
                    "carton_quantity": packing["carton_quantity"],
                    "carton_product_id": packing["carton_product_id"],
                    "tape_quantity": packing["tape_quantity"],
                    "tape_product_id": packing["tape_product_id"],
                },
                "utilities": {
                    "water_quantity": daily["water_quantity"],
                    "fuel_quantity": daily["fuel_quantity"],
                    "electricity_quantity": daily["electricity_quantity"],
                },
                # Déchets, from the validated reports' waste lines. There is
                # deliberately no single total: the lines are counted in
                # whatever unit each item is stocked in, and adding kilos of
                # dough to a count of cartons produces a number that cannot be
                # read. Callers that need one convert first -- they are the
                # ones holding the units.
                "waste": {
                    # Per stage, the way the plant's own form is laid out.
                    "by_category": waste["by_category"],
                    # Per item, which is the only grouping that can carry a unit.
                    "by_product": waste["by_product"],
                    # Quantity on lines that never said what was lost. Only ever
                    # non-zero for reports written before waste named its item;
                    # surfaced rather than hidden so it can be gone back and fixed.
                    "unattributed_quantity": waste["unattributed_quantity"],
                    # Rebroyat is not waste. It is recovered material that opens
                    # its own OF and goes back into a mix -- reported here because
                    # it is what the shift writes on the same line of the form.
                    "regrind": {
                        "quantity": daily["regrind_quantity"],
                        "product_id": daily["regrind_product_id"],
                    },
                },
                "time": {
                    "production_minutes": daily["production_minutes"] + packing["production_minutes"],
                    "downtime_minutes": daily["downtime_minutes"] + packing["downtime_minutes"],
                },
                "quality": quality,
                "report_counts": {
                    "daily": daily["report_count"],
                    "conditionnement": packing["report_count"],
                    "quality": quality["validated_report_count"],
                },
            }
        )

    def _daily_totals(self, *, tenant_id: str, of_id: str) -> dict:
        row = self._connection.execute(
            f"""
            SELECT
                count(*),
                COALESCE(SUM(d.regrind_input_quantity), 0),
                COALESCE(SUM(d.dough_quantity), 0),
                COALESCE(SUM(d.regrind_quantity), 0),
                COALESCE(SUM(d.water_quantity), 0),
                COALESCE(SUM(d.fuel_quantity), 0),
                COALESCE(SUM(d.electricity_quantity), 0),
                COALESCE(SUM(d.production_minutes), 0),
                COALESCE(SUM(d.downtime_minutes), 0),
                COALESCE(SUM(d.finished_product_quantity), 0),
                CASE WHEN COUNT(DISTINCT d.regrind_input_product_id) = 1 THEN MIN(d.regrind_input_product_id) END,
                CASE WHEN COUNT(DISTINCT d.regrind_product_id) = 1 THEN MIN(d.regrind_product_id) END
            FROM production.production_reports r
            JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.report_type = 'daily' AND r.{_VALIDATED}
            """,
            (tenant_id, of_id),
        ).fetchone()
        semolina = self._semolina_totals(tenant_id=tenant_id, of_id=of_id)
        return {
            "report_count": int(row[0]),
            "semolina_quantity": semolina["total"],
            "semolina_by_product": semolina["by_product"],
            "regrind_input_quantity": float(row[1]),
            "dough_quantity": float(row[2]),
            "regrind_quantity": float(row[3]),
            "water_quantity": float(row[4]),
            "fuel_quantity": float(row[5]),
            "electricity_quantity": float(row[6]),
            "production_minutes": int(row[7]),
            "downtime_minutes": int(row[8]),
            # Reported for yield, never added to produced_quantity.
            "reported_finished_product_quantity": float(row[9]),
            # Null when the lines disagree: a single unit would be a lie.
            "semolina_product_id": semolina["product_id"],
            "regrind_input_product_id": row[10],
            "regrind_product_id": row[11],
        }

    def _semolina_totals(self, *, tenant_id: str, of_id: str) -> dict:
        """Semoule poured in, across the OF's validated reports, grouped by quality.

        A separate query rather than a join into `_daily_totals`: a report can
        carry several semoule lines, and joining that many-rows table straight
        into a query that also sums single-valued daily_reports columns would
        multiply every one of those columns by the line count. Same shape as
        `_waste_totals` below, for the same reason.
        """
        rows = self._connection.execute(
            f"""
            SELECT sl.product_id, COALESCE(SUM(sl.quantity), 0)
            FROM production.report_semolina_lines sl
            JOIN production.production_reports r ON r.id = sl.report_id AND r.tenant_id = sl.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.{_VALIDATED}
            GROUP BY sl.product_id
            """,
            (tenant_id, of_id),
        ).fetchall()
        by_product = {product_id: float(quantity) for product_id, quantity in rows if product_id is not None}
        return {
            "total": sum(by_product.values()),
            "by_product": [
                {"product_id": product_id, "quantity": quantity}
                for product_id, quantity in sorted(by_product.items(), key=lambda kv: -kv[1])
            ],
            "product_id": next(iter(by_product)) if len(by_product) == 1 else None,
        }

    def _conditionnement_totals(self, *, tenant_id: str, of_id: str) -> dict:
        row = self._connection.execute(
            f"""
            SELECT
                count(*),
                COALESCE(SUM(c.finished_product_quantity), 0),
                COALESCE(SUM(c.packets_counted), 0),
                COALESCE(SUM(c.film_quantity), 0),
                COALESCE(SUM(c.carton_quantity), 0),
                COALESCE(SUM(c.tape_quantity), 0),
                COALESCE(SUM(c.production_minutes), 0),
                COALESCE(SUM(c.downtime_minutes), 0),
                CASE WHEN COUNT(DISTINCT c.film_product_id) = 1 THEN MIN(c.film_product_id) END,
                CASE WHEN COUNT(DISTINCT c.carton_product_id) = 1 THEN MIN(c.carton_product_id) END,
                CASE WHEN COUNT(DISTINCT c.tape_product_id) = 1 THEN MIN(c.tape_product_id) END
            FROM production.production_reports r
            JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.report_type = 'conditionnement' AND r.{_VALIDATED}
            """,
            (tenant_id, of_id),
        ).fetchone()
        return {
            "report_count": int(row[0]),
            "finished_product_quantity": float(row[1]),
            # Phase 9: the tally, which is what actually entered stock. Reported
            # beside the tonnage rather than instead of it -- they answer two
            # different questions, and the gap between them is the ecart.
            "packets_counted": float(row[2]),
            "film_quantity": float(row[3]),
            "carton_quantity": float(row[4]),
            "tape_quantity": float(row[5]),
            "production_minutes": int(row[6]),
            "downtime_minutes": int(row[7]),
            "film_product_id": row[8],
            "carton_product_id": row[9],
            "tape_product_id": row[10],
        }

    def _waste_totals(self, *, tenant_id: str, of_id: str) -> dict:
        """Déchets across the OF's validated reports, grouped two ways.

        By category because that is how the plant reads its own form, and by
        item because that is the only grouping a unit can be attached to. Both
        views come from the same rows, so they always agree.

        One report type's categories cannot leak into the other's: a daily
        report only ever carries raw_material and press lines, a packing report
        only product and packaging, and the domain refuses anything else.
        """
        rows = self._connection.execute(
            f"""
            SELECT w.category, w.product_id, COALESCE(SUM(w.quantity), 0)
            FROM production.report_waste_lines w
            JOIN production.production_reports r ON r.id = w.report_id AND r.tenant_id = w.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.{_VALIDATED}
            GROUP BY w.category, w.product_id
            """,
            (tenant_id, of_id),
        ).fetchall()

        by_category: dict[str, float] = {}
        by_product: dict[str, float] = {}
        unattributed = 0.0
        for category, product_id, quantity in rows:
            amount = float(quantity)
            by_category[category] = by_category.get(category, 0.0) + amount
            if product_id is None:
                unattributed += amount
            else:
                by_product[product_id] = by_product.get(product_id, 0.0) + amount

        return {
            "by_category": by_category,
            # Sorted by quantity so the worst loss is first -- a list ordered by
            # an opaque product id is a list nobody scans.
            "by_product": [
                {"product_id": product_id, "quantity": quantity}
                for product_id, quantity in sorted(by_product.items(), key=lambda kv: -kv[1])
            ],
            "unattributed_quantity": unattributed,
        }

    def _quality_summary(self, *, tenant_id: str, of_id: str) -> dict:
        """Quality through qc's public service — never a join into its schema."""
        from modules.qc.api.quality_service import QualityReportService

        return QualityReportService(self._connection).get_conformity_summary(tenant_id=tenant_id, of_id=of_id)

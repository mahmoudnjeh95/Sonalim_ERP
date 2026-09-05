"""What actually went into an OF, measured against the recipe it follows.

Warn, never block. Nothing in this file refuses anything: the check is read at a
GET endpoint and shown on screen, and neither filing nor validating a report ever
consults it. A line that has already run cannot be un-run by rejecting its report.

**Where the mix comes from.** Two places record material entering an OF, and they
overlap, so the rule has to be stated rather than guessed:

* the **validated daily reports** are authoritative for the products they name —
  semoule and rebroyat poured back in. They are what actually moved stock, and
  what decision 6 measures production against;
* the OF's **poured input lines** supply every other component. They are recorded
  when the OF is opened and are the only record of additives and anything else
  the daily report has no field for.

A product named by a daily report is therefore never also counted from the input
lines. Counting it twice would inflate its share and fire a warning about a mix
that was correct.
"""
from __future__ import annotations

import psycopg

from core.domain.result import Err, Ok, Result
from modules.production.domain.recipe_check import (
    PouredComponent,
    RecipeLimit,
    check_recipe_limits,
)


class RecipeCheckService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def check_work_order(self, *, tenant_id: str, of_id: str) -> Result[dict]:
        work_order = self._connection.execute(
            "SELECT reference, recipe_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
            (of_id, tenant_id),
        ).fetchone()
        if work_order is None:
            return Err("NOT_FOUND", f"work order {of_id} not found")
        reference, recipe_id = work_order

        poured = self._poured_mix(tenant_id=tenant_id, of_id=of_id)
        limits = self._recipe_limits(tenant_id=tenant_id, recipe_id=recipe_id)
        findings = check_recipe_limits(poured, limits)

        return Ok(
            {
                "of_id": of_id,
                "reference": reference,
                "recipe_id": recipe_id,
                # No recipe is not a violation, and the screen needs to say
                # "no formula to check against" rather than show an empty pass.
                "has_recipe": recipe_id is not None,
                "mix": [
                    {"product_id": component.product_id, "quantity": component.quantity}
                    for component in poured
                ],
                "mix_total": sum(component.quantity for component in poured),
                "findings": [finding.as_dict() for finding in findings],
                # Convenience for the UI badge, which only needs to know whether
                # there is anything to look at.
                "has_findings": bool(findings),
                "hard_finding_count": sum(1 for f in findings if f.severity == "hard"),
            }
        )

    def _poured_mix(self, *, tenant_id: str, of_id: str) -> list[PouredComponent]:
        """Every product recorded as entering this OF, one entry per product."""
        totals: dict[str, float] = {}
        from_reports: set[str] = set()

        # Semoule: one row per line, one or more lines per report, however many
        # qualities the shift poured.
        semolina_rows = self._connection.execute(
            """
            SELECT sl.product_id, COALESCE(SUM(sl.quantity), 0)
            FROM production.production_reports r
            JOIN production.report_semolina_lines sl ON sl.report_id = r.id AND sl.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.status = 'validated' AND sl.product_id IS NOT NULL
            GROUP BY sl.product_id
            """,
            (tenant_id, of_id),
        ).fetchall()
        for product_id, quantity in semolina_rows:
            from_reports.add(product_id)
            totals[product_id] = totals.get(product_id, 0.0) + float(quantity)

        # Rebroyat poured back in: still one product per report, authoritative
        # the same way semoule is.
        rebroyat_rows = self._connection.execute(
            """
            SELECT d.regrind_input_product_id, COALESCE(SUM(d.regrind_input_quantity), 0)
            FROM production.production_reports r
            JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.status = 'validated' AND d.regrind_input_product_id IS NOT NULL
            GROUP BY d.regrind_input_product_id
            """,
            (tenant_id, of_id),
        ).fetchall()
        for product_id, quantity in rebroyat_rows:
            # Named on a report counts even at zero: the shift said it poured
            # none of it, which is a different claim from never mentioning it.
            from_reports.add(product_id)
            totals[product_id] = totals.get(product_id, 0.0) + float(quantity)

        # Poured input lines fill in the components the daily report cannot record.
        input_rows = self._connection.execute(
            "SELECT product_id, COALESCE(SUM(quantity), 0) FROM production.work_order_inputs "
            "WHERE tenant_id = %s AND work_order_id = %s GROUP BY product_id",
            (tenant_id, of_id),
        ).fetchall()
        for product_id, quantity in input_rows:
            if product_id in from_reports:
                continue
            totals[product_id] = totals.get(product_id, 0.0) + float(quantity)

        return [PouredComponent(product_id=k, quantity=v) for k, v in sorted(totals.items())]

    def _recipe_limits(self, *, tenant_id: str, recipe_id: str | None) -> list[RecipeLimit]:
        if recipe_id is None:
            return []
        rows = self._connection.execute(
            "SELECT component_product_id, min_percentage, max_percentage, is_hard_limit "
            "FROM production.recipe_lines WHERE recipe_id = %s AND tenant_id = %s",
            (recipe_id, tenant_id),
        ).fetchall()
        return [
            RecipeLimit(
                component_product_id=row[0],
                min_percentage=float(row[1]),
                max_percentage=float(row[2]),
                is_hard_limit=row[3],
            )
            for row in rows
        ]

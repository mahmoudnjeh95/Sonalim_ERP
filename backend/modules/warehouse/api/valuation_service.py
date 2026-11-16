from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.warehouse.domain.valuation import (
    NEUTRAL_MOVE_TYPES,
    VALUATION_METHODS,
    Allocation,
    CostLayer,
    ProductValuation,
    allocate_fifo,
    allocation_cost,
    value_layers,
    weighted_average,
)

_LAYER_COLUMNS = "id, tenant_id, product_id, reference, move_type, quantity_in, quantity_remaining, unit_cost, received_at"


def _layer_from_row(row) -> CostLayer:
    return CostLayer(
        id=row[0], tenant_id=row[1], product_id=row[2], reference=row[3], move_type=row[4], quantity_in=float(row[5]),
        quantity_remaining=float(row[6]), unit_cost=float(row[7]) if row[7] is not None else None, received_at=row[8],
    )


class ValuationService:
    """Cost layers, valued FIFO unless the tenant chose the weighted average. StockService calls record_inflow / record_outflow in
    the same transaction as every movement that changes what the plant owns,
    so a layer never drifts from the stock it values. Imports nothing from
    StockService -- the dependency only runs one way.

    Writes here are deliberately not audited: they are a mechanical
    consequence of a stock movement that is itself recorded (stock_moves) and,
    where a person caused it, audited by the caller."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _fallback_unit_cost(self, tenant_id: str, product_id: str) -> float | None:
        row = self._connection.execute(
            "SELECT purchase_price FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
        ).fetchone()
        if row is None or row[0] is None or row[0] <= 0:
            return None
        return float(row[0])

    def valuation_method(self, *, tenant_id: str) -> str:
        row = self._connection.execute("SELECT valuation_method FROM warehouse.settings WHERE tenant_id = %s", (tenant_id,)).fetchone()
        return row[0] if row else "fifo"

    def set_valuation_method(self, *, tenant_id: str, actor_id: str, method: str) -> Result[str]:
        """Takes effect from now on and never rewrites past movements. Choosing the average brings the
        open layers to it at once, so the stock value shown doesn't depend on the next receipt. Going
        back to FIFO leaves those layers at the average they already carry."""
        if method not in VALUATION_METHODS:
            return Err("INVALID_VALUATION_METHOD", f"unknown valuation method {method}", f"méthode de valorisation inconnue {method}")
        previous = self.valuation_method(tenant_id=tenant_id)
        self._connection.execute(
            """
            INSERT INTO warehouse.settings (tenant_id, valuation_method, updated_by) VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET valuation_method = EXCLUDED.valuation_method,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, method, actor_id),
        )
        if method == "average" and previous != "average":
            products = self._connection.execute(
                "SELECT DISTINCT product_id FROM warehouse.cost_layers WHERE tenant_id = %s AND quantity_remaining > 0", (tenant_id,)
            ).fetchall()
            for (product_id,) in products:
                self._level_to_average(tenant_id, product_id)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.valuation_method.changed",
                     entity_type="warehouse_settings", entity_id=tenant_id, payload={"from": previous, "to": method})
        return Ok(method)

    def _open_layers_for_update(self, tenant_id: str, product_id: str) -> list[tuple[float, float | None]]:
        rows = self._connection.execute(
            """
            SELECT quantity_remaining, unit_cost FROM warehouse.cost_layers
            WHERE tenant_id = %s AND product_id = %s AND quantity_remaining > 0
            ORDER BY received_at, id
            FOR UPDATE
            """,
            (tenant_id, product_id),
        ).fetchall()
        return [(float(remaining), float(cost) if cost is not None else None) for remaining, cost in rows]

    def _level_to_average(self, tenant_id: str, product_id: str) -> None:
        """Every open valued layer takes the weighted average, so whichever one a later outflow draws
        from, the goods leave at that average."""
        average = weighted_average(self._open_layers_for_update(tenant_id, product_id))
        if average is None:
            return
        self._connection.execute(
            "UPDATE warehouse.cost_layers SET unit_cost = %s WHERE tenant_id = %s AND product_id = %s "
            "AND quantity_remaining > 0 AND unit_cost IS NOT NULL",
            (average, tenant_id, product_id),
        )

    def record_inflow(
        self,
        *,
        tenant_id: str,
        product_id: str,
        quantity: float,
        reference: str,
        move_type: str,
        unit_cost: float | None = None,
    ) -> None:
        """A new layer. Without a known cost (only a purchase receipt knows its
        landed cost) the catalog purchase price stands in, and without that the
        layer is unvalued rather than priced at an invented 0."""
        if move_type in NEUTRAL_MOVE_TYPES or quantity <= 0:
            return
        average_method = self.valuation_method(tenant_id=tenant_id) == "average"
        cost = unit_cost if unit_cost is not None and unit_cost >= 0 else None
        if cost is None and average_method:
            cost = weighted_average(self._open_layers_for_update(tenant_id, product_id))
        if cost is None:
            cost = self._fallback_unit_cost(tenant_id, product_id)
        self._connection.execute(
            f"""
            INSERT INTO warehouse.cost_layers ({_LAYER_COLUMNS})
            -- clock_timestamp(), not NOW(): NOW() is the transaction's start time, so two
            -- receipts in one transaction shared it and FIFO order fell to the `id`
            -- tie-break -- and ULIDs are not ordered inside a millisecond, which could draw
            -- the newer layer first and misprice what left stock.
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
            """,
            (str(ULID()), tenant_id, product_id, reference, move_type, quantity, quantity, cost),
        )
        if average_method:
            self._level_to_average(tenant_id, product_id)

    def record_outflow(
        self, *, tenant_id: str, product_id: str, quantity: float, reference: str, move_type: str
    ) -> list[Allocation]:
        if move_type in NEUTRAL_MOVE_TYPES or quantity <= 0:
            return []
        rows = self._connection.execute(
            """
            SELECT id, quantity_remaining, unit_cost FROM warehouse.cost_layers
            WHERE tenant_id = %s AND product_id = %s AND quantity_remaining > 0
            ORDER BY received_at, id
            FOR UPDATE
            """,
            (tenant_id, product_id),
        ).fetchall()
        layers = [(row[0], float(row[1]), float(row[2]) if row[2] is not None else None) for row in rows]
        allocations = allocate_fifo(layers, quantity)
        for allocation in allocations:
            if allocation.layer_id is not None:
                self._connection.execute(
                    "UPDATE warehouse.cost_layers SET quantity_remaining = quantity_remaining - %s WHERE id = %s",
                    (allocation.quantity, allocation.layer_id),
                )
            self._connection.execute(
                """
                INSERT INTO warehouse.cost_layer_consumptions
                    (id, tenant_id, product_id, layer_id, reference, move_type, quantity, unit_cost)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, product_id, allocation.layer_id, reference, move_type, allocation.quantity, allocation.unit_cost),
            )
        return allocations

    def record_delta(
        self, *, tenant_id: str, product_id: str, delta: float, reference: str, move_type: str, unit_cost: float | None = None
    ) -> None:
        """For corrections, whose sign is only known at run time."""
        if delta > 0:
            self.record_inflow(
                tenant_id=tenant_id, product_id=product_id, quantity=delta, reference=reference, move_type=move_type, unit_cost=unit_cost
            )
        elif delta < 0:
            self.record_outflow(tenant_id=tenant_id, product_id=product_id, quantity=-delta, reference=reference, move_type=move_type)

    # --- Reads ------------------------------------------------------------------------

    def list_layers(self, *, tenant_id: str, product_id: str, open_only: bool = True) -> list[CostLayer]:
        remaining_clause = " AND quantity_remaining > 0" if open_only else ""
        rows = self._connection.execute(
            f"""
            SELECT {_LAYER_COLUMNS} FROM warehouse.cost_layers
            WHERE tenant_id = %s AND product_id = %s{remaining_clause}
            ORDER BY received_at, id
            """,
            (tenant_id, product_id),
        ).fetchall()
        return [_layer_from_row(row) for row in rows]

    def get_valuation(self, *, tenant_id: str) -> list[ProductValuation]:
        rows = self._connection.execute(
            f"""
            SELECT {_LAYER_COLUMNS} FROM warehouse.cost_layers
            WHERE tenant_id = %s AND quantity_remaining > 0
            ORDER BY product_id, received_at, id
            """,
            (tenant_id,),
        ).fetchall()
        by_product: dict[str, list[CostLayer]] = {}
        for row in rows:
            layer = _layer_from_row(row)
            by_product.setdefault(layer.product_id, []).append(layer)
        return [value_layers(product_id, layers) for product_id, layers in by_product.items()]

    def cost_of_reference(self, *, tenant_id: str, reference: str) -> dict:
        """What the stock that left under `reference` cost -- a shipment's
        cost of goods sold, an OF's material cost."""
        rows = self._connection.execute(
            """
            SELECT layer_id, quantity, unit_cost FROM warehouse.cost_layer_consumptions
            WHERE tenant_id = %s AND reference = %s
            """,
            (tenant_id, reference),
        ).fetchall()
        allocations = [
            Allocation(layer_id=row[0], quantity=float(row[1]), unit_cost=float(row[2]) if row[2] is not None else None)
            for row in rows
        ]
        cost, unvalued = allocation_cost(allocations)
        return {
            "reference": reference,
            "quantity": sum(a.quantity for a in allocations),
            "cost": cost,
            "unvalued_quantity": unvalued,
            "currency": "XOF",
        }

    def costs_of_references(self, *, tenant_id: str, references: list[str]) -> dict[str, dict]:
        """`cost_of_reference` for several references in one query. Every reference asked
        for is in the result; one nothing left under has quantity and cost 0."""
        rows = self._connection.execute(
            """
            SELECT reference, layer_id, quantity, unit_cost FROM warehouse.cost_layer_consumptions
            WHERE tenant_id = %s AND reference = ANY(%s)
            """,
            (tenant_id, list(references)),
        ).fetchall()
        allocations: dict[str, list[Allocation]] = {reference: [] for reference in references}
        for reference, layer_id, quantity, unit_cost in rows:
            allocations[reference].append(
                Allocation(layer_id=layer_id, quantity=float(quantity), unit_cost=float(unit_cost) if unit_cost is not None else None)
            )
        result: dict[str, dict] = {}
        for reference, items in allocations.items():
            cost, unvalued = allocation_cost(items)
            result[reference] = {
                "reference": reference,
                "quantity": sum(a.quantity for a in items),
                "cost": cost,
                "unvalued_quantity": unvalued,
                "currency": "XOF",
            }
        return result

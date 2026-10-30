from __future__ import annotations

import psycopg
from ulid import ULID

from modules.warehouse.domain.valuation import (
    NEUTRAL_MOVE_TYPES,
    Allocation,
    CostLayer,
    ProductValuation,
    allocate_fifo,
    allocation_cost,
    value_layers,
)

_LAYER_COLUMNS = "id, tenant_id, product_id, reference, move_type, quantity_in, quantity_remaining, unit_cost, received_at"


def _layer_from_row(row) -> CostLayer:
    return CostLayer(
        id=row[0], tenant_id=row[1], product_id=row[2], reference=row[3], move_type=row[4], quantity_in=float(row[5]),
        quantity_remaining=float(row[6]), unit_cost=float(row[7]) if row[7] is not None else None, received_at=row[8],
    )


class ValuationService:
    """FIFO cost layers. StockService calls record_inflow / record_outflow in
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
        cost = unit_cost if unit_cost is not None and unit_cost >= 0 else self._fallback_unit_cost(tenant_id, product_id)
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

    def restore_outflow(
        self, *, tenant_id: str, product_id: str, quantity: float, reference: str, move_type: str
    ) -> None:
        """Undo an earlier outflow under `reference`: the quantity goes back into the
        very layers that outflow drew from, at their own cost and FIFO position, rather
        than opening a new layer at today's catalog price at the back of the queue.

        Each put-back is recorded as a negative consumption, so the reference's cost
        (`cost_of_reference`) nets to what is still really consumed. Anything beyond what
        the reference still has drawn opens a new layer, as a plain inflow would.
        """
        if move_type in NEUTRAL_MOVE_TYPES or quantity <= 0:
            return
        drawn = self._connection.execute(
            """
            SELECT layer_id, unit_cost, SUM(quantity) AS net
            FROM warehouse.cost_layer_consumptions
            WHERE tenant_id = %s AND product_id = %s AND reference = %s
            GROUP BY layer_id, unit_cost
            HAVING SUM(quantity) > 0
            ORDER BY MAX(consumed_at) DESC, layer_id NULLS FIRST
            """,
            (tenant_id, product_id, reference),
        ).fetchall()
        left = quantity
        for layer_id, unit_cost, net in drawn:
            if left <= 1e-9:
                break
            put_back = min(float(net), left)
            if layer_id is not None:
                self._connection.execute(
                    "UPDATE warehouse.cost_layers SET quantity_remaining = quantity_remaining + %s WHERE id = %s",
                    (put_back, layer_id),
                )
            # A layer-less draw was a shortfall nobody valued; undoing it restores no layer.
            self._connection.execute(
                """
                INSERT INTO warehouse.cost_layer_consumptions
                    (id, tenant_id, product_id, layer_id, reference, move_type, quantity, unit_cost, consumed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
                """,
                (str(ULID()), tenant_id, product_id, layer_id, reference, move_type, -put_back, unit_cost),
            )
            left -= put_back
        if left > 1e-9:
            self.record_inflow(tenant_id=tenant_id, product_id=product_id, quantity=left, reference=reference, move_type=move_type)

    def reverse_inflow(
        self, *, tenant_id: str, product_id: str, quantity: float, reference: str, move_type: str
    ) -> list[Allocation]:
        """Undo an earlier inflow under `reference`: the quantity leaves the layers that
        inflow opened, newest first, instead of the oldest stock on the shelf -- so taking
        back a production receipt removes exactly the cost it brought in. Whatever those
        layers no longer hold (already drawn by later outflows) is drawn FIFO as usual.
        """
        if move_type in NEUTRAL_MOVE_TYPES or quantity <= 0:
            return []
        rows = self._connection.execute(
            """
            SELECT id, quantity_remaining, unit_cost FROM warehouse.cost_layers
            WHERE tenant_id = %s AND product_id = %s AND reference = %s AND quantity_remaining > 0
            ORDER BY received_at DESC, id DESC
            FOR UPDATE
            """,
            (tenant_id, product_id, reference),
        ).fetchall()
        allocations: list[Allocation] = []
        left = quantity
        for layer_id, remaining, unit_cost in rows:
            if left <= 1e-9:
                break
            taken = min(float(remaining), left)
            allocations.append(Allocation(layer_id=layer_id, quantity=taken, unit_cost=float(unit_cost) if unit_cost is not None else None))
            left -= taken
        for allocation in allocations:
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
        if left > 1e-9:
            allocations += self.record_outflow(tenant_id=tenant_id, product_id=product_id, quantity=left, reference=reference, move_type=move_type)
        return allocations

    def consumption_cost(self, *, tenant_id: str, references: list[str], move_types: list[str]) -> dict:
        """What is still consumed under `references`, counting only `move_types` --
        an outflow's cost net of any put-backs (`restore_outflow`). `unvalued_quantity`
        is the part drawn with no known cost."""
        rows = self._connection.execute(
            """
            SELECT layer_id, quantity, unit_cost FROM warehouse.cost_layer_consumptions
            WHERE tenant_id = %s AND reference = ANY(%s) AND move_type = ANY(%s)
            """,
            (tenant_id, list(references), list(move_types)),
        ).fetchall()
        allocations = [
            Allocation(layer_id=row[0], quantity=float(row[1]), unit_cost=float(row[2]) if row[2] is not None else None)
            for row in rows
        ]
        cost, unvalued = allocation_cost(allocations)
        return {"cost": cost, "unvalued_quantity": unvalued, "quantity": sum(a.quantity for a in allocations)}

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

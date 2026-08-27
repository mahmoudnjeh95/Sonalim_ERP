from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.domain.entities import (
    StockLevel,
    adjust,
    consume_in_production,
    issue,
    receive,
    release_reservation,
    reserve,
    send_to_production,
)


class StockService:
    """Public API for the warehouse module. Callers commit; this class only executes writes."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_stock_items(self, tenant_id: str, location_id: str | None = None) -> list[StockLevel]:
        if location_id is not None:
            rows = self._connection.execute(
                """
                SELECT location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production
                FROM warehouse.stock_items
                                WHERE tenant_id = %s AND location_id = %s
                                    AND (quantity_on_hand > 0 OR quantity_reserved > 0 OR quantity_in_production > 0)
                ORDER BY product_id
                """,
                (tenant_id, location_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production
                FROM warehouse.stock_items
                                WHERE tenant_id = %s
                                    AND (quantity_on_hand > 0 OR quantity_reserved > 0 OR quantity_in_production > 0)
                ORDER BY location_id, product_id
                """,
                (tenant_id,),
            ).fetchall()
        return [
            StockLevel(
                location_id=location_id,
                product_id=product_id,
                quantity_on_hand=float(on_hand),
                quantity_reserved=float(reserved),
                quantity_in_production=float(in_production),
            )
            for location_id, product_id, on_hand, reserved, in_production in rows
        ]

    def get_available_quantity(self, tenant_id: str, product_id: str, location_id: str) -> float:
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()
        if row is None:
            return 0.0
        quantity_on_hand, quantity_reserved = row
        return float(quantity_on_hand - quantity_reserved)

    def reserve_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        correlation_id: str,
        reference: str,
        actor_id: str | None = None,
    ) -> Result[StockLevel]:
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
        )

        result = reserve(current, quantity)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_reserved = EXCLUDED.quantity_reserved
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id)
            VALUES (%s, %s, %s, %s, %s, 'reservation', %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, reference, actor_id),
        )
        publish_event(
            self._connection,
            event_type="warehouse.stock.reserved",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"product_id": product_id, "location_id": location_id, "quantity": quantity, "reference": reference},
        )
        return result

    def release_stock_reservation(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        reference: str,
        actor_id: str | None = None,
    ) -> Result[StockLevel]:
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
        )

        result = release_reservation(current, quantity)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_reserved = EXCLUDED.quantity_reserved
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id)
            VALUES (%s, %s, %s, %s, %s, 'reservation_released', %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, reference, actor_id),
        )
        return result

    def receive_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        correlation_id: str,
        reference: str,
        actor_id: str | None = None,
        move_type: str = "receipt",
    ) -> Result[StockLevel]:
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
        )

        result = receive(current, quantity)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, move_type, reference, actor_id),
        )
        publish_event(
            self._connection,
            event_type="warehouse.stock.received",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"product_id": product_id, "location_id": location_id, "quantity": quantity, "reference": reference},
        )
        return result

    def issue_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        reference: str,
        actor_id: str | None = None,
        move_type: str = "issue",
    ) -> Result[StockLevel]:
        """Records a "sortie" — physical consumption of stock (e.g. a receipt moving into production use)."""
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
        )

        result = issue(current, quantity)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, move_type, reference, actor_id),
        )
        return result

    def send_to_production_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        reference: str,
        actor_id: str | None = None,
    ) -> Result[StockLevel]:
        """Moves raw material out of on-hand into "en production" — called when a work
        order is created with poured raw-material quantities (see modules.production)."""
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved, quantity_in_production
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
            quantity_in_production=float(row[2]) if row else 0.0,
        )

        result = send_to_production(current, quantity)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand, quantity_in_production = EXCLUDED.quantity_in_production
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved, result.value.quantity_in_production),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id)
            VALUES (%s, %s, %s, %s, %s, 'send_to_production', %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, reference, actor_id),
        )
        return result

    def consume_in_production_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        reference: str,
        actor_id: str | None = None,
    ) -> Result[StockLevel]:
        """Fully consumes raw material previously sent to "en production" — called when
        the work order that poured it completes."""
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved, quantity_in_production
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
            quantity_in_production=float(row[2]) if row else 0.0,
        )

        result = consume_in_production(current, quantity)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_in_production = EXCLUDED.quantity_in_production
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved, result.value.quantity_in_production),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id)
            VALUES (%s, %s, %s, %s, %s, 'production_consumption', %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, reference, actor_id),
        )
        return result

    def adjust_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        delta: float,
        reason: str,
        actor_id: str | None = None,
    ) -> Result[StockLevel]:
        """Records an "ajustement" — a manual correction to on-hand quantity (e.g. a physical count)."""
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()

        current = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
        )

        result = adjust(current, delta)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand
            """,
            (tenant_id, location_id, product_id, result.value.quantity_on_hand, result.value.quantity_reserved),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id, reason)
            VALUES (%s, %s, %s, %s, %s, 'adjustment', %s, %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, delta, "manual_adjustment", actor_id, reason),
        )
        return result

    def list_stock_moves(
        self,
        *,
        tenant_id: str,
        location_id: str | None = None,
        product_id: str | None = None,
        move_type: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if location_id is not None:
            clauses.append("location_id = %s")
            params.append(location_id)
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        if move_type is not None:
            clauses.append("move_type = %s")
            params.append(move_type)
        params.append(limit)

        rows = self._connection.execute(
            f"""
            SELECT id, location_id, product_id, quantity, move_type, reference, actor_id, reason, created_at
            FROM warehouse.stock_moves
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
        return [
            {
                "id": mid,
                "location_id": location_id,
                "product_id": product_id,
                "quantity": float(quantity),
                "move_type": move_type,
                "reference": reference,
                "actor_id": actor_id,
                "reason": reason,
                "created_at": created_at.isoformat(),
            }
            for mid, location_id, product_id, quantity, move_type, reference, actor_id, reason, created_at in rows
        ]

    def transfer_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        from_location_id: str,
        to_location_id: str,
        quantity: float,
        correlation_id: str,
        reference: str,
        actor_id: str | None = None,
    ) -> Result[tuple[StockLevel, StockLevel]]:
        """Moves on-hand stock from one location to another as one atomic pair of
        moves (transfer_out at the source, transfer_in at the destination)."""
        if from_location_id == to_location_id:
            return Err("INVALID_TRANSFER", "source and destination locations must differ")

        issued = self.issue_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=from_location_id,
            quantity=quantity,
            reference=reference,
            actor_id=actor_id,
            move_type="transfer_out",
        )
        if isinstance(issued, Err):
            return issued

        received = self.receive_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=to_location_id,
            quantity=quantity,
            correlation_id=correlation_id,
            reference=reference,
            actor_id=actor_id,
            move_type="transfer_in",
        )
        if isinstance(received, Err):
            return received

        return Ok((issued.value, received.value))

    def admin_set_stock(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity_on_hand: float,
        quantity_reserved: float,
        quantity_in_production: float,
        actor_id: str,
    ) -> Result[StockLevel]:
        """Administrative override: directly overwrites all three stock buckets,
        bypassing the normal-flow invariants (reserve/issue/etc. all check against
        each other; this doesn't). Always audited since it's a direct correction."""
        if quantity_on_hand < 0 or quantity_reserved < 0 or quantity_in_production < 0:
            return Err("INVALID_QUANTITY", "quantities cannot be negative")

        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved, quantity_in_production
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()
        before = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=float(row[0]) if row else 0.0,
            quantity_reserved=float(row[1]) if row else 0.0,
            quantity_in_production=float(row[2]) if row else 0.0,
        )
        after = StockLevel(
            location_id=location_id,
            product_id=product_id,
            quantity_on_hand=quantity_on_hand,
            quantity_reserved=quantity_reserved,
            quantity_in_production=quantity_in_production,
        )

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand, quantity_reserved = EXCLUDED.quantity_reserved, quantity_in_production = EXCLUDED.quantity_in_production
            """,
            (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id, reason)
            VALUES (%s, %s, %s, %s, %s, 'admin_correction', %s, %s, %s)
            """,
            (
                str(ULID()),
                tenant_id,
                location_id,
                product_id,
                quantity_on_hand - before.quantity_on_hand,
                "admin_set_stock",
                actor_id,
                (
                    f"on_hand {before.quantity_on_hand}->{quantity_on_hand}, "
                    f"reserved {before.quantity_reserved}->{quantity_reserved}, "
                    f"in_production {before.quantity_in_production}->{quantity_in_production}"
                ),
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="stock_item.admin_updated",
            entity_type="stock_item",
            entity_id=f"{location_id}:{product_id}",
            payload={
                "before": {
                    "quantity_on_hand": before.quantity_on_hand,
                    "quantity_reserved": before.quantity_reserved,
                    "quantity_in_production": before.quantity_in_production,
                },
                "after": {
                    "quantity_on_hand": after.quantity_on_hand,
                    "quantity_reserved": after.quantity_reserved,
                    "quantity_in_production": after.quantity_in_production,
                },
            },
        )
        return Ok(after)

    def delete_stock_item(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        actor_id: str,
    ) -> Result[None]:
        """Deletes a stock row entirely. The values are captured in the audit log
        before deletion, since the row itself won't be there to recover them from."""
        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved, quantity_in_production
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"no stock row for product {product_id} at location {location_id}")

        quantity_on_hand, quantity_reserved, quantity_in_production = (float(value) for value in row)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="stock_item.deleted",
            entity_type="stock_item",
            entity_id=f"{location_id}:{product_id}",
            payload={
                "quantity_on_hand": quantity_on_hand,
                "quantity_reserved": quantity_reserved,
                "quantity_in_production": quantity_in_production,
            },
        )
        self._connection.execute(
            "DELETE FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
            (tenant_id, product_id, location_id),
        )
        return Ok(None)

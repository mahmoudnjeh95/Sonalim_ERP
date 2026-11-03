from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.entities import validate_quantity_for_uom
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

    def _validate_quantity(self, *, tenant_id: str, product_id: str, quantity: float) -> Result[None]:
        """Every quantity that lands in warehouse.stock_items must respect its
        product's own unit -- a whole number of cartons/pièces, any real number
        of kg/litres. An unresolvable product/uom is a catalog-data problem, not
        this call's to invent a new error for, so it passes through."""
        uom = CoreService(self._connection).get_product_uom(tenant_id, product_id)
        if uom is None:
            return Ok(None)
        return validate_quantity_for_uom(quantity, uom)

    def list_stock_items(self, tenant_id: str, location_id: str | None = None) -> list[StockLevel]:
        if location_id is not None:
            rows = self._connection.execute(
                """
                SELECT location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production
                FROM warehouse.stock_items
                WHERE tenant_id = %s AND location_id = %s
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

    def _assert_not_frozen(self, tenant_id: str, location_id: str) -> Err | None:
        """A full inventory freezes its location: counting a shelf while stock moves in and out of
        it would make the counts meaningless. Only closing the inventory itself may post there."""
        row = self._connection.execute(
            "SELECT number FROM warehouse.inventories WHERE tenant_id = %s AND location_id = %s "
            "AND status = 'open' AND type = 'full' LIMIT 1",
            (tenant_id, location_id),
        ).fetchone()
        if row is None:
            return None
        return Err(
            "LOCATION_FROZEN",
            f"this location is frozen by inventory {row[0]}; close it before moving stock",
            f"cet emplacement est gelé par l'inventaire {row[0]} ; clôturez-le avant de mouvementer le stock",
        )

    def get_available_quantity(self, tenant_id: str, product_id: str, location_id: str) -> float:
        """What this location can actually promise.

        Stock in a blocked location — quarantine — is deliberately zero here. The
        goods exist and stay on the books at value, but they are awaiting a
        disposition decision, so no other module may promise or reserve them. That
        control is the whole reason non-conforming product is segregated rather
        than merely flagged.
        """
        row = self._connection.execute(
            """
            SELECT si.quantity_on_hand, si.quantity_reserved, COALESCE(l.is_blocked, FALSE)
            FROM warehouse.stock_items si
            LEFT JOIN warehouse.locations l ON l.id = si.location_id AND l.tenant_id = si.tenant_id
            WHERE si.tenant_id = %s AND si.product_id = %s AND si.location_id = %s
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()
        if row is None:
            return 0.0
        quantity_on_hand, quantity_reserved, is_blocked = row
        if is_blocked:
            return 0.0
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
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation

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
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation

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

    def post_production_movement(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        quantity: float,
        direction: str,
        correlation_id: str,
        reference: str,
        move_type: str,
        actor_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        of_id: str | None = None,
    ) -> Result[StockLevel]:
        """Post a movement that records what physically happened, shortfall or not.

        The one place on this service where a withdrawal is allowed to drive a
        balance negative. A validated production report states what the line
        actually consumed; refusing it because inventory disagrees would make the
        record follow the stock figure instead of the other way round, so the
        movement goes through and the resulting variance is surfaced to whoever
        reconciles stock. Every other path — reservations above all — keeps its
        INSUFFICIENT_STOCK refusal, because those are promises about the future
        rather than records of the past.

        `source_type`, `source_id` and `of_id` are what let a number in inventory
        be traced back to the report and OF that produced it.
        """
        if quantity <= 0:
            return Err("INVALID_QUANTITY", "movement quantity must be positive", "la quantité du mouvement doit être positive")
        if direction not in ("in", "out"):
            return Err("INVALID_DIRECTION", "direction must be 'in' or 'out'", "la direction doit être 'in' ou 'out'")
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation
        frozen = self._assert_not_frozen(tenant_id, location_id)
        if frozen is not None:
            return frozen

        row = self._connection.execute(
            """
            SELECT quantity_on_hand, quantity_reserved
            FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            FOR UPDATE
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()
        current_on_hand = float(row[0]) if row else 0.0
        current_reserved = float(row[1]) if row else 0.0

        delta = quantity if direction == "in" else -quantity
        new_on_hand = current_on_hand + delta

        self._connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, location_id, product_id)
            DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand
            """,
            (tenant_id, location_id, product_id, new_on_hand, current_reserved),
        )
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_moves
                (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id,
                 source_type, source_id, of_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(ULID()),
                tenant_id,
                location_id,
                product_id,
                quantity,
                move_type,
                reference,
                actor_id,
                source_type,
                source_id,
                of_id,
            ),
        )
        publish_event(
            self._connection,
            event_type="warehouse.stock.received" if direction == "in" else "warehouse.stock.issued",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "product_id": product_id,
                "location_id": location_id,
                "quantity": quantity,
                "reference": reference,
            },
        )
        return Ok(
            StockLevel(
                location_id=location_id,
                product_id=product_id,
                quantity_on_hand=new_on_hand,
                quantity_reserved=current_reserved,
            )
        )

    def transfer_to_quarantine(
        self,
        *,
        tenant_id: str,
        product_id: str,
        from_location_id: str,
        quarantine_location_id: str,
        quantity: float,
        correlation_id: str,
        reference: str,
        actor_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        of_id: str | None = None,
    ) -> Result[None]:
        """Move product out of sellable stock and into a blocked location.

        The destination must actually be blocked — the whole point of quarantine is
        that the goods stop being promisable the moment they are pulled, and a
        quarantine that is merely a normal shelf would leave rejected product
        sellable on paper while it sits in a crate in the QC room.

        The goods stay on the books at value: they have not been written off, they
        are awaiting a decision.
        """
        row = self._connection.execute(
            "SELECT is_blocked FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
            (quarantine_location_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"location {quarantine_location_id} not found", f"emplacement {quarantine_location_id} introuvable")
        if not row[0]:
            return Err(
                "LOCATION_NOT_BLOCKED",
                "quarantine must be a blocked location, or the product stays sellable",
                "la quarantaine doit être un emplacement bloqué, sinon le produit reste vendable",
            )

        out = self.post_production_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=from_location_id,
            quantity=quantity,
            direction="out",
            correlation_id=correlation_id,
            reference=reference,
            move_type="transfer_out",
            actor_id=actor_id,
            source_type=source_type,
            source_id=source_id,
            of_id=of_id,
        )
        if isinstance(out, Err):
            return out

        into = self.post_production_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=quarantine_location_id,
            quantity=quantity,
            direction="in",
            correlation_id=correlation_id,
            reference=reference,
            move_type="transfer_in",
            actor_id=actor_id,
            source_type=source_type,
            source_id=source_id,
            of_id=of_id,
        )
        if isinstance(into, Err):
            return into
        return Ok(None)

    def release_from_quarantine(
        self,
        *,
        tenant_id: str,
        product_id: str,
        quarantine_location_id: str,
        quantity: float,
        correlation_id: str,
        reference: str,
        actor_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        of_id: str | None = None,
    ) -> Result[None]:
        """Take dispositioned product back out of quarantine.

        Only the finished product moves. The packaging inside it already left stock
        when the conditionnement report was validated, so the film, carton and tape
        are recorded as déchet and never deducted a second time.
        """
        released = self.post_production_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=quarantine_location_id,
            quantity=quantity,
            direction="out",
            correlation_id=correlation_id,
            reference=reference,
            move_type="issue",
            actor_id=actor_id,
            source_type=source_type,
            source_id=source_id,
            of_id=of_id,
        )
        if isinstance(released, Err):
            return released
        return Ok(None)

    def restore_from_quarantine(
        self,
        *,
        tenant_id: str,
        product_id: str,
        quarantine_location_id: str,
        destination_location_id: str,
        quantity: float,
        correlation_id: str,
        reference: str,
        actor_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        of_id: str | None = None,
    ) -> Result[None]:
        """Reverse a quarantine hold that turned out to be unwarranted.

        Unlike `release_from_quarantine` (a one-way disposition exit — the
        product is regrind/déchet/rework/back-to-stock and the disposition
        event tells downstream modules where the value actually went), the
        hold itself was wrong here — e.g. the quality report describing it
        got rejected — so the product goes back to exactly where it was
        pulled from. This is the mirror of `transfer_to_quarantine`, on the
        books as well as on the floor.
        """
        out = self.post_production_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=quarantine_location_id,
            quantity=quantity,
            direction="out",
            correlation_id=correlation_id,
            reference=reference,
            move_type="transfer_out",
            actor_id=actor_id,
            source_type=source_type,
            source_id=source_id,
            of_id=of_id,
        )
        if isinstance(out, Err):
            return out

        into = self.post_production_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=destination_location_id,
            quantity=quantity,
            direction="in",
            correlation_id=correlation_id,
            reference=reference,
            move_type="transfer_in",
            actor_id=actor_id,
            source_type=source_type,
            source_id=source_id,
            of_id=of_id,
        )
        if isinstance(into, Err):
            return into
        return Ok(None)

    def would_go_negative(self, *, tenant_id: str, product_id: str, location_id: str, quantity: float) -> bool:
        """Whether withdrawing `quantity` here would drive on-hand below zero.

        Used by report validation to decide up front whether the validator must
        explain a shortfall, before anything is written.
        """
        row = self._connection.execute(
            """
            SELECT quantity_on_hand FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
            """,
            (tenant_id, product_id, location_id),
        ).fetchone()
        on_hand = float(row[0]) if row else 0.0
        return on_hand - quantity < 0

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
        unit_cost: Decimal | None = None,
    ) -> Result[StockLevel]:
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation
        frozen = self._assert_not_frozen(tenant_id, location_id)
        if frozen is not None:
            return frozen
        # The average is over the whole product, so read what was on hand everywhere before this lands.
        on_hand_before = self._connection.execute(
            "SELECT COALESCE(SUM(quantity_on_hand), 0) FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s",
            (tenant_id, product_id),
        ).fetchone()[0]

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
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, actor_id, unit_cost)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, location_id, product_id, quantity, move_type, reference, actor_id, unit_cost),
        )
        if unit_cost is not None:
            from modules.warehouse.api.valuation_service import ValuationService

            ValuationService(self._connection).apply_receipt(
                tenant_id=tenant_id, product_id=product_id, on_hand_before=Decimal(str(on_hand_before)),
                quantity=Decimal(str(quantity)), unit_cost=Decimal(str(unit_cost)),
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
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation
        frozen = self._assert_not_frozen(tenant_id, location_id)
        if frozen is not None:
            return frozen

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
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation
        frozen = self._assert_not_frozen(tenant_id, location_id)
        if frozen is not None:
            return frozen

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
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=quantity)
        if isinstance(validation, Err):
            return validation
        frozen = self._assert_not_frozen(tenant_id, location_id)
        if frozen is not None:
            return frozen

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
        reference: str = "manual_adjustment",
        _from_inventory: bool = False,
    ) -> Result[StockLevel]:
        """Records an "ajustement" — a manual correction to on-hand quantity (e.g. a physical count)."""
        validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=delta)
        if isinstance(validation, Err):
            return validation
        frozen = None if _from_inventory else self._assert_not_frozen(tenant_id, location_id)
        if frozen is not None:
            return frozen

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
            (str(ULID()), tenant_id, location_id, product_id, delta, reference, actor_id, reason),
        )
        return result

    def list_stock_moves(
        self,
        *,
        tenant_id: str,
        location_id: str | None = None,
        product_id: str | None = None,
        move_type: str | None = None,
        reference: str | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
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
        if reference is not None:
            clauses.append("reference = %s")
            params.append(reference)
        # Calendar-day bounds, inclusive on both ends: a screen asks for
        # "September" and expects the 30th's evening movements in it.
        if date_from is not None:
            clauses.append("created_at >= %s")
            params.append(datetime.datetime.combine(date_from, datetime.time.min))
        if date_to is not None:
            clauses.append("created_at < %s")
            params.append(datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min))
        params.append(limit)

        rows = self._connection.execute(
            f"""
            SELECT id, location_id, product_id, quantity, move_type, reference, actor_id, reason, created_at, of_id
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
                "of_id": of_id,
            }
            for mid, location_id, product_id, quantity, move_type, reference, actor_id, reason, created_at, of_id in rows
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
            return Err(
                "INVALID_TRANSFER",
                "source and destination locations must differ",
                "l'emplacement source et l'emplacement de destination doivent être différents",
            )

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
        each other; this doesn't). Always audited since it's a direct correction.

        quantity_on_hand alone may be negative: post_production_movement already
        lets a validated production movement drive it there when the record
        disagrees with what inventory believes is on the shelf (a record of the
        past outranks a stock figure), and this override is exactly what
        reconciles that gap back -- refusing a negative correction here would
        make the correction follow the wrong number instead of fixing it.
        quantity_reserved and quantity_in_production stay non-negative: both are
        promises about future stock, not records of the past, so a negative one
        is just wrong.
        """
        if quantity_reserved < 0 or quantity_in_production < 0:
            return Err(
                "INVALID_QUANTITY",
                "reserved and in-production quantities cannot be negative",
                "les quantités réservée et en production ne peuvent pas être négatives",
            )
        for value in (quantity_on_hand, quantity_reserved, quantity_in_production):
            validation = self._validate_quantity(tenant_id=tenant_id, product_id=product_id, quantity=value)
            if isinstance(validation, Err):
                return validation

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
            return Err(
                "NOT_FOUND",
                f"no stock row for product {product_id} at location {location_id}",
                f"aucune ligne de stock pour le produit {product_id} à l'emplacement {location_id}",
            )

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

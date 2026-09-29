from __future__ import annotations

import datetime

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.api.service import StockService
from modules.warehouse.domain.reservation import StockReservation, expiry_release_quantity, validate_reservation_expiry

SYSTEM_ACTOR = "system:reservation-expiry"

_COLUMNS = (
    "id, tenant_id, product_id, location_id, reference, quantity, quantity_open, status, expires_at, created_by, "
    "created_at, closed_at"
)


def _from_row(row) -> StockReservation:
    return StockReservation(
        id=row[0], tenant_id=row[1], product_id=row[2], location_id=row[3], reference=row[4], quantity=float(row[5]),
        quantity_open=float(row[6]), status=row[7], expires_at=row[8], created_by=row[9], created_at=row[10], closed_at=row[11],
    )


class ReservationService:
    """The reservation ledger: what is held, for whom, until when -- and the
    sweep that gives lapsed holds back to available stock."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    def list_reservations(self, *, tenant_id: str, status: str | None = None) -> list[StockReservation]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM warehouse.stock_reservations WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC LIMIT 1000",
            params,
        ).fetchall()
        return [_from_row(row) for row in rows]

    def _get_for_update(self, *, tenant_id: str, reservation_id: str) -> Result[StockReservation]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM warehouse.stock_reservations WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (reservation_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"reservation {reservation_id} not found", f"réservation {reservation_id} introuvable")
        return Ok(_from_row(row))

    def _reload(self, reservation_id: str) -> StockReservation:
        return _from_row(
            self._connection.execute(f"SELECT {_COLUMNS} FROM warehouse.stock_reservations WHERE id = %s", (reservation_id,)).fetchone()
        )

    def _reserved_now(self, reservation: StockReservation) -> float:
        row = self._connection.execute(
            """
            SELECT quantity_reserved FROM warehouse.stock_items
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s FOR UPDATE
            """,
            (reservation.tenant_id, reservation.product_id, reservation.location_id),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def _close(
        self, reservation: StockReservation, *, actor_id: str, new_status: str, move_type: str
    ) -> Result[float]:
        """Releases whatever of this one row is still open and closes it."""
        release = expiry_release_quantity(quantity_open=reservation.quantity_open, quantity_reserved_now=self._reserved_now(reservation))
        if release > 0:
            released = self._stock.release_reserved_quantity(
                tenant_id=reservation.tenant_id, product_id=reservation.product_id, location_id=reservation.location_id,
                quantity=release, reference=reservation.reference, actor_id=actor_id, move_type=move_type,
            )
            if isinstance(released, Err):
                return released
        self._connection.execute(
            "UPDATE warehouse.stock_reservations SET quantity_open = 0, status = %s, closed_at = NOW() WHERE id = %s",
            (new_status, reservation.id),
        )
        return Ok(release)

    def release_reservation(self, *, tenant_id: str, actor_id: str, reservation_id: str) -> Result[StockReservation]:
        current = self._get_for_update(tenant_id=tenant_id, reservation_id=reservation_id)
        if isinstance(current, Err):
            return current
        if current.value.status != "active":
            return Err(
                "INVALID_STATE",
                f"reservation is already {current.value.status}",
                f"la réservation est déjà {current.value.status}",
            )
        closed = self._close(current.value, actor_id=actor_id, new_status="released", move_type="reservation_released")
        if isinstance(closed, Err):
            return closed
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="stock_reservation.released",
            entity_type="stock_reservation", entity_id=reservation_id,
            payload={"reference": current.value.reference, "quantity_released": closed.value},
        )
        return Ok(self._reload(reservation_id))

    def update_reservation(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        reservation_id: str,
        expires_at: datetime.datetime | None = None,
        clear_expiry: bool = False,
    ) -> Result[StockReservation]:
        """Edit-in-place: extend, shorten or remove a hold's expiry. Quantity
        isn't editable here -- changing what is held is a reserve or a
        release, both of which move the counter and leave a stock move."""
        current = self._get_for_update(tenant_id=tenant_id, reservation_id=reservation_id)
        if isinstance(current, Err):
            return current
        if clear_expiry:
            new_expiry = None
        elif expires_at is not None:
            validation = validate_reservation_expiry(expires_at=expires_at, now=datetime.datetime.now(datetime.timezone.utc))
            if isinstance(validation, Err):
                return validation
            new_expiry = expires_at
        else:
            new_expiry = current.value.expires_at

        self._connection.execute(
            "UPDATE warehouse.stock_reservations SET expires_at = %s WHERE id = %s AND tenant_id = %s",
            (new_expiry, reservation_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="stock_reservation.updated",
            entity_type="stock_reservation", entity_id=reservation_id,
            payload={"expires_at": new_expiry.isoformat() if new_expiry else None},
        )
        return Ok(self._reload(reservation_id))

    def expire_due_reservations(
        self, *, now: datetime.datetime, tenant_id: str | None = None, limit: int = 500
    ) -> list[StockReservation]:
        """The worker's sweep. Every tenant by default (the worker has no
        session); SKIP LOCKED so two workers never fight over one row, and a
        row someone is releasing by hand right now is simply left for the
        next tick."""
        clauses = ["status = 'active'", "expires_at IS NOT NULL", "expires_at <= %s"]
        params: list[object] = [now]
        if tenant_id is not None:
            clauses.append("tenant_id = %s")
            params.append(tenant_id)
        params.append(limit)
        rows = self._connection.execute(
            f"""
            SELECT {_COLUMNS} FROM warehouse.stock_reservations
            WHERE {' AND '.join(clauses)}
            ORDER BY expires_at
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            params,
        ).fetchall()

        expired: list[StockReservation] = []
        for row in rows:
            reservation = _from_row(row)
            closed = self._close(reservation, actor_id=SYSTEM_ACTOR, new_status="expired", move_type="reservation_expired")
            if isinstance(closed, Err):
                # One bad row must not wedge the sweep; it stays active and is
                # retried next tick, where the failure stays visible in logs.
                continue
            record_audit(
                self._connection, tenant_id=reservation.tenant_id, actor_id=SYSTEM_ACTOR, action="stock_reservation.expired",
                entity_type="stock_reservation", entity_id=reservation.id,
                payload={"reference": reservation.reference, "quantity_released": closed.value},
            )
            publish_event(
                self._connection,
                event_type="warehouse.reservation.expired",
                producer="warehouse",
                tenant_id=reservation.tenant_id,
                correlation_id=reservation.id,
                payload={
                    "reservation_id": reservation.id,
                    "product_id": reservation.product_id,
                    "location_id": reservation.location_id,
                    "reference": reservation.reference,
                    "quantity": closed.value,
                },
            )
            expired.append(self._reload(reservation.id))
        return expired

from __future__ import annotations

import dataclasses
import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.warehouse.domain.lot import (
    Lot,
    LotStock,
    receive_into_lot,
    transition_lot,
    validate_expiry_date,
    validate_lot_number,
    validate_new_lot,
)

_LOT_COLUMNS = "id, tenant_id, product_id, lot_number, status, expiry_date, produced_at, source_type, source_id"


def _row_to_lot(row: tuple) -> Lot:
    lot_id, tenant_id, product_id, lot_number, status, expiry_date, produced_at, source_type, source_id = row
    return Lot(
        id=lot_id,
        tenant_id=tenant_id,
        product_id=product_id,
        lot_number=lot_number,
        status=status,
        expiry_date=expiry_date.isoformat() if expiry_date else None,
        produced_at=produced_at.isoformat() if produced_at else None,
        source_type=source_type,
        source_id=source_id,
    )


class LotService:
    """Public API for lot/serial-tracked stock. Callers commit; this class only executes writes."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_lots(
        self,
        *,
        tenant_id: str,
        product_id: str | None = None,
        source_type: str | None = None,
        without_expiry: bool = False,
    ) -> list[Lot]:
        """`source_type` and `without_expiry` narrow the list to, for instance, the finished-goods
        lots production registered that are still waiting for their DLC."""
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        if source_type is not None:
            clauses.append("source_type = %s")
            params.append(source_type)
        if without_expiry:
            clauses.append("expiry_date IS NULL")
        rows = self._connection.execute(
            f"SELECT {_LOT_COLUMNS} FROM warehouse.lots WHERE {' AND '.join(clauses)} ORDER BY created_at DESC", params
        ).fetchall()
        return [_row_to_lot(row) for row in rows]

    def list_lot_stock(self, *, tenant_id: str, product_id: str | None = None) -> list[dict]:
        clauses = ["ls.tenant_id = %s"]
        params: list[object] = [tenant_id]
        if product_id is not None:
            clauses.append("l.product_id = %s")
            params.append(product_id)
        rows = self._connection.execute(
            f"""
            SELECT l.id, l.product_id, l.lot_number, l.status, l.expiry_date, ls.location_id, ls.quantity_on_hand
            FROM warehouse.lot_stock ls
            JOIN warehouse.lots l ON l.id = ls.lot_id AND l.tenant_id = ls.tenant_id
            WHERE {' AND '.join(clauses)}
            ORDER BY l.product_id, l.lot_number
            """,
            params,
        ).fetchall()
        return [
            {
                "lot_id": lot_id,
                "product_id": product_id,
                "lot_number": lot_number,
                "status": lot_status,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
                "location_id": location_id,
                "quantity_on_hand": float(quantity_on_hand),
            }
            for lot_id, product_id, lot_number, lot_status, expiry_date, location_id, quantity_on_hand in rows
        ]

    def register_lot(
        self,
        *,
        tenant_id: str,
        product_id: str,
        lot_number: str,
        actor_id: str | None = None,
        expiry_date: datetime.date | None = None,
        produced_at: datetime.datetime | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Result[Lot]:
        """Find or create a lot without moving any stock into it.

        Production calls this when a conditionnement report is validated: the DLC
        on that report is a real lot with a real expiry date, and it must exist
        whether or not the finished-product quantity has been posted yet. An
        existing lot is returned as-is rather than overwritten — the first
        validation that names a lot owns its expiry.
        """
        validation = validate_lot_number(lot_number=lot_number)
        if isinstance(validation, Err):
            return validation

        row = self._connection.execute(
            f"SELECT {_LOT_COLUMNS} FROM warehouse.lots WHERE tenant_id = %s AND product_id = %s AND lot_number = %s FOR UPDATE",
            (tenant_id, product_id, lot_number),
        ).fetchone()
        if row is not None:
            return Ok(_row_to_lot(row))

        lot_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO warehouse.lots
                (id, tenant_id, product_id, lot_number, status, expiry_date, produced_at, source_type, source_id)
            VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s)
            """,
            (lot_id, tenant_id, product_id, lot_number, expiry_date, produced_at, source_type, source_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id or "system:event-consumer",
            action="lot.created",
            entity_type="lot",
            entity_id=lot_id,
            payload={
                "product_id": product_id,
                "lot_number": lot_number,
                "expiry_date": expiry_date.isoformat() if expiry_date is not None else None,
                "source_type": source_type,
                "source_id": source_id,
            },
        )
        return Ok(
            Lot(
                id=lot_id,
                tenant_id=tenant_id,
                product_id=product_id,
                lot_number=lot_number,
                status="active",
                expiry_date=expiry_date.isoformat() if expiry_date is not None else None,
                produced_at=produced_at.isoformat() if produced_at is not None else None,
                source_type=source_type,
                source_id=source_id,
            )
        )

    def receive_lot(
        self,
        *,
        tenant_id: str,
        product_id: str,
        location_id: str,
        lot_number: str,
        quantity: float,
        actor_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Result[Lot]:
        """Finds or creates the lot (unique per tenant/product/lot_number) and adds `quantity`
        to its stock at `location_id`. Called from the procurement receipt-confirmed consumer,
        one call per receipt line that carries a lot_number."""
        validation = validate_new_lot(lot_number=lot_number, quantity=quantity)
        if isinstance(validation, Err):
            return validation

        row = self._connection.execute(
            f"SELECT {_LOT_COLUMNS} FROM warehouse.lots WHERE tenant_id = %s AND product_id = %s AND lot_number = %s FOR UPDATE",
            (tenant_id, product_id, lot_number),
        ).fetchone()

        if row is None:
            lot_id = str(ULID())
            self._connection.execute(
                """
                INSERT INTO warehouse.lots (id, tenant_id, product_id, lot_number, status, source_type, source_id)
                VALUES (%s, %s, %s, %s, 'active', %s, %s)
                """,
                (lot_id, tenant_id, product_id, lot_number, source_type, source_id),
            )
            lot = Lot(
                id=lot_id,
                tenant_id=tenant_id,
                product_id=product_id,
                lot_number=lot_number,
                status="active",
                expiry_date=None,
                produced_at=None,
                source_type=source_type,
                source_id=source_id,
            )
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id or "system:event-consumer",
                action="lot.created",
                entity_type="lot",
                entity_id=lot_id,
                payload={"product_id": product_id, "lot_number": lot_number, "source_type": source_type, "source_id": source_id},
            )
        else:
            lot = _row_to_lot(row)

        stock_row = self._connection.execute(
            "SELECT quantity_on_hand FROM warehouse.lot_stock WHERE tenant_id = %s AND lot_id = %s AND location_id = %s FOR UPDATE",
            (tenant_id, lot.id, location_id),
        ).fetchone()
        current_stock = LotStock(
            lot_id=lot.id, location_id=location_id, quantity_on_hand=float(stock_row[0]) if stock_row else 0.0
        )
        stock_result = receive_into_lot(current_stock, quantity)
        if isinstance(stock_result, Err):
            return stock_result

        self._connection.execute(
            """
            INSERT INTO warehouse.lot_stock (tenant_id, lot_id, location_id, quantity_on_hand)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, lot_id, location_id) DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand
            """,
            (tenant_id, lot.id, location_id, stock_result.value.quantity_on_hand),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id or "system:event-consumer",
            action="lot.stock_received",
            entity_type="lot",
            entity_id=lot.id,
            payload={"location_id": location_id, "quantity": quantity},
        )
        return Ok(lot)

    def set_expiry(
        self, *, tenant_id: str, actor_id: str, lot_id: str, expiry_date: datetime.date
    ) -> Result[Lot]:
        """Set, or correct, a lot's DLC.

        Production files a finished-goods lot with its number only; the DLC is entered
        afterwards by whoever owns it (quality). It is an audited change of its own, and
        correcting one already set is allowed -- the trail keeps what it was.
        """
        row = self._connection.execute(
            f"SELECT {_LOT_COLUMNS} FROM warehouse.lots WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lot_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lot {lot_id} not found", f"lot {lot_id} introuvable")
        lot = _row_to_lot(row)
        validation = validate_expiry_date(expiry_date=expiry_date, produced_at=lot.produced_at)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE warehouse.lots SET expiry_date = %s WHERE id = %s AND tenant_id = %s",
            (expiry_date, lot_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lot.expiry_set",
            entity_type="lot",
            entity_id=lot_id,
            payload={"lot_number": lot.lot_number, "from": lot.expiry_date, "to": expiry_date.isoformat()},
        )
        return Ok(dataclasses.replace(lot, expiry_date=expiry_date.isoformat()))

    def transition_lot_status(self, *, tenant_id: str, actor_id: str, lot_id: str, new_status: str) -> Result[Lot]:
        row = self._connection.execute(
            f"SELECT {_LOT_COLUMNS} FROM warehouse.lots WHERE id = %s AND tenant_id = %s FOR UPDATE", (lot_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lot {lot_id} not found", f"lot {lot_id} introuvable")
        lot = _row_to_lot(row)
        result = transition_lot(lot, new_status)
        if isinstance(result, Err):
            return result
        self._connection.execute("UPDATE warehouse.lots SET status = %s WHERE id = %s", (new_status, lot_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lot.status_changed",
            entity_type="lot",
            entity_id=lot_id,
            payload={"from_status": lot.status, "to_status": new_status},
        )
        return result

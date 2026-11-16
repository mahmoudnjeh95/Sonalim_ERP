from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.sequences import next_sequence_value
from core.events.outbox import publish_event
from modules.warehouse.api.service import StockService
from modules.warehouse.domain.fulfillment import (
    PICKABLE_STATUSES,
    PickList,
    PickListLine,
    Shipment,
    aggregate_order_lines,
    check_picking_complete,
    transition_pick_list,
    validate_packing,
    validate_picked_quantity,
)

SYSTEM_ACTOR = "system:event-consumer"

_PICK_LIST_COLUMNS = (
    "id, tenant_id, number, source_type, source_id, partner_id, location_id, reservation_reference, status, "
    "created_at, picked_at, cancelled_at"
)
_PICK_LINE_COLUMNS = "id, tenant_id, pick_list_id, product_id, quantity_requested, quantity_picked, picked_by, picked_at"
_SHIPMENT_COLUMNS = (
    "id, tenant_id, number, pick_list_id, status, package_count, total_weight_kg, carrier, tracking_reference, "
    "packed_by, packed_at, shipped_by, shipped_at"
)


def _pick_list_from_row(row) -> PickList:
    return PickList(
        id=row[0], tenant_id=row[1], number=row[2], source_type=row[3], source_id=row[4], partner_id=row[5],
        location_id=row[6], reservation_reference=row[7], status=row[8], created_at=row[9], picked_at=row[10],
        cancelled_at=row[11],
    )


def _pick_line_from_row(row) -> PickListLine:
    return PickListLine(
        id=row[0], tenant_id=row[1], pick_list_id=row[2], product_id=row[3], quantity_requested=float(row[4]),
        quantity_picked=float(row[5]) if row[5] is not None else None, picked_by=row[6], picked_at=row[7],
    )


def _shipment_from_row(row) -> Shipment:
    return Shipment(
        id=row[0], tenant_id=row[1], number=row[2], pick_list_id=row[3], status=row[4], package_count=row[5],
        total_weight_kg=float(row[6]) if row[6] is not None else None, carrier=row[7], tracking_reference=row[8],
        packed_by=row[9], packed_at=row[10], shipped_by=row[11], shipped_at=row[12],
    )


def _not_found(kind_en: str, kind_fr: str, entity_id: str) -> Err:
    return Err("NOT_FOUND", f"{kind_en} {entity_id} not found", f"{kind_fr} {entity_id} introuvable")


class FulfillmentService:
    """Outbound flow after a sales order is confirmed: pick -> pack -> ship.

    Sales has already reserved the stock by the time a pick list exists, so
    nothing here reserves; shipping is the single point where the reservation
    is released and the picked quantity actually leaves the books."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    # --- Pick lists -------------------------------------------------------------------

    def create_pick_list_for_order(
        self,
        *,
        tenant_id: str,
        order_id: str,
        partner_id: str | None,
        location_id: str,
        lines: list[dict],
        reservation_reference: str,
        actor_id: str = SYSTEM_ACTOR,
    ) -> Result[PickList]:
        """Idempotent on the order: a redelivered sales.order.confirmed returns
        the pick list the first delivery created instead of a second one."""
        existing = self._connection.execute(
            f"SELECT {_PICK_LIST_COLUMNS} FROM warehouse.pick_lists WHERE tenant_id = %s AND source_type = 'sales_order' AND source_id = %s",
            (tenant_id, order_id),
        ).fetchone()
        if existing is not None:
            return Ok(_pick_list_from_row(existing))

        # The reservation can be released by hand before the worker gets here, and a voucher can then
        # issue the order. Picking it afterwards would ship the goods again, and the release at ship
        # would eat into whatever other orders hold at this location.
        issued = self._connection.execute(
            "SELECT number FROM warehouse.vouchers WHERE tenant_id = %s AND type = 'issue' AND status = 'posted' "
            "AND ref_type = 'sales_order' AND ref_id = %s LIMIT 1",
            (tenant_id, order_id),
        ).fetchone()
        if issued is not None:
            return Err(
                "ORDER_ALREADY_ISSUED",
                f"order {order_id} already left the warehouse on voucher {issued[0]}",
                f"la commande {order_id} est déjà sortie de l'entrepôt par le bon {issued[0]}",
            )

        totals = aggregate_order_lines(lines)
        if not totals:
            return Err("EMPTY_ORDER", f"order {order_id} has nothing to pick", f"la commande {order_id} n'a rien à prélever")

        pick_list_id = str(ULID())
        number = next_sequence_value(self._connection, tenant_id=tenant_id, name="warehouse.pick_list", prefix="PK-")
        self._connection.execute(
            """
            INSERT INTO warehouse.pick_lists
                (id, tenant_id, number, source_type, source_id, partner_id, location_id, reservation_reference)
            VALUES (%s, %s, %s, 'sales_order', %s, %s, %s, %s)
            """,
            (pick_list_id, tenant_id, number, order_id, partner_id, location_id, reservation_reference),
        )
        for product_id, quantity in totals.items():
            self._connection.execute(
                """
                INSERT INTO warehouse.pick_list_lines (id, tenant_id, pick_list_id, product_id, quantity_requested)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, pick_list_id, product_id, quantity),
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="pick_list.created",
            entity_type="pick_list", entity_id=pick_list_id,
            payload={"number": number, "source_type": "sales_order", "source_id": order_id, "line_count": len(totals)},
        )
        return self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id)

    def list_pick_lists(self, *, tenant_id: str, status: str | None = None) -> list[PickList]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_PICK_LIST_COLUMNS} FROM warehouse.pick_lists WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC",
            params,
        ).fetchall()
        return [_pick_list_from_row(row) for row in rows]

    def get_pick_list(self, *, tenant_id: str, pick_list_id: str, for_update: bool = False) -> Result[PickList]:
        lock = " FOR UPDATE" if for_update else ""
        row = self._connection.execute(
            f"SELECT {_PICK_LIST_COLUMNS} FROM warehouse.pick_lists WHERE id = %s AND tenant_id = %s{lock}",
            (pick_list_id, tenant_id),
        ).fetchone()
        if row is None:
            return _not_found("pick list", "liste de prélèvement", pick_list_id)
        return Ok(_pick_list_from_row(row))

    def list_pick_lines(self, *, tenant_id: str, pick_list_id: str) -> list[PickListLine]:
        rows = self._connection.execute(
            f"SELECT {_PICK_LINE_COLUMNS} FROM warehouse.pick_list_lines WHERE tenant_id = %s AND pick_list_id = %s ORDER BY product_id",
            (tenant_id, pick_list_id),
        ).fetchall()
        return [_pick_line_from_row(row) for row in rows]

    def submit_pick(
        self, *, tenant_id: str, actor_id: str, pick_list_id: str, line_id: str, quantity_picked: float
    ) -> Result[PickListLine]:
        pick_list = self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id, for_update=True)
        if isinstance(pick_list, Err):
            return pick_list
        if pick_list.value.status not in PICKABLE_STATUSES:
            return Err(
                "INVALID_STATE",
                f"pick list is {pick_list.value.status}, picks can no longer be recorded",
                f"la liste de prélèvement est {pick_list.value.status}, les prélèvements ne peuvent plus être saisis",
            )

        row = self._connection.execute(
            f"SELECT {_PICK_LINE_COLUMNS} FROM warehouse.pick_list_lines WHERE id = %s AND tenant_id = %s AND pick_list_id = %s",
            (line_id, tenant_id, pick_list_id),
        ).fetchone()
        if row is None:
            return _not_found("pick list line", "ligne de prélèvement", line_id)
        line = _pick_line_from_row(row)

        validation = validate_picked_quantity(quantity_picked=quantity_picked, quantity_requested=line.quantity_requested)
        if isinstance(validation, Err):
            return validation
        if quantity_picked > 0:
            uom_check = self._stock._validate_quantity(tenant_id=tenant_id, product_id=line.product_id, quantity=quantity_picked)
            if isinstance(uom_check, Err):
                return uom_check

        self._connection.execute(
            "UPDATE warehouse.pick_list_lines SET quantity_picked = %s, picked_by = %s, picked_at = NOW() WHERE id = %s",
            (quantity_picked, actor_id, line_id),
        )
        if pick_list.value.status == "open":
            self._connection.execute("UPDATE warehouse.pick_lists SET status = 'picking' WHERE id = %s", (pick_list_id,))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="pick_list_line.picked",
            entity_type="pick_list", entity_id=pick_list_id,
            payload={"line_id": line_id, "product_id": line.product_id, "quantity_requested": line.quantity_requested,
                     "quantity_picked": quantity_picked},
        )
        updated = self._connection.execute(
            f"SELECT {_PICK_LINE_COLUMNS} FROM warehouse.pick_list_lines WHERE id = %s", (line_id,)
        ).fetchone()
        return Ok(_pick_line_from_row(updated))

    def complete_picking(self, *, tenant_id: str, actor_id: str, pick_list_id: str) -> Result[PickList]:
        pick_list = self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id, for_update=True)
        if isinstance(pick_list, Err):
            return pick_list
        transition = transition_pick_list(pick_list.value.status, "picked")
        if isinstance(transition, Err):
            return transition
        complete = check_picking_complete(self.list_pick_lines(tenant_id=tenant_id, pick_list_id=pick_list_id))
        if isinstance(complete, Err):
            return complete

        self._connection.execute(
            "UPDATE warehouse.pick_lists SET status = 'picked', picked_at = NOW() WHERE id = %s", (pick_list_id,)
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="pick_list.status_changed",
            entity_type="pick_list", entity_id=pick_list_id,
            payload={"from_status": pick_list.value.status, "to_status": "picked"},
        )
        return self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id)

    def cancel_pick_list(self, *, tenant_id: str, actor_id: str, pick_list_id: str, correlation_id: str) -> Result[PickList]:
        """Cancelling gives the reserved stock back: the pick list is the
        warehouse's hold on the order's reservation, and a cancelled one has
        nothing left to hold it for."""
        pick_list = self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id, for_update=True)
        if isinstance(pick_list, Err):
            return pick_list
        transition = transition_pick_list(pick_list.value.status, "cancelled")
        if isinstance(transition, Err):
            return transition
        if self._shipment_row_for_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id) is not None:
            return Err(
                "ALREADY_PACKED",
                "this pick list is already packed into a shipment",
                "cette liste de prélèvement est déjà emballée dans une expédition",
            )

        for line in self.list_pick_lines(tenant_id=tenant_id, pick_list_id=pick_list_id):
            released = self._stock.release_what_is_still_held(
                tenant_id=tenant_id,
                product_id=line.product_id,
                location_id=pick_list.value.location_id,
                quantity=line.quantity_requested,
                reference=pick_list.value.reservation_reference,
                actor_id=actor_id,
            )
            if isinstance(released, Err):
                return released

        self._connection.execute(
            "UPDATE warehouse.pick_lists SET status = 'cancelled', cancelled_at = NOW() WHERE id = %s", (pick_list_id,)
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="pick_list.status_changed",
            entity_type="pick_list", entity_id=pick_list_id,
            payload={"from_status": pick_list.value.status, "to_status": "cancelled"},
        )
        publish_event(
            self._connection,
            event_type="warehouse.pick_list.cancelled",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "pick_list_id": pick_list_id,
                "source_type": pick_list.value.source_type,
                "source_id": pick_list.value.source_id,
            },
        )
        return self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id)

    # --- Shipments --------------------------------------------------------------------

    def _shipment_row_for_pick_list(self, *, tenant_id: str, pick_list_id: str):
        return self._connection.execute(
            f"SELECT {_SHIPMENT_COLUMNS} FROM warehouse.shipments WHERE tenant_id = %s AND pick_list_id = %s",
            (tenant_id, pick_list_id),
        ).fetchone()

    def get_shipment(self, *, tenant_id: str, shipment_id: str, for_update: bool = False) -> Result[Shipment]:
        lock = " FOR UPDATE" if for_update else ""
        row = self._connection.execute(
            f"SELECT {_SHIPMENT_COLUMNS} FROM warehouse.shipments WHERE id = %s AND tenant_id = %s{lock}",
            (shipment_id, tenant_id),
        ).fetchone()
        if row is None:
            return _not_found("shipment", "expédition", shipment_id)
        return Ok(_shipment_from_row(row))

    def get_shipment_for_pick_list(self, *, tenant_id: str, pick_list_id: str) -> Shipment | None:
        row = self._shipment_row_for_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id)
        return _shipment_from_row(row) if row else None

    def list_shipments(self, *, tenant_id: str, status: str | None = None) -> list[Shipment]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_SHIPMENT_COLUMNS} FROM warehouse.shipments WHERE {' AND '.join(clauses)} ORDER BY packed_at DESC, id DESC",
            params,
        ).fetchall()
        return [_shipment_from_row(row) for row in rows]

    def pack(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        pick_list_id: str,
        package_count: int,
        total_weight_kg: float | None = None,
        carrier: str | None = None,
        tracking_reference: str | None = None,
    ) -> Result[Shipment]:
        pick_list = self.get_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id, for_update=True)
        if isinstance(pick_list, Err):
            return pick_list
        if pick_list.value.status != "picked":
            return Err(
                "INVALID_STATE",
                f"only a picked pick list can be packed (this one is {pick_list.value.status})",
                f"seule une liste prélevée peut être emballée (celle-ci est {pick_list.value.status})",
            )
        if self._shipment_row_for_pick_list(tenant_id=tenant_id, pick_list_id=pick_list_id) is not None:
            return Err(
                "ALREADY_PACKED",
                "this pick list is already packed into a shipment",
                "cette liste de prélèvement est déjà emballée dans une expédition",
            )
        validation = validate_packing(package_count=package_count, total_weight_kg=total_weight_kg)
        if isinstance(validation, Err):
            return validation

        shipment_id = str(ULID())
        number = next_sequence_value(self._connection, tenant_id=tenant_id, name="warehouse.shipment", prefix="SH-")
        self._connection.execute(
            """
            INSERT INTO warehouse.shipments
                (id, tenant_id, number, pick_list_id, package_count, total_weight_kg, carrier, tracking_reference, packed_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (shipment_id, tenant_id, number, pick_list_id, package_count, total_weight_kg, carrier, tracking_reference, actor_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="shipment.packed",
            entity_type="shipment", entity_id=shipment_id,
            payload={"number": number, "pick_list_id": pick_list_id, "package_count": package_count,
                     "total_weight_kg": total_weight_kg, "carrier": carrier},
        )
        return self.get_shipment(tenant_id=tenant_id, shipment_id=shipment_id)

    def admin_update_shipment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shipment_id: str,
        package_count: int | None = None,
        total_weight_kg: float | None = None,
        carrier: str | None = None,
        tracking_reference: str | None = None,
    ) -> Result[Shipment]:
        current = self.get_shipment(tenant_id=tenant_id, shipment_id=shipment_id, for_update=True)
        if isinstance(current, Err):
            return current
        updated_package_count = package_count if package_count is not None else current.value.package_count
        updated_weight = total_weight_kg if total_weight_kg is not None else current.value.total_weight_kg
        updated_carrier = carrier if carrier is not None else current.value.carrier
        updated_tracking = tracking_reference if tracking_reference is not None else current.value.tracking_reference
        validation = validate_packing(package_count=updated_package_count, total_weight_kg=updated_weight)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            UPDATE warehouse.shipments
            SET package_count = %s, total_weight_kg = %s, carrier = %s, tracking_reference = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated_package_count, updated_weight, updated_carrier, updated_tracking, shipment_id, tenant_id),
        )
        changes = {
            key: value
            for key, value in {
                "package_count": package_count,
                "total_weight_kg": total_weight_kg,
                "carrier": carrier,
                "tracking_reference": tracking_reference,
            }.items()
            if value is not None
        }
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="shipment.updated",
            entity_type="shipment", entity_id=shipment_id, payload=changes,
        )
        return self.get_shipment(tenant_id=tenant_id, shipment_id=shipment_id)

    def ship(self, *, tenant_id: str, actor_id: str, shipment_id: str, correlation_id: str) -> Result[Shipment]:
        """The moment stock actually leaves: for every line, the whole
        reservation is released (a short pick's remainder goes back to
        available, it isn't left dangling) and what was really picked is
        issued, all in the caller's single transaction."""
        shipment = self.get_shipment(tenant_id=tenant_id, shipment_id=shipment_id, for_update=True)
        if isinstance(shipment, Err):
            return shipment
        if shipment.value.status != "packed":
            return Err(
                "INVALID_STATE",
                f"shipment is already {shipment.value.status}",
                f"l'expédition est déjà {shipment.value.status}",
            )
        pick_list = self.get_pick_list(tenant_id=tenant_id, pick_list_id=shipment.value.pick_list_id, for_update=True)
        if isinstance(pick_list, Err):
            return pick_list
        transition = transition_pick_list(pick_list.value.status, "shipped")
        if isinstance(transition, Err):
            return transition

        lines = self.list_pick_lines(tenant_id=tenant_id, pick_list_id=pick_list.value.id)
        shipment_reference = f"shipment:{shipment_id}"
        for line in lines:
            released = self._stock.release_what_is_still_held(
                tenant_id=tenant_id,
                product_id=line.product_id,
                location_id=pick_list.value.location_id,
                quantity=line.quantity_requested,
                reference=pick_list.value.reservation_reference,
                actor_id=actor_id,
            )
            if isinstance(released, Err):
                return released
            picked = line.quantity_picked or 0
            if picked > 0:
                issued = self._stock.issue_stock(
                    tenant_id=tenant_id,
                    product_id=line.product_id,
                    location_id=pick_list.value.location_id,
                    quantity=picked,
                    reference=shipment_reference,
                    actor_id=actor_id,
                    move_type="shipment",
                )
                if isinstance(issued, Err):
                    return issued

        self._connection.execute(
            "UPDATE warehouse.shipments SET status = 'shipped', shipped_by = %s, shipped_at = NOW() WHERE id = %s",
            (actor_id, shipment_id),
        )
        self._connection.execute("UPDATE warehouse.pick_lists SET status = 'shipped' WHERE id = %s", (pick_list.value.id,))
        shipped_lines = [
            {"product_id": line.product_id, "quantity_requested": line.quantity_requested, "quantity_shipped": line.quantity_picked or 0}
            for line in lines
        ]
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="shipment.shipped",
            entity_type="shipment", entity_id=shipment_id,
            payload={"pick_list_id": pick_list.value.id, "lines": shipped_lines},
        )
        publish_event(
            self._connection,
            event_type="warehouse.shipment.shipped",
            event_version="1.1",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "shipment_id": shipment_id,
                "number": shipment.value.number,
                "pick_list_id": pick_list.value.id,
                "source_type": pick_list.value.source_type,
                "source_id": pick_list.value.source_id,
                "location_id": pick_list.value.location_id,
                "lines": shipped_lines,
            },
        )
        return self.get_shipment(tenant_id=tenant_id, shipment_id=shipment_id)

"""Moving packed goods from the line store to the final store.

Packed goods are posted into the line store, next to the production, when a shift is
validated. They stay there until someone with the right to says they may go: the release
moves each product to its own default storage location as an ordinary warehouse transfer.

All or nothing: one line that cannot move stops the whole release, and nothing is posted.
Lots are registered records here, with no per-store lot stock, so only product stock moves.

What is offered comes from the packing reports of one day, not from the store's stock level:
each finished product packed that day, how much of it, how much has already been released
(remembered in `stock_release_lines`) and how much the line store still holds. The list opens
on yesterday, or on today once nothing from yesterday is left unreleased. Quantities are in each
product's own unit; cartons are only the screen's way of reading them.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.domain.packaging_estimate import finished_quantity_from_count
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService

# A quantity typed with decimals may differ from the stored one in the last binary digit.
_EPSILON = 1e-9


class _Abort(Exception):
    """Carries an `Err` out of the savepoint so every transfer already posted is undone."""

    def __init__(self, err: Err) -> None:
        super().__init__(err.message)
        self.err = err


class StockReleaseService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._core = CoreService(connection)
        self._stock = StockService(connection)
        self._classifications = ProductClassificationService(connection)

    def _line_store(self, tenant_id: str) -> str | None:
        return DashboardSettingsService(self._connection).line_store_id(tenant_id=tenant_id)

    def _packed_on(self, tenant_id: str, day: datetime.date) -> dict[str, float]:
        """Finished product per product that validated packing reports of `day` brought in.

        The same count validation posted to stock (`finished_quantity_from_count`, with the
        packets-per-carton frozen on each report), so the list and the store cannot disagree.
        """
        rows = self._connection.execute(
            """
            SELECT COALESCE(c.product_id, w.product_id), c.carton_quantity, c.waste_carton_quantity, c.packets_counted, c.snapshot_packets_per_carton
            FROM production.conditionnement_reports c
            JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.status = 'validated' AND r.report_date = %s
            """,
            (tenant_id, day),
        ).fetchall()
        packed: dict[str, float] = {}
        for product_id, cartons, waste, counted, per_carton in rows:
            packed[product_id] = packed.get(product_id, 0.0) + finished_quantity_from_count(
                packets_per_carton=float(per_carton) if per_carton else None,
                carton_quantity=float(cartons),
                packets_counted=float(counted),
                waste_carton_quantity=float(waste),
            )
        return {product_id: quantity for product_id, quantity in packed.items() if quantity > 0}

    def _released_on(self, tenant_id: str, day: datetime.date) -> dict[str, float]:
        rows = self._connection.execute(
            "SELECT product_id, SUM(quantity) FROM production.stock_release_lines WHERE tenant_id = %s AND packed_on = %s GROUP BY product_id",
            (tenant_id, day),
        ).fetchall()
        return {product_id: float(total) for product_id, total in rows}

    def get_release_list(self, *, tenant_id: str, day: datetime.date | None = None, today: datetime.date | None = None) -> dict:
        """The products packed on `day`, what has left the line store and what still can.

        Without a `day` it opens on yesterday while anything packed then is still unreleased,
        and on today otherwise (a quiet Sunday, or everything already released). A product the
        line store cannot cover is still listed, greyed out, so it is never silently missing.
        """
        today = today or datetime.date.today()
        if day is not None:
            return self._list_for(tenant_id, day, today)
        yesterday = self._list_for(tenant_id, today - datetime.timedelta(days=1), today)
        if any(item["remaining"] > 0 for item in yesterday["items"]):
            return yesterday
        return self._list_for(tenant_id, today, today)

    def _list_for(self, tenant_id: str, day: datetime.date, today: datetime.date) -> dict:
        header = {"day": day.isoformat(), "today": today.isoformat()}
        line_id = self._line_store(tenant_id)
        if line_id is None:
            return {**header, "line_store": None, "items": []}
        names = {location.id: location.name for location in LocationService(self._connection).list_locations(tenant_id=tenant_id)}
        on_hand = {level.product_id: level.quantity_on_hand for level in self._stock.list_stock_items(tenant_id, location_id=line_id)}
        released = self._released_on(tenant_id, day)
        items = []
        for product_id, packed in self._packed_on(tenant_id, day).items():
            product = self._core.get_product(tenant_id, product_id)
            if product is None:
                continue
            remaining = max(packed - released.get(product_id, 0.0), 0.0)
            destination = product.default_location_id
            per_carton = product.packets_per_carton
            classification = self._classifications.get_classification(tenant_id, product_id)
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "uom_id": product.uom_id,
                    # Cartons are only a way of reading pieces: None means a sac, counted one by one.
                    "packets_per_carton": per_carton if per_carton and per_carton > 0 else None,
                    "packaging_format": classification.packaging_format if classification else None,
                    "packed": packed,
                    "released": released.get(product_id, 0.0),
                    "remaining": remaining,
                    # What the line store actually holds caps it: goods validated before a line store
                    # was set went straight to the product's own store and cannot be moved from here.
                    "releasable": min(remaining, max(on_hand.get(product_id, 0.0), 0.0)),
                    "destination": {"id": destination, "name": names.get(destination)} if destination else None,
                }
            )
        items.sort(key=lambda item: item["product_name"].lower())
        return {**header, "line_store": {"id": line_id, "name": names.get(line_id)}, "items": items}

    def release(self, *, tenant_id: str, actor_id: str, day: datetime.date, items: list[dict]) -> Result[dict]:
        line_id = self._line_store(tenant_id)
        if line_id is None:
            return Err("NO_LINE_STORE", "no line store is set in the production settings, so there is nothing to release")
        if not items:
            return Err("NOTHING_TO_RELEASE", "choose at least one product to release")

        on_hand = {level.product_id: level.quantity_on_hand for level in self._stock.list_stock_items(tenant_id, location_id=line_id)}
        packed = self._packed_on(tenant_id, day)
        released = self._released_on(tenant_id, day)
        plan: list[tuple[str, str, float, str]] = []  # (product id, name, quantity, destination)
        seen: set[str] = set()
        for item in items:
            product_id = str(item.get("product_id") or "")
            if product_id in seen:
                return Err("DUPLICATE_ENTRY", f"product {product_id} is listed twice")
            seen.add(product_id)
            product = self._core.get_product(tenant_id, product_id)
            if product is None:
                return Err("NOT_FOUND", f"product {product_id} not found")
            quantity = float(item.get("quantity") or 0)
            if quantity <= 0:
                return Err("INVALID_QUANTITY", f"{product.name}: the quantity to release must be more than zero")
            if quantity > on_hand.get(product_id, 0.0) + _EPSILON:
                return Err(
                    "INSUFFICIENT_STOCK",
                    f"{product.name}: only {on_hand.get(product_id, 0.0):g} is in the line store, {quantity:g} asked",
                )
            left = packed.get(product_id, 0.0) - released.get(product_id, 0.0)
            if quantity > left + _EPSILON:
                return Err(
                    "EXCEEDS_PACKED",
                    f"{product.name}: only {max(left, 0.0):g} of what was packed on {day.isoformat()} is left to release, {quantity:g} asked",
                )
            if not product.default_location_id:
                return Err("NO_DEFAULT_LOCATION", f"{product.name} has no default storage location to be released into")
            if product.default_location_id == line_id:
                return Err("INVALID_TRANSFER", f"{product.name}: its default storage location is the line store itself")
            plan.append((product_id, product.name, quantity, product.default_location_id))

        reference = f"stock_release:{datetime.date.today().isoformat()}"
        correlation_id = str(ULID())
        try:
            with self._connection.transaction():
                for product_id, name, quantity, destination in plan:
                    moved = self._stock.transfer_stock(
                        tenant_id=tenant_id,
                        product_id=product_id,
                        from_location_id=line_id,
                        to_location_id=destination,
                        quantity=quantity,
                        correlation_id=correlation_id,
                        reference=reference,
                        actor_id=actor_id,
                    )
                    if isinstance(moved, Err):
                        raise _Abort(Err(moved.code, f"{name}: {moved.message}"))
                    self._connection.execute(
                        "INSERT INTO production.stock_release_lines "
                        "(id, tenant_id, release_id, packed_on, product_id, quantity, from_location_id, to_location_id, released_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (str(ULID()), tenant_id, correlation_id, day, product_id, quantity, line_id, destination, actor_id),
                    )
        except _Abort as abort:
            return abort.err

        moved_lines = [{"product_id": p, "quantity": q, "to_location_id": d} for p, _n, q, d in plan]
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="stock.released",
            entity_type="stock_release",
            entity_id=correlation_id,
            payload={"from_location_id": line_id, "packed_on": day.isoformat(), "released": moved_lines},
        )
        return Ok({"reference": reference, "day": day.isoformat(), "released": moved_lines})

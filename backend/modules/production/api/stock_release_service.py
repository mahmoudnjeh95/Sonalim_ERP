"""Moving packed goods from the line store to the final store.

Packed goods are posted into the line store, next to the production, when a shift is
validated. They stay there until someone with the right to says they may go: the release
moves each product to its own default storage location as an ordinary warehouse transfer.

All or nothing: one line that cannot move stops the whole release, and nothing is posted.
Lots are registered records here, with no per-store lot stock, so only product stock moves.

What is offered comes from the packing reports of one day, not from the store's stock level:
each finished product packed that day, how much of it, how much has already been released
(remembered in `stock_release_lines`) and how much the line store still holds. Only what quality
control has validated as conforming may go: packed goods still waiting on their shift's QC report,
or rejected by it, are shown as pending and refused by the release itself. The list opens
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

# How far back the backlog looks for goods packed but never released. Older than this, an
# unreleased balance is taken as a deliberate hold (quarantine, a write-off pending) rather
# than something forgotten, and stays out of the supervisor's way.
_BACKLOG_LOOKBACK_DAYS = 7


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
            SELECT COALESCE(p.product_id, w.product_id), p.carton_quantity, p.waste_carton_quantity, p.packets_counted, p.snapshot_packets_per_carton
            FROM production.shift_packing_rows p
            JOIN production.shift_reports s ON s.id = p.shift_report_id AND s.tenant_id = p.tenant_id
            JOIN production.work_orders w ON w.id = p.of_id AND w.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND s.status = 'validated' AND s.report_date = %s
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

    def _qc_validated_on(self, tenant_id: str, day: datetime.date) -> dict[str, float]:
        """Conforming pieces per product that validated QC reports of `day` cleared -- asked of qc."""
        from modules.qc.api.quality_service import QualityReportService

        return QualityReportService(self._connection).get_validated_conforming(tenant_id=tenant_id, day=day)

    def get_release_list(self, *, tenant_id: str, day: datetime.date | None = None, today: datetime.date | None = None) -> dict:
        """The products packed on `day`, what has left the line store and what still can.

        Without a `day` it opens on yesterday while anything packed then is still unreleased,
        and on today otherwise (a quiet Sunday, or everything already released). A product the
        line store cannot cover is still listed, greyed out, so it is never silently missing.

        Alongside `day`'s own `items`, `backlog` lists what earlier days (within the lookback
        window, excluding `day` itself) still have unreleased, so a supervisor who has moved
        on to a later day is not left to hunt for what an older one left behind.
        """
        today = today or datetime.date.today()
        if day is not None:
            result = self._list_for(tenant_id, day, today)
        else:
            yesterday = self._list_for(tenant_id, today - datetime.timedelta(days=1), today)
            result = yesterday if any(item["remaining"] > 0 for item in yesterday["items"]) else self._list_for(tenant_id, today, today)
        result["backlog"] = self._backlog(tenant_id, exclude_day=datetime.date.fromisoformat(result["day"]), today=today)
        return result

    def _backlog(self, tenant_id: str, *, exclude_day: datetime.date, today: datetime.date) -> list[dict]:
        """Earlier days, within the lookback window, that still have something unreleased."""
        backlog = []
        for offset in range(1, _BACKLOG_LOOKBACK_DAYS + 1):
            day = today - datetime.timedelta(days=offset)
            if day == exclude_day:
                continue
            listed = self._list_for(tenant_id, day, today)
            items = [item for item in listed["items"] if item["remaining"] > 0]
            if items:
                backlog.append({"day": listed["day"], "items": items})
        backlog.sort(key=lambda entry: entry["day"])
        return backlog

    def _list_for(self, tenant_id: str, day: datetime.date, today: datetime.date) -> dict:
        header = {"day": day.isoformat(), "today": today.isoformat()}
        line_id = self._line_store(tenant_id)
        if line_id is None:
            return {**header, "line_store": None, "items": []}
        names = {location.id: location.name for location in LocationService(self._connection).list_locations(tenant_id=tenant_id)}
        on_hand = {level.product_id: level.quantity_on_hand for level in self._stock.list_stock_items(tenant_id, location_id=line_id)}
        released = self._released_on(tenant_id, day)
        qc_validated = self._qc_validated_on(tenant_id, day)
        items = []
        for product_id, packed in self._packed_on(tenant_id, day).items():
            product = self._core.get_product(tenant_id, product_id)
            if product is None:
                continue
            remaining = max(packed - released.get(product_id, 0.0), 0.0)
            destination = product.default_location_id
            per_carton = product.packets_per_carton
            classification = self._classifications.get_classification(tenant_id, product_id)
            qc_conforming = qc_validated.get(product_id, 0.0)
            # What QC has cleared and is not released yet: only that may leave the line store.
            qc_remaining = max(qc_conforming - released.get(product_id, 0.0), 0.0)
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
                    # QC caps it too: packed goods QC has not validated as conforming stay put.
                    "releasable": min(remaining, max(on_hand.get(product_id, 0.0), 0.0), qc_remaining),
                    # Packed but not cleared: its shift's QC report is not validated yet, or QC rejected it.
                    "pending_qc": max(packed - qc_conforming, 0.0),
                    "destination": {"id": destination, "name": names.get(destination)} if destination else None,
                }
            )
        items.sort(key=lambda item: item["product_name"].lower())
        return {**header, "line_store": {"id": line_id, "name": names.get(line_id)}, "items": items}

    def release(self, *, tenant_id: str, actor_id: str, day: datetime.date, items: list[dict]) -> Result[dict]:
        """Releases `items`, each against the day it was packed on.

        `day` is the day the dialog had open; an item with no `packed_on` of its own (the
        common case) is taken as packed on `day`. An item naming an earlier `packed_on` is a
        backlog row the supervisor is clearing alongside `day`'s own goods.
        """
        line_id = self._line_store(tenant_id)
        if line_id is None:
            return Err(
                "NO_LINE_STORE",
                "no line store is set in the production settings, so there is nothing to release",
                "aucun stock ligne n'est défini dans les paramètres de production, il n'y a donc rien à libérer",
            )
        if not items:
            return Err("NOTHING_TO_RELEASE", "choose at least one product to release", "choisissez au moins un produit à libérer")

        on_hand = {level.product_id: level.quantity_on_hand for level in self._stock.list_stock_items(tenant_id, location_id=line_id)}
        packed_cache: dict[datetime.date, dict[str, float]] = {}
        released_cache: dict[datetime.date, dict[str, float]] = {}
        qc_cache: dict[datetime.date, dict[str, float]] = {}

        def _for_day(cache: dict[datetime.date, dict[str, float]], loader, packed_on: datetime.date) -> dict[str, float]:
            if packed_on not in cache:
                cache[packed_on] = loader(tenant_id, packed_on)
            return cache[packed_on]

        plan: list[tuple[str, str, float, str, datetime.date]] = []  # (product id, name, quantity, destination, packed_on)
        seen: set[tuple[str, datetime.date]] = set()
        for item in items:
            product_id = str(item.get("product_id") or "")
            packed_on = item.get("packed_on") or day
            if isinstance(packed_on, str):
                packed_on = datetime.date.fromisoformat(packed_on)
            key = (product_id, packed_on)
            if key in seen:
                return Err(
                    "DUPLICATE_ENTRY",
                    f"product {product_id} is listed twice for {packed_on.isoformat()}",
                    f"le produit {product_id} est listé deux fois pour {packed_on.isoformat()}",
                )
            seen.add(key)
            product = self._core.get_product(tenant_id, product_id)
            if product is None:
                return Err("NOT_FOUND", f"product {product_id} not found", f"produit {product_id} introuvable")
            quantity = float(item.get("quantity") or 0)
            if quantity <= 0:
                return Err(
                    "INVALID_QUANTITY",
                    f"{product.name}: the quantity to release must be more than zero",
                    f"{product.name} : la quantité à libérer doit être supérieure à zéro",
                )
            if quantity > on_hand.get(product_id, 0.0) + _EPSILON:
                return Err(
                    "INSUFFICIENT_STOCK",
                    f"{product.name}: only {on_hand.get(product_id, 0.0):g} is in the line store, {quantity:g} asked",
                    f"{product.name} : seulement {on_hand.get(product_id, 0.0):g} est dans le stock ligne, {quantity:g} demandé",
                )
            packed = _for_day(packed_cache, self._packed_on, packed_on)
            released = _for_day(released_cache, self._released_on, packed_on)
            qc_validated = _for_day(qc_cache, self._qc_validated_on, packed_on)
            left = packed.get(product_id, 0.0) - released.get(product_id, 0.0)
            if quantity > left + _EPSILON:
                return Err(
                    "EXCEEDS_PACKED",
                    f"{product.name}: only {max(left, 0.0):g} of what was packed on {packed_on.isoformat()} is left to release, {quantity:g} asked",
                    f"{product.name} : seulement {max(left, 0.0):g} de ce qui a été conditionné le {packed_on.isoformat()} reste à libérer, {quantity:g} demandé",
                )
            # Checked here too, not only in the list: a stale or forged request must not move
            # goods QC has not validated as conforming, whatever the line store holds.
            qc_left = qc_validated.get(product_id, 0.0) - released.get(product_id, 0.0)
            if quantity > qc_left + _EPSILON:
                return Err(
                    "EXCEEDS_QC_VALIDATED",
                    f"{product.name}: only {max(qc_left, 0.0):g} has been validated as conforming by quality control, {quantity:g} asked",
                    f"{product.name} : seulement {max(qc_left, 0.0):g} a été validé conforme par le contrôle qualité, {quantity:g} demandé",
                )
            if not product.default_location_id:
                return Err(
                    "NO_DEFAULT_LOCATION",
                    f"{product.name} has no default storage location to be released into",
                    f"{product.name} n'a pas d'emplacement de stockage par défaut vers lequel être libéré",
                )
            if product.default_location_id == line_id:
                return Err(
                    "INVALID_TRANSFER",
                    f"{product.name}: its default storage location is the line store itself",
                    f"{product.name} : son emplacement de stockage par défaut est le stock ligne lui-même",
                )
            # Two lines for the same product on different days would draw from the same on-hand
            # pool twice; keep it honest by charging the second line against what the first left.
            on_hand[product_id] = on_hand.get(product_id, 0.0) - quantity
            plan.append((product_id, product.name, quantity, product.default_location_id, packed_on))

        reference = f"stock_release:{datetime.date.today().isoformat()}"
        correlation_id = str(ULID())
        try:
            with self._connection.transaction():
                for product_id, name, quantity, destination, packed_on in plan:
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
                        raise _Abort(Err(moved.code, f"{name}: {moved.message}", f"{name} : {moved.message_fr or moved.message}"))
                    self._connection.execute(
                        "INSERT INTO production.stock_release_lines "
                        "(id, tenant_id, release_id, packed_on, product_id, quantity, from_location_id, to_location_id, released_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (str(ULID()), tenant_id, correlation_id, packed_on, product_id, quantity, line_id, destination, actor_id),
                    )
        except _Abort as abort:
            return abort.err

        moved_lines = [{"product_id": p, "quantity": q, "to_location_id": d, "packed_on": po.isoformat()} for p, _n, q, d, po in plan]
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

from __future__ import annotations

import datetime

import psycopg

from modules.warehouse.domain.analytics import (
    CONSUMPTION_MOVE_TYPES,
    CORRECTION_MOVE_TYPES,
    INBOUND_MOVE_TYPES,
    OUTBOUND_MOVE_TYPES,
    coverage,
    is_dormant,
    stock_value,
)

# Lots whose DLC falls within this many days are "expiring soon".
EXPIRY_HORIZON_DAYS = 30
# How many recent corrections the overview lists (the count in `summary` is the whole period).
RECENT_CORRECTIONS_LIMIT = 50


class WarehouseAnalyticsService:
    """Read-only KPIs over the warehouse's own tables plus the shared-kernel product catalog.

    Everything a stock manager reads at a glance -- what is on hand and worth, how
    fast it is used, what is about to run out or expire, how much the books had to
    be corrected -- from `warehouse.stock_items`, `warehouse.stock_moves` and
    `warehouse.lots`. Nothing here reaches into another module's schema: the
    product category (raw material, packaging, finished good) lives in the
    production module and is joined on the screen, not here.

    Quantities are never summed across units of measure: 3 t of semolina and
    3,000 film reels are not "3,003 of stock". Every quantity figure is returned
    per product or per unit; only *value* (F CFA) and *counts* are summed.

    An optional `site_id` scopes every figure to one site's locations -- omit it
    for the tenant-wide view. It is a filter on `warehouse.locations`, not a
    warehouse.stock_moves/stock_items column, so every query below joins
    locations only when a site was actually asked for.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def overview(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        consumption_window_days: int = 30,
        dormant_after_days: int = 60,
        today: datetime.date | None = None,
        site_id: str | None = None,
    ) -> dict:
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        today = today or datetime.date.today()
        period_start = datetime.datetime.combine(date_from, datetime.time.min)
        period_end = datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min)
        window_start = datetime.datetime.combine(today - datetime.timedelta(days=consumption_window_days), datetime.time.min)

        products = self._product_rows(tenant_id)
        self._apply_stock_levels(tenant_id, products, site_id)
        self._apply_consumption_window(tenant_id, products, window_start, site_id)
        self._apply_last_movement(tenant_id, products, today, site_id)
        self._apply_period_flows(tenant_id, products, period_start, period_end, site_id)

        rows: list[dict] = []
        for product in products.values():
            has_stock = product["on_hand"] != 0 or product["reserved"] != 0 or product["in_production"] != 0
            has_activity = product["period_move_count"] > 0
            if not has_stock and not has_activity:
                continue
            cover = coverage(product["on_hand"], product["window_consumed"], consumption_window_days)
            value = stock_value(product["on_hand"], product["unit_cost"])
            rows.append(
                {
                    "product_id": product["product_id"],
                    "sku": product["sku"],
                    "name": product["name"],
                    "uom_id": product["uom_id"],
                    "on_hand": product["on_hand"],
                    "blocked_on_hand": product["blocked_on_hand"],
                    "reserved": product["reserved"],
                    "in_production": product["in_production"],
                    "unit_cost": product["unit_cost"],
                    "value": value,
                    "stock_alert_threshold": product["stock_alert_threshold"],
                    "avg_daily_consumption": cover.avg_daily_consumption,
                    "days_of_cover": cover.days_of_cover,
                    "coverage_status": cover.status,
                    "last_move_at": product["last_move_at"].isoformat() if product["last_move_at"] else None,
                    "idle_days": product["idle_days"],
                    "is_dormant": is_dormant(product["on_hand"], product["idle_days"], dormant_after_days),
                    "period_inbound": product["period_inbound"],
                    "period_outbound": product["period_outbound"],
                    "period_consumed": product["period_consumed"],
                    "period_corrections": product["period_corrections"],
                    "period_corrections_count": product["period_corrections_count"],
                    "period_move_count": product["period_move_count"],
                }
            )
        rows.sort(key=lambda r: (r["name"] or "", r["sku"] or ""))

        moves_by_type, flow_by_uom = self._period_totals(tenant_id, period_start, period_end, site_id)
        daily = self._daily_flows(tenant_id, period_start, period_end, site_id)
        corrections = self._recent_corrections(tenant_id, period_start, period_end, site_id)
        expiring_lots = self._expiring_lots(tenant_id, today, site_id)

        below_threshold = [
            r for r in rows if r["stock_alert_threshold"] is not None and 0 < r["on_hand"] < r["stock_alert_threshold"]
        ]
        out_of_stock = [r for r in rows if r["stock_alert_threshold"] is not None and r["on_hand"] <= 0]
        valued = [r for r in rows if r["value"] is not None]
        unvalued = [r for r in rows if r["value"] is None and r["on_hand"] > 0]

        summary = {
            "products_in_stock": sum(1 for r in rows if r["on_hand"] > 0),
            "stock_value": sum(r["value"] for r in valued),
            "valued_products": len(valued),
            "unvalued_products": len(unvalued),
            "below_threshold": len(below_threshold),
            "out_of_stock": len(out_of_stock),
            "negative_stock": sum(1 for r in rows if r["on_hand"] < 0),
            "blocked_products": sum(1 for r in rows if r["blocked_on_hand"] > 0),
            "coverage_critical": sum(1 for r in rows if r["coverage_status"] == "critical"),
            "coverage_warning": sum(1 for r in rows if r["coverage_status"] == "warning"),
            "dormant_count": sum(1 for r in rows if r["is_dormant"]),
            "movements_count": sum(m["count"] for m in moves_by_type),
            "corrections_count": sum(m["count"] for m in moves_by_type if m["move_type"] in CORRECTION_MOVE_TYPES),
            "lots_expired": sum(1 for lot in expiring_lots if lot["days_until_expiry"] < 0),
            "lots_expiring_soon": sum(1 for lot in expiring_lots if lot["days_until_expiry"] >= 0),
        }

        return {
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "consumption_window_days": consumption_window_days,
                "dormant_after_days": dormant_after_days,
                "expiry_horizon_days": EXPIRY_HORIZON_DAYS,
            },
            "summary": summary,
            "flow_by_uom": flow_by_uom,
            "moves_by_type": moves_by_type,
            "daily": daily,
            "products": rows,
            "corrections": corrections,
            "expiring_lots": expiring_lots,
        }

    # --- building blocks ------------------------------------------------------------------

    def _product_rows(self, tenant_id: str) -> dict[str, dict]:
        rows = self._connection.execute(
            """
            SELECT id, sku, name, uom_id, purchase_price, stock_alert_threshold
            FROM core.products
            WHERE tenant_id = %s
            """,
            (tenant_id,),
        ).fetchall()
        return {
            pid: {
                "product_id": pid,
                "sku": sku,
                "name": name,
                "uom_id": uom_id,
                "unit_cost": float(purchase_price) if purchase_price is not None and purchase_price > 0 else None,
                "stock_alert_threshold": float(threshold) if threshold is not None else None,
                "on_hand": 0.0,
                "blocked_on_hand": 0.0,
                "reserved": 0.0,
                "in_production": 0.0,
                "window_consumed": 0.0,
                "last_move_at": None,
                "idle_days": None,
                "period_inbound": 0.0,
                "period_outbound": 0.0,
                "period_consumed": 0.0,
                "period_corrections": 0.0,
                "period_corrections_count": 0,
                "period_move_count": 0,
            }
            for pid, sku, name, uom_id, purchase_price, threshold in rows
        }

    def _apply_stock_levels(self, tenant_id: str, products: dict[str, dict], site_id: str | None = None) -> None:
        site_clause = "AND l.site_id = %s" if site_id is not None else ""
        params = (tenant_id, site_id) if site_id is not None else (tenant_id,)
        rows = self._connection.execute(
            f"""
            SELECT si.product_id, si.quantity_on_hand, si.quantity_reserved, si.quantity_in_production,
                   COALESCE(l.is_blocked, FALSE)
            FROM warehouse.stock_items si
            LEFT JOIN warehouse.locations l ON l.id = si.location_id AND l.tenant_id = si.tenant_id
            WHERE si.tenant_id = %s {site_clause}
            """,
            params,
        ).fetchall()
        for product_id, on_hand, reserved, in_production, is_blocked in rows:
            product = products.get(product_id)
            if product is None:
                continue
            product["on_hand"] += float(on_hand)
            product["reserved"] += float(reserved)
            product["in_production"] += float(in_production)
            if is_blocked:
                product["blocked_on_hand"] += float(on_hand)

    def _apply_consumption_window(
        self, tenant_id: str, products: dict[str, dict], window_start: datetime.datetime, site_id: str | None = None
    ) -> None:
        join, site_clause, extra = self._site_join("sm", site_id)
        rows = self._connection.execute(
            f"""
            SELECT sm.product_id, SUM(sm.quantity)
            FROM warehouse.stock_moves sm
            {join}
            WHERE sm.tenant_id = %s AND sm.move_type = ANY(%s) AND sm.created_at >= %s {site_clause}
            GROUP BY sm.product_id
            """,
            [tenant_id, list(CONSUMPTION_MOVE_TYPES), window_start, *extra],
        ).fetchall()
        for product_id, consumed in rows:
            product = products.get(product_id)
            if product is not None:
                product["window_consumed"] = float(consumed)

    def _apply_last_movement(
        self, tenant_id: str, products: dict[str, dict], today: datetime.date, site_id: str | None = None
    ) -> None:
        join, site_clause, extra = self._site_join("sm", site_id)
        rows = self._connection.execute(
            f"""
            SELECT sm.product_id, MAX(sm.created_at) FROM warehouse.stock_moves sm
            {join}
            WHERE sm.tenant_id = %s {site_clause}
            GROUP BY sm.product_id
            """,
            [tenant_id, *extra],
        ).fetchall()
        for product_id, last_move_at in rows:
            product = products.get(product_id)
            if product is None or last_move_at is None:
                continue
            product["last_move_at"] = last_move_at
            product["idle_days"] = max((today - last_move_at.date()).days, 0)

    def _apply_period_flows(
        self,
        tenant_id: str,
        products: dict[str, dict],
        period_start: datetime.datetime,
        period_end: datetime.datetime,
        site_id: str | None = None,
    ) -> None:
        join, site_clause, extra = self._site_join("sm", site_id)
        rows = self._connection.execute(
            f"""
            SELECT sm.product_id, sm.move_type, COUNT(*), SUM(sm.quantity)
            FROM warehouse.stock_moves sm
            {join}
            WHERE sm.tenant_id = %s AND sm.created_at >= %s AND sm.created_at < %s {site_clause}
            GROUP BY sm.product_id, sm.move_type
            """,
            [tenant_id, period_start, period_end, *extra],
        ).fetchall()
        for product_id, move_type, count, quantity in rows:
            product = products.get(product_id)
            if product is None:
                continue
            quantity = float(quantity)
            product["period_move_count"] += int(count)
            if move_type in INBOUND_MOVE_TYPES or move_type == "transfer_in":
                product["period_inbound"] += abs(quantity)
            if move_type in OUTBOUND_MOVE_TYPES:
                product["period_outbound"] += abs(quantity)
            if move_type in CONSUMPTION_MOVE_TYPES:
                product["period_consumed"] += abs(quantity)
            if move_type in CORRECTION_MOVE_TYPES:
                product["period_corrections"] += quantity
                product["period_corrections_count"] += int(count)

    def _period_totals(
        self,
        tenant_id: str,
        period_start: datetime.datetime,
        period_end: datetime.datetime,
        site_id: str | None = None,
    ) -> tuple[list[dict], list[dict]]:
        join, site_clause, extra = self._site_join("sm", site_id)
        rows = self._connection.execute(
            f"""
            SELECT sm.move_type, p.uom_id, COUNT(*), SUM(sm.quantity)
            FROM warehouse.stock_moves sm
            JOIN core.products p ON p.id = sm.product_id
            {join}
            WHERE sm.tenant_id = %s AND sm.created_at >= %s AND sm.created_at < %s {site_clause}
            GROUP BY sm.move_type, p.uom_id
            """,
            [tenant_id, period_start, period_end, *extra],
        ).fetchall()
        by_type: dict[str, dict] = {}
        by_uom: dict[str, dict] = {}
        for move_type, uom_id, count, quantity in rows:
            quantity = float(quantity)
            entry = by_type.setdefault(move_type, {"move_type": move_type, "count": 0})
            entry["count"] += int(count)
            flow = by_uom.setdefault(
                uom_id, {"uom_id": uom_id, "inbound": 0.0, "outbound": 0.0, "consumed": 0.0, "corrections": 0.0}
            )
            if move_type in INBOUND_MOVE_TYPES or move_type == "transfer_in":
                flow["inbound"] += abs(quantity)
            if move_type in OUTBOUND_MOVE_TYPES:
                flow["outbound"] += abs(quantity)
            if move_type in CONSUMPTION_MOVE_TYPES:
                flow["consumed"] += abs(quantity)
            if move_type in CORRECTION_MOVE_TYPES:
                flow["corrections"] += quantity
        moves_by_type = sorted(by_type.values(), key=lambda m: -m["count"])
        flow_by_uom = sorted(by_uom.values(), key=lambda f: -(f["inbound"] + f["outbound"]))
        return moves_by_type, flow_by_uom

    def _daily_flows(
        self,
        tenant_id: str,
        period_start: datetime.datetime,
        period_end: datetime.datetime,
        site_id: str | None = None,
    ) -> list[dict]:
        join, site_clause, extra = self._site_join("sm", site_id)
        rows = self._connection.execute(
            f"""
            SELECT sm.created_at::date AS day, p.uom_id, sm.move_type, SUM(sm.quantity)
            FROM warehouse.stock_moves sm
            JOIN core.products p ON p.id = sm.product_id
            {join}
            WHERE sm.tenant_id = %s AND sm.created_at >= %s AND sm.created_at < %s {site_clause}
            GROUP BY 1, 2, 3
            ORDER BY 1
            """,
            [tenant_id, period_start, period_end, *extra],
        ).fetchall()
        daily: dict[tuple[datetime.date, str], dict] = {}
        for day, uom_id, move_type, quantity in rows:
            quantity = float(quantity)
            entry = daily.setdefault((day, uom_id), {"day": day.isoformat(), "uom_id": uom_id, "inbound": 0.0, "outbound": 0.0})
            if move_type in INBOUND_MOVE_TYPES or move_type == "transfer_in":
                entry["inbound"] += abs(quantity)
            if move_type in OUTBOUND_MOVE_TYPES:
                entry["outbound"] += abs(quantity)
        return [daily[key] for key in sorted(daily)]

    def _recent_corrections(
        self,
        tenant_id: str,
        period_start: datetime.datetime,
        period_end: datetime.datetime,
        site_id: str | None = None,
    ) -> list[dict]:
        join, site_clause, extra = self._site_join("sm", site_id)
        rows = self._connection.execute(
            f"""
            SELECT sm.id, sm.product_id, sm.location_id, sm.quantity, sm.move_type, sm.reason, sm.reference, sm.actor_id, sm.created_at
            FROM warehouse.stock_moves sm
            {join}
            WHERE sm.tenant_id = %s AND sm.move_type = ANY(%s) AND sm.created_at >= %s AND sm.created_at < %s {site_clause}
            ORDER BY sm.created_at DESC
            LIMIT %s
            """,
            [tenant_id, list(CORRECTION_MOVE_TYPES), period_start, period_end, *extra, RECENT_CORRECTIONS_LIMIT],
        ).fetchall()
        return [
            {
                "id": move_id,
                "product_id": product_id,
                "location_id": location_id,
                "quantity": float(quantity),
                "move_type": move_type,
                "reason": reason,
                "reference": reference,
                "actor_id": actor_id,
                "created_at": created_at.isoformat(),
            }
            for move_id, product_id, location_id, quantity, move_type, reason, reference, actor_id, created_at in rows
        ]

    def _expiring_lots(self, tenant_id: str, today: datetime.date, site_id: str | None = None) -> list[dict]:
        horizon = today + datetime.timedelta(days=EXPIRY_HORIZON_DAYS)
        join, site_clause, extra = self._site_join("ls", site_id)
        rows = self._connection.execute(
            f"""
            SELECT l.id, l.product_id, l.lot_number, l.expiry_date, COALESCE(SUM(ls.quantity_on_hand), 0)
            FROM warehouse.lots l
            LEFT JOIN warehouse.lot_stock ls ON ls.lot_id = l.id AND ls.tenant_id = l.tenant_id
            {join}
            WHERE l.tenant_id = %s AND l.status = 'active' AND l.expiry_date IS NOT NULL AND l.expiry_date <= %s {site_clause}
            GROUP BY l.id, l.product_id, l.lot_number, l.expiry_date
            ORDER BY l.expiry_date, l.lot_number
            """,
            [tenant_id, horizon, *extra],
        ).fetchall()
        return [
            {
                "lot_id": lot_id,
                "product_id": product_id,
                "lot_number": lot_number,
                "expiry_date": expiry_date.isoformat(),
                "days_until_expiry": (expiry_date - today).days,
                "quantity_on_hand": float(quantity),
            }
            for lot_id, product_id, lot_number, expiry_date, quantity in rows
        ]

    @staticmethod
    def _site_join(move_alias: str, site_id: str | None) -> tuple[str, str, list[object]]:
        """A location join + WHERE fragment + its bind params, built only when a
        site filter was actually asked for -- every caller passes the join
        straight into an f-string and the params straight into the bind list,
        so a tenant-wide call (site_id=None) runs the exact query it always did."""
        if site_id is None:
            return "", "", []
        join = f"JOIN warehouse.locations loc ON loc.id = {move_alias}.location_id AND loc.tenant_id = {move_alias}.tenant_id"
        return join, "AND loc.site_id = %s", [site_id]

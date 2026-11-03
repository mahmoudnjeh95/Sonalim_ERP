from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg

from modules.warehouse.domain.valuation import value_of, weighted_average


class ValuationService:
    """Weighted-average cost (CMUP) per product, plus the valued-stock and movements reports.
    Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def apply_receipt(self, *, tenant_id: str, product_id: str, on_hand_before: Decimal, quantity: Decimal, unit_cost: Decimal) -> Decimal:
        """Fold a costed receipt into the product's average. A product with no average yet takes the
        receipt's cost as it is; only receipts change the average (issues and transfers never do)."""
        row = self._connection.execute(
            "SELECT avg_cost FROM warehouse.stock_valuation WHERE tenant_id = %s AND product_id = %s FOR UPDATE",
            (tenant_id, product_id),
        ).fetchone()
        old_cost = row[0] if row else Decimal("0")
        new_cost = weighted_average(on_hand_before, old_cost, quantity, unit_cost)
        self._connection.execute(
            """
            INSERT INTO warehouse.stock_valuation (tenant_id, product_id, avg_cost, cost_source, updated_at)
            VALUES (%s, %s, %s, 'receipt', NOW())
            ON CONFLICT (tenant_id, product_id)
            DO UPDATE SET avg_cost = EXCLUDED.avg_cost, cost_source = 'receipt', updated_at = NOW()
            """,
            (tenant_id, product_id, new_cost),
        )
        return new_cost

    def valued_stock(self, *, tenant_id: str, location_id: str | None = None) -> dict[str, Any]:
        params: list[Any] = [tenant_id]
        location_clause = ""
        if location_id:
            location_clause = " AND si.location_id = %s"
            params.append(location_id)
        rows = self._connection.execute(
            f"""
            SELECT si.product_id, p.sku, p.name, SUM(si.quantity_on_hand), v.avg_cost, v.cost_source
            FROM warehouse.stock_items si
            JOIN core.products p ON p.id = si.product_id
            LEFT JOIN warehouse.stock_valuation v ON v.tenant_id = si.tenant_id AND v.product_id = si.product_id
            WHERE si.tenant_id = %s{location_clause}
            GROUP BY si.product_id, p.sku, p.name, v.avg_cost, v.cost_source
            HAVING SUM(si.quantity_on_hand) <> 0
            ORDER BY p.name
            """,
            params,
        ).fetchall()
        items, total = [], Decimal("0")
        for product_id, sku, name, quantity, avg_cost, source in rows:
            value = value_of(quantity, avg_cost) if avg_cost is not None else None
            if value is not None:
                total += value
            items.append({
                "product_id": product_id, "sku": sku, "name": name, "quantity": quantity, "avg_cost": avg_cost,
                "cost_source": source, "value": value, "missing_cost": avg_cost is None, "negative": quantity < 0,
            })
        return {"items": items, "total_value": total, "missing_cost_count": sum(1 for i in items if i["missing_cost"])}

    def movements_report(self, *, tenant_id: str, product_id: str | None = None, location_id: str | None = None,
                         move_type: str | None = None, date_from: datetime.date | None = None,
                         date_to: datetime.date | None = None, limit: int = 2000) -> list[dict[str, Any]]:
        clauses, params = ["m.tenant_id = %s"], [tenant_id]
        for column, value, op in (("m.product_id", product_id, "="), ("m.location_id", location_id, "="),
                                  ("m.move_type", move_type, "="), ("m.created_at::date", date_from, ">="),
                                  ("m.created_at::date", date_to, "<=")):
            if value:
                clauses.append(f"{column} {op} %s")
                params.append(value)
        params.append(limit)
        rows = self._connection.execute(
            f"""
            SELECT m.created_at, m.move_type, p.sku, p.name, l.name, m.quantity, m.unit_cost, m.reference,
                   m.source_type, m.source_id, v.number, v.type
            FROM warehouse.stock_moves m
            JOIN core.products p ON p.id = m.product_id
            LEFT JOIN warehouse.locations l ON l.id = m.location_id
            LEFT JOIN warehouse.vouchers v ON m.source_type = 'voucher' AND v.id = m.source_id
            WHERE {' AND '.join(clauses)}
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
        keys = ["created_at", "move_type", "sku", "product", "location", "quantity", "unit_cost", "reference",
                "source_type", "source_id", "voucher_number", "voucher_type"]
        return [dict(zip(keys, r, strict=True)) for r in rows]

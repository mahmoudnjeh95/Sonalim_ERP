from __future__ import annotations

import datetime
from typing import Any

import psycopg


class MovementsReportService:
    """Read-only stock movements report: the move ledger with the voucher that caused each move."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

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

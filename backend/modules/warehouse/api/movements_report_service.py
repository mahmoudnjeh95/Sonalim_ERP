from __future__ import annotations

import datetime
import logging
from typing import Any, Callable

import psycopg

logger = logging.getLogger(__name__)

# Invoices and credit notes are not stock moves: the report lists them, as the manual's does, but marks
# them `informational` so no stock figure or valuation ever adds them up.
DOCUMENT_KINDS = ("sales_invoice", "sales_credit_note", "purchase_invoice", "purchase_credit_note")


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
        moves = [{**dict(zip(keys, r, strict=True)), "informational": False, "partner": None} for r in rows]
        deliveries = [{**row, "informational": False, "partner": None}
                      for row in self._delivery_notes(tenant_id, product_id, location_id, move_type, date_from, date_to, limit)]
        # Invoices belong to no depot, so a location filter leaves them out.
        documents = [] if location_id else self._documents(tenant_id, product_id, move_type, date_from, date_to)
        return sorted(moves + deliveries + documents, key=lambda row: row["created_at"], reverse=True)[:limit]

    def _documents(self, tenant_id, product_id, move_type, date_from, date_to) -> list[dict[str, Any]]:
        if move_type and move_type not in DOCUMENT_KINDS:
            return []
        rows: list[tuple[str, dict[str, Any]]] = []
        for kind, read in self._document_readers().items():
            if move_type and move_type != kind:
                continue
            try:
                # A savepoint, so a failing read leaves the connection usable for the rest of the report.
                with self._connection.transaction():
                    found = read(self._connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to)
            except Exception:  # an informational column must never take the stock report down with it
                logger.exception("movements report: reading %s failed", kind)
                continue
            rows.extend((kind, row) for row in found if not product_id or row["product_id"] == product_id)
        if not rows:
            return []
        products = {r[0]: (r[1], r[2]) for r in self._connection.execute(
            "SELECT id, sku, name FROM core.products WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, list({row["product_id"] for _, row in rows}))).fetchall()}
        partners = dict(self._connection.execute(
            "SELECT id, name FROM core.partners WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, list({row["partner_id"] for _, row in rows if row.get("partner_id")}))).fetchall())
        result = []
        for kind, row in rows:
            sku, name = products.get(row["product_id"], (None, None))
            if sku is None:
                continue
            date = row["date"]
            at = date if isinstance(date, datetime.datetime) else datetime.datetime.combine(date, datetime.time(), datetime.timezone.utc)
            result.append({"created_at": at, "move_type": kind, "sku": sku, "product": name, "location": None,
                           "quantity": row["quantity"], "unit_cost": None, "reference": row["number"], "source_type": kind,
                           "source_id": row.get("document_id"), "voucher_number": row["number"], "voucher_type": None,
                           "informational": True, "partner": partners.get(row.get("partner_id"))})
        return result

    @staticmethod
    def _document_readers() -> dict[str, Callable[..., list[dict[str, Any]]]]:
        """Each owning module's public read. Finance's sales invoice lines are new: until its report reads
        exist, the report goes on without them."""
        from modules.procurement.api import report_queries as procurement

        readers: dict[str, Callable[..., list[dict[str, Any]]]] = {
            "purchase_invoice": procurement.list_invoice_lines_for_report,
            "purchase_credit_note": procurement.list_credit_notes_for_report,
        }
        try:
            from modules.finance.api import report_queries as finance
        except ImportError:
            return readers
        for kind, name in (("sales_invoice", "list_invoice_lines_for_report"), ("sales_credit_note", "list_credit_notes_for_report")):
            if hasattr(finance, name):
                readers[kind] = getattr(finance, name)
        return readers

    def _delivery_notes(self, tenant_id, product_id, location_id, move_type, date_from, date_to, limit) -> list[dict[str, Any]]:
        """A delivery note from an issue voucher moves no stock (the issue did) but the report still traces
        it, as the manual's does. A re-delivery after a return has a real move, so it is already listed."""
        if move_type and move_type != "delivery":
            return []
        clauses, params = ["v.tenant_id = %s", "v.type = 'delivery'", "v.status = 'posted'", "v.billable"], [tenant_id]
        for column, value, op in (("l.product_id", product_id, "="), ("v.source_location_id", location_id, "="),
                                  ("v.posted_at::date", date_from, ">="), ("v.posted_at::date", date_to, "<=")):
            if value:
                clauses.append(f"{column} {op} %s")
                params.append(value)
        params.append(limit)
        rows = self._connection.execute(
            f"""
            SELECT v.posted_at, p.sku, p.name, loc.name, l.quantity, l.unit_cost, v.number, v.id
            FROM warehouse.vouchers v
            JOIN warehouse.voucher_lines l ON l.voucher_id = v.id
            JOIN core.products p ON p.id = l.product_id
            LEFT JOIN warehouse.locations loc ON loc.id = v.source_location_id
            WHERE {' AND '.join(clauses)}
            ORDER BY v.posted_at DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
        return [{"created_at": r[0], "move_type": "delivery", "sku": r[1], "product": r[2], "location": r[3], "quantity": r[4],
                 "unit_cost": r[5], "reference": r[6], "source_type": "voucher", "source_id": r[7], "voucher_number": r[6],
                 "voucher_type": "delivery"} for r in rows]

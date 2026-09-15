from __future__ import annotations

import datetime

import psycopg

from core.api.service import CoreService
from core.domain.exchange_rate import BASE_CURRENCY
from modules.procurement.api.service import PurchaseOrderService

# The six consumables the plant tracks fournisseur-by-fournisseur every month.
# Film/carton/scotch/ruban come off the conditionnement report and can be
# split by PC/PL (the OF's own product_type); gasoil/fuel come off the daily
# report and have no product reference at all (see production_report.py's
# DailyReportDetail -- fuel/gasoil never got a *_product_id column), so they
# carry no PC/PL split and cannot be priced against procurement's order
# history the way the other four can.
_PACKAGING_CATEGORIES = ("film", "carton", "scotch", "ruban")
_FUEL_CATEGORIES = ("gasoil", "fuel")
CATEGORIES = _PACKAGING_CATEGORIES + _FUEL_CATEGORIES


class ConsumptionReportService:
    """Monthly consumption by supplier, for the packaging/fuel consumables the
    plant used to reassemble by hand from five separate spreadsheets every
    month. Sourced entirely from data the shop floor already records on daily
    and conditionnement reports (film/carton/scotch/ruban quantities and
    fournisseurs, gasoil/fuel quantities and fournisseurs) -- this adds no new
    capture, only the aggregation and costing nobody had built yet.

    Only validated reports count, matching every other aggregate in this
    module (see TeamPerformanceService) -- a draft is a team's working notes,
    not a result to report a supplier's monthly consumption against.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_monthly_consumption_by_supplier(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        if category is not None and category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")

        clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        packaging_union = " UNION ALL ".join(
            f"""
            SELECT
                '{name}' AS category,
                date_trunc('month', r.report_date)::date AS month,
                w.product_type AS pc_pl,
                c.{name}_product_id AS product_id,
                c.{name}_supplier_id AS supplier_id,
                SUM(c.{name}_quantity) AS quantity
            FROM production.conditionnement_reports c
            JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
            LEFT JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE {where} AND c.{name}_quantity > 0
            GROUP BY month, pc_pl, c.{name}_product_id, c.{name}_supplier_id
            """
            for name in _PACKAGING_CATEGORIES
        )
        packaging_rows = self._connection.execute(packaging_union, params * len(_PACKAGING_CATEGORIES)).fetchall()

        fuel_union = " UNION ALL ".join(
            f"""
            SELECT
                '{name}' AS category,
                date_trunc('month', r.report_date)::date AS month,
                NULL AS pc_pl,
                NULL AS product_id,
                d.{name}_supplier_id AS supplier_id,
                SUM(d.{name}_quantity) AS quantity
            FROM production.daily_reports d
            JOIN production.production_reports r ON r.id = d.report_id AND r.tenant_id = d.tenant_id
            WHERE {where} AND d.{name}_quantity > 0
            GROUP BY month, d.{name}_supplier_id
            """
            for name in _FUEL_CATEGORIES
        )
        fuel_rows = self._connection.execute(fuel_union, params * len(_FUEL_CATEGORIES)).fetchall()

        rows = [
            {
                "category": cat,
                "month": month.isoformat(),
                "pc_pl": pc_pl,
                "product_id": product_id,
                "supplier_id": supplier_id,
                "quantity": float(quantity),
            }
            for cat, month, pc_pl, product_id, supplier_id, quantity in (*packaging_rows, *fuel_rows)
        ]
        if category is not None:
            rows = [row for row in rows if row["category"] == category]

        self._apply_costs(tenant_id, rows)
        return rows

    def _apply_costs(self, tenant_id: str, rows: list[dict]) -> None:
        """Fills unit_price/cost (always in BASE_CURRENCY/XOF -- CFA) from
        procurement's own order history -- the same last-price-paid-to-this-
        supplier lookup the purchase order screen uses (see LastPrice), never a
        fabricated or estimated figure. Every supplier's price here is in EUR
        today, so this converts through the tenant's own EUR->XOF exchange
        rate history (core.exchange_rates), using the rate in effect on the
        date that price was recorded rather than today's rate -- the same
        convention procurement's own cost reports already use (see
        PurchaseOrderService.list_confirmed_receipt_line_details).

        A row with no supplier, no product (gasoil/fuel -- see the class
        docstring), no order history, or -- unlikely for EUR, but possible for
        a currency with no rate on file -- no exchange rate to convert its
        price with, is left unpriced rather than shown under the wrong
        currency or guessed at.
        """
        procurement = PurchaseOrderService(self._connection)
        core_service = CoreService(self._connection)
        product_ids_by_supplier: dict[str, set[str]] = {}
        for row in rows:
            if row["supplier_id"] and row["product_id"]:
                product_ids_by_supplier.setdefault(row["supplier_id"], set()).add(row["product_id"])

        last_prices: dict[tuple[str, str], tuple[float, str, str | None]] = {}
        for supplier_id, product_ids in product_ids_by_supplier.items():
            for last_price in procurement.list_last_prices(
                tenant_id=tenant_id, supplier_id=supplier_id, product_ids=list(product_ids)
            ):
                last_prices[(supplier_id, last_price.product_id)] = (
                    last_price.unit_price, last_price.unit_price_currency, last_price.order_date,
                )

        rate_cache: dict[tuple[str, str], float | None] = {}

        def rate_to_cfa(currency_code: str, as_of: datetime.date) -> float | None:
            cache_key = (currency_code, as_of.isoformat())
            if cache_key not in rate_cache:
                exchange_rate = core_service.get_exchange_rate(tenant_id=tenant_id, currency_code=currency_code, as_of_date=as_of)
                rate_cache[cache_key] = exchange_rate.rate_to_base if exchange_rate else None
            return rate_cache[cache_key]

        for row in rows:
            key = (row["supplier_id"], row["product_id"])
            match = last_prices.get(key) if row["supplier_id"] and row["product_id"] else None
            if match is None:
                row.update(unit_price=None, unit_price_currency=None, cost=None, priced=False)
                continue

            unit_price, currency, order_date = match
            as_of = datetime.date.fromisoformat(order_date) if order_date else datetime.date.today()
            rate = rate_to_cfa(currency, as_of)
            if rate is None:
                row.update(unit_price=None, unit_price_currency=None, cost=None, priced=False)
                continue

            unit_price_cfa = unit_price * rate
            row.update(unit_price=unit_price_cfa, unit_price_currency=BASE_CURRENCY, cost=row["quantity"] * unit_price_cfa, priced=True)

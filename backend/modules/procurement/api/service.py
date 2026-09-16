from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.exchange_rate import BASE_CURRENCY
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.procurement.domain.entities import (
    LastPrice,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    apply_receipt_to_line,
    compute_cost_anomaly,
    compute_landed_cost,
    confirm_purchase_order_receipt,
    receive_against_order,
    transition_purchase_order,
    validate_new_purchase_order,
    validate_new_purchase_order_line,
    validate_receipt_fees,
)
from modules.warehouse.api.lot_service import LotService
from modules.warehouse.api.service import StockService

_ORDER_COLUMNS = "id, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes, is_import"
_LINE_COLUMNS = (
    "id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, quantity_received, "
    "status, unit_price, unit_price_currency"
)
_RECEIPT_COLUMNS = (
    "id, tenant_id, purchase_order_id, location_id, status, currency_code, invoice_number, invoice_date, origin_country, "
    "carrier, transport_company_name, driver_name, base_cost, license_fee, insurance_fee, transit_fee, transport_fee, "
    "customs_duty, handling_fee, total_cost, confirmed_at"
)
_RECEIPT_LINE_COLUMNS = "id, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit"


def _row_to_order(row: tuple) -> PurchaseOrder:
    rid, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes, is_import = row
    return PurchaseOrder(
        id=rid,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        status=status,
        order_date=order_date.isoformat() if order_date else None,
        expected_date=expected_date.isoformat() if expected_date else None,
        currency_code=currency_code,
        notes=notes,
        is_import=is_import,
    )


def _row_to_line(row: tuple) -> PurchaseOrderLine:
    rid, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, quantity_received, status, unit_price, unit_price_currency = row
    return PurchaseOrderLine(
        id=rid,
        tenant_id=tenant_id,
        purchase_order_id=purchase_order_id,
        product_id=product_id,
        uom_id=uom_id,
        quantity_ordered=float(quantity_ordered),
        quantity_received=float(quantity_received),
        status=status,
        unit_price=float(unit_price),
        unit_price_currency=unit_price_currency,
    )


def _row_to_receipt(row: tuple) -> PurchaseOrderReceipt:
    (
        rid, tenant_id, purchase_order_id, location_id, status, currency_code, invoice_number, invoice_date, origin_country,
        carrier, transport_company_name, driver_name, base_cost, license_fee, insurance_fee, transit_fee, transport_fee,
        customs_duty, handling_fee, total_cost, confirmed_at,
    ) = row
    return PurchaseOrderReceipt(
        id=rid,
        tenant_id=tenant_id,
        purchase_order_id=purchase_order_id,
        location_id=location_id,
        status=status,
        currency_code=currency_code,
        invoice_number=invoice_number,
        invoice_date=invoice_date.isoformat() if invoice_date else None,
        origin_country=origin_country,
        carrier=carrier,
        transport_company_name=transport_company_name,
        driver_name=driver_name,
        base_cost=float(base_cost),
        license_fee=float(license_fee),
        insurance_fee=float(insurance_fee),
        transit_fee=float(transit_fee),
        transport_fee=float(transport_fee),
        customs_duty=float(customs_duty),
        handling_fee=float(handling_fee),
        total_cost=float(total_cost),
        confirmed_at=confirmed_at.isoformat() if confirmed_at else None,
    )


def _row_to_receipt_line(row: tuple) -> PurchaseOrderReceiptLine:
    rid, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit = row
    return PurchaseOrderReceiptLine(
        id=rid,
        tenant_id=tenant_id,
        purchase_order_receipt_id=purchase_order_receipt_id,
        purchase_order_line_id=purchase_order_line_id,
        quantity=float(quantity),
        lot_number=lot_number,
        cost_per_unit=float(cost_per_unit),
    )


class PurchaseOrderService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _check_line_uom(self, *, tenant_id: str, product_id: str, uom_id: str) -> Result[None]:
        """A PO line may legitimately order in a unit other than the product's own
        (tons for a kg-tracked product) -- confirm_receipt converts between them.
        What it must never do is cross into a different *category* of measurement
        (a kg-tracked film ordered in pièces), which is what silently corrupted the
        historical `gasoil`/`film-*` lines this check is here to stop happening again."""
        core_service = CoreService(self._connection)
        product_uom = core_service.get_product_uom(tenant_id, product_id)
        line_uom = core_service.get_uom(tenant_id, uom_id)
        if product_uom is None or line_uom is None:
            return Err("NOT_FOUND", "product or unit of measure not found")
        if line_uom.category != product_uom.category:
            return Err(
                "UOM_CATEGORY_MISMATCH",
                f"line unit {line_uom.code} ({line_uom.category}) does not match product's unit "
                f"{product_uom.code} ({product_uom.category})",
            )
        return Ok(None)

    # --- Orders -------------------------------------------------------------------------

    def create_purchase_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        lines: list[dict],
        supplier_id: str | None = None,
        currency_code: str | None = None,
        order_date: datetime.date | None = None,
        expected_date: datetime.date | None = None,
        notes: str | None = None,
        is_import: bool = False,
    ) -> Result[PurchaseOrder]:
        header_validation = validate_new_purchase_order(currency_code=currency_code)
        if isinstance(header_validation, Err):
            return header_validation
        if not lines:
            return Err("INVALID_LINES", "a purchase order needs at least one line")
        for line in lines:
            line_validation = validate_new_purchase_order_line(
                quantity_ordered=line["quantity_ordered"], unit_price=line.get("unit_price", 0)
            )
            if isinstance(line_validation, Err):
                return line_validation
            uom_validation = self._check_line_uom(tenant_id=tenant_id, product_id=line["product_id"], uom_id=line["uom_id"])
            if isinstance(uom_validation, Err):
                return uom_validation

        order_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO procurement.purchase_orders
                (id, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes, is_import)
            VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s, %s)
            """,
            (order_id, tenant_id, supplier_id, order_date, expected_date, currency_code, notes, is_import),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO procurement.purchase_order_lines
                    (id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, unit_price, unit_price_currency)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()),
                    tenant_id,
                    order_id,
                    line["product_id"],
                    line["uom_id"],
                    line["quantity_ordered"],
                    line.get("unit_price", 0),
                    line.get("unit_price_currency", "EUR"),
                ),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.created",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={"supplier_id": supplier_id, "line_count": len(lines)},
        )
        return Ok(self._get_order(tenant_id, order_id))

    def list_purchase_orders(self, *, tenant_id: str, status: str | None = None, supplier_id: str | None = None) -> list[PurchaseOrder]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if supplier_id is not None:
            clauses.append("supplier_id = %s")
            params.append(supplier_id)
        rows = self._connection.execute(
            f"SELECT {_ORDER_COLUMNS} FROM procurement.purchase_orders WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_row_to_order(row) for row in rows]

    def _get_order(self, tenant_id: str, order_id: str, *, for_update: bool = False) -> PurchaseOrder | None:
        suffix = " FOR UPDATE" if for_update else ""
        row = self._connection.execute(
            f"SELECT {_ORDER_COLUMNS} FROM procurement.purchase_orders WHERE id = %s AND tenant_id = %s{suffix}",
            (order_id, tenant_id),
        ).fetchone()
        return _row_to_order(row) if row else None

    def list_lines(self, *, tenant_id: str, purchase_order_id: str) -> list[PurchaseOrderLine]:
        rows = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM procurement.purchase_order_lines WHERE tenant_id = %s AND purchase_order_id = %s ORDER BY created_at",
            (tenant_id, purchase_order_id),
        ).fetchall()
        return [_row_to_line(row) for row in rows]

    def list_last_prices(self, *, tenant_id: str, supplier_id: str, product_ids: list[str]) -> list[LastPrice]:
        """Most recent unit price this supplier was ordered at for each product, derived
        from order history rather than a standalone price catalog (none exists yet)."""
        if not product_ids:
            return []
        rows = self._connection.execute(
            """
            SELECT DISTINCT ON (pol.product_id) pol.product_id, pol.unit_price, pol.unit_price_currency, po.order_date
            FROM procurement.purchase_order_lines pol
            JOIN procurement.purchase_orders po ON po.id = pol.purchase_order_id AND po.tenant_id = pol.tenant_id
            WHERE pol.tenant_id = %s AND po.supplier_id = %s AND pol.product_id = ANY(%s)
            ORDER BY pol.product_id, po.order_date DESC NULLS LAST, pol.created_at DESC
            """,
            (tenant_id, supplier_id, product_ids),
        ).fetchall()
        return [
            LastPrice(
                product_id=r[0], unit_price=float(r[1]), unit_price_currency=r[2],
                order_date=r[3].isoformat() if r[3] else None,
            )
            for r in rows
        ]

    def list_price_history(
        self, *, tenant_id: str, product_id: str, supplier_id: str | None = None
    ) -> list[dict]:
        """Every purchase-order price on record for this product, oldest to
        newest -- the trend a single LastPrice can't show. Each line is also
        converted to BASE_CURRENCY (XOF) using the exchange rate in effect on
        its own order date, the same honest-or-unpriced convention
        ConsumptionReportService uses (see CoreService.get_exchange_rate) --
        never today's rate applied retroactively to an old order."""
        clauses = ["pol.tenant_id = %s", "pol.product_id = %s"]
        params: list[object] = [tenant_id, product_id]
        if supplier_id is not None:
            clauses.append("po.supplier_id = %s")
            params.append(supplier_id)
        rows = self._connection.execute(
            f"""
            SELECT po.id, po.supplier_id, po.order_date, pol.unit_price, pol.unit_price_currency, pol.quantity_ordered
            FROM procurement.purchase_order_lines pol
            JOIN procurement.purchase_orders po ON po.id = pol.purchase_order_id AND po.tenant_id = pol.tenant_id
            WHERE {' AND '.join(clauses)}
            ORDER BY po.order_date NULLS LAST, pol.created_at
            """,
            params,
        ).fetchall()

        core_service = CoreService(self._connection)
        rate_cache: dict[tuple[str, str], float | None] = {}
        history: list[dict] = []
        for order_id, order_supplier_id, order_date, unit_price, currency, quantity in rows:
            as_of = order_date or datetime.date.today()
            rate_key = (currency, as_of.isoformat())
            if rate_key not in rate_cache:
                exchange_rate = core_service.get_exchange_rate(tenant_id=tenant_id, currency_code=currency, as_of_date=as_of)
                rate_cache[rate_key] = exchange_rate.rate_to_base if exchange_rate else None
            rate = rate_cache[rate_key]
            history.append(
                {
                    "order_id": order_id,
                    "supplier_id": order_supplier_id,
                    "order_date": order_date.isoformat() if order_date else None,
                    "quantity_ordered": float(quantity),
                    "unit_price": float(unit_price),
                    "unit_price_currency": currency,
                    "unit_price_cfa": float(unit_price) * rate if rate is not None else None,
                }
            )
        return history

    def list_supplier_leaderboard(self, *, tenant_id: str) -> list[dict]:
        """Ranks every supplier ever ordered from by how often they held the
        lowest recorded CFA price on a product -- the aggregate view behind
        list_price_history's per-product best-supplier highlight. Ties for a
        product's lowest price keep whichever supplier's order came first,
        matching list_price_history's own chronological ordering."""
        rows = self._connection.execute(
            """
            SELECT pol.product_id, po.supplier_id, po.order_date, pol.unit_price, pol.unit_price_currency
            FROM procurement.purchase_order_lines pol
            JOIN procurement.purchase_orders po ON po.id = pol.purchase_order_id AND po.tenant_id = pol.tenant_id
            WHERE pol.tenant_id = %s AND po.supplier_id IS NOT NULL
            ORDER BY pol.product_id, po.order_date NULLS LAST, pol.created_at
            """,
            (tenant_id,),
        ).fetchall()

        core_service = CoreService(self._connection)
        rate_cache: dict[tuple[str, str], float | None] = {}
        best_by_product: dict[str, tuple[str, float]] = {}
        orders_by_supplier: dict[str, int] = {}
        products_by_supplier: dict[str, set[str]] = {}

        for product_id, supplier_id, order_date, unit_price, currency in rows:
            orders_by_supplier[supplier_id] = orders_by_supplier.get(supplier_id, 0) + 1
            products_by_supplier.setdefault(supplier_id, set()).add(product_id)

            as_of = order_date or datetime.date.today()
            rate_key = (currency, as_of.isoformat())
            if rate_key not in rate_cache:
                exchange_rate = core_service.get_exchange_rate(tenant_id=tenant_id, currency_code=currency, as_of_date=as_of)
                rate_cache[rate_key] = exchange_rate.rate_to_base if exchange_rate else None
            rate = rate_cache[rate_key]
            if rate is None:
                continue
            price_cfa = float(unit_price) * rate

            current_best = best_by_product.get(product_id)
            if current_best is None or price_cfa < current_best[1]:
                best_by_product[product_id] = (supplier_id, price_cfa)

        best_price_wins: dict[str, int] = {}
        for winning_supplier_id, _ in best_by_product.values():
            best_price_wins[winning_supplier_id] = best_price_wins.get(winning_supplier_id, 0) + 1

        leaderboard = [
            {
                "supplier_id": supplier_id,
                "products_supplied": len(products_by_supplier[supplier_id]),
                "total_orders": orders_by_supplier[supplier_id],
                "best_price_count": best_price_wins.get(supplier_id, 0),
            }
            for supplier_id in orders_by_supplier
        ]
        leaderboard.sort(key=lambda row: (-row["best_price_count"], -row["products_supplied"]))
        return leaderboard

    def add_line(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        purchase_order_id: str,
        product_id: str,
        uom_id: str,
        quantity_ordered: float,
        unit_price: float = 0,
        unit_price_currency: str = "EUR",
    ) -> Result[PurchaseOrderLine]:
        order = self._get_order(tenant_id, purchase_order_id, for_update=True)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {purchase_order_id} not found")
        if order.status != "draft":
            return Err("INVALID_TRANSITION", "lines can only be added while the order is in draft")
        validation = validate_new_purchase_order_line(quantity_ordered=quantity_ordered, unit_price=unit_price)
        if isinstance(validation, Err):
            return validation
        uom_validation = self._check_line_uom(tenant_id=tenant_id, product_id=product_id, uom_id=uom_id)
        if isinstance(uom_validation, Err):
            return uom_validation

        line_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO procurement.purchase_order_lines
                (id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, unit_price, unit_price_currency)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (line_id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, unit_price, unit_price_currency),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.line_added",
            entity_type="purchase_order",
            entity_id=purchase_order_id,
            payload={"line_id": line_id, "product_id": product_id, "quantity_ordered": quantity_ordered},
        )
        row = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM procurement.purchase_order_lines WHERE id = %s", (line_id,)
        ).fetchone()
        return Ok(_row_to_line(row))

    def _transition(self, *, tenant_id: str, actor_id: str, order_id: str, new_status: str) -> Result[PurchaseOrder]:
        order = self._get_order(tenant_id, order_id, for_update=True)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {order_id} not found")
        result = transition_purchase_order(order, new_status)
        if isinstance(result, Err):
            return result
        self._connection.execute("UPDATE procurement.purchase_orders SET status = %s WHERE id = %s", (new_status, order_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.status_changed",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={"from_status": order.status, "to_status": new_status},
        )
        publish_event(
            self._connection,
            event_type="procurement.purchase_order.status_changed",
            producer="procurement",
            tenant_id=tenant_id,
            correlation_id=str(ULID()),
            payload={"purchase_order_id": order_id, "from_status": order.status, "to_status": new_status},
        )
        return result

    def validate_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="validated")

    def approve_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="approved")

    def place_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="ordered")

    def refuse_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="refused")

    def cancel_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="canceled")

    def admin_update_purchase_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        order_id: str,
        supplier_id: str | None = None,
        order_date: datetime.date | None = None,
        expected_date: datetime.date | None = None,
        currency_code: str | None = None,
        notes: str | None = None,
        is_import: bool | None = None,
    ) -> Result[PurchaseOrder]:
        """Direct edit of header fields, gated by procurement.admin_purchase_orders. Allowed
        regardless of the order's current status -- the elevated permission is what limits
        blast radius here, matching warehouse.admin_material_receipts."""
        current = self._get_order(tenant_id, order_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"purchase order {order_id} not found")

        merged_currency = currency_code if currency_code is not None else current.currency_code
        validation = validate_new_purchase_order(currency_code=merged_currency)
        if isinstance(validation, Err):
            return validation

        merged_supplier = supplier_id if supplier_id is not None else current.supplier_id
        merged_order_date = order_date if order_date is not None else current.order_date
        merged_expected_date = expected_date if expected_date is not None else current.expected_date
        merged_notes = notes if notes is not None else current.notes
        merged_is_import = is_import if is_import is not None else current.is_import

        self._connection.execute(
            """
            UPDATE procurement.purchase_orders
            SET supplier_id = %s, order_date = %s, expected_date = %s, currency_code = %s, notes = %s, is_import = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (merged_supplier, merged_order_date, merged_expected_date, merged_currency, merged_notes, merged_is_import, order_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.updated",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={
                "supplier_id": merged_supplier,
                "order_date": str(merged_order_date) if merged_order_date else None,
                "expected_date": str(merged_expected_date) if merged_expected_date else None,
                "currency_code": merged_currency,
                "notes": merged_notes,
            },
        )
        return Ok(self._get_order(tenant_id, order_id))

    # --- Goods receipts ------------------------------------------------------------------

    def create_receipt(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        purchase_order_id: str,
        location_id: str,
        currency_code: str,
        lines: list[dict],
        invoice_number: str | None = None,
        invoice_date: datetime.date | None = None,
        origin_country: str | None = None,
        carrier: str | None = None,
        transport_company_name: str | None = None,
        driver_name: str | None = None,
        base_cost: float = 0,
        license_fee: float = 0,
        insurance_fee: float = 0,
        transit_fee: float = 0,
        transport_fee: float = 0,
        customs_duty: float = 0,
        handling_fee: float = 0,
    ) -> Result[PurchaseOrderReceipt]:
        """Drafts a goods-receipt event covering one or more lines of one order. No stock or
        line quantities are touched yet -- that only happens on confirm_receipt, so a draft
        can be corrected freely before it's committed."""
        order = self._get_order(tenant_id, purchase_order_id)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {purchase_order_id} not found")
        if order.status not in ("ordered", "partially_received"):
            return Err("INVALID_TRANSITION", f"cannot record a receipt against a purchase order in status {order.status}")
        if not currency_code or not currency_code.strip():
            return Err("INVALID_CURRENCY", "currency_code is required when recording a receipt")
        if not lines:
            return Err("INVALID_LINES", "a goods receipt needs at least one line")
        for line in lines:
            if line["quantity"] <= 0:
                return Err("INVALID_QUANTITY", "received quantity must be positive")

        fee_validation = validate_receipt_fees(
            is_import=order.is_import,
            license_fee=license_fee,
            insurance_fee=insurance_fee,
            transit_fee=transit_fee,
            customs_duty=customs_duty,
        )
        if isinstance(fee_validation, Err):
            return fee_validation

        total_quantity = sum(line["quantity"] for line in lines)
        cost_result = compute_landed_cost(
            base_cost=base_cost,
            license_fee=license_fee,
            insurance_fee=insurance_fee,
            transit_fee=transit_fee,
            transport_fee=transport_fee,
            customs_duty=customs_duty,
            handling_fee=handling_fee,
            quantity=total_quantity,
        )
        if isinstance(cost_result, Err):
            return cost_result
        total_cost, cost_per_unit = cost_result.value

        receipt_id = str(ULID())
        self._connection.execute(
            f"""
            INSERT INTO procurement.purchase_order_receipts
                (id, tenant_id, purchase_order_id, location_id, status, currency_code, invoice_number, invoice_date, origin_country,
                 carrier, transport_company_name, driver_name, base_cost, license_fee, insurance_fee, transit_fee, transport_fee,
                 customs_duty, handling_fee, total_cost)
            VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                receipt_id, tenant_id, purchase_order_id, location_id, currency_code, invoice_number, invoice_date, origin_country,
                carrier, transport_company_name, driver_name, base_cost, license_fee, insurance_fee, transit_fee, transport_fee,
                customs_duty, handling_fee, total_cost,
            ),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO procurement.purchase_order_receipt_lines
                    (id, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, receipt_id, line["purchase_order_line_id"], line["quantity"], line.get("lot_number"), cost_per_unit),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order_receipt.created",
            entity_type="purchase_order_receipt",
            entity_id=receipt_id,
            payload={"purchase_order_id": purchase_order_id, "line_count": len(lines), "total_cost": total_cost},
        )
        row = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE id = %s", (receipt_id,)
        ).fetchone()
        return Ok(_row_to_receipt(row))

    def list_receipts(self, *, tenant_id: str, purchase_order_id: str | None = None) -> list[PurchaseOrderReceipt]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if purchase_order_id is not None:
            clauses.append("purchase_order_id = %s")
            params.append(purchase_order_id)
        rows = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_row_to_receipt(row) for row in rows]

    def get_receipt(self, *, tenant_id: str, receipt_id: str) -> PurchaseOrderReceipt | None:
        """Looks up one receipt by id, carrying its `purchase_order_id` -- how a stock
        move's `purchase_order_receipt:{receipt_id}` reference resolves back to the order
        it came from (see StockMoveDetailDialog's "View purchase order" link)."""
        row = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE id = %s AND tenant_id = %s",
            (receipt_id, tenant_id),
        ).fetchone()
        return _row_to_receipt(row) if row else None

    def list_receipt_lines(self, *, tenant_id: str, purchase_order_receipt_id: str) -> list[PurchaseOrderReceiptLine]:
        rows = self._connection.execute(
            f"""
            SELECT {_RECEIPT_LINE_COLUMNS} FROM procurement.purchase_order_receipt_lines
            WHERE tenant_id = %s AND purchase_order_receipt_id = %s
            """,
            (tenant_id, purchase_order_receipt_id),
        ).fetchall()
        return [_row_to_receipt_line(row) for row in rows]

    def confirm_receipt(self, *, tenant_id: str, actor_id: str, receipt_id: str, correlation_id: str) -> Result[PurchaseOrder]:
        """Applies a drafted receipt's lines to their purchase-order lines, re-derives the
        order's receiving status from every one of its lines, and posts stock plus
        creates/tops-up the lot for each line. All in one transaction: line/order
        updates, the audit rows, the stock/lot writes, and the outbox insert commit
        or roll back together."""
        receipt_row = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (receipt_id, tenant_id),
        ).fetchone()
        if receipt_row is None:
            return Err("NOT_FOUND", f"purchase order receipt {receipt_id} not found")
        receipt = _row_to_receipt(receipt_row)

        transition_result = confirm_purchase_order_receipt(receipt.status)
        if isinstance(transition_result, Err):
            return transition_result

        order = self._get_order(tenant_id, receipt.purchase_order_id, for_update=True)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {receipt.purchase_order_id} not found")

        receipt_lines = self.list_receipt_lines(tenant_id=tenant_id, purchase_order_receipt_id=receipt_id)
        event_lines: list[dict] = []
        for receipt_line in receipt_lines:
            line_row = self._connection.execute(
                f"SELECT {_LINE_COLUMNS} FROM procurement.purchase_order_lines WHERE id = %s AND tenant_id = %s FOR UPDATE",
                (receipt_line.purchase_order_line_id, tenant_id),
            ).fetchone()
            if line_row is None:
                return Err("NOT_FOUND", f"purchase order line {receipt_line.purchase_order_line_id} not found")
            line = _row_to_line(line_row)
            applied = apply_receipt_to_line(line, receipt_line.quantity)
            if isinstance(applied, Err):
                return applied
            updated_line = applied.value
            # unit_price is never entered at order creation (see PurchaseOrdersPage) -- it's
            # derived here from the receipt's actual landed cost (freight/customs/etc. divided
            # across quantity), so it reflects real cost instead of a guess made before receiving.
            # Priced in the receipt's own currency (not the order's, which may still be unset).
            self._connection.execute(
                """
                UPDATE procurement.purchase_order_lines
                SET quantity_received = %s, status = %s, unit_price = %s, unit_price_currency = %s
                WHERE id = %s
                """,
                (updated_line.quantity_received, updated_line.status, receipt_line.cost_per_unit, receipt.currency_code, updated_line.id),
            )
            event_lines.append(
                {
                    "product_id": updated_line.product_id,
                    "quantity": receipt_line.quantity,
                    "uom_id": updated_line.uom_id,
                    "lot_number": receipt_line.lot_number,
                }
            )

        all_line_statuses = [line.status for line in self.list_lines(tenant_id=tenant_id, purchase_order_id=order.id)]
        order_result = receive_against_order(order, all_line_statuses)
        if isinstance(order_result, Err):
            return order_result
        updated_order = order_result.value

        if order.currency_code is None:
            # First receipt on an order that had no currency at creation -- now that one's
            # known, backfill the order record so lists/reports have something to show.
            self._connection.execute(
                "UPDATE procurement.purchase_orders SET currency_code = %s WHERE id = %s",
                (receipt.currency_code, order.id),
            )
        self._connection.execute(
            "UPDATE procurement.purchase_orders SET status = %s WHERE id = %s", (updated_order.status, updated_order.id)
        )
        self._connection.execute(
            "UPDATE procurement.purchase_order_receipts SET status = 'confirmed', confirmed_at = NOW() WHERE id = %s",
            (receipt_id,),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order_receipt.confirmed",
            entity_type="purchase_order_receipt",
            entity_id=receipt_id,
            payload={"purchase_order_id": order.id, "from_status": order.status, "to_status": updated_order.status},
        )

        # Post stock (and top up/create the lot) synchronously, in the same
        # transaction as the rest of this confirmation, rather than only via
        # the outbox event below — this deployment has no running message
        # broker/worker to consume it, so relying on that alone silently never
        # moves stock. The event is still published (for audit/future
        # consumers) but immediately marked sent so a worker that does show up
        # later never reprocesses it and double-posts this receipt's stock.
        stock_service = StockService(self._connection)
        lot_service = LotService(self._connection)
        core_service = CoreService(self._connection)
        for event_line in event_lines:
            # The receipt line was placed against `event_line["uom_id"]` (the PO
            # line's own unit), which may legitimately differ from the product's
            # stocked unit (ordered in tons, tracked in kg) -- convert via
            # ratio_to_base before this touches stock, or the raw number gets
            # posted as if it were already in the product's own unit.
            product_uom = core_service.get_product_uom(tenant_id, event_line["product_id"])
            line_uom = core_service.get_uom(tenant_id, event_line["uom_id"])
            if product_uom is None or line_uom is None:
                return Err("NOT_FOUND", "product or unit of measure not found")
            if line_uom.category != product_uom.category:
                return Err(
                    "UOM_CATEGORY_MISMATCH",
                    f"line unit {line_uom.code} does not match product unit {product_uom.code}",
                )
            converted_quantity = event_line["quantity"] * float(line_uom.ratio_to_base) / float(product_uom.ratio_to_base)

            stock_result = stock_service.receive_stock(
                tenant_id=tenant_id,
                product_id=event_line["product_id"],
                location_id=receipt.location_id,
                quantity=converted_quantity,
                correlation_id=correlation_id,
                reference=f"purchase_order_receipt:{receipt_id}",
                actor_id=actor_id,
            )
            if isinstance(stock_result, Err):
                return stock_result
            if event_line["lot_number"]:
                lot_result = lot_service.receive_lot(
                    tenant_id=tenant_id,
                    product_id=event_line["product_id"],
                    location_id=receipt.location_id,
                    lot_number=event_line["lot_number"],
                    quantity=converted_quantity,
                    actor_id=actor_id,
                    source_type="purchase_order_receipt",
                    source_id=receipt_id,
                )
                if isinstance(lot_result, Err):
                    return lot_result

        event_id = publish_event(
            self._connection,
            event_type="procurement.purchase_order_receipt.confirmed",
            producer="procurement",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "purchase_order_receipt_id": receipt_id,
                "purchase_order_id": order.id,
                "location_id": receipt.location_id,
                "lines": event_lines,
            },
        )
        self._connection.execute("UPDATE events.outbox SET sent_at = NOW() WHERE event_id = %s", (event_id,))
        return Ok(updated_order)

    def _base_currency_rate(self, *, tenant_id: str, currency_code: str, as_of: datetime.date | None, cache: dict) -> float:
        """Rate to multiply an amount in `currency_code` by to get it in BASE_CURRENCY
        (XOF), as of the given date -- this is what lets a CFA receipt from Mali and a EUR
        receipt from Turkiye/Spain be summed or compared at all (point 4 of the MP cost
        plan). Falls back to 1.0 (no conversion) when no rate has been recorded rather than
        dropping the row, since an unconverted number still beats a missing one -- callers
        needing to know this happened should check core.exchange-rates coverage directly."""
        if currency_code == BASE_CURRENCY:
            return 1.0
        effective_date = as_of or datetime.date.today()
        key = (currency_code, effective_date)
        if key not in cache:
            core_service = CoreService(self._connection)
            rate = core_service.get_exchange_rate(tenant_id=tenant_id, currency_code=currency_code, as_of_date=effective_date)
            cache[key] = rate.rate_to_base if rate else None
        return cache[key] if cache[key] is not None else 1.0

    def list_confirmed_receipt_line_details(self, *, tenant_id: str) -> list[dict]:
        """Flat, one-row-per-receipt-line view of every confirmed goods receipt, for
        product-level cost/trend analysis. cost_per_unit * quantity is this line's own
        share of its shipment's total landed cost -- a receipt spanning multiple products
        splits its freight/customs/insurance costs proportionally across their quantities,
        so this is the right granularity for a per-product report (unlike the receipt's own
        total_cost, which covers every line on it). total_cost_base converts that amount to
        BASE_CURRENCY so mixed-currency sourcing (local CFA vs. imported EUR/TRY) can be
        summed and trended together -- total_cost (the receipt's own currency) is kept
        alongside it for transparency.

        Also flags cost anomalies (the "Majoration" warning in the BD MP tracking sheet):
        each row's cost_per_unit_base is compared against that product+unit's weighted
        average cost across every *other* confirmed receipt -- a receipt priced >15% above
        that baseline is_cost_anomaly=True. Requires at least one other receipt for the same
        (product_id, uom_id) to have a baseline at all."""
        rows = self._connection.execute(
            """
            SELECT r.id, l.product_id, l.uom_id, rl.quantity, r.invoice_date, rl.quantity * rl.cost_per_unit,
                   r.currency_code, r.origin_country, po.is_import, po.supplier_id
            FROM procurement.purchase_order_receipt_lines rl
            JOIN procurement.purchase_order_receipts r ON r.id = rl.purchase_order_receipt_id AND r.tenant_id = rl.tenant_id
            JOIN procurement.purchase_order_lines l ON l.id = rl.purchase_order_line_id AND l.tenant_id = rl.tenant_id
            JOIN procurement.purchase_orders po ON po.id = r.purchase_order_id AND po.tenant_id = r.tenant_id
            WHERE rl.tenant_id = %s AND r.status = 'confirmed'
            ORDER BY r.invoice_date
            """,
            (tenant_id,),
        ).fetchall()

        rate_cache: dict = {}
        decorated = []
        for receipt_id, product_id, uom_id, quantity, invoice_date, total_cost, currency_code, origin_country, is_import, supplier_id in rows:
            rate = self._base_currency_rate(tenant_id=tenant_id, currency_code=currency_code, as_of=invoice_date, cache=rate_cache)
            decorated.append(
                {
                    "receipt_id": receipt_id,
                    "product_id": product_id,
                    "uom_id": uom_id,
                    "quantity": float(quantity),
                    "invoice_date": invoice_date.isoformat() if invoice_date else None,
                    "total_cost": float(total_cost),
                    "currency_code": currency_code,
                    "total_cost_base": float(total_cost) * rate,
                    "base_currency": BASE_CURRENCY,
                    "origin_country": origin_country,
                    "is_import": is_import,
                    "supplier_id": supplier_id,
                }
            )

        # (product_id, uom_id) -> running totals, to derive each row's "every OTHER receipt"
        # baseline by subtracting its own contribution back out.
        totals: dict[tuple[str, str], dict] = {}
        for row in decorated:
            key = (row["product_id"], row["uom_id"])
            bucket = totals.setdefault(key, {"quantity": 0.0, "cost_base": 0.0})
            bucket["quantity"] += row["quantity"]
            bucket["cost_base"] += row["total_cost_base"]

        for row in decorated:
            cost_per_unit_base = row["total_cost_base"] / row["quantity"] if row["quantity"] else 0.0
            bucket = totals[(row["product_id"], row["uom_id"])]
            baseline_quantity = bucket["quantity"] - row["quantity"]
            baseline_avg = (bucket["cost_base"] - row["total_cost_base"]) / baseline_quantity if baseline_quantity > 0 else None
            deviation_pct, is_anomaly = compute_cost_anomaly(cost_per_unit=cost_per_unit_base, baseline_avg_cost_per_unit=baseline_avg)
            row["cost_per_unit_base"] = cost_per_unit_base
            row["baseline_avg_cost_per_unit"] = baseline_avg
            row["cost_deviation_pct"] = deviation_pct
            row["is_cost_anomaly"] = is_anomaly

        return decorated

    def cost_summary(self, *, tenant_id: str) -> list[dict]:
        """Per (material, unit, origin, import-vs-local) landed cost, converted to
        BASE_CURRENCY so a Mali CFA receipt and a Turkiye EUR receipt for the same semoule
        are actually comparable -- averaging raw cost_per_unit across currencies was
        meaningless. Grouping includes uom_id too: a product ordered in tons on one order
        and kg on another must not have those cost_per_unit values blended, or the average
        is off by the unit ratio. Reports both the average and the best (lowest) cost/unit
        seen in the group, at line granularity, so "what's the cheapest this material has
        ever landed at" (point 5 of the MP cost plan) is answerable directly from this
        endpoint."""
        rows = self._connection.execute(
            """
            SELECT l.product_id, l.uom_id, r.origin_country, po.is_import, rl.quantity, rl.cost_per_unit,
                   r.currency_code, r.invoice_date, r.id
            FROM procurement.purchase_order_receipt_lines rl
            JOIN procurement.purchase_order_receipts r ON r.id = rl.purchase_order_receipt_id AND r.tenant_id = rl.tenant_id
            JOIN procurement.purchase_order_lines l ON l.id = rl.purchase_order_line_id AND l.tenant_id = rl.tenant_id
            JOIN procurement.purchase_orders po ON po.id = r.purchase_order_id AND po.tenant_id = r.tenant_id
            WHERE rl.tenant_id = %s AND r.status = 'confirmed'
            """,
            (tenant_id,),
        ).fetchall()

        rate_cache: dict = {}
        groups: dict[tuple[str, str, str | None, bool], dict] = {}
        for product_id, uom_id, origin_country, is_import, quantity, cost_per_unit, currency_code, invoice_date, receipt_id in rows:
            rate = self._base_currency_rate(tenant_id=tenant_id, currency_code=currency_code, as_of=invoice_date, cache=rate_cache)
            cost_per_unit_base = float(cost_per_unit) * rate
            key = (product_id, uom_id, origin_country, is_import)
            bucket = groups.setdefault(key, {"total_quantity": 0.0, "total_cost_base": 0.0, "best_cost_per_unit": None, "receipt_ids": set()})
            bucket["total_quantity"] += float(quantity)
            bucket["total_cost_base"] += float(quantity) * cost_per_unit_base
            if bucket["best_cost_per_unit"] is None or cost_per_unit_base < bucket["best_cost_per_unit"]:
                bucket["best_cost_per_unit"] = cost_per_unit_base
            bucket["receipt_ids"].add(receipt_id)

        return [
            {
                "product_id": product_id,
                "uom_id": uom_id,
                "origin_country": origin_country,
                "is_import": is_import,
                "total_quantity": bucket["total_quantity"],
                "average_cost_per_unit": bucket["total_cost_base"] / bucket["total_quantity"] if bucket["total_quantity"] else 0.0,
                "best_cost_per_unit": bucket["best_cost_per_unit"],
                "receipt_count": len(bucket["receipt_ids"]),
                "base_currency": BASE_CURRENCY,
            }
            for (product_id, uom_id, origin_country, is_import), bucket in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2] or ""))
        ]

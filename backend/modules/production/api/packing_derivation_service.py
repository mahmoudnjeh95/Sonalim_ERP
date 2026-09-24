"""Fills in what a packing row no longer asks the team to type.

A row names the product it packs. The OF comes from the shift's production (or the OF the row
already holds); from the product come the packing type, the packets its cartons make and the
finished-goods store; from each packaging item's default storage location, the stores stock
moves through. A figure the team did type (packets, a store) is never overwritten. A row that
names no product takes its OF's, and is refused only when it is handed in.
"""
from __future__ import annotations

import psycopg

from core.api.service import CoreService
from core.domain.result import Err, Ok, Result
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.domain.packaging_estimate import finished_quantity_from_count
from modules.production.domain.packing_derivation import (
    packing_type_label,
    pick_packaging_location,
    resolve_packing_order,
)

_PACKAGING_PRODUCTS = ("film_product_id", "carton_product_id", "tape_product_id", "scotch_product_id", "ruban_product_id")

_ORDER_PROBLEMS = {
    "PRODUCTION_FIRST": "packing row {n}: enter and save this shift's production first; a lot is filed under its work order",
    "OF_AMBIGUOUS": "packing row {n}: this shift ran several work orders; pick the OF for this lot",
}


def derive_packing_rows(connection: psycopg.Connection, *, tenant_id: str, shift_id: str, rows: list[dict]) -> Result[None]:
    """Complete the cleaned packing rows in place, or say why one cannot be saved."""
    core = CoreService(connection)
    classifications = ProductClassificationService(connection)
    # Packed goods wait in the line store, next to the production, until they are released;
    # with none set they go straight to the product's own store.
    line_store = DashboardSettingsService(connection).line_store_id(tenant_id=tenant_id)

    run_order: dict[str, str] = {}  # run id -> its work order
    runs_of_order: dict[str, list[str]] = {}  # work order -> its runs on this shift
    order_product: dict[str, str | None] = {}  # work order -> its own product
    for run_id, of_id, of_product in connection.execute(
        """
        SELECT r.id, r.of_id, w.product_id
        FROM production.shift_runs r
        JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
        WHERE r.tenant_id = %s AND r.shift_report_id = %s
        ORDER BY r.line_order, r.id
        """,
        (tenant_id, shift_id),
    ).fetchall():
        run_order[run_id] = of_id
        runs_of_order.setdefault(of_id, []).append(run_id)
        order_product.setdefault(of_id, of_product)

    def product_of_order(of_id: str) -> str | None:
        if of_id not in order_product:
            found = connection.execute(
                "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s", (of_id, tenant_id)
            ).fetchone()
            order_product[of_id] = found[0] if found else None
        return order_product[of_id]

    for index, row in enumerate(rows, start=1):
        of_id, problem = resolve_packing_order(
            given_of_id=row["of_id"],
            run_of_id=run_order.get(row["run_id"]) if row["run_id"] else None,
            shift_orders={of: order_product[of] for of in runs_of_order},
            product_id=row["product_id"],
        )
        if problem:
            return Err(problem, _ORDER_PROBLEMS[problem].format(n=index))
        row["of_id"] = of_id
        if not row["run_id"] and len(runs_of_order.get(of_id, [])) == 1:
            row["run_id"] = runs_of_order[of_id][0]
        if not row["product_id"]:
            row["product_id"] = product_of_order(of_id)

        product = core.get_product(tenant_id, row["product_id"]) if row["product_id"] else None
        if product is not None:
            classification = classifications.get_classification(tenant_id, row["product_id"])
            row["packing_type"] = packing_type_label(
                packaging_format=classification.packaging_format if classification else None,
                net_weight_grams=product.net_weight_grams,
            )
            if not row["packets_counted"]:
                row["packets_counted"] = finished_quantity_from_count(
                    packets_per_carton=product.packets_per_carton,
                    carton_quantity=row["carton_quantity"],
                    packets_counted=0.0,
                    waste_carton_quantity=row["waste_carton_quantity"],
                )
            if not row["finished_goods_location_id"]:
                row["finished_goods_location_id"] = line_store or product.default_location_id

        if not row["packaging_location_id"]:
            stores = []
            for column in _PACKAGING_PRODUCTS:
                item = core.get_product(tenant_id, row[column]) if row[column] else None
                if item is not None:
                    stores.append(item.default_location_id)
            location, conflict = pick_packaging_location(stores)
            if conflict:
                return Err(
                    "PACKAGING_STORES_DIFFER",
                    f"packing row {index}: its packaging items have different default storage locations; "
                    "packaging is taken from one store per row",
                )
            row["packaging_location_id"] = location
    return Ok(None)

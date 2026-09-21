"""Fills in what a packing row no longer asks the team to type.

A row names the production it comes from. From that run's work order and product the row
takes its OF and its packing type; from the product's own figures, the packets its cartons
make; from each item's default storage location, the stores stock moves through. A figure
the team did type (packets, a store) is never overwritten. A row without a run is an old
one: it keeps whatever it carries and is refused only when it is handed in.
"""
from __future__ import annotations

import psycopg

from core.api.service import CoreService
from core.domain.result import Err, Ok, Result
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.domain.packaging_estimate import finished_quantity_from_count
from modules.production.domain.packing_derivation import packing_type_label, pick_packaging_location

_PACKAGING_PRODUCTS = ("film_product_id", "carton_product_id", "tape_product_id", "scotch_product_id", "ruban_product_id")


def derive_packing_rows(connection: psycopg.Connection, *, tenant_id: str, shift_id: str, rows: list[dict]) -> Result[None]:
    """Complete the cleaned packing rows in place, or say why one cannot be saved."""
    core = CoreService(connection)
    classifications = ProductClassificationService(connection)
    # Packed goods wait in the line store, next to the production, until they are released;
    # with none set they go straight to the product's own store.
    line_store = DashboardSettingsService(connection).line_store_id(tenant_id=tenant_id)

    wanted = sorted({row["run_id"] for row in rows if row["run_id"]})
    runs: dict[str, tuple[str, str | None]] = {}
    if wanted:
        for run_id, of_id, product_id in connection.execute(
            """
            SELECT r.id, r.of_id, w.product_id
            FROM production.shift_runs r
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.shift_report_id = %s AND r.id = ANY(%s)
            """,
            (tenant_id, shift_id, wanted),
        ).fetchall():
            runs[run_id] = (of_id, product_id)

    for index, row in enumerate(rows, start=1):
        run = runs.get(row["run_id"]) if row["run_id"] else None
        if run is None:
            if not row["of_id"]:
                return Err("INVALID_VALUE", f"packing row {index}: pick the production this lot comes from")
            continue
        row["of_id"], product_id = run

        product = core.get_product(tenant_id, product_id) if product_id else None
        if product is not None:
            classification = classifications.get_classification(tenant_id, product_id)
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

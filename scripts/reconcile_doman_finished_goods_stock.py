"""One-off correction for three Doman finished-goods products whose
"Entrepôt Produits Finis" on-hand quantity was inflated by a report-validation
double-posting bug (see project notes on the OF double-post bug).

For doman-pl-500g, every validated production.conditionnement_reports row was
found posted to warehouse.stock_moves multiple times (as many as 7x for a
single report), while its legitimate one-off legacy production entries and a
non-conformity removal are real. This recomputes the correct on-hand as:

    sum(finished_quantity_from_count(...) for each VALIDATED conditionnement
        report, counted once) + legitimate legacy production - non-conformity
        removals

For doman-pc-500g and doman-pc-4540g-sac, no conditionnement report exists at
all in the current OF system -- their recorded on-hand (3 and 1000) comes
entirely from a handful of pre-rebuild legacy "work_order:<id>" stock moves
whose work orders no longer exist in production.work_orders and whose
fractional quantities (e.g. 0.75, 0.09) look like leftover tonnage figures
from before the piece-based conditionnement system, not real packet counts.
With no current OF evidence to support any packet count, this resets both to
0 rather than keep an unverifiable legacy figure.

Applies the correction through StockService.admin_set_stock -- the same
audited path the "Modifier > Editer directement" UI action uses -- so the
change lands in warehouse.stock_moves (admin_correction) and core.audit_log
exactly like a manual correction would.

Usage:
    DATABASE_URL=... python -m scripts.reconcile_doman_finished_goods_stock --tenant demo [--apply]

Without --apply, only prints the computed before/after values.
"""

from __future__ import annotations

import argparse

from core.db import get_connection
from modules.warehouse.api.service import StockService

FINISHED_GOODS_LOCATION_CODE = "produits-finis"


def finished_quantity_from_count(packets_per_carton, carton_quantity, packets_counted) -> float:
    if packets_per_carton and packets_per_carton > 0 and carton_quantity and carton_quantity > 0:
        return float(carton_quantity) * float(packets_per_carton)
    return float(packets_counted)


def correct_quantity_for_reported_product(connection, tenant_id: str, product_id: str) -> float:
    """Sum each validated conditionnement report's true output exactly once."""
    rows = connection.execute(
        """
        SELECT c.carton_quantity, c.packets_counted, c.snapshot_packets_per_carton
        FROM production.production_reports r
        JOIN production.conditionnement_reports c ON c.report_id = r.id
        JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
        WHERE r.tenant_id = %s AND w.product_id = %s AND r.report_type = 'conditionnement' AND r.status = 'validated'
        """,
        (tenant_id, product_id),
    ).fetchall()
    return sum(finished_quantity_from_count(ppc, carton_qty, packets_counted) for carton_qty, packets_counted, ppc in rows)


CORRECTIONS = [
    {
        "sku": "doman-pl-500g",
        # 310640 from validated reports (deduplicated) - 20 removed for a
        # non-conformity, + 0 legacy (its one legacy move references a work
        # order that no longer exists in production.work_orders).
        "compute": lambda connection, tenant_id, product_id: correct_quantity_for_reported_product(
            connection, tenant_id, product_id
        )
        - 20,
    },
    {
        "sku": "doman-pc-500g",
        # No conditionnement report exists for this product at all; its
        # current figure is entirely pre-rebuild legacy noise against deleted
        # work orders. No current OF evidence supports any non-zero figure.
        "compute": lambda connection, tenant_id, product_id: 0.0,
    },
    {
        "sku": "doman-pc-4540g-sac",
        "compute": lambda connection, tenant_id, product_id: 0.0,
    },
]


def run(tenant_id: str, apply: bool) -> None:
    with get_connection() as connection:
        location_row = connection.execute(
            "SELECT id FROM warehouse.locations WHERE tenant_id = %s AND code = %s",
            (tenant_id, FINISHED_GOODS_LOCATION_CODE),
        ).fetchone()
        if location_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no {FINISHED_GOODS_LOCATION_CODE!r} location")
        location_id = location_row[0]

        admin_user = connection.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (tenant_id,)
        ).fetchone()
        actor_id = admin_user[0]

        stock = StockService(connection)
        for correction in CORRECTIONS:
            sku = correction["sku"]
            product_row = connection.execute(
                "SELECT id FROM core.products WHERE tenant_id = %s AND sku = %s", (tenant_id, sku)
            ).fetchone()
            product_id = product_row[0]

            current = connection.execute(
                "SELECT quantity_on_hand, quantity_reserved, quantity_in_production FROM warehouse.stock_items "
                "WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
                (tenant_id, product_id, location_id),
            ).fetchone()
            before_on_hand = float(current[0]) if current else 0.0
            reserved = float(current[1]) if current else 0.0
            in_production = float(current[2]) if current else 0.0

            correct_on_hand = correction["compute"](connection, tenant_id, product_id)

            print(f"{sku}: on_hand {before_on_hand} -> {correct_on_hand} (reserved={reserved}, in_production={in_production} unchanged)")

            if apply:
                result = stock.admin_set_stock(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    location_id=location_id,
                    quantity_on_hand=correct_on_hand,
                    quantity_reserved=reserved,
                    quantity_in_production=in_production,
                    actor_id=actor_id,
                )
                if hasattr(result, "code"):
                    raise RuntimeError(f"failed to correct {sku}: {result.code} {result.message}")

        if apply:
            connection.commit()
            print("Committed.")
        else:
            connection.rollback()
            print("Dry run only -- pass --apply to write these corrections.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(args.tenant, args.apply)


if __name__ == "__main__":
    main()

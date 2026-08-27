"""One-off backfill: copies every warehouse.material_receipts row into the new procurement
schema (purchase_orders / purchase_order_lines / purchase_order_receipts /
purchase_order_receipt_lines), then the old table/service/router can be dropped.

This does NOT touch warehouse.stock_items or warehouse.stock_moves, and does NOT publish
procurement.purchase_order_receipt.confirmed. Stock for 'received'/'in_use' rows was already
posted once, historically, by the old MaterialReceiptService.mark_received code path -- this
script only gives that already-settled history a home in the new schema. Replaying it through
the live confirm_receipt() service/event flow would double-post that stock.

Status mapping (old -> new), each old receipt becomes a single-line purchase order:
    draft                        -> draft            (nothing received yet)
    confirmed                    -> validated
    sent                         -> approved
    in_transit, in_transport     -> ordered           (no equivalent transit sub-states in the
                                                        new model; both collapse to "ordered")
    received, in_use             -> fully_received    (quantity_received = quantity_ordered),
                                                        plus a confirmed purchase_order_receipt
                                                        carrying the landed-cost fields.
"in_use" (issued to production) has no purchase-order equivalent -- that consumption already
happened via warehouse.stock_moves and is untouched by this migration.

Each created purchase order's notes field records "Migrated from material_receipt <id>", which
this script also uses to detect and skip rows already migrated, so it is safe to re-run.

Usage:
    DATABASE_URL=... python -m scripts.migrate_material_receipts_to_procurement --tenant demo --actor-email demo@sonalim-erp.local
"""

from __future__ import annotations

import argparse
import sys

from ulid import ULID

from core.audit import record_audit
from core.db import get_connection
from modules.procurement.domain.entities import compute_landed_cost

_RECEIVED_STATUSES = {"received", "in_use"}

_ORDER_STATUS_MAP = {
    "draft": "draft",
    "confirmed": "validated",
    "sent": "approved",
    "in_transit": "ordered",
    "in_transport": "ordered",
    "received": "fully_received",
    "in_use": "fully_received",
}


def _lookup_user_id(connection, tenant_id: str, email: str) -> str | None:
    row = connection.execute("SELECT id FROM core.users WHERE tenant_id = %s AND email = %s", (tenant_id, email)).fetchone()
    return row[0] if row else None


def _already_migrated(connection, tenant_id: str, old_receipt_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM procurement.purchase_orders WHERE tenant_id = %s AND notes = %s",
        (tenant_id, f"Migrated from material_receipt {old_receipt_id}"),
    ).fetchone()
    return row is not None


def migrate(tenant_id: str, actor_email: str) -> None:
    migrated = 0
    skipped = 0

    with get_connection() as connection:
        actor_id = _lookup_user_id(connection, tenant_id, actor_email)
        if actor_id is None:
            raise SystemExit(f"no user with email {actor_email!r} in tenant {tenant_id!r}")

        rows = connection.execute(
            """
            SELECT id, product_id, location_id, supplier_id, status, invoice_number, invoice_date, received_at,
                   origin_country, quantity, uom_id, unit_price, unit_price_currency, base_cost, license_fee,
                   insurance_fee, transit_fee, transport_fee, customs_duty, carrier, total_cost, cost_per_unit,
                   created_at
            FROM warehouse.material_receipts
            WHERE tenant_id = %s
            ORDER BY created_at
            """,
            (tenant_id,),
        ).fetchall()

        for row in rows:
            (
                old_id, product_id, location_id, supplier_id, old_status, invoice_number, invoice_date, received_at,
                origin_country, quantity, uom_id, unit_price, unit_price_currency, base_cost, license_fee,
                insurance_fee, transit_fee, transport_fee, customs_duty, carrier, total_cost, cost_per_unit,
                created_at,
            ) = row

            if _already_migrated(connection, tenant_id, old_id):
                print(f"skipping {old_id}: already migrated")
                skipped += 1
                continue

            new_status = _ORDER_STATUS_MAP[old_status]
            was_received = old_status in _RECEIVED_STATUSES
            notes = f"Migrated from material_receipt {old_id}"

            order_id = str(ULID())
            connection.execute(
                """
                INSERT INTO procurement.purchase_orders
                    (id, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes, created_at)
                VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s)
                """,
                (order_id, tenant_id, supplier_id, new_status, created_at.date(), unit_price_currency, notes, created_at),
            )

            line_id = str(ULID())
            connection.execute(
                """
                INSERT INTO procurement.purchase_order_lines
                    (id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, quantity_received,
                     status, unit_price, unit_price_currency, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    line_id, tenant_id, order_id, product_id, uom_id, quantity,
                    quantity if was_received else 0,
                    "fully_received" if was_received else "pending",
                    unit_price, unit_price_currency, created_at,
                ),
            )

            if was_received:
                # Recomputed rather than trusted from the old row, so a migrated receipt is
                # provably consistent with the same landed-cost formula procurement uses now.
                cost_result = compute_landed_cost(
                    base_cost=float(base_cost), license_fee=float(license_fee), insurance_fee=float(insurance_fee),
                    transit_fee=float(transit_fee), transport_fee=float(transport_fee), customs_duty=float(customs_duty),
                    quantity=float(quantity),
                )
                recomputed_total_cost, recomputed_cost_per_unit = cost_result.value

                receipt_id = str(ULID())
                confirmed_at = received_at or created_at
                connection.execute(
                    """
                    INSERT INTO procurement.purchase_order_receipts
                        (id, tenant_id, purchase_order_id, location_id, status, invoice_number, invoice_date,
                         origin_country, carrier, base_cost, license_fee, insurance_fee, transit_fee, transport_fee,
                         customs_duty, total_cost, confirmed_at, created_at)
                    VALUES (%s, %s, %s, %s, 'confirmed', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        receipt_id, tenant_id, order_id, location_id, invoice_number, invoice_date, origin_country,
                        carrier, base_cost, license_fee, insurance_fee, transit_fee, transport_fee, customs_duty,
                        recomputed_total_cost, confirmed_at, created_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO procurement.purchase_order_receipt_lines
                        (id, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit)
                    VALUES (%s, %s, %s, %s, %s, NULL, %s)
                    """,
                    (str(ULID()), tenant_id, receipt_id, line_id, quantity, recomputed_cost_per_unit),
                )

            record_audit(
                connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="purchase_order.migrated_from_material_receipt",
                entity_type="purchase_order",
                entity_id=order_id,
                payload={"material_receipt_id": old_id, "old_status": old_status, "new_status": new_status},
            )
            connection.commit()
            migrated += 1
            print(f"migrated {old_id} -> purchase_order {order_id} ({old_status} -> {new_status})")

    print(f"\nMigrated {migrated}, skipped {skipped} (already migrated).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo", help="tenant_id to migrate (default: demo)")
    parser.add_argument("--actor-email", required=True, help="email of the user to record as the actor for every audit log entry")
    args = parser.parse_args()
    migrate(args.tenant, args.actor_email)


if __name__ == "__main__":
    sys.exit(main())

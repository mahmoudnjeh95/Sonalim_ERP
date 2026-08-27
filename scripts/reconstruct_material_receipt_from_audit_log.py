"""One-off incident recovery: modules/warehouse/migrations/0008_warehouse_drop_material_receipts.sql
was applied on 2026-08-26 without first running scripts/migrate_material_receipts_to_procurement.py,
so warehouse.material_receipts was dropped with 3 receipts still in it and never copied over.

core.audit_log preserves partial history for all 3:
  - 01M0SZ33PVT3KH7G8R34EHHY72: explicitly deleted by the user on 2026-08-24 (material_receipt.deleted).
    Not reconstructed here -- recreating a record the user intentionally deleted would be wrong.
  - 01M0VBF75B2CVTQ462BRKS3VB8: also explicitly deleted by the user (2026-08-25). Not reconstructed.
  - 01M0SRX22JVX4FCP6F0454BNHG: audit log only has its later status_changed events (in_transit ->
    in_transport -> received), no material_receipt.created row, so product/quantity/cost were never
    captured. Not reconstructable from audit log alone -- this one is genuinely lost.
  - 01M0VB2SBA1ZS549H0DKJ264XF: reconstructed below. Reached 'received' (stock was already posted to
    warehouse.stock_items back on 2026-08-25 and is untouched by the drop, so this script does NOT
    call the live confirm_receipt()/StockService flow -- that would double-post the stock. It only
    inserts historical rows directly, exactly like scripts/migrate_material_receipts_to_procurement.py
    does for settled history.

What's NOT recoverable for that one receipt (not captured in the audit payloads at all):
  supplier_id, location_id (guessed as the raw-materials location below), invoice_number/date,
  origin_country, carrier, and the individual landed-cost fee breakdown (only the total_cost survived,
  recorded here as base_cost with the other fee fields at zero).

Usage:
    DATABASE_URL=... python -m scripts.reconstruct_material_receipt_from_audit_log --tenant demo --actor-email demo@sonalim-erp.local
"""

from __future__ import annotations

import argparse
import datetime

from ulid import ULID

from core.audit import record_audit
from core.db import get_connection

OLD_RECEIPT_ID = "01M0VB2SBA1ZS549H0DKJ264XF"
PRODUCT_ID = "01M0SP0TEYJ5M7S5APB3V0F67V"  # semoule-ble-dur-salem
UOM_ID = "01M0SP0TEXPATTAHCGYPED9Y3A"  # ton
LOCATION_ID = "01M0SHXEGEW0B3Y2C45244WG3Q"  # raw-materials (best guess -- not captured in audit log)
QUANTITY = 24000.0
TOTAL_COST = 9045230356.65
CONFIRMED_AT = datetime.datetime(2026, 8, 25, 3, 13, 22, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
ORDER_DATE = datetime.date(2026, 8, 25)

NOTES = (
    f"Reconstructed from core.audit_log after material_receipt {OLD_RECEIPT_ID} was lost when "
    "warehouse.material_receipts was dropped on 2026-08-26 before the data migration ran. "
    "supplier/location/invoice/carrier and the landed-cost fee breakdown were not captured in the "
    "audit trail and are not recoverable; location is a best guess, cost is recorded as one lump sum."
)


def already_reconstructed(connection, tenant_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM procurement.purchase_orders WHERE tenant_id = %s AND notes = %s", (tenant_id, NOTES)
    ).fetchone()
    return row is not None


def reconstruct(tenant_id: str, actor_email: str) -> None:
    with get_connection() as connection:
        if already_reconstructed(connection, tenant_id):
            print("Already reconstructed -- nothing to do.")
            return

        actor_id = connection.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s AND email = %s", (tenant_id, actor_email)
        ).fetchone()
        if actor_id is None:
            raise SystemExit(f"no user with email {actor_email!r} in tenant {tenant_id!r}")
        actor_id = actor_id[0]

        order_id = str(ULID())
        connection.execute(
            """
            INSERT INTO procurement.purchase_orders
                (id, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes)
            VALUES (%s, %s, NULL, 'fully_received', %s, NULL, 'EUR', %s)
            """,
            (order_id, tenant_id, ORDER_DATE, NOTES),
        )

        line_id = str(ULID())
        connection.execute(
            """
            INSERT INTO procurement.purchase_order_lines
                (id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, quantity_received,
                 status, unit_price, unit_price_currency)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'fully_received', 0, 'EUR')
            """,
            (line_id, tenant_id, order_id, PRODUCT_ID, UOM_ID, QUANTITY, QUANTITY),
        )

        receipt_id = str(ULID())
        connection.execute(
            """
            INSERT INTO procurement.purchase_order_receipts
                (id, tenant_id, purchase_order_id, location_id, status, base_cost, license_fee, insurance_fee,
                 transit_fee, transport_fee, customs_duty, total_cost, confirmed_at)
            VALUES (%s, %s, %s, %s, 'confirmed', %s, 0, 0, 0, 0, 0, %s, %s)
            """,
            (receipt_id, tenant_id, order_id, LOCATION_ID, TOTAL_COST, TOTAL_COST, CONFIRMED_AT),
        )

        connection.execute(
            """
            INSERT INTO procurement.purchase_order_receipt_lines
                (id, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit)
            VALUES (%s, %s, %s, %s, %s, NULL, %s)
            """,
            (str(ULID()), tenant_id, receipt_id, line_id, QUANTITY, TOTAL_COST / QUANTITY),
        )

        record_audit(
            connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.reconstructed_from_audit_log",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={"source_material_receipt_id": OLD_RECEIPT_ID, "incident": "2026-08-26 premature material_receipts drop"},
        )
        connection.commit()
        print(f"Reconstructed purchase_order {order_id} (line {line_id}, receipt {receipt_id}) from {OLD_RECEIPT_ID}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--actor-email", required=True)
    args = parser.parse_args()
    reconstruct(args.tenant, args.actor_email)


if __name__ == "__main__":
    main()

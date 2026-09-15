"""One-off data script for the Sonalim Pasta tenant: records real purchase
orders (with prices) for the packaging/fuel suppliers, derived from the only
rows in the plant's April 2025 hand-built spreadsheets that actually had a
non-zero, non-blank "Coût en CFA"/"Prix unitaire" filled in -- most rows in
those sheets never had a price entered at all.

This gives ConsumptionReportService.list_monthly_consumption_by_supplier and
PurchaseOrderService.list_price_history something real to price against,
instead of every row showing unpriced.

Each order is pushed through the full lifecycle (draft -> validated ->
approved -> ordered -> receipt created -> confirmed), not left as a bare
draft, so it behaves like any other real order in the system. Prices are
recorded directly in XOF (CFA) -- the spreadsheet's own "(CFA)" columns say
these were never in another currency, unlike the EUR orders already in the
system for other materials.

One approximation, documented rather than hidden: the spreadsheet prices a
carton/film by which *finished pasta product* it packs (e.g. "Spagetti 1.2
Pasta Douman 500g"); our catalog only has generic PC/PL carton and film SKUs,
not one per pasta variant. Prices are attached to the closest matching
generic product instead.

Usage:
    DATABASE_URL=... python -m scripts.seed_packaging_price_history_april2025 --tenant demo
"""

from __future__ import annotations

import argparse
import datetime

from core.db import get_connection
from core.domain.result import Err
from modules.procurement.api.service import PurchaseOrderService

# supplier name -> (product sku, quantity, unit_price CFA), sourced from the
# April 2025 sheets' only filled-in rows.
_ORDERS: tuple[tuple[str, str, float, float], ...] = (
    ("LA ROCHETTE", "carton-pl-500g-b", 74455, 287.1115),
    ("SCS MDC", "carton-pc-500g", 41109, 415.0),
    ("CNP", "film-pl-laize-230mm", 10241.38, 2043.0177),
    ("CNP", "film-pc-laize-390mm", 2302.84, 2089.3206),
    ("RONZULLI", "film-pl-laize-230mm", 2845.03, 2825.404),
    ("RONZULLI", "film-pc-laize-390mm", 3825.40, 2470.5165),
    # Not a distinct XLS row -- Ronzulli's own PL price (above) reapplied to the
    # 390mm laize variant, since that's the one already in real conditionnement
    # report data rather than the 230mm variant guessed at first.
    ("RONZULLI", "film-pl-laize-390mm", 2845.03, 2825.404),
    ("Damoiseau", "ruban-tb200", 56, 18200.0),
    ("Damoiseau", "ruban-videojet", 200, 20220.0),
    ("Oryx", "fuel", 33870, 650.0),
)

_ORDER_DATE = datetime.date(2025, 4, 15)
_RECEIPT_LOCATION_CODE = "Other MP"


def _first_user(connection, tenant_id: str) -> str:
    row = connection.execute(
        "SELECT id FROM core.users WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (tenant_id,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"no user found for tenant {tenant_id!r}")
    return row[0]


def _supplier_id(connection, tenant_id: str, name: str) -> str:
    row = connection.execute(
        "SELECT id FROM core.partners WHERE tenant_id = %s AND name = %s", (tenant_id, name)
    ).fetchone()
    if row is None:
        raise SystemExit(f"supplier {name!r} not found -- run scripts.add_packaging_suppliers first")
    return row[0]


def _product(connection, tenant_id: str, sku: str) -> tuple[str, str]:
    row = connection.execute(
        "SELECT id, uom_id FROM core.products WHERE tenant_id = %s AND sku = %s", (tenant_id, sku)
    ).fetchone()
    if row is None:
        raise SystemExit(f"product {sku!r} not found")
    return row[0], row[1]


def _location_id(connection, tenant_id: str, code: str) -> str:
    row = connection.execute(
        "SELECT id FROM warehouse.locations WHERE tenant_id = %s AND code = %s", (tenant_id, code)
    ).fetchone()
    if row is None:
        raise SystemExit(f"location {code!r} not found")
    return row[0]


def run(tenant_id: str, actor_id: str | None) -> None:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        actor = actor_id or _first_user(connection, tenant_id)
        location_id = _location_id(connection, tenant_id, _RECEIPT_LOCATION_CODE)

        created: list[str] = []
        for supplier_name, sku, quantity, unit_price in _ORDERS:
            supplier_id = _supplier_id(connection, tenant_id, supplier_name)
            product_id, uom_id = _product(connection, tenant_id, sku)

            order = service.create_purchase_order(
                tenant_id=tenant_id, actor_id=actor, supplier_id=supplier_id,
                order_date=_ORDER_DATE, currency_code="XOF",
                lines=[
                    {
                        "product_id": product_id, "uom_id": uom_id, "quantity_ordered": quantity,
                        "unit_price": unit_price, "unit_price_currency": "XOF",
                    }
                ],
            )
            if isinstance(order, Err):
                print(f"  SKIP {supplier_name}/{sku}: {order.code} {order.message}")
                continue
            order_id = order.value.id

            for transition in (service.validate_order, service.approve_order, service.place_order):
                result = transition(tenant_id=tenant_id, actor_id=actor, order_id=order_id)
                if isinstance(result, Err):
                    print(f"  SKIP {supplier_name}/{sku}: {result.code} {result.message}")
                    break
            else:
                lines = service.list_lines(tenant_id=tenant_id, purchase_order_id=order_id)
                receipt = service.create_receipt(
                    tenant_id=tenant_id, actor_id=actor, purchase_order_id=order_id,
                    location_id=location_id, currency_code="XOF",
                    base_cost=quantity * unit_price,
                    lines=[{"purchase_order_line_id": lines[0].id, "quantity": quantity}],
                )
                if isinstance(receipt, Err):
                    print(f"  SKIP receipt {supplier_name}/{sku}: {receipt.code} {receipt.message}")
                    continue
                confirmed = service.confirm_receipt(
                    tenant_id=tenant_id, actor_id=actor, receipt_id=receipt.value.id, correlation_id=order_id,
                )
                if isinstance(confirmed, Err):
                    print(f"  SKIP confirm {supplier_name}/{sku}: {confirmed.code} {confirmed.message}")
                    continue
                created.append(f"{supplier_name} / {sku} @ {unit_price:.2f} CFA")
        connection.commit()

    print(f"Created and fulfilled {len(created)} purchase order(s):")
    for line in created:
        print(f"  {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--actor-id", default=None, help="Defaults to the tenant's first user.")
    args = parser.parse_args()
    run(args.tenant, args.actor_id)


if __name__ == "__main__":
    main()

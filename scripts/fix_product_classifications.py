"""One-off data fix for the Sonalim Pasta tenant's production classifications.

Two independent problems, fixed in one pass:

1. Some raw_material classifications were entered through the "Classifier un produit"
   dialog with the product's internal core.products id (a ULID) pasted into the
   product_id field instead of its sku — e.g. "01M0SP0TF14GFQXXQ5A6KK1VVP" instead of
   "semoule-fine-salem". This rewrites those rows to use the matching sku.
2. finished_good classifications (doman-pc-4540g-sac, etc.) were never registered as
   products in the core catalog, so the Warehouse module has nothing to track their
   stock against. This registers one core.products row per finished_good
   classification (uom "ea", net_weight_grams parsed from a trailing "<N>g" in the
   identifier when present) and ensures a "Produits finis" warehouse location exists.

Usage:
    DATABASE_URL=... python -m scripts.fix_product_classifications --tenant demo
"""

from __future__ import annotations

import argparse
import re

from ulid import ULID

from core.db import get_connection

FINISHED_GOODS_LOCATION_CODE = "produits-finis"
FINISHED_GOODS_LOCATION_NAME = "Entrepôt Produits Finis"

_WEIGHT_RE = re.compile(r"(\d+)g")


def fix_raw_material_identifiers(connection, tenant_id: str) -> list[tuple[str, str]]:
    """Rewrites classification rows keyed by an internal product id to use that product's sku."""
    rows = connection.execute(
        """
        SELECT pc.product_id, p.sku
        FROM production.product_classifications pc
        JOIN core.products p ON p.tenant_id = pc.tenant_id AND p.id = pc.product_id
        WHERE pc.tenant_id = %s AND pc.product_id != p.sku
        """,
        (tenant_id,),
    ).fetchall()

    fixed: list[tuple[str, str]] = []
    for internal_id, sku in rows:
        conflict = connection.execute(
            "SELECT 1 FROM production.product_classifications WHERE tenant_id = %s AND product_id = %s",
            (tenant_id, sku),
        ).fetchone()
        if conflict is not None:
            # A classification already exists under the correct sku — the ULID-keyed
            # row is a pure duplicate, drop it rather than overwrite the good row.
            connection.execute(
                "DELETE FROM production.product_classifications WHERE tenant_id = %s AND product_id = %s",
                (tenant_id, internal_id),
            )
        else:
            connection.execute(
                "UPDATE production.product_classifications SET product_id = %s WHERE tenant_id = %s AND product_id = %s",
                (sku, tenant_id, internal_id),
            )
        fixed.append((internal_id, sku))
    return fixed


def register_finished_goods(connection, tenant_id: str) -> list[str]:
    uom_row = connection.execute("SELECT id FROM core.uoms WHERE tenant_id = %s AND code = 'ea'", (tenant_id,)).fetchone()
    if uom_row is None:
        raise RuntimeError(f"tenant {tenant_id!r} has no 'ea' unit of measure — run scripts.seed_dev first")
    uom_id = uom_row[0]

    finished_goods = connection.execute(
        "SELECT DISTINCT product_id FROM production.product_classifications WHERE tenant_id = %s AND category = 'finished_good'",
        (tenant_id,),
    ).fetchall()

    created: list[str] = []
    for (product_id,) in finished_goods:
        exists = connection.execute(
            "SELECT 1 FROM core.products WHERE tenant_id = %s AND sku = %s", (tenant_id, product_id)
        ).fetchone()
        if exists is not None:
            continue
        weight_match = _WEIGHT_RE.search(product_id)
        net_weight_grams = float(weight_match.group(1)) if weight_match else None
        name = product_id.replace("-", " ").upper()
        connection.execute(
            """
            INSERT INTO core.products (id, tenant_id, sku, name, uom_id, net_weight_grams)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, sku) DO NOTHING
            """,
            (str(ULID()), tenant_id, product_id, name, uom_id, net_weight_grams),
        )
        created.append(product_id)
    return created


def ensure_finished_goods_location(connection, tenant_id: str) -> bool:
    existing = connection.execute(
        "SELECT 1 FROM warehouse.locations WHERE tenant_id = %s AND code = %s",
        (tenant_id, FINISHED_GOODS_LOCATION_CODE),
    ).fetchone()
    if existing is not None:
        return False
    connection.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
        (str(ULID()), tenant_id, FINISHED_GOODS_LOCATION_CODE, FINISHED_GOODS_LOCATION_NAME),
    )
    return True


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        fixed = fix_raw_material_identifiers(connection, tenant_id)
        created = register_finished_goods(connection, tenant_id)
        location_created = ensure_finished_goods_location(connection, tenant_id)
        connection.commit()

    if fixed:
        for internal_id, sku in fixed:
            print(f"  fixed identifiant: {internal_id} -> {sku}")
    print(f"Fixed {len(fixed)} classification identifier(s).")

    if created:
        for sku in created:
            print(f"  registered finished good: {sku}")
    print(f"Registered {len(created)} finished-good product(s) in core.products.")

    print(f"'{FINISHED_GOODS_LOCATION_NAME}' warehouse location {'created' if location_created else 'already existed'}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()

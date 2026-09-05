"""Read-only audit of unit-of-measure and quantity integrity across the tenant's data.

Reports, never fixes. Correcting any specific row this script surfaces is a
separate, human-reviewed follow-up (a physical stock count is a fact only a
person can supply; guessing at it here would risk corrupting real inventory
numbers) -- either a narrowly-scoped fix script modeled on
scripts/fix_product_classifications.py once the right values are known, or a
manual correction through the existing admin_set_stock / update_product
endpoints.

Five sections:

1. Fractional on-hand/reserved/in-production quantities for integer-only-UOM
   products (warehouse.stock_items) -- e.g. 3.07 "ea" of a carton-counted good.
2. Fractional stock-move quantities for integer-only-UOM products
   (warehouse.stock_moves), grouped by move_type.
3. Purchase order lines whose own uom_id is a different *category* than their
   product's own uom_id (procurement.purchase_order_lines) -- these may have
   already posted a wrong quantity to stock before the conversion fix landed.
4. Non-integer conforming_cartons/non_conforming_cartons
   (qc.quality_report_details) -- cartons are always a whole count.
5. Product master-data review flags -- products whose own UOM looks wrong
   (a fuel/water product counted in pièces, a semolina product that isn't in
   the same weight unit as its near-duplicates), found generically by grouping
   products on a normalized name prefix and flagging any group that disagrees
   on UOM category.

Usage:
    DATABASE_URL=... python -m scripts.audit_uom_quantity_integrity --tenant demo
"""

from __future__ import annotations

import argparse
import re

from core.db import get_connection

# Strips a trailing size/packaging token so near-duplicate products group
# together for section 5 -- e.g. "Doman PC 500gr" and "Doman PC 200gr" share
# the prefix "doman pc", but so do genuinely different products, so this is a
# heuristic grouping to review, not a verdict.
_TRAILING_SIZE_RE = re.compile(r"\s*\d+\s*(g|gr|kg|ml|l|mm|cm)\.?\s*$", re.IGNORECASE)


def _normalized_prefix(name: str) -> str:
    stripped = _TRAILING_SIZE_RE.sub("", name).strip().lower()
    return stripped or name.strip().lower()


def fractional_stock_items(connection, tenant_id: str) -> list[tuple]:
    return connection.execute(
        """
        SELECT p.sku, p.name, u.code, si.location_id, si.quantity_on_hand, si.quantity_reserved, si.quantity_in_production
        FROM warehouse.stock_items si
        JOIN core.products p ON p.id = si.product_id AND p.tenant_id = si.tenant_id
        JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
        WHERE si.tenant_id = %s AND u.is_integer_only
          AND (si.quantity_on_hand != round(si.quantity_on_hand)
               OR si.quantity_reserved != round(si.quantity_reserved)
               OR si.quantity_in_production != round(si.quantity_in_production))
        ORDER BY p.sku
        """,
        (tenant_id,),
    ).fetchall()


def fractional_stock_moves(connection, tenant_id: str) -> list[tuple]:
    return connection.execute(
        """
        SELECT p.sku, u.code, sm.quantity, sm.move_type, sm.created_at
        FROM warehouse.stock_moves sm
        JOIN core.products p ON p.id = sm.product_id AND p.tenant_id = sm.tenant_id
        JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
        WHERE sm.tenant_id = %s AND u.is_integer_only AND sm.quantity != round(sm.quantity)
        ORDER BY sm.move_type, sm.created_at DESC
        """,
        (tenant_id,),
    ).fetchall()


def mismatched_po_lines(connection, tenant_id: str) -> list[tuple]:
    return connection.execute(
        """
        SELECT p.sku, p.name, pu.code, pu.category, lu.code, lu.category, pol.quantity_ordered, pol.purchase_order_id
        FROM procurement.purchase_order_lines pol
        JOIN core.products p ON p.id = pol.product_id AND p.tenant_id = pol.tenant_id
        JOIN core.uoms pu ON pu.id = p.uom_id AND pu.tenant_id = p.tenant_id
        JOIN core.uoms lu ON lu.id = pol.uom_id AND lu.tenant_id = pol.tenant_id
        WHERE pol.tenant_id = %s AND lu.category != pu.category
        ORDER BY p.sku
        """,
        (tenant_id,),
    ).fetchall()


def non_integer_carton_details(connection, tenant_id: str) -> list[tuple]:
    return connection.execute(
        """
        SELECT qrd.report_id, qr.of_id, qrd.conforming_cartons, qrd.non_conforming_cartons
        FROM qc.quality_report_details qrd
        JOIN qc.quality_reports qr ON qr.id = qrd.report_id AND qr.tenant_id = qrd.tenant_id
        WHERE qrd.tenant_id = %s
          AND (qrd.conforming_cartons != round(qrd.conforming_cartons)
               OR qrd.non_conforming_cartons != round(qrd.non_conforming_cartons))
        ORDER BY qrd.report_id
        """,
        (tenant_id,),
    ).fetchall()


def product_uom_review_flags(connection, tenant_id: str) -> list[tuple]:
    rows = connection.execute(
        "SELECT p.sku, p.name, u.code, u.category FROM core.products p JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id WHERE p.tenant_id = %s ORDER BY p.name",
        (tenant_id,),
    ).fetchall()

    groups: dict[str, list[tuple]] = {}
    for sku, name, code, category in rows:
        groups.setdefault(_normalized_prefix(name), []).append((sku, name, code, category))

    flagged: list[tuple] = []
    for prefix, members in groups.items():
        categories = {category for *_rest, category in members}
        if len(members) > 1 and len(categories) > 1:
            flagged.append((prefix, members))
    return flagged


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        stock_items = fractional_stock_items(connection, tenant_id)
        stock_moves = fractional_stock_moves(connection, tenant_id)
        po_lines = mismatched_po_lines(connection, tenant_id)
        carton_details = non_integer_carton_details(connection, tenant_id)
        review_flags = product_uom_review_flags(connection, tenant_id)
        # Belt-and-suspenders: this script only ever SELECTs, but roll back
        # explicitly rather than letting `with get_connection()` commit
        # whatever the (empty) transaction happens to hold on exit.
        connection.rollback()

    print(f"=== UOM / quantity integrity audit -- tenant {tenant_id!r} ===\n")

    print("1. Fractional stock_items quantities for integer-only-UOM products")
    for sku, name, code, location_id, on_hand, reserved, in_production in stock_items:
        print(f"   {sku} ({name}) @ {location_id}: on_hand={on_hand} reserved={reserved} in_production={in_production} [{code}]")
    print(f"   Section 1: {len(stock_items)} row(s) found\n")

    print("2. Fractional stock_moves quantities for integer-only-UOM products")
    for sku, code, quantity, move_type, created_at in stock_moves:
        print(f"   {sku}: {quantity} {code} ({move_type}, {created_at:%Y-%m-%d %H:%M})")
    print(f"   Section 2: {len(stock_moves)} row(s) found\n")

    print("3. Purchase order lines whose unit category differs from their product's")
    for sku, name, product_code, product_category, line_code, line_category, quantity, order_id in po_lines:
        print(
            f"   {sku} ({name}): ordered {quantity} {line_code} ({line_category}), "
            f"product is tracked in {product_code} ({product_category}) -- PO {order_id}"
        )
    print(f"   Section 3: {len(po_lines)} row(s) found\n")

    print("4. Non-integer conforming_cartons / non_conforming_cartons")
    for report_id, of_id, conforming, non_conforming in carton_details:
        print(f"   report {report_id} (OF {of_id}): conforming={conforming} non_conforming={non_conforming}")
    if not carton_details:
        print("   0 rows -- no live cleanup needed here")
    print(f"   Section 4: {len(carton_details)} row(s) found\n")

    print("5. Product master-data review flags (same name prefix, disagreeing UOM category)")
    for prefix, members in review_flags:
        print(f"   \"{prefix}\":")
        for sku, name, code, category in members:
            print(f"      {sku} ({name}): {code} [{category}]")
    print(f"   Section 5: {len(review_flags)} group(s) flagged\n")

    print("Correcting any of the above is a separate, human-reviewed follow-up -- this script only reports.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()

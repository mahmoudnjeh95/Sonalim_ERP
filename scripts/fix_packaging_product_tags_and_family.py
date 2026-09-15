"""One-off data fix for the Sonalim Pasta tenant's packaging products.

The conditionnement report's Film/Carton/Ruban pickers show every product in the
catalog, because nothing in the data says "this product is a film" (as opposed to
a carton, a raw material, or a finished good) or "this carton is PC-only". This
fixes both:

1. Tags the packaging products by role, using core.product_tags/product_tag_links
   (the same tables the purchase-order screen already uses to match vendors to
   products). "FILM" already existed as a tag but was linked to the wrong product
   (fuel, not any actual film) -- this clears that stray link and tags every
   film/carton/scotch/ruban product correctly, creating "CARTON", "SCOTCH" and
   "RUBAN" tags as needed. SCOTCH and RUBAN used to be one combined "RUBAN" tag
   (matched by `ruban|scotch`) until the conditionnement report split scotch tape
   and printer ribbon into separate consumption fields -- see migration 0039.
2. Sets product_family to "PC" or "PL" on packaging products whose name says which
   pasta type they're for (e.g. "Carton PC 500g"), leaving it null on generic ones
   ("Carton standard") that apply to both -- product_family is free-text and
   unvalidated by design (see core/migrations/0021_core_product_family.sql), so
   this doesn't collide with its use on finished goods to group SKUs by pasta line.

Usage:
    DATABASE_URL=... python -m scripts.fix_packaging_product_tags_and_family --tenant demo
"""

from __future__ import annotations

import argparse
import re

from ulid import ULID

from core.db import get_connection

_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FILM", re.compile(r"film", re.IGNORECASE)),
    ("CARTON", re.compile(r"carton", re.IGNORECASE)),
    ("SCOTCH", re.compile(r"scotch", re.IGNORECASE)),
    ("RUBAN", re.compile(r"ruban", re.IGNORECASE)),
)
_FAMILY_RE = re.compile(r"\bP([CL])\b", re.IGNORECASE)


def ensure_tag(connection, tenant_id: str, name: str) -> str:
    row = connection.execute(
        "SELECT id FROM core.product_tags WHERE tenant_id = %s AND name = %s", (tenant_id, name)
    ).fetchone()
    if row is not None:
        return row[0]
    tag_id = str(ULID())
    connection.execute(
        "INSERT INTO core.product_tags (id, tenant_id, name) VALUES (%s, %s, %s)", (tag_id, tenant_id, name)
    )
    return tag_id


def tag_packaging_products(connection, tenant_id: str) -> list[tuple[str, str]]:
    tag_id_by_role = {role: ensure_tag(connection, tenant_id, role) for role, _ in _ROLE_PATTERNS}

    products = connection.execute("SELECT id, sku, name FROM core.products WHERE tenant_id = %s", (tenant_id,)).fetchall()

    linked: list[tuple[str, str]] = []
    for product_id, sku, name in products:
        role = next((role for role, pattern in _ROLE_PATTERNS if pattern.search(name)), None)
        # Every packaging role tag is mutually exclusive with the other two, so a
        # product not matching this role loses any stray link to it -- this is what
        # clears "fuel" from FILM, a bad manual assignment found while building this.
        for other_role, other_tag_id in tag_id_by_role.items():
            if other_role != role:
                connection.execute(
                    "DELETE FROM core.product_tag_links WHERE product_id = %s AND tag_id = %s", (product_id, other_tag_id)
                )
        if role is None:
            continue
        tag_id = tag_id_by_role[role]
        connection.execute(
            """
            INSERT INTO core.product_tag_links (product_id, tag_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (product_id, tag_id),
        )
        linked.append((sku, role))
    return linked


def set_packaging_family(connection, tenant_id: str) -> list[tuple[str, str]]:
    products = connection.execute(
        """
        SELECT p.id, p.sku, p.name
        FROM core.products p
        JOIN core.product_tag_links l ON l.product_id = p.id
        JOIN core.product_tags t ON t.id = l.tag_id AND t.tenant_id = %s
        WHERE p.tenant_id = %s AND t.name IN ('FILM', 'CARTON', 'SCOTCH', 'RUBAN')
        """,
        (tenant_id, tenant_id),
    ).fetchall()

    updated: list[tuple[str, str]] = []
    for product_id, sku, name in products:
        match = _FAMILY_RE.search(name)
        family = f"P{match.group(1).upper()}" if match else None
        connection.execute("UPDATE core.products SET product_family = %s WHERE id = %s", (family, product_id))
        if family is not None:
            updated.append((sku, family))
    return updated


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        linked = tag_packaging_products(connection, tenant_id)
        updated = set_packaging_family(connection, tenant_id)
        connection.commit()

    for sku, role in linked:
        print(f"  tagged {sku} -> {role}")
    print(f"Tagged {len(linked)} packaging product(s).")

    for sku, family in updated:
        print(f"  product_family {sku} -> {family}")
    print(f"Set product_family on {len(updated)} PC/PL-specific packaging product(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()

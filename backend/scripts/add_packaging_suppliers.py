"""One-off data script for the Sonalim Pasta tenant: adds the fournisseurs named
in the plant's monthly consumption spreadsheets (Carton, Film, Rub&Scotch,
Gasoil, Fuel) as core.partners, and tags the packaging ones so they show up as
suggested vendors on the matching packaging products -- see
scripts/fix_packaging_product_tags_and_family.py for how products get those
same FILM/CARTON/SCOTCH/RUBAN tags, and
core.api.service.CoreService.list_suggested_vendors_for_product for the
tag-matching query this feeds (a partner is suggested for a product when they
share a tag).

Also creates the two printer-ribbon products ("Ruban Imprimante TB200",
"Ruban Imprimante Videojet") tagged RUBAN, since neither exists in the catalog
yet -- DAMOISEAU supplies both per the Rub&Scotch sheet, and the ribbon model
(TB200 vs Videojet) is just which of these two the operator picks, not a
separate field (see modules/production/domain/production_report.py's
ConditionnementReportDetail.ruban_product_id).

Run scripts/fix_packaging_product_tags_and_family.py first -- this script
looks up the FILM/CARTON/SCOTCH/RUBAN tags by name and fails loudly if a role
it needs isn't there yet.

Usage:
    DATABASE_URL=... python -m scripts.add_packaging_suppliers --tenant demo
"""

from __future__ import annotations

import argparse

from core.api.service import CoreService
from core.db import get_connection
from core.domain.result import Err

# name -> role tags. Role tags match the product tags from
# fix_packaging_product_tags_and_family.py (FILM, CARTON, SCOTCH, RUBAN).
# Suppliers with no role tag (Gasoil/Fuel) are just added as general suppliers
# -- daily reports have no product association for fuel/gasoil to tag-match against.
_SUPPLIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SCS", ("CARTON",)),
    ("Rochette", ("CARTON",)),
    ("Maman Savon", ("CARTON",)),
    ("Safalim", ("CARTON",)),
    ("El Safa", ("CARTON",)),
    ("Ronzulli", ("FILM",)),
    ("TRB", ("FILM",)),
    ("CNP", ("FILM",)),
    ("Vee Dee", ("FILM",)),
    ("Printo Pack", ("FILM",)),
    ("Damoiseau", ("RUBAN",)),
    ("Oryx", ()),
    ("Toure Kounda", ()),
)

# sku -> (name, role tag). Neither ribbon model exists as a product yet.
_RUBAN_PRODUCTS: tuple[tuple[str, str], ...] = (
    ("ruban-tb200", "Ruban Imprimante TB200"),
    ("ruban-videojet", "Ruban Imprimante Videojet"),
)

_PIECE_UOM_CODE = "ea"


def _first_user(connection, tenant_id: str) -> str | None:
    row = connection.execute(
        "SELECT id FROM core.users WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (tenant_id,)
    ).fetchone()
    return row[0] if row else None


def _tag_id(connection, tenant_id: str, name: str) -> str:
    row = connection.execute(
        "SELECT id FROM core.product_tags WHERE tenant_id = %s AND name = %s", (tenant_id, name)
    ).fetchone()
    if row is None:
        raise SystemExit(f"tag {name!r} does not exist yet -- run fix_packaging_product_tags_and_family first")
    return row[0]

def _piece_uom_id(connection, tenant_id: str) -> str:
    row = connection.execute(
        "SELECT id FROM core.uoms WHERE tenant_id = %s AND code = %s", (tenant_id, _PIECE_UOM_CODE)
    ).fetchone()
    if row is None:
        raise SystemExit(f"no {_PIECE_UOM_CODE!r} UOM for tenant {tenant_id!r}")
    return row[0]


def add_ruban_products(connection, service: CoreService, tenant_id: str, actor_id: str) -> list[str]:
    uom_id = _piece_uom_id(connection, tenant_id)
    ruban_tag_id = _tag_id(connection, tenant_id, "RUBAN")
    created: list[str] = []
    for sku, name in _RUBAN_PRODUCTS:
        existing = connection.execute(
            "SELECT id FROM core.products WHERE tenant_id = %s AND sku = %s", (tenant_id, sku)
        ).fetchone()
        if existing is not None:
            product_id = existing[0]
        else:
            # product_type is a required pasta-shape enum that means nothing for a
            # consumable -- 'PL' here matches the filler value already used on the
            # tenant's other non-pasta packaging products (carton, film, scotch).
            result = service.create_product(
                tenant_id=tenant_id, actor_id=actor_id, sku=sku, name=name,
                product_type="PL", uom_id=uom_id, is_sellable=False, is_purchasable=True,
            )
            if isinstance(result, Err):
                print(f"  SKIP product {name}: {result.code} {result.message}")
                continue
            product_id = result.value.id
            created.append(name)
        service.set_product_tags(tenant_id=tenant_id, actor_id=actor_id, product_id=product_id, tag_ids=[ruban_tag_id])
    return created


def add_suppliers(connection, service: CoreService, tenant_id: str, actor_id: str) -> tuple[list[str], list[tuple[str, tuple[str, ...]]]]:
    tag_ids = {role: _tag_id(connection, tenant_id, role) for _, roles in _SUPPLIERS for role in roles}

    created: list[str] = []
    tagged: list[tuple[str, tuple[str, ...]]] = []
    for name, roles in _SUPPLIERS:
        existing = connection.execute(
            "SELECT id FROM core.partners WHERE tenant_id = %s AND lower(name) = lower(%s)", (tenant_id, name)
        ).fetchone()
        if existing is None:
            result = service.create_partner(tenant_id=tenant_id, actor_id=actor_id, name=name, kind="supplier")
            if isinstance(result, Err):
                print(f"  SKIP {name}: {result.code} {result.message}")
                continue
            partner_id = result.value.id
            created.append(name)
        else:
            partner_id = existing[0]
        if not roles:
            continue
        current = connection.execute(
            "SELECT tag_id FROM core.partner_tag_links WHERE partner_id = %s", (partner_id,)
        ).fetchall()
        wanted = {tag_ids[role] for role in roles} | {row[0] for row in current}
        result = service.set_partner_tags(tenant_id=tenant_id, actor_id=actor_id, partner_id=partner_id, tag_ids=list(wanted))
        if isinstance(result, Err):
            print(f"  SKIP tagging {name}: {result.code} {result.message}")
            continue
        tagged.append((name, roles))
    return created, tagged


def run(tenant_id: str, actor_id: str | None) -> None:
    with get_connection() as connection:
        service = CoreService(connection)
        actor = actor_id or _first_user(connection, tenant_id)
        if actor is None:
            raise SystemExit(f"no user found for tenant {tenant_id!r} -- pass --actor-id explicitly")

        created_products = add_ruban_products(connection, service, tenant_id, actor)
        created_partners, tagged = add_suppliers(connection, service, tenant_id, actor)
        connection.commit()

    print(f"Created {len(created_products)} ruban product(s): {', '.join(created_products) or '(none, already existed)'}")
    print(f"Created {len(created_partners)} new supplier(s): {', '.join(created_partners) or '(none, all already existed)'}")
    print(f"Tagged {len(tagged)} supplier(s):")
    for name, roles in tagged:
        print(f"  {name} -> {', '.join(roles)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--actor-id", default=None, help="Defaults to the tenant's first user.")
    args = parser.parse_args()
    run(args.tenant, args.actor_id)


if __name__ == "__main__":
    main()

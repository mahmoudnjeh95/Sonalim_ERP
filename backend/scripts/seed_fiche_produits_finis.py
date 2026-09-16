"""One-off data load: registers the 24 finished-good pasta products from the
"fiche produit fini" (packaging spec sheet) into core.products.

Field mapping from the sheet to core.products columns:
  Produit                        -> product_family (grouping label, e.g. "Spaghetti 1,1")
  Designation                    -> name (e.g. "Spaghetti 1,1 200g")
  Grammage(g)                    -> net_weight_grams
  Poids d'emballage Vide(g)/pcs  -> empty_packaging_weight_grams (already grams, no conversion)
  nombre de sachet/paquet        -> sachets_per_package
  Nobre de paquet/palette        -> cartons_per_pallet (the sheet's "paquet" is the same physical
                                     box as "carton" elsewhere on the sheet -- verified by cross-
                                     checking "Poid de carton" == sachets_per_package * grammage)
  Poid de carton                 -> carton_weight_grams, converted kg -> g (sheet is in kg: e.g.
                                     Spaghetti 1,1/200g: 40 sachets x 200g = 8000g = "8" on the sheet)
  Type                           -> product_type (PL/PC)

Columns NOT stored (pure reporting ratios, recomputed live wherever needed instead of
duplicated in the DB): Nombre de palette/Tonne, Quantite de sachet/tonne, Poids
d'emballage/tonne.

packets_per_carton is left NULL for all these rows -- the sheet has no separate
"packet inside carton" tier; sachets go directly into the carton (the sheet's "paquet").

selling_price / purchase_price are not on the sheet and are left at 0 (default);
uom_id is "ea" (Piece) since each SKU sells as one packaged unit, not by weight.

Usage:
    DATABASE_URL=... python -m scripts.seed_fiche_produits_finis --tenant demo
"""

from __future__ import annotations

import argparse

from core.api.service import CoreService
from core.db import get_connection
from core.domain.result import Err

# family, designation_suffix, net_weight_g, empty_pkg_g, sachets_per_package, cartons_per_pallet, carton_kg, product_type, sku
ROWS = [
    ("Spaghetti 1,1", "200g", 200, 3, 40, 80, 8, "PL", "SPAG-11-200G"),
    ("Spaghetti 1,1", "500g", 500, 4, 20, 100, 10, "PL", "SPAG-11-500G"),
    ("Spaghetti 1,2", "200g", 200, 3, 40, 80, 8, "PL", "SPAG-12-200G"),
    ("Spaghetti 1,2", "500g", 500, 4, 20, 100, 10, "PL", "SPAG-12-500G"),
    ("Toursade", "200g", 200, 3.5, 40, 80, 8, "PC", "TOUR-200G"),
    ("Toursade", "500g", 500, 5.5, 20, 70, 10, "PC", "TOUR-500G"),
    ("Toursade", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "TOUR-4540G"),
    ("Escargot moyenne", "200g", 200, 3.5, 40, 80, 8, "PC", "ESCM-200G"),
    ("Escargot moyenne", "500g", 500, 5.5, 20, 70, 10, "PC", "ESCM-500G"),
    ("Escargot moyenne", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "ESCM-4540G"),
    ("Coquiette N7", "200g", 200, 3.5, 40, 80, 8, "PC", "COQ7-200G"),
    ("Coquiette N7", "500g", 500, 5.5, 20, 70, 10, "PC", "COQ7-500G"),
    ("Coquiette N7", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "COQ7-4540G"),
    ("Vermicelle", "500g", 500, 5.5, 20, 70, 10, "PC", "VERM-500G"),
    ("Vermicelle", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "VERM-4540G"),
    ("Coquiette N6", "500g", 500, 5.5, 20, 70, 10, "PC", "COQ6-500G"),
    ("Coquiette N6", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "COQ6-4540G"),
    ("Long oiseau", "500g", 500, 3, 20, 80, 10, "PC", "LOIS-500G"),
    ("Long oiseau", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "LOIS-4540G"),
    ("Annelini", "500g", 500, 3, 20, 80, 10, "PC", "ANNE-500G"),
    ("Annelini", "4540g", 4540, 42.5, 1, 100, 4.54, "PC", "ANNE-4540G"),
    # NOTE: carton_kg for these last two "Pate courte" rows is transcribed exactly as shown
    # on the source sheet (10 for 200g, 8 for 500g) even though it breaks the
    # sachets_per_package x grammage pattern every other row follows (200g should be ~8,
    # 500g should be ~10) -- looks like a swap in the source data. Flagged for the user to
    # verify against the original sheet rather than silently "corrected" here.
    ("Pate courte", "200g", 200, 3.5, 40, 80, 10, "PC", "PC-200G"),
    ("Pate courte", "500g", 500, 5.5, 20, 70, 8, "PC", "PC-500G"),
    ("Pate courte", "4540g", 4540, 42.6, 1, 100, 4.54, "PC", "PC-4540G"),
]


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        uom_row = connection.execute(
            "SELECT id FROM core.uoms WHERE tenant_id = %s AND code = 'ea'", (tenant_id,)
        ).fetchone()
        if uom_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no 'ea' unit of measure")
        uom_id = uom_row[0]

        user_row = connection.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (tenant_id,)
        ).fetchone()
        if user_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no users to attribute this import to")
        actor_id = user_row[0]

        service = CoreService(connection)
        created: list[str] = []
        skipped: list[str] = []
        for family, suffix, net_g, empty_pkg_g, sachets_per_pkg, cartons_per_pallet, carton_kg, product_type, sku in ROWS:
            existing = connection.execute(
                "SELECT 1 FROM core.products WHERE tenant_id = %s AND sku = %s", (tenant_id, sku)
            ).fetchone()
            if existing is not None:
                skipped.append(sku)
                continue

            result = service.create_product(
                tenant_id=tenant_id,
                actor_id=actor_id,
                sku=sku,
                name=f"{family} {suffix}",
                product_type=product_type,
                product_family=family,
                uom_id=uom_id,
                net_weight_grams=net_g,
                empty_packaging_weight_grams=empty_pkg_g,
                sachets_per_package=sachets_per_pkg,
                cartons_per_pallet=cartons_per_pallet,
                carton_weight_grams=carton_kg * 1000,
            )
            if isinstance(result, Err):
                raise RuntimeError(f"failed to create {sku}: {result.code} {result.message}")
            created.append(sku)

        connection.commit()

    for sku in created:
        print(f"  created: {sku}")
    for sku in skipped:
        print(f"  skipped (already exists): {sku}")
    print(f"\nCreated {len(created)} product(s), skipped {len(skipped)} already present, out of {len(ROWS)} total.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()

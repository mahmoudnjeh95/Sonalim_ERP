"""Seeds the UoMs and Product catalog entries needed to record real Sonalim Pasta
purchases (raw material, cardboard, film) — no prices or quantities, catalog data only.

Usage:
    DATABASE_URL=... python -m scripts.seed_sonalim_products --tenant demo
"""

from __future__ import annotations

import argparse

from ulid import ULID

from core.db import get_connection

UOMS = [
    ("kg", "Kilogramme", "weight", 1),
    ("ton", "Tonne", "weight", 1000),
    ("ea", "Pièce", "unit", 1),
    ("l", "Litre", "volume", 1),
    ("m", "Mètre", "length", 1),
]

SUPPLIERS = [
    "SAVON MALI SARL",
    "LA ROCHETTE",
    "S.P.P.M",
    "SCS MDC",
    "TRB Group",
    "Regner IMPEX",
    "Print Active",
    "RONZULLI",
    "CNP",
]

PRODUCTS = [
    ("semoule-ble-dur-salem", "Semoule Blé Dur SALEM", "ton"),
    ("semoule-ble-dur-salem-tn", "Semoule Blé Dur SALEM TN", "ton"),
    ("semoule-extra-fine-salem", "Semoule Extra Fine SALEM", "ton"),
    ("semoule-fine-salem", "Semoule Fine SALEM", "ton"),
    ("carton-pl-500g-b", "Carton PL 500g B", "ea"),
    ("carton-pl-500g-c", "Carton PL 500g C", "ea"),
    ("carton-pc-500g", "Carton PC 500g", "ea"),
    ("film-pl-laize-390mm", "Film PL Laize 390mm", "kg"),
    ("film-pl-laize-230mm", "Film PL Laize 230mm", "kg"),
    ("film-pc-laize-230mm", "Film PC Laize 230mm", "kg"),
    ("film-pc-laize-390mm", "Film PC Laize 390mm", "kg"),
]


def seed(tenant_id: str) -> None:
    with get_connection() as connection:
        for code, name, category, ratio_to_base in UOMS:
            connection.execute(
                """
                INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base, is_integer_only)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO UPDATE SET name = EXCLUDED.name
                """,
                (str(ULID()), tenant_id, code, name, category, ratio_to_base, category == "unit"),
            )

        uom_ids = {
            code: connection.execute(
                "SELECT id FROM core.uoms WHERE tenant_id = %s AND code = %s", (tenant_id, code)
            ).fetchone()[0]
            for code in {"ea", "kg", "ton"}
        }

        for name in SUPPLIERS:
            connection.execute(
                """
                INSERT INTO core.partners (id, tenant_id, name, kind)
                VALUES (%s, %s, %s, 'supplier')
                ON CONFLICT (tenant_id, name) DO NOTHING
                """,
                (str(ULID()), tenant_id, name),
            )

        for sku, name, uom_code in PRODUCTS:
            connection.execute(
                """
                INSERT INTO core.products (id, tenant_id, sku, name, uom_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, sku) DO NOTHING
                """,
                (str(ULID()), tenant_id, sku, name, uom_ids[uom_code]),
            )
        connection.commit()

    print(f"Seeded {len(UOMS)} UoMs, {len(SUPPLIERS)} suppliers, and {len(PRODUCTS)} products for tenant {tenant_id!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    seed(args.tenant)


if __name__ == "__main__":
    main()

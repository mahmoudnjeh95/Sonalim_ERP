"""Seeds spare parts for the maintenance checkpoint walkthrough. Dev-only.

    .venv/Scripts/python -m scripts.seed_spare_parts

Run after `scripts.seed_dev` (which creates the "Pièces de rechange" location) and
`scripts.seed_maintenance` (the demo machines and their checkpoints). It:

- adds two shelves under "Pièces de rechange" (Étagère A, Étagère B);
- creates six spare parts with French names, their default location set to
  "Pièces de rechange", and receives their stock onto the shelves (one part is
  left at zero, to show an out-of-stock part);
- names "Pièces de rechange" as the maintenance spare-parts location;
- lists parts on the demo checkpoints that have none yet.

Idempotent: an existing shelf (by code), product (by SKU) or setting is left as
it is, and a checkpoint that already lists parts is not touched. Products and
stock go through the shared kernel's and the warehouse's public services.
"""
from __future__ import annotations

from ulid import ULID

from core.api.service import CoreService
from core.db import get_connection
from core.domain.result import Err
from modules.maintenance.api.map_service import MapService
from modules.maintenance.api.spare_parts_service import SparePartsService
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService

TENANT = "demo"
DEMO_EMAIL = "demo@sonalim-erp.local"
STORE_CODE = "spare-parts"

SHELVES = [("spare-parts-a", "Étagère A"), ("spare-parts-b", "Étagère B")]

# sku, name, unit code, shelf code (None: the store itself), quantity received
PARTS = [
    ("PDR-ROUL-6204", "Roulement 6204-2RS", "ea", "spare-parts-a", 6),
    ("PDR-COUR-SPZ1250", "Courroie trapézoïdale SPZ 1250", "ea", "spare-parts-a", 3),
    ("PDR-GRAISSE-H1", "Graisse alimentaire NSF H1", "kg", "spare-parts-b", 4.5),
    ("PDR-JOINT-50", "Joint torique Ø 50 mm", "ea", "spare-parts-b", 20),
    ("PDR-FUS-10A", "Fusible 10 A", "ea", None, 12),
    ("PDR-FILTRE-HYD", "Filtre à huile hydraulique", "ea", None, 0),
]

# checkpoint label -> [(sku, quantity)]
CHECKPOINT_PARTS = {
    "Graissage palier": [("PDR-GRAISSE-H1", 0.2)],
    "Courroie d'entraînement": [("PDR-COUR-SPZ1250", 1)],
    "Nettoyage trémie": [("PDR-JOINT-50", 2)],
    "Serrage fixations": [("PDR-ROUL-6204", 2), ("PDR-FUS-10A", 1)],
    "État général": [("PDR-FILTRE-HYD", 1)],
}


def _ok(result, context: str):
    if isinstance(result, Err):
        raise SystemExit(f"{context}: {result.code} {result.message}")
    return result.value


def seed() -> None:
    with get_connection() as connection:
        actor = connection.execute("SELECT id FROM core.users WHERE email = %s", (DEMO_EMAIL,)).fetchone()
        if actor is None:
            raise SystemExit("demo user not found: run scripts.seed_dev first")
        actor_id = actor[0]

        locations = LocationService(connection)
        by_code = {location.code: location for location in locations.list_locations(tenant_id=TENANT)}
        store = by_code.get(STORE_CODE)
        if store is None:
            raise SystemExit(f"location {STORE_CODE!r} not found: run scripts.seed_dev first")

        for code, name in SHELVES:
            if code not in by_code:
                by_code[code] = _ok(
                    locations.create_location(
                        tenant_id=TENANT, actor_id=actor_id, code=code, name=name,
                        site_id=store.site_id, parent_location_id=store.id,
                    ),
                    f"create shelf {name}",
                )
                print(f"shelf: {name}")

        core = CoreService(connection)
        stock = StockService(connection)
        units = {uom.code: uom.id for uom in core.list_uoms(TENANT)}
        product_by_sku: dict[str, str] = {}
        for sku, name, unit, shelf, quantity in PARTS:
            existing = connection.execute(
                "SELECT id FROM core.products WHERE tenant_id = %s AND sku = %s", (TENANT, sku)
            ).fetchone()
            if existing is not None:
                product_by_sku[sku] = existing[0]
                continue
            # product_type is a required pasta-line field with no neutral value; PL is its default.
            product = _ok(
                core.create_product(
                    tenant_id=TENANT, actor_id=actor_id, sku=sku, name=name, product_type="PL",
                    uom_id=units[unit], is_sellable=False, default_location_id=store.id,
                ),
                f"create product {name}",
            )
            product_by_sku[sku] = product.id
            if quantity:
                _ok(
                    stock.receive_stock(
                        tenant_id=TENANT, product_id=product.id, location_id=by_code[shelf or STORE_CODE].id,
                        quantity=quantity, correlation_id=str(ULID()), reference="seed:spare-parts", actor_id=actor_id,
                    ),
                    f"receive {name}",
                )
            print(f"part: {name} ({quantity} {unit})")

        spare = SparePartsService(connection)
        if spare.settings(TENANT)["spare_parts_location_id"] is None:
            _ok(spare.set_location(tenant_id=TENANT, actor_id=actor_id, location_id=store.id), "set spare-parts location")
            print(f"spare-parts location: {store.name}")

        maps = MapService(connection)
        rows = connection.execute(
            """
            SELECT c.id, c.label FROM maintenance.checkpoints c
            WHERE c.tenant_id = %s AND c.archived_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM maintenance.checkpoint_parts cp WHERE cp.checkpoint_id = c.id)
            """,
            (TENANT,),
        ).fetchall()
        for checkpoint_id, label in rows:
            wanted = CHECKPOINT_PARTS.get(label)
            if not wanted:
                continue
            _ok(
                maps.update_checkpoint(
                    tenant_id=TENANT, actor_id=actor_id, checkpoint_id=checkpoint_id,
                    parts=[{"product_id": product_by_sku[sku], "quantity": quantity} for sku, quantity in wanted],
                ),
                f"parts on {label}",
            )
            print(f"checkpoint parts: {label}")

        connection.commit()
    print("done")


if __name__ == "__main__":
    seed()

"""Brings the catalog in line with the plant's product list ("19-liste mp, film, carton, PF"):
raw materials (semoules), film and carton types per supplier, and finished products (PL/PC).

    # Preview (everything runs, then is rolled back):
    DATABASE_URL=... python -m scripts.seed_client_product_list
    docker compose exec -T app python -m scripts.seed_client_product_list
    # Keep it:
    ... python -m scripts.seed_client_product_list --commit

What it does, in one transaction:
  * RENAMES the existing products that are on the list (matched by SKU; same id, so
    stock, OFs, shift rows and purchase orders stay attached). Only name and family
    change -- classification, weights and stores are left as they are.
  * CREATES the list's products that do not exist yet (matched by SKU, then by name).
    Each new product copies its unit, default store, carton specs and production
    classification from a named TEMPLATE product of the same kind and weight.
  * Creates the missing suppliers (matched case-insensitively, aliases below) and tags
    every carton supplier CARTON and every film supplier FILM, so they are suggested on
    those items.
  * DELETES the old film items made from the carton list (before the plant's own film
    list, 2026-10-05) when nothing references them; any still in use are kept and listed.

Nothing else is deleted. Products that are not on the list (Spaghetti 1,1, Pate courte,
Doman..., Annelini/Long oiseau 4540g, the old Film ... Laize / Carton PL 500g B|C
items) are left untouched. Running it twice changes nothing the second time.

Name decisions (2026-09-25, with the user): "Spagetti" is written "Spaghetti" and
"Fne" is written "Fine"; film and carton items carry their supplier in the name,
because the shift form picks a film/carton TYPE and has no supplier column.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

from core.api.service import CoreService
from core.db import get_connection
from core.domain.result import Err
from modules.production.api.product_classification_service import ProductClassificationService

# --- Finished products -------------------------------------------------------------
# sku -> (name, family). Existing SKUs are renamed; the others are created from TEMPLATES.
FINISHED: tuple[tuple[str, str, str], ...] = (
    ("SPAG-12-500G", "Pâte Longue 1.2 PASTA DOUMAN 500gr", "Spaghetti 1.2 Pasta Douman"),
    ("SPAG-12-200G", "Pâte Longue 1.2 PASTA DOUMAN 200gr", "Spaghetti 1.2 Pasta Douman"),
    ("PRIMA-12-500G", "Pâte Longue 1.2 PASTA PRIMA 500gr", "Spaghetti 1.2 Pasta Prima"),
    ("PRIMA-12-200G", "Pâte Longue 1.2 PASTA PRIMA 200gr", "Spaghetti 1.2 Pasta Prima"),
    ("COQ7-500G", "Pâte Courte Coquillettes N°7 500gr", "Coquillettes N°7"),
    ("TOUR-500G", "Pâte Courte Torsadés 500gr", "Torsadés"),
    ("ESCM-500G", "Pâte Courte Escargots Moyens 500gr", "Escargots Moyens"),
    ("VERM-500G", "Pâte Courte vermicelles 500gr", "Vermicelles"),
    ("COQ6-500G", "Pâte Courte Coquillettes N° 6 500gr", "Coquillettes N°6"),
    ("COQ4-500G", "Pâte Courte Coquillettes N° 4 500gr", "Coquillettes N°4"),
    ("LOIS-500G", "Pâte Courte langue d'oiseau 500gr", "Langue d'oiseau"),
    ("ANNE-500G", "Pâte Courte annelinis 500gr", "Annelinis"),
    ("BATL-500G", "Pâte Courte Batons long 500gr", "Batons long"),
    ("PLUM-500G", "Pâte Courte Plûme long 500gr", "Plûme long"),
    ("COQ7-200G", "Pâte Courte Coquillettes N°7 200gr", "Coquillettes N°7"),
    ("TOUR-200G", "Pâte Courte Torsadés 200gr", "Torsadés"),
    ("ESCM-200G", "Pâte Courte Escargots Moyens 200gr", "Escargots Moyens"),
    ("VERM-200G", "Pâte Courte vermicelles 200gr", "Vermicelles"),
    ("COQ6-200G", "Pâte Courte Coquillettes N° 6 200gr", "Coquillettes N°6"),
    ("COQ7-4540G", "Pâte Courte Coquillettes N°7 4540gr", "Coquillettes N°7"),
    ("TOUR-4540G", "Pâte Courte Torsadés 4540gr", "Torsadés"),
    ("ESCM-4540G", "Pâte Courte Escargots Moyens 4540gr", "Escargots Moyens"),
    ("VERM-4540G", "Pâte Courte vermicelles 4540gr", "Vermicelles"),
    ("COQ6-4540G", "Pâte Courte Coquillettes N° 6 4540gr", "Coquillettes N°6"),
)

# --- Raw materials -----------------------------------------------------------------
# sku -> name. The first six already exist (renamed); the last three are created.
RAW: tuple[tuple[str, str], ...] = (
    ("semoule-ble-dur-salem", "Semoule Ble Dure SALEM Blé dure 1 (Turquie)"),
    ("Blé_dure_SALEM_Turkey", "Semoule Ble Dure SALEM Blé dure 2 (Turquie)"),
    ("semoule-extra-fine-salem", "Semoule Ble Dure SALEM Extra Fine (Turquie)"),
    ("semoule-ble-dur-salem-tn", "Semoule Blé dure SALEM (Tunisie)"),
    ("semoule-fine-salem", "Semoule Blé dure SALEM Fine Doree (Tunisie)"),
    ("REBROYAT-SEMOULE", "Semoule rébroyé"),
    ("semoule-salem-ble-dure-3-tr", "Semoule Ble Dure SALEM Blé dure 3 (Turquie)"),
    ("semoule-salem-ble-dure-4-tr", "Semoule Ble Dure SALEM Blé dure 4 (Turquie)"),
    ("semoule-salem-extra-fine-eg", "Semoule Ble Dure SALEM Extra Fine (Egypte)"),
)

# New product sku -> existing product it copies unit, store, carton specs and classification from.
TEMPLATES: dict[str, str] = {
    "PRIMA-12-500G": "SPAG-12-500G",
    "PRIMA-12-200G": "SPAG-12-200G",
    "COQ4-500G": "COQ6-500G",
    "BATL-500G": "COQ6-500G",
    "PLUM-500G": "COQ6-500G",
    "VERM-200G": "COQ7-200G",
    "COQ6-200G": "COQ7-200G",
    "semoule-salem-ble-dure-3-tr": "semoule-fine-salem",
    "semoule-salem-ble-dure-4-tr": "semoule-fine-salem",
    "semoule-salem-extra-fine-eg": "semoule-fine-salem",
}
FILM_TEMPLATE = "film-pc-laize-390mm"  # kg, raw-materials store, packaging_component / film
CARTON_TEMPLATE = "carton-pc-500g"  # pieces, raw-materials store, packaging_component / carton

# --- Carton types ------------------------------------------------------------------
# (supplier as written on the list, format, PL|PC).
PACKAGING: tuple[tuple[str, str, str], ...] = (
    ("SCS", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("Rochette", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("MAMAN SAVON", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("Royal Crown Packaging", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("SAFALIM", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("Mici embaci", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("MASTER PACK", "Spaghetti 1.2 Pasta Douman 500 g", "PL"),
    ("Rochette", "Spaghetti 1.2 Pasta Prima 500 g", "PL"),
    ("Rochette", "Spaghetti 1.2 Pasta Prima 200 g", "PL"),
    ("El Safa", "Spaghetti 1.2 Pasta Prima 200 g", "PL"),
    ("SCS", "Torsade,Esc,Coq7 500 g", "PC"),
    ("Rochette", "Torsade,Esc,Coq7 500 g", "PC"),
    ("MAMAN SAVON", "Torsade,Esc,Coq7 500 g", "PC"),
    ("Royal Crown Packaging", "Torsade,Esc,Coq7 Ver 500 g", "PC"),
    ("MASTER PACK", "Torsade,Esc,Coq7 500 g", "PC"),
    ("Mici embaci", "Torsade,Esc,Coq7 500 g", "PC"),
    ("SONAPACK", "Torsade,Esc,Coq7 500 g", "PC"),
    ("SAFALIM", "Torsade,Esc,Coq7 500 g", "PC"),
    ("Rochette", "Vermicelle,Ann,Coq6 500 g", "PC"),
    ("El Safa", "Langue d'oiseau,Coq4 500 g", "PC"),
    ("Rochette", "Vermicelle,Ann,Coq6 200 g", "PC"),
    ("Rochette", "Torsade,Esc,Coq7 200 g", "PC"),
)

# --- Film types (the plant's "Type de Film" table, 2026-10-05) -------------------------
# (supplier as written on the table, format, film width in mm, PL|PC).
FILMS: tuple[tuple[str, str, int, str], ...] = (
    ("Ronzulli (Active print)", "Spaghetti 1.2 Pasta Douman 500 g", 230, "PL"),
    ("Ronzulli", "Spaghetti 1.2 Pasta Douman 500 g", 230, "PL"),
    ("TRB", "Spaghetti 1.2 Pasta Douman 500 g", 230, "PL"),
    ("CNP", "Spaghetti 1.2 Pasta Douman 500 g", 230, "PL"),
    ("DEVPAC", "Spaghetti 1.2 Pasta Douman 500 g", 230, "PL"),
    ("Ronzulli", "Spaghetti 1.2 Pasta Douman 500 g", 170, "PL"),
    ("Ronzulli", "Spaghetti 1.2 Pasta Prima 500 g", 230, "PL"),
    ("Ronzulli", "Spaghetti 1.2 Pasta Prima 200 g", 170, "PL"),
    ("Vee Dee", "Spaghetti 1.2 Pasta Prima 200 g", 170, "PL"),
    ("Ronzulli (Active print)", "Torsade, Esc, etc. Pasta Douman 500 g", 390, "PC"),
    ("Ronzulli", "Torsade, Esc, etc. Pasta Douman 500 g", 390, "PC"),
    ("TRB", "Torsade, Esc, etc. Pasta Douman 500 g", 390, "PC"),
    ("CNP", "Torsade, Esc, etc. Pasta Douman 500 g", 390, "PC"),
    ("DEVPAC", "Torsade, Esc, etc. Pasta Douman 500 g", 390, "PC"),
    ("Printo Pack", "Torsade, Esc, etc. Pasta Douman 200 g", 310, "PC"),
    ("Ronzulli", "Torsade, Esc, etc. Pasta Douman 200 g", 230, "PC"),
    ("Ronzulli", "Torsade, Esc, etc. Pasta Douman 4540 g", 730, "PC"),
    ("Ronzulli", "Torsade, Esc, etc. Pasta Douman 4540 g", 790, "PC"),
)

# Columns holding a product id with no foreign key behind them (the shift form's rows and
# a few others), checked before an old film item is deleted. A foreign-keyed reference
# makes the delete itself fail.
UNKEYED_PRODUCT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("production.shift_packing_rows", "film_product_id"),
    ("production.shift_waste_lines", "product_id"),
    ("production.shift_versements", "product_id"),
    ("production.shift_rebroyat_versements", "product_id"),
    ("production.shift_run_semolina_lines", "product_id"),
    ("qc.quality_conformity_lines", "product_id"),
    ("maintenance.part_request_lines", "product_id"),
)

# Supplier on the list -> partner names to look for, in order (case-insensitive). The first
# one is used when none exists. "SCS" is the partner "SCS MDC": the bare "SCS" duplicate
# was kept off the server by sync_master_data. Ronzulli films printed by Active Print are
# still bought from Ronzulli.
SUPPLIER_ALIASES: dict[str, tuple[str, ...]] = {
    "SCS": ("SCS MDC", "SCS"),
    "Ronzulli (Active print)": ("RONZULLI",),
    "Ronzulli": ("RONZULLI",),
    "TRB": ("TRB Group", "TRB"),
}


@dataclass
class Report:
    renamed: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    unchanged: int = 0
    suppliers_created: list[str] = field(default_factory=list)
    suppliers_tagged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    kept_in_use: list[str] = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _packaging_sku(kind: str, supplier: str, fmt: str) -> str:
    return f"{kind}-{_slug(supplier)}-{_slug(fmt)}"


def _film_sku(supplier: str, fmt: str, width_mm: int) -> str:
    return f"film-{_slug(supplier)}-{_slug(fmt)}-{width_mm}mm"


class _InUse(Exception):
    """Undoes one old film's delete (its savepoint) when a foreign key still points at it."""


class Seeder:
    def __init__(self, conn, tenant: str, actor: str):
        self.conn = conn
        self.tenant = tenant
        self.actor = actor
        self.core = CoreService(conn)
        self.classes = ProductClassificationService(conn)
        self.report = Report()

    # -- lookups ------------------------------------------------------------------
    def _product(self, sku: str, name: str | None = None):
        row = self.conn.execute(
            "SELECT id FROM core.products WHERE tenant_id = %s AND sku = %s", (self.tenant, sku)
        ).fetchone()
        if row is None and name is not None:
            row = self.conn.execute(
                "SELECT id FROM core.products WHERE tenant_id = %s AND lower(name) = lower(%s)", (self.tenant, name)
            ).fetchone()
        return self.core.get_product(self.tenant, row[0]) if row else None

    def _template(self, sku: str):
        product = self._product(sku)
        if product is None:
            raise SystemExit(f"template product {sku!r} does not exist on this database")
        return product, self.classes.get_classification(self.tenant, product.id)

    def _tag_id(self, name: str) -> str:
        row = self.conn.execute(
            "SELECT id FROM core.product_tags WHERE tenant_id = %s AND name = %s", (self.tenant, name)
        ).fetchone()
        if row is not None:
            return row[0]
        return _ok(self.core.create_product_tag(tenant_id=self.tenant, actor_id=self.actor, name=name)).id

    # -- writes -------------------------------------------------------------------
    def rename_or_create(self, sku: str, name: str, family: str | None, template_sku: str | None,
                         product_type: str | None = None, tag: str | None = None) -> None:
        product = self._product(sku, name)
        if product is not None:
            changes = {"name": name}
            if family is not None:
                changes["product_family"] = family
            if product_type is not None:
                changes["product_type"] = product_type
            changes = {k: v for k, v in changes.items() if getattr(product, k) != v}
            if changes:
                _ok(self.core.update_product(tenant_id=self.tenant, actor_id=self.actor, product_id=product.id, **changes))
                self.report.renamed.append(f"{product.name}  ->  {name}" if "name" in changes else f"{name} ({', '.join(changes)})")
            else:
                self.report.unchanged += 1
            return

        if template_sku is None:
            raise SystemExit(f"{sku!r} is not on this database and has no template to be created from")
        template, classification = self._template(template_sku)
        created = _ok(self.core.create_product(
            tenant_id=self.tenant, actor_id=self.actor, sku=sku, name=name,
            product_type=product_type or template.product_type,
            product_family=family,
            uom_id=template.uom_id,
            net_weight_grams=_float(template.net_weight_grams),
            sachets_per_package=_float(template.sachets_per_package),
            packets_per_carton=_float(template.packets_per_carton),
            carton_weight_grams=_float(template.carton_weight_grams),
            is_sellable=template.is_sellable,
            is_purchasable=template.is_purchasable,
            default_location_id=template.default_location_id,
        ))
        if classification is not None:
            _ok(self.classes.set_classification(
                tenant_id=self.tenant, actor_id=self.actor, product_id=created.id,
                category=classification.category, is_regrind=classification.is_regrind,
                packaging_format=classification.packaging_format, is_water=classification.is_water,
                packaging_kind=classification.packaging_kind, is_energy=classification.is_energy,
            ))
        if tag is not None:
            _ok(self.core.set_product_tags(tenant_id=self.tenant, actor_id=self.actor, product_id=created.id,
                                           tag_ids=[self._tag_id(tag)]))
        self.report.created.append(f"{sku}  {name}")

    def supplier(self, listed: str, tag_ids: list[str]) -> None:
        partner_id = None
        for candidate in SUPPLIER_ALIASES.get(listed, (listed,)):
            row = self.conn.execute(
                "SELECT id FROM core.partners WHERE tenant_id = %s AND lower(name) = lower(%s) AND kind <> 'customer'",
                (self.tenant, candidate),
            ).fetchone()
            if row is not None:
                partner_id = row[0]
                break
        if partner_id is None:
            name = SUPPLIER_ALIASES.get(listed, (listed,))[0]
            partner_id = _ok(self.core.create_partner(tenant_id=self.tenant, actor_id=self.actor, name=name, kind="supplier")).id
            self.report.suppliers_created.append(name)
        current = {r[0] for r in self.conn.execute(
            "SELECT tag_id FROM core.partner_tag_links WHERE partner_id = %s", (partner_id,)
        ).fetchall()}
        if not set(tag_ids) <= current:
            _ok(self.core.set_partner_tags(tenant_id=self.tenant, actor_id=self.actor, partner_id=partner_id,
                                           tag_ids=sorted(current | set(tag_ids))))
            self.report.suppliers_tagged.append(listed)

    def delete_old_film(self, sku: str) -> None:
        """An old film item made from the carton list goes when nothing points at it."""
        product = self._product(sku)
        if product is None:
            return
        used = [
            f"{table}.{column}" for table, column in UNKEYED_PRODUCT_COLUMNS
            if self.conn.execute(f"SELECT 1 FROM {table} WHERE {column} = %s LIMIT 1", (product.id,)).fetchone()
        ]
        if not used:
            try:
                with self.conn.transaction():  # savepoint: an in-use product undoes only its own delete
                    # Its own rows go with it: tags and production classification.
                    self.conn.execute("DELETE FROM core.product_tag_links WHERE product_id = %s", (product.id,))
                    self.conn.execute("DELETE FROM production.product_classifications WHERE product_id = %s", (product.id,))
                    result = self.core.delete_product(tenant_id=self.tenant, actor_id=self.actor, product_id=product.id)
                    if isinstance(result, Err):
                        raise _InUse(result.code)
            except _InUse as error:
                used = [str(error)]
        if used:
            self.report.kept_in_use.append(f"{product.name}  ({', '.join(used)})")
        else:
            self.report.deleted.append(f"{sku}  {product.name}")

    def run(self) -> Report:
        for sku, name, family in FINISHED:
            self.rename_or_create(sku, name, family, TEMPLATES.get(sku))
        for sku, name in RAW:
            self.rename_or_create(sku, name, None, TEMPLATES.get(sku))
        for supplier, fmt, line_type in PACKAGING:
            self.rename_or_create(_packaging_sku("carton", supplier, fmt), f"Carton {supplier} - {fmt}", line_type,
                                  CARTON_TEMPLATE, product_type=line_type, tag="CARTON")
        for supplier, fmt, width_mm, line_type in FILMS:
            self.rename_or_create(_film_sku(supplier, fmt, width_mm), f"Film {supplier} - {fmt} - {width_mm} mm",
                                  line_type, FILM_TEMPLATE, product_type=line_type, tag="FILM")
        for supplier, fmt, _ in PACKAGING:
            self.delete_old_film(_packaging_sku("film", supplier, fmt))
        for tag, suppliers in (("CARTON", [s for s, _, _ in PACKAGING]), ("FILM", [s for s, _, _, _ in FILMS])):
            tag_ids = [self._tag_id(tag)]
            for supplier in dict.fromkeys(suppliers):
                self.supplier(supplier, tag_ids)
        return self.report


def _ok(result):
    if isinstance(result, Err):
        raise SystemExit(f"{result.code}: {result.message}")
    return result.value


def _float(value) -> float | None:
    return float(value) if value is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--commit", action="store_true", help="keep the changes (default: preview and roll back)")
    args = parser.parse_args()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (args.tenant,)
        ).fetchone()
        if row is None:
            print(f"no user in tenant {args.tenant!r}", file=sys.stderr)
            return 1
        report = Seeder(conn, args.tenant, row[0]).run()

        print(f"Renamed {len(report.renamed)}:")
        for line in report.renamed:
            print(f"  {line}")
        print(f"Created {len(report.created)}:")
        for line in report.created:
            print(f"  {line}")
        print(f"Already up to date: {report.unchanged}")
        print(f"Suppliers created: {', '.join(report.suppliers_created) or '(none)'}")
        print(f"Suppliers tagged: {', '.join(report.suppliers_tagged) or '(none)'}")
        print(f"Old film items deleted {len(report.deleted)}:")
        for line in report.deleted:
            print(f"  {line}")
        print(f"Old film items kept (still in use) {len(report.kept_in_use)}:")
        for line in report.kept_in_use:
            print(f"  {line}")

        if args.commit:
            conn.commit()
            print("COMMITTED")
        else:
            conn.rollback()
            print("PREVIEW: everything above was rolled back -- rerun with --commit to keep it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

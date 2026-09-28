"""One-time master-data sync: copies the reference data the app needs (units, tags,
suppliers, products, classifications, locations, lines, machines, molds, BOMs, shift
settings) from a source database into another one, e.g. local -> server.

Two steps:

    # 1. On the machine holding the reference data (local): write the snapshot.
    DATABASE_URL=... python -m scripts.sync_master_data export
    #    -> scripts/data/master_data.json (committed, so it ships in the image)

    # 2. On the server: preview, then apply.
    docker compose exec -T app python -m scripts.sync_master_data apply
    docker compose exec -T app python -m scripts.sync_master_data apply --commit

`apply` only ADDS what is missing. A row is matched by its natural key (SKU, name,
code...), never by id, and a row that already exists is left untouched -- nothing on
the target is overwritten or deleted. References (a product's unit, a machine's line,
a tag link...) are resolved to the target's own ids. Without --commit everything runs
in one transaction that is rolled back, so the preview also proves the inserts pass
every constraint. Running it twice is harmless: the second run adds nothing.

What is left out of the snapshot is listed in EXCLUDE below (plus every customer:
those are demo data, the server keeps its real ones). Rows pointing at an excluded
row (its tag links, classification, BOM...) are dropped with it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ulid import ULID

from core.db import get_connection

SNAPSHOT = Path(__file__).parent / "data" / "master_data.json"


@dataclass(frozen=True)
class Table:
    name: str
    # Natural key, in terms of exported values (FK columns hold the referenced key).
    key: tuple[str, ...]
    # FK column -> referenced table name (its natural key must be a single column).
    fks: dict[str, str] = field(default_factory=dict)
    has_id: bool = True
    tenant_scoped: bool = True
    ci_key: bool = False  # key compared case-insensitively (report_options' unique index)
    where: str = ""  # extra export filter


# Insertion order: every table comes after the tables it references.
TABLES: tuple[Table, ...] = (
    Table("core.uoms", ("code",)),
    Table("core.currencies", ("code",), has_id=False, tenant_scoped=False),
    Table("core.product_tags", ("name",)),
    Table("core.partners", ("name",), where="kind <> 'customer'"),
    Table("core.partner_tag_links", ("partner_id", "tag_id"),
          fks={"partner_id": "core.partners", "tag_id": "core.product_tags"},
          has_id=False, tenant_scoped=False),
    Table("warehouse.sites", ("code",)),
    Table("warehouse.locations", ("code",), fks={"site_id": "warehouse.sites"}),
    Table("core.products", ("sku",),
          fks={"uom_id": "core.uoms", "default_location_id": "warehouse.locations",
               "parent_product_id": "core.products"}),
    Table("core.product_tag_links", ("product_id", "tag_id"),
          fks={"product_id": "core.products", "tag_id": "core.product_tags"},
          has_id=False, tenant_scoped=False),
    Table("core.report_options", ("kind", "label"), ci_key=True),
    Table("production.work_centers", ("code",)),
    Table("maintenance.equipment", ("code",), fks={"work_center_id": "production.work_centers"}),
    Table("production.molds", ("code",)),
    Table("production.resource_types", ("code",)),
    Table("production.product_classifications", ("product_id",),
          fks={"product_id": "core.products"}, has_id=False),
    Table("production.packaging_boms", ("target_product_id", "version"),
          fks={"target_product_id": "core.products"}),
    # Lines are only added together with a BOM this run creates (see _apply_bom_lines).
    Table("production.packaging_bom_lines", ("bom_id", "component_product_id"),
          fks={"component_product_id": "core.products"}),
    Table("production.shift_windows", ("shift",), has_id=False),
    Table("production.store_roles", ("location_id",),
          fks={"location_id": "warehouse.locations"}, has_id=False),
    Table("production.team_rotation", ("team",), has_id=False),
    Table("production.regrind_defaults", ("input_product_id",),
          fks={"input_product_id": "core.products", "output_product_id": "core.products"}),
)
BY_NAME = {t.name: t for t in TABLES}

# Rows the plant does not want on the server, by natural key.
EXCLUDE: dict[str, set[str]] = {
    "core.products": {
        "CARTON-STD", "doman-pc-4540g-sac", "doman-pc-200g", "doman-pc-500g", "doman-pl-500g",
        "eau", "fuel", "gasoil",
    },
    "core.partners": {"SCS"},
    "core.product_tags": {"sac"},
    "production.work_centers": {"Line-03"},
    "maintenance.equipment": {"M-PC-3"},
}
# Duplicate tags folded into the one kept: links to "sac" become links to "Sac".
TAG_RENAME = {"sac": "Sac"}

_DROPPED_COLUMNS = {"id", "tenant_id", "created_at", "updated_at"}


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.date, dt.time, dt.datetime)):
        return value.isoformat()
    return value


def _ref_key_column(table_name: str) -> str:
    return BY_NAME[table_name].key[0]


def export(conn, tenant: str) -> dict:
    # id -> natural key, per referenced table, filled as tables are exported.
    id_to_key: dict[str, dict[str, str]] = {}
    exported_keys: dict[str, set[str]] = {}
    snapshot: dict[str, list[dict]] = {}

    for table in TABLES:
        conditions = []
        params: list = []
        if table.tenant_scoped:
            conditions.append("tenant_id = %s")
            params.append(tenant)
        if table.where:
            conditions.append(table.where)
        if table.name == "core.partner_tag_links":
            conditions.append("partner_id IN (SELECT id FROM core.partners WHERE tenant_id = %s)")
            params.append(tenant)
        if table.name == "core.product_tag_links":
            conditions.append("product_id IN (SELECT id FROM core.products WHERE tenant_id = %s)")
            params.append(tenant)
        sql = f"SELECT * FROM {table.name}"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        cur = conn.execute(sql, params)
        columns = [d.name for d in cur.description]

        rows: list[dict] = []
        seen: set[tuple] = set()
        mapping = id_to_key.setdefault(table.name, {})
        for raw in cur.fetchall():
            record = dict(zip(columns, raw))
            row = {}
            dropped = False
            for col, value in record.items():
                if col in table.fks and value is not None:
                    ref = table.fks[col]
                    value = id_to_key.get(ref, {}).get(value)
                    if ref == "core.product_tags":
                        value = TAG_RENAME.get(value, value)
                    if value is None or value not in exported_keys.get(ref, set()):
                        dropped = True  # points at an excluded / unknown row
                        break
                if col == "bom_id":
                    value = id_to_key["production.packaging_boms"].get(value)
                    if value is None:
                        dropped = True
                        break
                if col in _DROPPED_COLUMNS:
                    continue
                row[col] = _json_value(value)
            if dropped:
                continue
            if len(table.key) == 1 and row[table.key[0]] in EXCLUDE.get(table.name, set()):
                if table.name == "core.product_tags" and row["name"] in TAG_RENAME:
                    mapping[record["id"]] = row["name"]  # its links move to the kept tag
                continue
            key = tuple(row[k] for k in table.key)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if "id" in record and len(table.key) == 1:
                mapping[record["id"]] = row[table.key[0]]
                exported_keys.setdefault(table.name, set()).add(row[table.key[0]])
            if table.name == "production.packaging_boms":
                # Lines reference their BOM as "target_sku@version".
                mapping[record["id"]] = f"{row['target_product_id']}@{row['version']}"
        rows.sort(key=lambda r: json.dumps([r[k] for k in table.key], default=str))
        snapshot[table.name] = rows
    return snapshot


class _Resolver:
    """Natural key -> target id, per table, including rows inserted this run."""

    def __init__(self, conn, tenant: str):
        self.conn = conn
        self.tenant = tenant
        self.cache: dict[str, dict[str, str]] = {}

    def load(self, table_name: str) -> dict[str, str]:
        if table_name not in self.cache:
            key = _ref_key_column(table_name)
            rows = self.conn.execute(
                f"SELECT {key}, id FROM {table_name} WHERE tenant_id = %s", (self.tenant,)
            ).fetchall()
            self.cache[table_name] = {k: i for k, i in rows}
        return self.cache[table_name]

    def id_for(self, table_name: str, key: str) -> str | None:
        return self.load(table_name).get(key)


def apply(conn, tenant: str, snapshot: dict) -> list[str]:
    resolver = _Resolver(conn, tenant)
    report: list[str] = []
    new_boms: dict[str, str] = {}  # "sku@version" -> new bom id

    for table in TABLES:
        rows = snapshot.get(table.name, [])
        added, existing, skipped = [], 0, []
        for source in rows:
            row = dict(source)
            if table.name == "production.packaging_bom_lines":
                bom_id = new_boms.get(row["bom_id"])
                if bom_id is None:
                    existing += 1  # BOM already on the target: its lines are its own
                    continue
                row["bom_id"] = bom_id

            missing_ref = None
            for col, ref in table.fks.items():
                if row.get(col) is None:
                    continue
                target_id = resolver.id_for(ref, row[col])
                if target_id is None:
                    missing_ref = f"{col}={row[col]}"
                    break
                row[col] = target_id
            label = " / ".join(str(source[k]) for k in table.key)
            if missing_ref:
                skipped.append(f"{label} (no {missing_ref} on target)")
                continue

            if table.name != "production.packaging_bom_lines" and _exists(conn, table, tenant, row):
                existing += 1
                continue

            if table.tenant_scoped:
                row["tenant_id"] = tenant
            new_id = None
            if table.has_id:
                new_id = str(ULID())
                row["id"] = new_id
            cols = list(row)
            conn.execute(
                f"INSERT INTO {table.name} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                [row[c] for c in cols],
            )
            added.append(label)
            if new_id and len(table.key) == 1:
                resolver.load(table.name)[source[table.key[0]]] = new_id
            if table.name == "production.packaging_boms":
                new_boms[f"{source['target_product_id']}@{source['version']}"] = new_id

        line = f"{table.name}: {len(added)} added, {existing} already there"
        if skipped:
            line += f", {len(skipped)} skipped"
        report.append(line)
        report.extend(f"    + {a}" for a in added)
        report.extend(f"    ! {s}" for s in skipped)
    return report


def _exists(conn, table: Table, tenant: str, row: dict) -> bool:
    conditions, params = [], []
    if table.tenant_scoped:
        conditions.append("tenant_id = %s")
        params.append(tenant)
    for k in table.key:
        if table.ci_key and isinstance(row[k], str):
            conditions.append(f"lower({k}) = lower(%s)")
        else:
            conditions.append(f"{k} IS NOT DISTINCT FROM %s")
        params.append(row[k])
    if table.name == "production.packaging_boms":
        # One active BOM per product: an active one on the target wins, whatever its version.
        conditions = conditions[:1] + ["target_product_id = %s", "(version = %s OR status = 'active')"]
        params = params[:1] + [row["target_product_id"], row["version"]]
    sql = f"SELECT 1 FROM {table.name} WHERE {' AND '.join(conditions)} LIMIT 1"
    return conn.execute(sql, params).fetchone() is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write the snapshot from this database")
    exp.add_argument("--tenant", default="demo")
    app = sub.add_parser("apply", help="add the snapshot's missing rows to this database")
    app.add_argument("--tenant", default="demo")
    app.add_argument("--commit", action="store_true", help="keep the changes (default: preview and roll back)")
    args = parser.parse_args(argv)

    with get_connection() as conn:
        if args.command == "export":
            snapshot = export(conn, args.tenant)
            SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            for name, rows in snapshot.items():
                print(f"{name}: {len(rows)}")
            print(f"wrote {SNAPSHOT}")
            return 0

        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        users = conn.execute("SELECT count(*) FROM core.users WHERE tenant_id = %s", (args.tenant,)).fetchone()[0]
        if users == 0:
            tenants = [r[0] for r in conn.execute("SELECT DISTINCT tenant_id FROM core.users").fetchall()]
            print(f"No user in tenant {args.tenant!r} on this database (tenants with users: {tenants}). "
                  "Pass --tenant.", file=sys.stderr)
            return 1
        for line in apply(conn, args.tenant, snapshot):
            print(line)
        if args.commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nPreview only -- rolled back. Re-run with --commit to keep it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

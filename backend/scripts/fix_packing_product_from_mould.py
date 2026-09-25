"""Re-tag packing rows that were saved under their work order's product after a mould change.

A packing row names the product it packed; a row saved without one took its work order's
product. When the mould of the run it drew from says otherwise, the stock, the lot, the tonnage
and every report built on that row are wrong. This corrects such rows through the shift's own
workflow: reverse the validated shift (its stock comes back), save the packing section with the
right product, hand the sections in again and validate again. QC's conformity lines follow their
row's product.

Which product a mould makes is not recorded anywhere, so it is given on the command line:

    cd backend
    PYTHONPATH=. .venv/Scripts/python scripts/fix_packing_product_from_mould.py --line Line_2_PC \
        --map MLD-PC-01=COQ6-500G --map MLD-PC-02=doman-pc-500g --map MLD-PC-03=doman-pc-200g --dry-run

Only validated shifts are touched, oldest first, each in its own savepoint. A shift is left alone
and listed when its QC raised a non-conformity on a row being re-tagged (the quarantine moves name
the old product) or when a step refuses; the rest go through. `--dry-run` rolls everything back.
"""
from __future__ import annotations

import argparse
import datetime
import sys

from ulid import ULID

from core.db import get_connection
from core.domain.result import Err
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService

REASON = "Produit du conditionnement corrigé d'après le moule du passage"


class Skip(Exception):
    pass


def ok(result, step: str):
    if isinstance(result, Err):
        raise Skip(f"{step}: {result.code} {result.message}")
    return result.value


def parse_map(pairs: list[str]) -> dict[str, str]:
    mapping = {}
    for pair in pairs:
        mould, sep, sku = pair.partition("=")
        if not sep or not mould.strip() or not sku.strip():
            raise SystemExit(f"--map expects MOULD_CODE=PRODUCT_SKU, got {pair!r}")
        mapping[mould.strip()] = sku.strip()
    return mapping


def rows_to_fix(conn, tenant: str, line_id: str, mould_product: dict[str, str], date_from, date_to) -> dict[str, dict[str, str]]:
    """shift id -> {packing row id: product it should name}, for validated shifts only."""
    found: dict[str, dict[str, str]] = {}
    for shift_id, row_id, current, mould in conn.execute(
        """
        SELECT s.id, p.id, p.product_id, m.code
        FROM production.shift_packing_rows p
        JOIN production.shift_reports s ON s.id = p.shift_report_id AND s.tenant_id = p.tenant_id
        JOIN production.shift_runs r ON r.id = p.run_id AND r.tenant_id = p.tenant_id
        JOIN production.molds m ON m.id = r.mold_id AND m.tenant_id = r.tenant_id
        WHERE p.tenant_id = %s AND s.work_center_id = %s AND s.status = 'validated'
          AND s.report_date BETWEEN %s AND %s
        ORDER BY s.report_date, s.id, p.line_order
        """,
        (tenant, line_id, date_from, date_to),
    ).fetchall():
        wanted = mould_product.get(mould)
        if wanted and wanted != current:
            found.setdefault(shift_id, {})[row_id] = wanted
    return found


def fix_shift(conn, tenant: str, shift_id: str, new_products: dict[str, str]) -> None:
    shifts = ShiftReportService(conn)
    validation = ShiftValidationService(conn)
    header = conn.execute(
        "SELECT validated_by, report_date, shift FROM production.shift_reports WHERE id = %s AND tenant_id = %s",
        (shift_id, tenant),
    ).fetchone()
    actor = header[0]
    if not actor:
        raise Skip("no validator recorded to act as")

    quarantined = conn.execute(
        """
        SELECT DISTINCT nc.reference FROM qc.non_conformities nc
        JOIN qc.quality_reports q ON q.id = nc.quality_report_id AND q.tenant_id = nc.tenant_id
        JOIN qc.quality_conformity_lines l ON l.report_id = q.id AND l.tenant_id = q.tenant_id
        WHERE q.tenant_id = %s AND q.shift_report_id = %s AND l.shift_packing_row_id = ANY(%s)
          AND nc.product_id = l.product_id
        """,
        (tenant, shift_id, list(new_products)),
    ).fetchall()
    if quarantined:
        raise Skip(f"QC non-conformity {', '.join(r[0] for r in quarantined)} quarantined the old product")

    ok(validation.reverse_shift(tenant_id=tenant, actor_id=actor, shift_report_id=shift_id, reason=REASON), "reverse")

    shift = ok(shifts.get_shift(tenant_id=tenant, shift_report_id=shift_id), "read")
    packing = next(s for s in shift["sections"] if s["key"] == "packing")
    rows = [dict(row, product_id=new_products.get(row["id"], row["product_id"])) for row in packing["payload"]["rows"]]
    ok(shifts.save_section(tenant_id=tenant, actor_id=actor, shift_report_id=shift_id, section_key="packing",
                           payload={**packing["payload"], "rows": rows}), "save packing")

    shift = ok(shifts.get_shift(tenant_id=tenant, shift_report_id=shift_id), "read")
    for section in shift["sections"]:
        if section["status"] not in ("submitted", "nothing_to_report"):
            ok(shifts.submit_section(tenant_id=tenant, actor_id=actor, shift_report_id=shift_id, section_key=section["key"]),
               f"submit {section['key']}")
    ok(validation.validate_shift(tenant_id=tenant, actor_id=actor, shift_report_id=shift_id, correlation_id=str(ULID())),
       "validate")

    for row_id, product_id in new_products.items():
        conn.execute(
            "UPDATE qc.quality_conformity_lines SET product_id = %s, updated_at = NOW() "
            "WHERE tenant_id = %s AND shift_packing_row_id = %s",
            (product_id, tenant, row_id),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--line", required=True, help="work center name or code")
    parser.add_argument("--map", action="append", default=[], metavar="MOULD=SKU", required=True)
    parser.add_argument("--from", dest="date_from", type=datetime.date.fromisoformat, default=datetime.date.min)
    parser.add_argument("--to", dest="date_to", type=datetime.date.fromisoformat, default=datetime.date.max)
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    args = parser.parse_args()
    by_code = parse_map(args.map)

    with get_connection() as conn:
        line = conn.execute(
            "SELECT id FROM production.work_centers WHERE tenant_id = %s AND (name = %s OR code = %s)",
            (args.tenant, args.line, args.line),
        ).fetchone()
        if line is None:
            raise SystemExit(f"no work center {args.line!r} for tenant {args.tenant!r}")
        skus = dict(conn.execute(
            "SELECT sku, id FROM core.products WHERE tenant_id = %s AND sku = ANY(%s)", (args.tenant, list(by_code.values()))
        ).fetchall())
        missing = sorted(set(by_code.values()) - set(skus))
        if missing:
            raise SystemExit(f"unknown product SKU(s): {', '.join(missing)}")
        mould_product = {mould: skus[sku] for mould, sku in by_code.items()}

        todo = rows_to_fix(conn, args.tenant, line[0], mould_product, args.date_from, args.date_to)
        print(f"{sum(len(v) for v in todo.values())} packing row(s) to re-tag in {len(todo)} validated shift(s)")
        fixed, skipped = 0, []
        with conn.transaction(force_rollback=args.dry_run):
            for shift_id, new_products in todo.items():
                try:
                    with conn.transaction():
                        fix_shift(conn, args.tenant, shift_id, new_products)
                    fixed += 1
                except Skip as reason:
                    skipped.append(f"{shift_id}: {reason}")
        print(f"{'would fix' if args.dry_run else 'fixed'} {fixed} shift(s)")
        for line_text in skipped:
            print(f"  skipped {line_text}")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())

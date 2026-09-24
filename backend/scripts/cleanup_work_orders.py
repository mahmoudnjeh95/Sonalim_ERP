"""Delete old work orders, keeping only 2 (one PC, one PL).

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/cleanup_work_orders.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/cleanup_work_orders.py
"""
from __future__ import annotations

import argparse
from core.db import get_connection

TENANT = "demo"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with get_connection() as conn:
        # Get work orders by line, newest first
        ofs = conn.execute("""
            SELECT wo.id, wc.code, p.sku, wo.created_at
            FROM production.work_orders wo
            JOIN production.work_centers wc ON wo.work_center_id = wc.id
            JOIN core.products p ON wo.product_id = p.id
            WHERE wo.tenant_id = %s
            ORDER BY wc.code, wo.created_at DESC
        """, (TENANT,)).fetchall()

        print(f"Total work orders: {len(ofs)}")

        # Keep only newest PC and newest PL
        keep = set()
        by_line = {}
        for wo_id, line_code, sku, created_at in ofs:
            line = "PC" if "Line_2" in line_code else "PL"
            if line not in by_line:
                by_line[line] = wo_id
                keep.add(wo_id)
                print(f"Keep {line}: {sku} ({wo_id})")

        to_delete = [wo_id for wo_id, _, _, _ in ofs if wo_id not in keep]
        print(f"\nDelete {len(to_delete)} work orders")

        if args.dry_run:
            print("DRY RUN - no changes")
            return 0

        # Collect all dependent IDs across all OFs
        prod_report_ids = []
        daily_report_ids = []
        scrap_record_ids = []

        for wo_id in to_delete:
            # Get production_reports
            prod_ids = [r[0] for r in conn.execute("SELECT id FROM production.production_reports WHERE of_id = %s", (wo_id,)).fetchall()]
            prod_report_ids.extend(prod_ids)

            # Get daily_reports from production_reports (report_id is the PK)
            if prod_ids:
                daily_ids = [r[0] for r in conn.execute("SELECT report_id FROM production.daily_reports WHERE report_id = ANY(%s)", (prod_ids,)).fetchall()]
                daily_report_ids.extend(daily_ids)

            # Get scrap records
            scrap_ids = [r[0] for r in conn.execute("SELECT id FROM production.scrap_records WHERE work_order_id = %s", (wo_id,)).fetchall()]
            scrap_record_ids.extend(scrap_ids)

        # Delete in one transaction with all dependencies
        with conn.transaction():
            # Delete from tables that reference the above
            if prod_report_ids:
                conn.execute("DELETE FROM production.report_revisions WHERE report_id = ANY(%s)", (prod_report_ids,))
                conn.execute("DELETE FROM production.conditionnement_reports WHERE report_id = ANY(%s)", (prod_report_ids,))
            if daily_report_ids:
                conn.execute("DELETE FROM production.conditionnement_reports WHERE daily_report_id = ANY(%s)", (daily_report_ids,))

            # Delete the reports (daily_reports uses report_id as PK)
            if daily_report_ids:
                conn.execute("DELETE FROM production.daily_reports WHERE report_id = ANY(%s)", (daily_report_ids,))
            if prod_report_ids:
                conn.execute("DELETE FROM production.production_reports WHERE id = ANY(%s)", (prod_report_ids,))

            # Delete work order dependencies
            for wo_id in to_delete:
                conn.execute("DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s", (wo_id,))

            if scrap_record_ids:
                conn.execute("DELETE FROM production.regrind_batch_inputs WHERE scrap_record_id = ANY(%s)", (scrap_record_ids,))

            for wo_id in to_delete:
                conn.execute("DELETE FROM production.regrind_batches WHERE work_order_id = %s", (wo_id,))

            if scrap_record_ids:
                conn.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (scrap_record_ids,))

            for wo_id in to_delete:
                conn.execute("DELETE FROM production.shift_packing_rows WHERE of_id = %s", (wo_id,))
                conn.execute("DELETE FROM production.shift_runs WHERE of_id = %s", (wo_id,))
                conn.execute("DELETE FROM production.work_orders WHERE id = %s", (wo_id,))
                print(f"Deleted {wo_id}")

        conn.commit()
        print(f"Successfully deleted {len(to_delete)} work orders")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

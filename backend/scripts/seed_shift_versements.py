"""Give the seeded shifts the versement (MP versé + rebroyat) their packed tonnage implies, and a 2 % packaging tolerance.

The two-weeks seed was written before the versement became the only typed input, so its
validated shifts carry no versement: every run's semoule, Pâte and rebroyat used came out as 0,
nothing left the raw-material store and the rendement cannot be read.

The versement is worked back from what each shift packed (its packing rows' tonnage), using the
ratios of the client's July 2024 report ("Sonali rapport général juillet.xlsx", RECAP PL / PC):

    PL  rendement 101.0 %  (207.8 t conditionné / 205.7 t fab)   MP = S.Salem 94.2 % + S.Extra fine 5.8 %
        rebroyat (semoule broyée) 21.2 t = 11.5 % of the 184.5 t MP
    PC  rendement  99.8 %  (108.1 t / 108.3 t)                   MP = S.Salem 89.7 % + S.fine 10.3 %

July's PC poured no rebroyat, but the client wants it on both lines, so PC takes PL's share.
Each shift gets its own draw around those figures. The shift is not reversed: its packed goods,
lots, QC and releases stay as they are. The versement is saved through the section code (which
derives every run's semoule lines, dough and rebroyat used), the raw material is posted out of
stock exactly as validation posts it, and the shift's legacy report copy is brought in line.
Rebroyat has no stock in the seed, so an opening receipt covering it is dated before the OFs.

    cd backend
    PYTHONPATH=. .venv/Scripts/python scripts/seed_shift_versements.py --dry-run
    PYTHONPATH=. .venv/Scripts/python scripts/seed_shift_versements.py

Shifts that already have a versement are skipped, unless `--redo`: then the raw material this
script posted for them is put back first (and those net-zero moves dropped) and they are planned
again. The draws are seeded per shift, so a profile left unchanged gives the same figures.
"""
from __future__ import annotations

import argparse
import datetime
import os
import random
import sys

from dotenv import load_dotenv
from ulid import ULID

load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from core.db import get_connection
from core.domain.result import Err
from modules.production.api.packaging_variance_service import PackagingTolerancePolicyService
from modules.production.api.shift_sections import save_section_rows
from modules.production.api.shift_stock_service import ShiftStockService
from modules.production.api.shift_validation_service import _runs
from modules.warehouse.api.service import StockService

TENANT = "demo"
ACTOR_EMAIL = "demo@sonalim-erp.local"
TOLERANCE_PERCENT = 2.0
REBROYAT_SKU = "REBROYAT-SEMOULE"
REBROYAT_RECEIPT = "seed-rebroyat-opening"

# Per line type: rendement band, MP split, rebroyat share of MP (0 = none).
PROFILES = {
    "PL": dict(yield_band=(0.995, 1.025), mp=[("semoule-ble-dur-salem", 0.942), ("semoule-extra-fine-salem", 0.058)],
               rebroyat_band=(0.09, 0.14), rebroyat_odds=0.9),
    "PC": dict(yield_band=(0.985, 1.011), mp=[("semoule-ble-dur-salem", 0.897), ("semoule-fine-salem", 0.103)],
               rebroyat_band=(0.09, 0.14), rebroyat_odds=0.9),
}
LINE_TYPE = {"Line_1": "PL", "Line_2": "PC"}


def ok(result, what: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{what}: {result.code} {result.message}")
    return result.value


def plan_versement(rng: random.Random, profile: dict, packed: float, skus: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Versement rows (t) for a shift that packed `packed` tonnes."""
    fab = packed / rng.uniform(*profile["yield_band"])
    share = rng.uniform(*profile["rebroyat_band"]) if rng.random() < profile["rebroyat_odds"] else 0.0
    rebroyat = round(fab * share / (1 + share), 3)
    mp = fab - rebroyat
    first = rng.uniform(-0.01, 0.01)  # the MP mix moves a little shift to shift
    (main_sku, main_share), (second_sku, _) = profile["mp"]
    main = round(mp * min(0.99, main_share + first), 3)
    versements = [
        dict(product_id=skus[main_sku], location_id=None, quantity=main),
        dict(product_id=skus[second_sku], location_id=None, quantity=round(mp - main, 3)),
    ]
    rebroyat_rows = [dict(product_id=skus[REBROYAT_SKU], location_id=None, quantity=rebroyat)] if rebroyat > 0 else []
    return versements, rebroyat_rows


def sync_legacy_copy(conn, run: dict) -> None:
    """The validated shift's old-shaped daily report, as materialize_shift would now write it."""
    conn.execute(
        "UPDATE production.daily_reports SET dough_quantity = %s, regrind_input_quantity = %s, regrind_input_product_id = %s, "
        "raw_material_location_id = %s WHERE report_id = %s AND tenant_id = %s",
        (run["dough_quantity"], run["regrind_input_quantity"], run["regrind_input_product_id"],
         run["raw_material_location_id"], run["id"], TENANT),
    )
    conn.execute("DELETE FROM production.report_semolina_lines WHERE report_id = %s AND tenant_id = %s", (run["id"], TENANT))
    for line in run["semolina_lines"]:
        conn.execute(
            "INSERT INTO production.report_semolina_lines (id, tenant_id, report_id, product_id, quantity, location_id, line_order) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (line["id"], TENANT, run["id"], line["product_id"], line["quantity"], line["location_id"], line["line_order"]),
        )


def seed_tolerances(conn, actor: str) -> int:
    policies = PackagingTolerancePolicyService(conn)
    ok(policies.set_policy(tenant_id=TENANT, actor_id=actor, tolerance_percent=TOLERANCE_PERCENT), "tenant default tolerance")
    # Some classification rows name the product by its SKU rather than its id; take either.
    finished = [row[0] for row in conn.execute(
        "SELECT DISTINCT p.id FROM production.product_classifications c "
        "JOIN core.products p ON p.tenant_id = c.tenant_id AND (p.id = c.product_id OR p.sku = c.product_id) "
        "WHERE c.tenant_id = %s AND c.category = 'finished_good'",
        (TENANT,),
    ).fetchall()]
    for product_id in finished:
        ok(policies.set_policy(tenant_id=TENANT, actor_id=actor, tolerance_percent=TOLERANCE_PERCENT, product_id=product_id),
           f"tolerance {product_id}")
    return len(finished)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    parser.add_argument("--redo", action="store_true", help="plan again the shifts this script already gave a versement")
    args = parser.parse_args()

    with get_connection() as conn, conn.transaction(force_rollback=args.dry_run):
        actor = conn.execute("SELECT id FROM core.users WHERE email = %s", (ACTOR_EMAIL,)).fetchone()[0]
        skus = dict(conn.execute("SELECT sku, id FROM core.products WHERE tenant_id = %s", (TENANT,)).fetchall())
        stock = ShiftStockService(conn)

        untouched = "" if args.redo else """
              AND NOT EXISTS (SELECT 1 FROM production.shift_versements v WHERE v.shift_report_id = s.id)
              AND NOT EXISTS (SELECT 1 FROM production.shift_rebroyat_versements v WHERE v.shift_report_id = s.id)"""
        shifts = conn.execute(
            f"""
            SELECT s.id, wc.code, s.report_date, s.shift, s.validated_at,
                   (SELECT COALESCE(SUM(p.finished_product_quantity), 0) FROM production.shift_packing_rows p
                    WHERE p.shift_report_id = s.id AND p.tenant_id = s.tenant_id)
            FROM production.shift_reports s
            JOIN production.work_centers wc ON wc.id = s.work_center_id
            WHERE s.tenant_id = %s AND s.status = 'validated'{untouched}
            ORDER BY s.report_date, s.validated_at
            """,
            (TENANT,),
        ).fetchall()

        if args.redo:
            # Put back what the earlier pass took out, the way a reversal does; the pair nets to
            # zero on stock, so both moves go and the history shows only the final consumption.
            undone = 0
            for shift_id, *_ in shifts:
                correlation = str(ULID())
                for run in _runs(conn, TENANT, shift_id):
                    ok(stock.post_run(tenant_id=TENANT, actor_id=actor, run=run, correlation_id=correlation, reverse=True),
                       f"undo {shift_id}")
                    undone += conn.execute(
                        "DELETE FROM warehouse.stock_moves WHERE tenant_id = %s AND reference = %s "
                        "AND move_type = 'production_consumption'",
                        (TENANT, f"shift_run:{run['id']}"),
                    ).rowcount
            print(f"redo: {undone} consumption move(s) put back and dropped")

        plans = []
        for shift_id, line, day, shift, validated_at, packed in shifts:
            profile = PROFILES.get(LINE_TYPE.get(line, ""))
            if profile is None or float(packed) <= 0:
                print(f"  skipped {day} {line} {shift}: {'no profile for the line' if profile is None else 'nothing packed'}")
                continue
            rng = random.Random(f"versement-{day.isoformat()}-{line}-{shift}")
            plans.append((shift_id, line, day, shift, validated_at, float(packed), *plan_versement(rng, profile, float(packed), skus)))

        rebroyat_needed = sum(r["quantity"] for *_, rebroyat in plans for r in rebroyat)
        store = conn.execute("SELECT default_location_id FROM core.products WHERE id = %s", (skus[REBROYAT_SKU],)).fetchone()[0]
        on_hand = float((conn.execute(
            "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
            (TENANT, skus[REBROYAT_SKU], store),
        ).fetchone() or (0,))[0])
        if rebroyat_needed > on_hand:
            ok(StockService(conn).receive_stock(
                tenant_id=TENANT, product_id=skus[REBROYAT_SKU], location_id=store,
                quantity=round(rebroyat_needed - on_hand + 5, 0),
                correlation_id=str(ULID()), reference=REBROYAT_RECEIPT, actor_id=actor,
            ), "receive rebroyat")
            conn.execute("UPDATE warehouse.stock_moves SET created_at = %s WHERE reference = %s",
                         (datetime.datetime(2026, 9, 9, 8, 0), REBROYAT_RECEIPT))

        totals: dict[str, list[float]] = {}
        for shift_id, line, day, shift, validated_at, packed, versements, rebroyat in plans:
            ok(save_section_rows(conn, tenant_id=TENANT, shift_report_id=shift_id, section_key="runs",
                                 payload={"versements": versements, "rebroyat_versements": rebroyat}), f"{day} {line} {shift} versement")
            correlation = str(ULID())
            for run in _runs(conn, TENANT, shift_id):
                ok(stock.post_run(tenant_id=TENANT, actor_id=actor, run=run, correlation_id=correlation), f"{day} {line} {shift} post")
                conn.execute(
                    "UPDATE warehouse.stock_moves SET created_at = %s WHERE tenant_id = %s AND reference = %s "
                    "AND move_type = 'production_consumption'",
                    (validated_at, TENANT, f"shift_run:{run['id']}"),
                )
                sync_legacy_copy(conn, run)
            mp = sum(v["quantity"] for v in versements)
            reb = sum(r["quantity"] for r in rebroyat)
            total = totals.setdefault(line, [0.0, 0.0, 0.0])
            total[0] += mp
            total[1] += reb
            total[2] += packed
            print(f"  {day} {line:6} {shift:11} MP {mp:7.3f} t  rebroyat {reb:6.3f} t  packed {packed:7.3f} t  "
                  f"rendement {100 * packed / (mp + reb):6.2f} %")

        print()
        for line, (mp, reb, packed) in sorted(totals.items()):
            print(f"{line}: MP {mp:.3f} t + rebroyat {reb:.3f} t -> packed {packed:.3f} t, rendement {100 * packed / (mp + reb):.2f} %")
        print(f"{len(plans)} shift(s) given a versement")

        count = seed_tolerances(conn, actor)
        print(f"packaging tolerance {TOLERANCE_PERCENT} %: tenant default + {count} finished product(s)")
        if args.dry_run:
            print("DRY RUN: rolled back")
    return 0


if __name__ == "__main__":
    sys.exit(main())

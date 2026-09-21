"""Load a month of QC work, through the real services: quality reports, follow-ups and non-conformities.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_qc_month.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_qc_month.py

QC inspects the packing reports the month's shifts produced (the ones not yet inspected). Not every shift is
inspected, the newest ones are still waiting for QC, and the newest reports are handed in, sent back or still
drafts. Carton counts come from what the packing report says was packed; defect wording is the plant's own
(taken from the reports already recorded). A few rejected reports are revised and validated again. Validated
reports open their follow-up window, older ones get observations, and reports with enough non-conforming
cartons raise a non-conformity that is pulled into quarantine, dispositioned and (when old enough) closed.

Process indices are left empty except on some reports, where they are set close to the one reading a
person entered by hand (pre-dryer 10, humidity 34.5, cooling 10). PF and SUMO have no reading to go on and stay empty.

Test data, generated from a fixed seed. Already-inspected packing reports are skipped, so a rerun adds nothing.
The events the services queue are left unsent, like every other seeder's.
"""
from __future__ import annotations

import datetime
import random
from collections import Counter

from ulid import ULID

from core.domain.result import Err
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.api.quality_service import FollowUpService, QualityReportService
from modules.qc.domain.non_conformity import DispositionLine
from modules.qc.domain.quality import QualityReportDetail
from scripts.seed_common import TENANT, TODAY, actor_id, business_time, run, stamp_audit, stamp_events

NOW = datetime.datetime.combine(TODAY, datetime.time(15, 0))

# The defect wording already used in the recorded quality reports.
DEFECTS = [
    "Carton écrasé / déformé",
    "Scellage défectueux",
    "Produits endommagés à l'intérieur du carton",
    "Quantité incorrecte à l'intérieur (manque de pièces)",
    "Carton mouillé / taché",
    "Pièces endommagées",
]
# The one hand-entered process reading in the data.
LAB_READING = dict(pre_dryer_index=10.0, humidity_percentage=34.5, cooling_index=10.0)
OBSERVATIONS = ["Aucun retour client sur ce lot", "Contrôle d'un échantillon en stock : conforme", "Lot revu au magasin, RAS"]
CORRECTIVE_ACTIONS = ["Contrôle renforcé en fin de ligne", "Sensibilisation de l'équipe", "Réglage de la machine", "Vérification du scellage"]
REJECTION = "Quantités à revérifier avec le rapport de conditionnement"
NC_MIN_CARTONS = 6


def at(moment: datetime.datetime) -> datetime.datetime:
    return min(moment, NOW)


def fate(rng: random.Random, age: int) -> str:
    if age >= 6:
        return rng.choices(["validated", "revised"], weights=[9, 1])[0]
    if age >= 3:
        return rng.choices(["validated", "submitted", "draft", "rejected"], weights=[5, 5, 3, 2])[0]
    return rng.choices(["submitted", "draft", "rejected", "validated"], weights=[4, 4, 2, 2])[0]


def expect(result, what: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{what}: {result.code} {result.message}")
    return result.value


def work(conn, args) -> int:
    actor = actor_id(conn)
    quality, follow_ups, ncs = QualityReportService(conn), FollowUpService(conn), NonConformityService(conn)
    locations = dict(conn.execute("SELECT code, id FROM warehouse.locations WHERE tenant_id = %s", (TENANT,)).fetchall())
    source, quarantine = locations["produits-finis"], locations["QUARANTINE"]
    product_of = dict(conn.execute("SELECT id, product_id FROM production.work_orders WHERE tenant_id = %s", (TENANT,)).fetchall())
    pack_size = {pid: (float(ppc) if ppc else 1.0) for pid, ppc in conn.execute(
        "SELECT id, packets_per_carton FROM core.products WHERE tenant_id = %s", (TENANT,)).fetchall()}

    candidates = sorted(quality.list_inspectable_conditionnement_reports(tenant_id=TENANT), key=lambda r: (r["report_date"], r["shift"], r["team"] or ""))
    outcomes: Counter = Counter()
    failures: list[str] = []
    for row in candidates:
        day = row["report_date"]
        age = (TODAY - day).days
        rng = random.Random(f"qc-{row['conditionnement_report_id']}")
        cartons = int(row["carton_quantity"] or 0)
        if cartons <= 0 or rng.random() >= (0.3 if age <= 1 else 0.7):
            outcomes["not inspected"] += 1
            continue

        non_conforming = rng.randint(1, 12) if rng.random() < 0.3 else 0
        readings = {k: round(v * rng.uniform(0.92, 1.08), 1) for k, v in LAB_READING.items()} if rng.random() < 0.2 else {}
        detail = QualityReportDetail(
            **readings,
            conforming_cartons=cartons - non_conforming, non_conforming_cartons=non_conforming,
            defect_details=rng.choice(DEFECTS) if non_conforming else None,
        )
        outcome = fate(rng, age)
        created = business_time(rng, day + datetime.timedelta(days=1), 7, 10) if row["shift"] == "night" else business_time(rng, day, 16, 19)
        created = at(created)
        try:
            with conn.transaction():
                report = expect(quality.create_report(tenant_id=TENANT, actor_id=actor, conditionnement_report_id=row["conditionnement_report_id"], detail=detail), "create")
                rid = report["report"].id if isinstance(report, dict) else report.id
                stamp_audit(conn, rid, created)
                last, submitted, validated_at = created, None, None
                if outcome != "draft":
                    submitted = at(created + datetime.timedelta(minutes=rng.randint(20, 90)))
                    expect(quality.submit_report(tenant_id=TENANT, actor_id=actor, report_id=rid), "submit")
                    stamp_audit(conn, rid, submitted)
                    last = submitted
                if outcome == "rejected" or outcome == "revised":
                    last = at(submitted + datetime.timedelta(hours=rng.randint(2, 8)))
                    expect(quality.reject_report(tenant_id=TENANT, actor_id=actor, report_id=rid, reason=REJECTION), "reject")
                    stamp_audit(conn, rid, last)
                if outcome == "revised":
                    last = at(last + datetime.timedelta(hours=rng.randint(1, 3)))
                    expect(quality.revise_report(tenant_id=TENANT, actor_id=actor, report_id=rid), "revise")
                    stamp_audit(conn, rid, last)
                    submitted = at(last + datetime.timedelta(minutes=rng.randint(20, 60)))
                    expect(quality.submit_report(tenant_id=TENANT, actor_id=actor, report_id=rid), "resubmit")
                    stamp_audit(conn, rid, submitted)
                    last = submitted
                if outcome in ("validated", "revised"):
                    validated_at = at(last + datetime.timedelta(hours=rng.randint(1, 20), minutes=rng.randint(0, 59)))
                    correlation = str(ULID())
                    expect(quality.validate_report(tenant_id=TENANT, actor_id=actor, report_id=rid, correlation_id=correlation,
                                                   product_id=product_of.get(row["of_id"])), "validate")
                    stamp_audit(conn, rid, validated_at)
                    stamp_events(conn, correlation, validated_at)
                    last = validated_at
                    conn.execute("UPDATE qc.quality_follow_ups SET created_at = %s, updated_at = %s WHERE quality_report_id = %s", (validated_at, validated_at, rid))
                conn.execute("UPDATE qc.quality_reports SET created_at = %s, updated_at = %s, submitted_at = %s, validated_at = %s WHERE id = %s",
                             (created, last, submitted, validated_at, rid))

                if validated_at is not None:
                    seed_follow_up(conn, follow_ups, actor, rng, rid, validated_at)
                    if non_conforming >= NC_MIN_CARTONS and rng.random() < 0.85:
                        seed_non_conformity(conn, ncs, actor, rng, outcomes, rid=rid, of_id=row["of_id"], product_id=product_of.get(row["of_id"]),
                                            pack_size=pack_size, source=source, quarantine=quarantine, defect=detail.defect_details, cartons=non_conforming,
                                            raised_at=validated_at + datetime.timedelta(minutes=rng.randint(30, 120)))
            outcomes[f"report {outcome}"] += 1
        except Exception as error:  # one bad report must not stop the month
            failures.append(f"{day} {row['team']} {row['shift']}: {error}")
            print(f"  FAILED {day} {row['team']} {row['shift']}: {error}")

    print("\nby outcome:", dict(outcomes))
    for label, sql in [
        ("quality reports", "SELECT status, count(*) FROM qc.quality_reports GROUP BY 1"),
        ("follow-ups", "SELECT status, count(*) FROM qc.quality_follow_ups GROUP BY 1"),
        ("non-conformities", "SELECT status, count(*) FROM qc.non_conformities GROUP BY 1"),
    ]:
        print(f"{label} now:", conn.execute(sql).fetchall())
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    return 0


def seed_follow_up(conn, follow_ups: FollowUpService, actor: str, rng: random.Random, rid: str, validated_at: datetime.datetime) -> None:
    """Older validated reports get a follow-up observation, and the oldest of those are completed."""
    age = (TODAY - validated_at.date()).days
    if age < 8 or rng.random() >= 0.35:
        return
    observed = validated_at.date() + datetime.timedelta(days=rng.randint(3, 14))
    if observed > TODAY:
        return
    moment = at(datetime.datetime.combine(observed, datetime.time(rng.randint(8, 16), rng.randint(0, 59))))
    follow_up = expect(follow_ups.record_observation(tenant_id=TENANT, actor_id=actor, quality_report_id=rid, observed_on=observed, observation=rng.choice(OBSERVATIONS)), "observe")
    stamp_audit(conn, follow_up.id, moment)
    conn.execute("UPDATE qc.quality_follow_ups SET created_at = %s, updated_at = %s WHERE id = %s", (moment, moment, follow_up.id))
    if age >= 15 and rng.random() < 0.6:
        done = at(moment + datetime.timedelta(days=rng.randint(1, 5)))
        expect(follow_ups.transition(tenant_id=TENANT, actor_id=actor, follow_up_id=follow_up.id, new_status="completed", result="conforme"), "complete follow-up")
        stamp_audit(conn, follow_up.id, done)
        conn.execute("UPDATE qc.quality_follow_ups SET updated_at = %s WHERE id = %s", (done, follow_up.id))


def seed_non_conformity(conn, ncs: NonConformityService, actor: str, rng: random.Random, outcomes: Counter, *, rid: str, of_id: str,
                        product_id: str | None, pack_size: dict, source: str, quarantine: str, defect: str, cartons: int,
                        raised_at: datetime.datetime) -> None:
    """Raise, disposition and close one non-conformity, stopping wherever its dates run out."""
    if product_id is None or raised_at > NOW:
        return
    correlation = str(ULID())
    severity = "major" if cartons >= 10 else "minor"
    # A savepoint, so a refusal (say, no stock of that product in the finished store) leaves the report itself intact.
    try:
        with conn.transaction():
            nc = expect(ncs.raise_non_conformity(
                tenant_id=TENANT, actor_id=actor, of_id=of_id, product_id=product_id, quantity=0, source_location_id=source, defect_type=defect,
                correlation_id=correlation, quarantine_location_id=quarantine, severity=severity, quality_report_id=rid), "raise NC")
            stamp_audit(conn, nc.id, raised_at)
            stamp_events(conn, correlation, raised_at)
            conn.execute("UPDATE warehouse.stock_moves SET created_at = %s WHERE reference = %s", (raised_at, f"non_conformity:{nc.id}"))
            state, updated = "quarantined", raised_at
            dispositioned_at = raised_at + datetime.timedelta(hours=rng.randint(2, 24))
            closed_at = dispositioned_at + datetime.timedelta(days=rng.randint(1, 4), hours=rng.randint(0, 6))
            # Recent ones are still being worked: some wait in quarantine, some are dispositioned but not closed.
            progress = rng.random() if (TODAY - raised_at.date()).days <= 12 else 1.0
            if dispositioned_at <= NOW and progress >= 0.25:
                lines = disposition_lines(rng, nc.quantity)
                correlation = str(ULID())
                expect(ncs.disposition(tenant_id=TENANT, actor_id=actor, non_conformity_id=nc.id, lines=lines, correlation_id=correlation), "disposition")
                stamp_audit(conn, nc.id, dispositioned_at)
                stamp_events(conn, correlation, dispositioned_at)
                conn.execute("UPDATE warehouse.stock_moves SET created_at = %s WHERE reference = %s AND created_at > %s", (dispositioned_at, f"non_conformity:{nc.id}", raised_at))
                conn.execute("UPDATE qc.nc_dispositions SET created_at = %s WHERE non_conformity_id = %s", (dispositioned_at, nc.id))
                state, updated = "dispositioned", dispositioned_at
                if closed_at <= NOW and progress >= 0.6:
                    expect(ncs.close(tenant_id=TENANT, actor_id=actor, non_conformity_id=nc.id, corrective_action=rng.choice(CORRECTIVE_ACTIONS)), "close NC")
                    stamp_audit(conn, nc.id, closed_at)
                    conn.execute("UPDATE qc.non_conformities SET closed_at = %s WHERE id = %s", (closed_at, nc.id))
                    state, updated = "closed", closed_at
            conn.execute("UPDATE qc.non_conformities SET raised_at = %s, created_at = %s, updated_at = %s WHERE id = %s", (raised_at, raised_at, updated, nc.id))
        outcomes[f"non-conformity {state}"] += 1
    except RuntimeError as refusal:
        outcomes[f"non-conformity refused ({str(refusal).split(':')[1].strip().split(' ')[0]})"] += 1


def disposition_lines(rng: random.Random, quantity: float) -> tuple[DispositionLine, ...]:
    """The whole quantity goes one way, or splits between two of the ways a rejected product can go."""
    ways = rng.sample(["regrind", "dechet", "rework", "return_to_stock"], k=rng.choice([1, 1, 2]))
    if len(ways) == 1:
        return (DispositionLine(component="product", disposition=ways[0], quantity=quantity),)
    first = round(quantity * rng.choice([0.5, 0.6, 0.75]))
    return (DispositionLine(component="product", disposition=ways[0], quantity=first),
            DispositionLine(component="product", disposition=ways[1], quantity=quantity - first))


if __name__ == "__main__":
    raise SystemExit(run(__doc__, work))

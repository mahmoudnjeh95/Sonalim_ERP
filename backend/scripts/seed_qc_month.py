"""Load a month of QC work, through the real services: quality reports, follow-ups and non-conformities.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_qc_month.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_qc_month.py

QC inspects the validated shift reports the month's production produced (the ones not yet inspected;
run `seed_shift_month.py` first so there is something to inspect). Every fiche de shift older than a
day or two gets its quality report -- the dashboards need the whole month, not a sample -- while the
newest shifts are where a real week leaves them: some still waiting for QC, the freshest reports
handed in, sent back or still drafts. Carton counts come from what each shift's packing rows say was
packed, split per product line; defect wording is the plant's own (taken from the reports already
recorded).

The defects are not spread evenly, on purpose, so the quality dashboards have something to find: the
200 g format and the line's third team reject more, night shifts reject a little more, one bad week in
September rejects a lot more, and each product has its own signature defect. A few rejected reports are
revised and validated again. Validated reports open their follow-up window, older ones get
observations, and reports with enough non-conforming cartons raise a non-conformity that is pulled
into quarantine, dispositioned and (when old enough) closed.

Contrôle des paramètres readings are entered the way the paper sheet actually gets filled: two or
three of its nine groups, on some reports, not all nine every time.

Test data, generated from a fixed seed. Already-inspected shift reports are skipped, so a rerun adds
nothing. The events the services queue are left unsent, like every other seeder's.
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
from modules.qc.domain.parameters import PARAMETER_GROUPS
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
OBSERVATIONS = ["Aucun retour client sur ce lot", "Contrôle d'un échantillon en stock : conforme", "Lot revu au magasin, RAS"]
CORRECTIVE_ACTIONS = ["Contrôle renforcé en fin de ligne", "Sensibilisation de l'équipe", "Réglage de la machine", "Vérification du scellage"]
REJECTION = "Quantités à revérifier avec le rapport de conditionnement"
COMMENTS = ["RAS", "Lecture faite en fin de poste", "Contrôle visuel uniquement"]
NC_MIN_CARTONS = 8
# Each format has a signature defect it sees more than the others (the sachet weld on the 200 g,
# crushed cartons on the long pasta) -- so "top defect by product" is a real finding, not noise.
SIGNATURE_DEFECT = {"doman-pc-200g": "Scellage défectueux", "doman-pl-500g": "Carton écrasé / déformé", "COQ6-500G": "Pièces endommagées"}
BAD_WEEK = (datetime.date(2026, 9, 7), datetime.date(2026, 9, 12))

# A couple of plausible readings per group, so a seeded entry looks like a real one
# instead of a wall of zeros. Fields left out of a given entry stay unset, the same
# as an inspector who only filled part of the row.
PARAMETER_SAMPLES: dict[str, dict] = {
    "presse": {"pression": 45.0, "debit_bar": 6.2, "niveau_moulange_percent": 72.0},
    "pompe_vide": {"niveau_huile": 0.8, "temperature_c": 38.0, "niveau_vide_bar": -0.9},
    "sechage": {"temperature_c": 78.0, "delta": 4.5},
    "chaudiere": {"t_aller_c": 90.0, "p_aller_bar": 3.2, "t_retour_c": 70.0, "p_retour_bar": 2.8},
    "compresseurs": {"pression_bar": 7.5, "temperature_c": 32.0},
    "traitement_eau": {"niveau_cuve1": 60.0, "niveau_cuve2": 55.0, "niveau_sel": 40.0},
    "chiller": {"t_entree_c": 12.0, "t_sortie_c": 7.0, "p_entree_bar": 4.0, "p_sortie_bar": 3.5},
    "additif": {"tableau": "PL", "niveau_tremie": 65.0},
    "proprete_locaux": {"lave_m": "OK", "chaud": "OK", "silo": "OK"},
}


def at(moment: datetime.datetime) -> datetime.datetime:
    return min(moment, NOW)


def fate(rng: random.Random, age: int) -> str:
    if age >= 10:
        return rng.choices(["validated", "revised"], weights=[9, 1])[0]
    if age >= 6:
        return rng.choices(["validated", "revised", "submitted", "draft", "rejected"], weights=[12, 2, 3, 1, 1])[0]
    if age >= 3:
        return rng.choices(["validated", "submitted", "draft", "rejected"], weights=[5, 5, 3, 2])[0]
    return rng.choices(["submitted", "draft", "rejected", "validated"], weights=[4, 4, 2, 2])[0]


def defect_odds(sku: str | None, team: str | None, shift: str | None, day: datetime.date) -> float:
    """How likely this product line's cartons include rejects -- the patterns the dashboards should surface."""
    odds = {"doman-pc-200g": 0.55, "COQ6-500G": 0.35, "doman-pc-500g": 0.3}.get(sku or "", 0.25)
    if team and team.endswith("C"):
        odds += 0.12
    if shift == "night":
        odds += 0.08
    if BAD_WEEK[0] <= day <= BAD_WEEK[1]:
        odds += 0.25
    return min(odds, 0.95)


def reject_share(rng: random.Random, sku: str | None, day: datetime.date) -> float:
    """Share of the line's cartons rejected, when any are: a few per thousand normally, more in the bad week."""
    high = 0.028 if sku == "doman-pc-200g" else 0.02
    if BAD_WEEK[0] <= day <= BAD_WEEK[1]:
        high += 0.02
    return rng.uniform(0.003, high)


def pick_defect(rng: random.Random, sku: str | None) -> str:
    signature = SIGNATURE_DEFECT.get(sku or "")
    if signature and rng.random() < 0.5:
        return signature
    return rng.choice(DEFECTS)


def expect(result, what: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{what}: {result.code} {result.message}")
    return result.value


def work(conn, args) -> int:
    actor = actor_id(conn)
    quality, follow_ups, ncs = QualityReportService(conn), FollowUpService(conn), NonConformityService(conn)
    locations = dict(conn.execute("SELECT code, id FROM warehouse.locations WHERE tenant_id = %s", (TENANT,)).fetchall())
    source, quarantine = locations["produits-finis"], locations["QUARANTINE"]
    sku_of = dict(conn.execute("SELECT id, sku FROM core.products WHERE tenant_id = %s", (TENANT,)).fetchall())
    # What each packing row says was boxed: the count QC actually inspects. Read straight from
    # production's table, as seed_shift_month does -- this is a dev seeder, not module code.
    cartons_of_row = {
        row_id: int(cartons or 0)
        for row_id, cartons in conn.execute(
            "SELECT id, carton_quantity FROM production.shift_packing_rows WHERE tenant_id = %s", (TENANT,)
        ).fetchall()
    }

    candidates = sorted(
        quality.list_inspectable_shift_reports(tenant_id=TENANT), key=lambda r: (r["report_date"], r["shift"], r["team"] or "")
    )
    group_keys = list(PARAMETER_GROUPS)
    outcomes: Counter = Counter()
    failures: list[str] = []
    for row in candidates:
        day = row["report_date"]
        if isinstance(day, str):
            day = datetime.date.fromisoformat(day)
        age = (TODAY - day).days
        rng = random.Random(f"qc-{row['shift_report_id']}")
        # Every finished shift is inspected; the last two days are still partly on the inspector's desk.
        if rng.random() >= (0.5 if age <= 1 else 0.97):
            outcomes["not inspected"] += 1
            continue

        outcome = fate(rng, age)
        created = business_time(rng, day + datetime.timedelta(days=1), 7, 10) if row["shift"] == "night" else business_time(rng, day, 16, 19)
        created = at(created)
        try:
            with conn.transaction():
                report = expect(quality.create_report(tenant_id=TENANT, actor_id=actor, shift_report_id=row["shift_report_id"]), "create")
                rid = report["report"].id
                lines = report["lines"]
                if not lines:
                    outcomes["no packing rows"] += 1
                    continue
                stamp_audit(conn, rid, created)

                # Conformity per product line, on the cartons that line's packing row says were
                # boxed. Which lines reject, and how much, follows the patterns above.
                line_edits = []
                non_conforming_by_line: dict[str, tuple[str, str, int, str | None]] = {}
                for line in lines:
                    sku = sku_of.get(line.product_id)
                    cartons = cartons_of_row.get(line.shift_packing_row_id) or rng.randint(200, 1200)
                    rejects = rng.random() < defect_odds(sku, row["team"], row["shift"], day)
                    non_conforming = max(1, round(cartons * reject_share(rng, sku, day))) if rejects else 0
                    defect = pick_defect(rng, sku) if non_conforming else None
                    line_edits.append(
                        {
                            "shift_packing_row_id": line.shift_packing_row_id,
                            "conforming_cartons": cartons - non_conforming,
                            "non_conforming_cartons": non_conforming,
                            "defect_details": defect,
                        }
                    )
                    if non_conforming:
                        non_conforming_by_line[line.shift_packing_row_id] = (line.of_id, line.product_id, non_conforming, defect)
                detail = QualityReportDetail(
                    comments=rng.choice(COMMENTS) if rng.random() < 0.4 else None,
                    corrective_action=rng.choice(CORRECTIVE_ACTIONS) if non_conforming_by_line and rng.random() < 0.6 else None,
                )
                expect(
                    quality.update_draft(tenant_id=TENANT, actor_id=actor, report_id=rid, lines=line_edits, detail=detail),
                    "update draft",
                )

                # A couple of the nine Contrôle des paramètres groups, filled the way
                # the paper sheet actually gets filled -- not all nine every shift.
                for group_key in rng.sample(group_keys, k=rng.choice([0, 2, 2, 3])):
                    sample = PARAMETER_SAMPLES[group_key]
                    fields = {k: v for k, v in sample.items() if rng.random() < 0.8}
                    expect(
                        quality.save_parameter_entry(
                            tenant_id=TENANT, actor_id=actor, report_id=rid, group_key=group_key,
                            entry_label=business_time(rng, day, 6, 22).strftime("%Hh%M"), fields=fields,
                        ),
                        "parameter entry",
                    )

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
                    expect(
                        quality.validate_report(tenant_id=TENANT, actor_id=actor, report_id=rid, correlation_id=correlation),
                        "validate",
                    )
                    stamp_audit(conn, rid, validated_at)
                    stamp_events(conn, correlation, validated_at)
                    last = validated_at
                    conn.execute("UPDATE qc.quality_follow_ups SET created_at = %s, updated_at = %s WHERE quality_report_id = %s", (validated_at, validated_at, rid))
                conn.execute("UPDATE qc.quality_reports SET created_at = %s, updated_at = %s, submitted_at = %s, validated_at = %s WHERE id = %s",
                             (created, last, submitted, validated_at, rid))

                if validated_at is not None:
                    seed_follow_up(conn, follow_ups, actor, rng, rid, validated_at)
                    for of_id, product_id, non_conforming, defect in non_conforming_by_line.values():
                        if non_conforming >= NC_MIN_CARTONS and rng.random() < 0.85:
                            seed_non_conformity(
                                conn, ncs, actor, rng, outcomes, rid=rid, of_id=of_id, product_id=product_id,
                                source=source, quarantine=quarantine, defect=defect, cartons=non_conforming,
                                raised_at=validated_at + datetime.timedelta(minutes=rng.randint(30, 120)),
                            )
            outcomes[f"report {outcome}"] += 1
        except Exception as error:  # one bad report must not stop the month
            failures.append(f"{day} {row['team']} {row['shift']}: {error}")
            print(f"  FAILED {day} {row['team']} {row['shift']}: {error}")

    print("\nby outcome:", dict(outcomes))
    for label, sql in [
        ("quality reports", "SELECT status, count(*) FROM qc.quality_reports GROUP BY 1"),
        ("follow-ups", "SELECT status, count(*) FROM qc.quality_follow_ups GROUP BY 1"),
        ("non-conformities", "SELECT status, count(*) FROM qc.non_conformities GROUP BY 1"),
        ("parameter entries", "SELECT group_key, count(*) FROM qc.quality_parameters GROUP BY 1"),
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
                        product_id: str | None, source: str, quarantine: str, defect: str | None, cartons: int,
                        raised_at: datetime.datetime) -> None:
    """Raise, disposition and close one non-conformity, stopping wherever its dates run out."""
    if product_id is None or raised_at > NOW:
        return
    correlation = str(ULID())
    severity = "critical" if cartons >= 30 else "major" if cartons >= 15 else "minor"
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

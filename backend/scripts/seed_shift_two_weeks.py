"""Seed 2 weeks of shift reports starting from today (Sep 24).

    cd backend
    PYTHONPATH=. .venv/Scripts/python scripts/seed_shift_two_weeks.py --dry-run
    PYTHONPATH=. .venv/Scripts/python scripts/seed_shift_two_weeks.py

Generates 3 shifts per line per day for 14 days (2 weeks).
- Line_1 (PL): morning, afternoon, night
- Line_2 (PC): morning, afternoon, night (extended)

Skips any shifts that already exist. All shifts are left in 'submitted' state
(handed in, waiting for validation).
"""
from __future__ import annotations

import argparse
import datetime
import os
import random
import sys
from collections import Counter

from dotenv import load_dotenv
from ulid import ULID

# Load .env from repo root
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from core.db import get_connection
from core.domain.result import Err, Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.dashboard import ShiftWindow, shift_order, team_rotation_schedule
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "demo"
ACTOR_EMAIL = "demo@sonalim-erp.local"
TODAY = datetime.date(2026, 9, 24)
REGRIND_LINE_CODE = "rebroyat_01"

# The plant's real 4-team rotation (Production Settings > Team Rotation) is the
# source of truth for who is on which shift -- see team_for(), which reads it
# from production.team_rotation rather than guessing a pattern here. A team not
# in CREWS (e.g. one added in Settings after this list was written) still gets
# a report, just with no named crew filled in.
CREWS = {
    "Équipe A": dict(conducteur="Alou Traoré", agent_fabrication="Moussa Soumaoro", machiniste="D. Samaké", aide_machiniste="S. Togola"),
    "Équipe B": dict(conducteur="Ibrahim Keita", agent_fabrication="Sékou Camara", machiniste="K. Doumbia", aide_machiniste="M. Dembélé"),
    "Équipe C": dict(conducteur="Amadou Coulibaly", agent_fabrication="Bakary Sidibé", machiniste="S. Fofana", aide_machiniste="A. Konaté"),
    "Équipe D": dict(conducteur="Souleymane Diarra", agent_fabrication="Oumar Diallo", machiniste="B. Traoré", aide_machiniste="Y. Cissé"),
}

LINES = {
    "PL": dict(
        wc="Line_1", shifts=("matin", "après-midi", "nuit"), extrusion="PL-01-02", packing_machine="PL-01-03",
        film="film-pl-laize-230mm", carton="carton-pl-500g-c", second_semolina="semoule-extra-fine-salem", lot_start=6100,
        planned=80,
        products=[dict(sku="doman-pl-500g", mold="MLD-PL-01", rate=1.55, net_kg=0.5, ppc=20, film_kg=0.0045, packing_type="Sachet 500 g")],
    ),
    "PC": dict(
        wc="Line_2", shifts=("matin", "après-midi", "nuit"), extrusion="PC-02-02", packing_machine="PC-02-03",
        film="film-pc-laize-390mm", carton="carton-pc-500g", second_semolina="semoule-fine-salem", lot_start=7100,
        planned=40,
        products=[
            dict(sku="COQ6-500G", mold="MLD-PC-01", rate=0.95, net_kg=0.5, ppc=20, film_kg=0.0045, packing_type="Sachet 500 g"),
            dict(sku="doman-pc-500g", mold="MLD-PC-02", rate=0.92, net_kg=0.5, ppc=20, film_kg=0.0045, packing_type="Sachet 500 g"),
            dict(sku="doman-pc-200g", mold="MLD-PC-03", rate=0.70, net_kg=0.2, ppc=40, film_kg=0.0028, packing_type="Sachet 200 g"),
        ],
    ),
}

STOP_KINDS = [
    ("cleaning_extruder", "cleaning", "mechanical", "production", (15, 45), "Nettoyage de la presse", "Nettoyage puis reprise de la production"),
    ("electrical_failure", "corrective", "electric", "production", (8, 30), "Coupure sur l'EDM", "Basculement sur le groupe électrogène"),
    ("semolina_shortage", "corrective", "other", "production", (10, 35), "Manque de semoule", "Approvisionnement du silo"),
    ("die_jam", "corrective", "mechanical", "production", (12, 40), "Alarme centrifugeuse", "Nettoyage centrifugeuse et reprise"),
    ("team_break", "preventive", "other", "production", (15, 30), "Pause équipe", "Reprise après la pause"),
    ("film_jam", "corrective", "pneumatic", "packing", (8, 25), "Bourrage film", "Changement de bobine et réglage"),
    ("packaging_supply_shortage", "corrective", "other", "packing", (10, 30), "Manque de cartons", "Approvisionnement en cartons"),
    ("extruder_failure", "corrective", "mechanical", "production", (25, 70), "Panne extrudeuse", "Réglage capteur puis reprise"),
]

WASTE_KINDS = [
    ("press", (20, 90), "Nettoyage presse"),
    ("kneading", (2, 15), "Nettoyage pétrin"),
    ("pouring", (3, 12), "Nettoyage matière première"),
    ("cross", (2, 30), "Changement de moule"),
    ("raw_material", (1, 6), "Réglage capteur"),
]


class Refs:
    """The plant's own rows, looked up once by code."""

    def __init__(self, conn) -> None:
        one = lambda sql, *params: conn.execute(sql, params).fetchone()
        self.actor = one("SELECT id FROM core.users WHERE email = %s", ACTOR_EMAIL)[0]
        self.wc = dict(conn.execute("SELECT code, id FROM production.work_centers WHERE tenant_id = %s", (TENANT,)).fetchall())
        self.equipment = dict(conn.execute("SELECT code, id FROM maintenance.equipment WHERE tenant_id = %s", (TENANT,)).fetchall())
        self.molds = dict(conn.execute("SELECT code, id FROM production.molds WHERE tenant_id = %s", (TENANT,)).fetchall())
        self.products = dict(conn.execute("SELECT sku, id FROM core.products WHERE tenant_id = %s", (TENANT,)).fetchall())
        self.locations = dict(conn.execute("SELECT code, id FROM warehouse.locations WHERE tenant_id = %s", (TENANT,)).fetchall())
        self.windows = {
            shift: (start, end)
            for shift, start, end in conn.execute(
                "SELECT shift, start_time, end_time FROM production.shift_windows WHERE tenant_id = %s", (TENANT,)
            ).fetchall()
        }
        self.raw_store = self.locations["raw-materials"]
        self.finished_store = self.locations["produits-finis"]
        self.shift_cycle = shift_order(
            [ShiftWindow(shift=shift, start=start, end=end) for shift, (start, end) in self.windows.items()]
        )
        self.rotation = conn.execute(
            "SELECT team, anchor_date, anchor_stop FROM production.team_rotation WHERE tenant_id = %s ORDER BY team",
            (TENANT,),
        ).fetchall()


def window_of(refs: Refs, day: datetime.date, shift: str) -> tuple[datetime.datetime, datetime.datetime]:
    start, end = refs.windows[shift]
    begin = datetime.datetime.combine(day, start)
    finish = datetime.datetime.combine(day, end)
    if finish <= begin:
        finish += datetime.timedelta(days=1)
    return begin, finish


def iso(moment: datetime.datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def hhmm(value: datetime.time) -> str:
    return value.strftime("%H:%M")


class OrderBook:
    """One ongoing OF per line, reused across all shifts."""

    def __init__(self, conn, refs: Refs) -> None:
        self._service = WorkOrderService(conn)
        self._refs = refs
        self._orders: dict[str, str] = {}  # line -> of_id
        self.created: list[str] = []

    def checkpoint(self) -> int:
        return len(self.created)

    def forget_after(self, checkpoint: int) -> None:
        del self.created[checkpoint:]

    def get(self, line: str, product: dict, day: datetime.date) -> str:
        """Get or create a single ongoing OF per line."""
        if line not in self._orders:
            cfg = LINES[line]
            made = self._service.create_work_order(
                tenant_id=TENANT, actor_id=self._refs.actor, product_id=self._refs.products[product["sku"]],
                planned_quantity=cfg["planned"], work_center_id=self._refs.wc[cfg["wc"]], start_date=day,
            )
            if isinstance(made, Err):
                raise RuntimeError(f"cannot create a work order: {made.message}")
            started = self._service.start_work_order(tenant_id=TENANT, actor_id=self._refs.actor, work_order_id=made.value.id)
            if isinstance(started, Err):
                raise RuntimeError(f"cannot start a work order: {started.message}")
            self._orders[line] = made.value.id
            self.created.append(made.value.id)
        return self._orders[line]


def build_shift(rng: random.Random, refs: Refs, orders: OrderBook, lots: Counter, line: str, day: datetime.date, shift: str) -> dict:
    """Generate shift data."""
    cfg = LINES[line]
    begin, finish = window_of(refs, day, shift)
    minutes = int((finish - begin).total_seconds() // 60)
    hours = minutes // 60

    two_runs = line == "PC" and rng.random() < 0.55
    products = rng.sample(cfg["products"], 2) if two_runs else [rng.choice(cfg["products"])]
    split = begin + datetime.timedelta(minutes=int(minutes * rng.uniform(0.4, 0.6))) if two_runs else None
    windows = [(begin, split), (split, finish)] if two_runs else [(begin, finish)]

    stops: list[dict] = []
    cursor = begin + datetime.timedelta(minutes=rng.randint(30, 90))
    if two_runs:
        stops.append(dict(kind=("format_change", "preventive", "mechanical", "production", "Changement de moule",
                                "Nettoyage puis changement de moule"), start=split - datetime.timedelta(minutes=rng.randint(15, 25)),
                          minutes=rng.randint(30, 55)))
    for _ in range(rng.choice([1, 1, 2, 2, 3])):
        kind = rng.choice(STOP_KINDS)
        length = rng.randint(*kind[4])
        if cursor + datetime.timedelta(minutes=length + 20) > finish:
            break
        start = cursor
        if two_runs and abs((start - split).total_seconds()) < 90 * 60:
            start = split + datetime.timedelta(minutes=45)
            if start + datetime.timedelta(minutes=length + 20) > finish:
                continue
        stops.append(dict(kind=(kind[0], kind[1], kind[2], kind[3], kind[5], kind[6]), start=start, minutes=length))
        cursor = start + datetime.timedelta(minutes=length + rng.randint(40, 100))
    for stop in stops:
        stop["end"] = stop["start"] + datetime.timedelta(minutes=stop["minutes"])

    def stops_in(window):
        return [s for s in stops if window[0] <= s["start"] < window[1]]

    runs, packing, waste_lines = [], [], []
    for index, (product, window) in enumerate(zip(products, windows)):
        run_stops = sum(s["minutes"] for s in stops_in(window))
        span = int((window[1] - window[0]).total_seconds() // 60)
        run_minutes = max(60, span - run_stops)
        finished = round(product["rate"] * run_minutes / 60 * rng.uniform(0.92, 1.04), 2)
        semolina = round(finished * 0.9, 2)
        main = round(semolina * 0.92, 2)
        second = round(semolina - main, 2)
        regrind = round(rng.uniform(0.03, 0.22), 3) if rng.random() < 0.12 else 0
        runs.append(dict(
            of_id=orders.get(line, product, day), mold_id=refs.molds[product["mold"]], equipment_id=refs.equipment[cfg["extrusion"]],
            lot_number=None, start_time=hhmm(window[0].time()), end_time=hhmm(window[1].time()),
            production_minutes=run_minutes, dough_quantity=finished, finished_product_quantity=finished,
            regrind_quantity=regrind, raw_material_location_id=refs.raw_store,
            water_percentage=round(rng.uniform(29.6, 31.4), 1), humidity_percentage=round(rng.uniform(11.2, 12.4), 2),
            semolina_flow_rate=round(semolina / max(run_minutes / 60, 1), 2),
            semolina_lines=[
                dict(product_id=refs.products["semoule-ble-dur-salem"], location_id=refs.raw_store, quantity=main,
                     bag_count=round(main * 20), lot_number=f"BSTK{rng.randint(1, 4)}"),
                dict(product_id=refs.products[cfg["second_semolina"]], location_id=refs.raw_store, quantity=second,
                     bag_count=round(second * 20), lot_number=f"BSTK{rng.randint(5, 6)}"),
            ],
        ))
        lots[line] += 1
        lot = f"B{cfg['lot_start'] + lots[line]}SNL"
        runs[-1]["lot_number"] = lot
        packets = round(finished * 1000 / product["net_kg"] * rng.uniform(0.97, 0.995))
        cartons = round(packets / product["ppc"])
        packing.append(dict(
            of_id=runs[-1]["of_id"], product_id=refs.products[product["sku"]], run_index=index,
            equipment_id=refs.equipment[cfg["packing_machine"]], lot_number=lot,
            packing_type=product["packing_type"], film_type="Polypropylène",
            finished_product_quantity=round(cartons * product["ppc"] * product["net_kg"] / 1000, 2), packets_counted=packets,
            film_quantity=round(packets * product["film_kg"] * rng.uniform(0.97, 1.03), 2), carton_quantity=cartons,
            waste_carton_quantity=rng.randint(0, 10), scotch_quantity=max(1, round(cartons / 120)),
            ruban_quantity=1 if rng.random() < 0.12 else 0,
            film_product_id=refs.products[cfg["film"]], carton_product_id=refs.products[cfg["carton"]],
            scotch_product_id=refs.products["scotch"], ruban_product_id=refs.products["ruban-tb200"],
            packaging_location_id=refs.raw_store, finished_goods_location_id=refs.finished_store,
            production_minutes=run_minutes,
        ))
        # The floor's carton tally includes the waste cartons; only the others hold packets.
        packing[-1]["carton_quantity"] += packing[-1]["waste_carton_quantity"]
        for category, (low, high), cause in rng.sample(WASTE_KINDS, rng.choice([1, 2, 2, 3])):
            waste_lines.append(dict(
                category=category, product_id=refs.products["semoule-ble-dur-salem"], quantity=rng.randint(low, high),
                run_index=index, occurred_at=iso(window[0] + datetime.timedelta(minutes=rng.randint(20, max(21, span - 20)))),
                lot_number=lot, note=cause,
            ))

    stop_rows = []
    for stop in stops:
        motif, type_, classification, side, breakdown, action = stop["kind"]
        run_index = 0 if not two_runs else (0 if stop["start"] < split else 1)
        stop_rows.append(dict(
            equipment_id=refs.equipment[cfg["extrusion"] if side == "production" else cfg["packing_machine"]],
            started_at=iso(stop["start"]), ended_at=iso(stop["end"]), motif=motif, downtime_type=type_,
            classification=classification, note=breakdown, corrective_action=action,
            **({"run_index": run_index} if side == "production" else {"packing_index": run_index}),
        ))

    mold_washes = []
    if two_runs:
        mold_washes.append(dict(mold_id=runs[0]["mold_id"], washed_at=iso(split - datetime.timedelta(minutes=10)), state="Propre"))
    if rng.random() < 0.5:
        mold_washes.append(dict(mold_id=runs[-1]["mold_id"], washed_at=iso(finish - datetime.timedelta(minutes=35)), state="Propre"))

    packing_waste = []
    for index in range(len(packing)):
        if rng.random() < 0.85:
            packing_waste.append(dict(
                category="packaging", product_id=refs.products[cfg["film"]], quantity=round(rng.uniform(2, 9), 1),
                packing_index=index, occurred_at=iso(begin + datetime.timedelta(minutes=rng.randint(60, minutes - 30))),
                lot_number=packing[index]["lot_number"], note="Changement de bobine et problème de poids et collage",
            ))
        if rng.random() < 0.4:
            packing_waste.append(dict(
                category="product", product_id=refs.products[products[index]["sku"]], quantity=rng.randint(2, 35),
                packing_index=index, occurred_at=iso(begin + datetime.timedelta(minutes=rng.randint(60, minutes - 30))),
                lot_number=packing[index]["lot_number"], note="Paquets déformés",
            ))

    packet_checks = []
    if rng.random() < 0.92:
        net_g = int(products[0]["net_kg"] * 1000)
        for hour in range(hours):
            weak = rng.random() < 0.07
            packet_checks.append(dict(
                checked_at=iso(begin + datetime.timedelta(hours=hour)), film_state="Bon", packet_weight_grams=net_g + rng.randint(-3, 4),
                long_weld="Bon", vertical_weld="Bon", date_print="Faible" if weak else "Bon",
                note="Réglage de l'imprimante effectué" if weak else None,
            ))

    silo = [
        dict(side="production", phase="start", format=products[0]["sku"], lot_number=runs[0]["lot_number"], level_percent=rng.randint(45, 85), line_state="En marche"),
        dict(side="production", phase="end", format=products[-1]["sku"], lot_number=runs[-1]["lot_number"], level_percent=rng.randint(15, 45), line_state="En marche"),
        dict(side="packing", phase="start", format=products[0]["sku"], lot_number=packing[0]["lot_number"], level_percent=0, line_state="En marche"),
        dict(side="packing", phase="end", format=products[-1]["sku"], lot_number=packing[-1]["lot_number"], level_percent=0, line_state="En marche"),
    ]
    gasoil_shift = rng.random() < 0.4
    energy = dict(
        fuel_quantity=rng.randint(430, 640), gasoil_quantity=rng.randint(35, 95) if gasoil_shift else 0,
        gasoil_flow_rate=round(rng.uniform(12, 18), 1) if gasoil_shift else 0, generator_hours=round(rng.uniform(3, 6), 1) if gasoil_shift else 0,
        electricity_quantity=round(rng.uniform(1100, 1750), 1),
    )
    return dict(
        runs=runs, packing=packing, stops=stop_rows, waste_lines=waste_lines, mold_washes=mold_washes, packing_waste=packing_waste,
        packet_checks=packet_checks, silo=silo, energy=energy,
        staffing=dict(control_room=1, petrin=rng.choice([2, 2, 3]), semoule=1, broyage=1),
        first_of=runs[0]["of_id"],
    )


def team_for(refs: Refs, day: datetime.date, shift: str) -> str | None:
    """Who is on `shift` on `day`, per the plant's actual team rotation
    (Production Settings > Team Rotation) -- not a pattern invented here, so
    the seeded reports agree with what the dashboard computes for the same
    rotation config. None means every configured team is resting or off that
    slot (e.g. no rotation configured at all): the caller skips the shift."""
    if not refs.rotation:
        return None
    schedule = team_rotation_schedule(shifts=refs.shift_cycle, rotation=refs.rotation, date=day)
    for entry in schedule:
        if entry["shift"] == shift:
            return entry["team"]
    return None


def resolve(rows: list[dict], run_ids: list[str], packing_ids: list[str]) -> list[dict]:
    """Turn 'run_index' / 'packing_index' into the ids the server gave those rows."""
    out = []
    for row in rows:
        row = dict(row)
        if "run_index" in row:
            row["run_id"] = run_ids[row.pop("run_index")]
        if "packing_index" in row:
            row["packing_row_id"] = packing_ids[row.pop("packing_index")]
        out.append(row)
    return out


def ok(result, what: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{what}: {result.code} - {result.message}")
    return result.value


def apply_shift(conn, refs: Refs, line: str, day: datetime.date, shift: str, plan: dict, rng: random.Random) -> str:
    """Write the shift. Returns the shift's id. All shifts are submitted (handed in)."""
    shifts = ShiftReportService(conn)
    cfg = LINES[line]
    team = team_for(refs, day, shift)
    if team is None:
        raise RuntimeError(f"no team rotation configured for {day} {shift} -- run Production Settings > Team Rotation first")
    crew = dict(CREWS.get(team, {}))
    if rng.random() < 0.1:
        crew["machiniste"] = rng.choice([c["machiniste"] for c in CREWS.values()])
    header = ok(shifts.open_shift(tenant_id=TENANT, actor_id=refs.actor, work_center_id=refs.wc[cfg["wc"]], report_date=day, shift=shift, team=team), "open")
    sid = header["id"]
    ok(shifts.update_header(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, fields=crew), "header")

    def save(key: str, payload: dict):
        ok(shifts.save_section(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_key=key, payload=payload), f"save {key}")

    def rows_of(key: str, part: str) -> list[dict]:
        section = next(s for s in ok(shifts.get_shift(tenant_id=TENANT, shift_report_id=sid), "read")["sections"] if s["key"] == key)
        return section["payload"][part]

    save("runs", {"runs": plan["runs"]})
    run_ids = [r["id"] for r in rows_of("runs", "runs")]
    save("packing", {"rows": resolve(plan["packing"], run_ids, [])})
    packing_ids = [r["id"] for r in rows_of("packing", "rows")]

    payloads = {
        "waste_production": {"waste_lines": resolve(plan["waste_lines"], run_ids, packing_ids), "mold_washes": plan["mold_washes"]},
        "stops": {"stops": resolve(plan["stops"], run_ids, packing_ids)},
        "silo": {"states": plan["silo"]},
        "staffing": {"staffing": plan["staffing"]},
        "packet_checks": {"checks": plan["packet_checks"]},
        "waste_packing": {"waste_lines": resolve(plan["packing_waste"], run_ids, packing_ids)},
        "energy": {"energy": plan["energy"]},
    }

    def empty(key: str) -> bool:
        payload = payloads[key]
        return all(not value for value in payload.values())

    def hand_in(key: str):
        if key in ("runs", "packing"):
            ok(shifts.submit_section(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_key=key), f"submit {key}")
        elif empty(key):
            ok(shifts.declare_nothing(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_key=key), f"nothing {key}")
        else:
            save(key, payloads[key])
            ok(shifts.submit_section(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_key=key), f"submit {key}")

    for key in SECTION_KEYS:
        hand_in(key)

    return sid


def backdate(conn, sid: str, day: datetime.date, shift: str, refs: Refs, rng: random.Random) -> None:
    """Make the timestamps read like the shift really happened then."""
    _, finish = window_of(refs, day, shift)
    submitted = finish + datetime.timedelta(minutes=rng.randint(8, 45))
    started = window_of(refs, day, shift)[0]
    conn.execute("UPDATE production.shift_reports SET created_at = %s, updated_at = %s, submitted_at = %s WHERE id = %s",
                 (started, submitted, submitted, sid))
    conn.execute("UPDATE production.shift_report_sections SET updated_at = %s, submitted_at = %s WHERE shift_report_id = %s",
                 (submitted, submitted, sid))
    conn.execute("UPDATE core.audit_log SET occurred_at = %s WHERE entity_id = %s", (submitted, sid))


def shifts_to_seed(day: datetime.date, line: str) -> list[str]:
    """Determine which shifts should exist for a given day/line.

    - Past days: all 3 shifts exist (matin, après-midi, nuit)
    - Today (Sep 24): only matin exists (après-midi/nuit haven't finished yet)
    - Future days: no shifts exist yet
    """
    if day < TODAY:
        # Past days: all shifts completed
        return LINES[line]["shifts"]
    elif day == TODAY:
        # Today: only the morning shift has completed (it ends at 14:00)
        # Night shift from yesterday (Sep 23) is already seeded
        # Afternoon shift is currently happening, night hasn't started
        return ["matin"]
    else:
        # Future days: no shifts yet (they'll be created as teams work)
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="first", default=(TODAY - datetime.timedelta(days=7)).isoformat(), help="start date (default: 7 days ago)")
    parser.add_argument("--to", dest="last", default=TODAY.isoformat(), help="end date (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll it all back")
    args = parser.parse_args()
    first = datetime.date.fromisoformat(args.first)
    last = datetime.date.fromisoformat(args.last)

    outcomes: Counter = Counter()
    failures: list[str] = []
    with get_connection() as conn:
        refs = Refs(conn)
        orders = OrderBook(conn, refs)
        lots: Counter = Counter()
        if not args.dry_run:
            conn.commit()
        tasks = []
        day = first
        while day <= last:
            for line in ("PL", "PC"):
                for shift in shifts_to_seed(day, line):
                    tasks.append((day, line, shift))
            day += datetime.timedelta(days=1)
        done = 0
        for day, line, shift in tasks:
            exists = conn.execute(
                "SELECT 1 FROM production.shift_reports WHERE tenant_id = %s AND work_center_id = %s AND report_date = %s AND shift = %s",
                (TENANT, refs.wc[LINES[line]["wc"]], day, shift)).fetchone()
            if exists:
                outcomes["skipped (already there)"] += 1
                print(f"  skip {day} {line} {shift} (already exists)")
                continue
            if done >= 100:
                print(f"  limit reached at {day} {line} {shift}")
                break
            rng = random.Random(f"{day.isoformat()}-{line}-{shift}")
            checkpoint = orders.checkpoint()
            try:
                with conn.transaction():
                    plan = build_shift(rng, refs, orders, lots, line, day, shift)
                    sid = apply_shift(conn, refs, line, day, shift, plan, rng)
                    backdate(conn, sid, day, shift, refs, rng)
                outcomes["submitted"] += 1
                done += 1
                if not args.dry_run:
                    conn.commit()
                print(f"  created {day} {line} {shift}")
            except Exception as error:
                orders.forget_after(checkpoint)
                failures.append(f"{day} {line} {shift}: {error}")
                print(f"  FAILED {day} {line} {shift}: {error}", file=sys.stderr)

        if args.dry_run:
            conn.rollback()
            print("\nDRY RUN: everything above was rolled back")
        else:
            conn.commit()

    print(f"\nshifts created: {dict(outcomes)}")
    print(f"work orders created: {len(orders.created)}")
    if failures:
        print(f"\n{len(failures)} shift(s) failed:")
        for line in failures[:20]:
            print("  ", line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

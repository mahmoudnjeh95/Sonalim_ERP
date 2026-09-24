"""Load a month of shift reports, through the real services, so there is something to see and validate.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_shift_month.py --dry-run --limit 6
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_shift_month.py

It fills the shift screens the way teams would, hands sections in, and validates the older
shifts so stock, dashboards and the day sheet have history. The newest shifts are left where
they would be in a real week: handed in and waiting for the validator, a few sent back, a few
edited after hand-in (so the history panel has something to show), and a few unfinished.

Everything is test data. It is generated from a fixed seed, so a run is repeatable, and it
skips any line/date/shift that already has a report. `--dry-run` does the whole job in one
transaction and rolls it back.
"""
from __future__ import annotations

import argparse
import datetime
import random
import sys
from collections import Counter

from ulid import ULID

from core.db import get_connection
from core.domain.result import Err, Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "demo"
ACTOR_EMAIL = "demo@sonalim-erp.local"
TODAY = datetime.date(2026, 9, 20)
FIRST_DAY = datetime.date(2026, 8, 20)
REGRIND_LINE_CODE = "rebroyat_01"

TEAMS = ["Équipe A", "Équipe B", "Équipe C"]
CREWS = {
    "Équipe A": dict(conducteur="Alou Traoré", agent_fabrication="Moussa Soumaoro", machiniste="D. Samaké", aide_machiniste="S. Togola"),
    "Équipe B": dict(conducteur="Ibrahim Keita", agent_fabrication="Sékou Camara", machiniste="K. Doumbia", aide_machiniste="M. Dembélé"),
    "Équipe C": dict(conducteur="Amadou Coulibaly", agent_fabrication="Bakary Sidibé", machiniste="S. Fofana", aide_machiniste="A. Konaté"),
}

LINES = {
    "PL": dict(
        wc="Line_1", shifts=("morning", "afternoon", "night"), extrusion="PL-01-02", packing_machine="PL-01-03",
        film="film-pl-laize-230mm", carton="carton-pl-500g-c", second_semolina="semoule-extra-fine-salem", lot_start=6100,
        planned=80,
        products=[dict(sku="doman-pl-500g", mold="MLD-PL-01", rate=1.55, net_kg=0.5, ppc=20, film_kg=0.0045, packing_type="Sachet 500 g")],
    ),
    "PC": dict(
        wc="Line_2", shifts=("morning", "afternoon"), extrusion="PC-02-02", packing_machine="PC-02-03",
        film="film-pc-laize-390mm", carton="carton-pc-500g", second_semolina="semoule-fine-salem", lot_start=7100,
        planned=40,
        products=[
            dict(sku="COQ6-500G", mold="MLD-PC-01", rate=0.95, net_kg=0.5, ppc=20, film_kg=0.0045, packing_type="Sachet 500 g"),
            dict(sku="doman-pc-500g", mold="MLD-PC-02", rate=0.92, net_kg=0.5, ppc=20, film_kg=0.0045, packing_type="Sachet 500 g"),
            dict(sku="doman-pc-200g", mold="MLD-PC-03", rate=0.70, net_kg=0.2, ppc=40, film_kg=0.0028, packing_type="Sachet 200 g"),
        ],
    ),
}

# Stops: (motif, type, classification, side, minutes range, breakdown, corrective action)
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

# What happens to each shift. Anything not listed is validated (older) or handed in (this week).
SPECIAL = {
    (datetime.date(2026, 8, 25), "PL", "morning"): "validated+revised",
    (datetime.date(2026, 9, 1), "PL", "afternoon"): "validated+revised",
    (datetime.date(2026, 8, 28), "PC", "afternoon"): "validated+revised",
    (datetime.date(2026, 9, 5), "PL", "morning"): "validated+revised",
    (datetime.date(2026, 9, 15), "PL", "morning"): "revised",
    (datetime.date(2026, 9, 18), "PC", "afternoon"): "revised",
    (datetime.date(2026, 9, 16), "PL", "afternoon"): "returned:packing:Le nombre de cartons ne correspond pas aux paquets comptés",
    (datetime.date(2026, 9, 17), "PC", "morning"): "returned:energy:Le compteur électrique semble faux, vérifier le relevé",
    (datetime.date(2026, 9, 19), "PL", "night"): "partial",
    (datetime.date(2026, 9, 19), "PC", "afternoon"): "draft",
    (TODAY, "PL", "night"): "draft_runs",
}


def outcome_for(day: datetime.date, line: str, shift: str) -> str:
    special = SPECIAL.get((day, line, shift))
    if special:
        return special
    return "submitted" if day >= datetime.date(2026, 9, 14) else "validated"


def shifts_for(day: datetime.date, line: str) -> list[str]:
    """The plant rests on Sundays (today excepted), and each line has one maintenance day."""
    if day == TODAY:
        return {"PL": ["morning", "afternoon", "night"], "PC": ["morning"]}[line]
    if day.weekday() == 6:
        return []
    if line == "PC" and day == datetime.date(2026, 9, 2):
        return []
    if line == "PL" and day == datetime.date(2026, 8, 27):
        return ["night"]
    return list(LINES[line]["shifts"])


def hhmm(value: datetime.time) -> str:
    return value.strftime("%H:%M")


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


def window_of(refs: Refs, day: datetime.date, shift: str) -> tuple[datetime.datetime, datetime.datetime]:
    start, end = refs.windows[shift]
    begin = datetime.datetime.combine(day, start)
    finish = datetime.datetime.combine(day, end)
    if finish <= begin:
        finish += datetime.timedelta(days=1)
    return begin, finish


def iso(moment: datetime.datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


class OrderBook:
    """One OF per line, product and week, created on first use."""

    def __init__(self, conn, refs: Refs) -> None:
        self._service = WorkOrderService(conn)
        self._refs = refs
        self._orders: dict[tuple, str] = {}
        self._keys: list[tuple] = []
        self.created: list[tuple[str, datetime.date]] = []

    def checkpoint(self) -> int:
        return len(self.created)

    def forget_after(self, checkpoint: int) -> None:
        """A shift that rolled back took its new work orders with it; drop them from the cache too."""
        for key in self._keys[checkpoint:]:
            self._orders.pop(key, None)
        del self._keys[checkpoint:]
        del self.created[checkpoint:]

    def get(self, line: str, product: dict, day: datetime.date) -> str:
        key = (line, product["sku"], day.isocalendar()[1])
        if key not in self._orders:
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
            self._orders[key] = made.value.id
            self._keys.append(key)
            self.created.append((made.value.id, day))
        return self._orders[key]


def build_shift(rng: random.Random, refs: Refs, orders: OrderBook, lots: Counter, line: str, day: datetime.date, shift: str) -> dict:
    """Everything one shift's team would write, as section payloads. Rows point at a run or a lot by index."""
    cfg = LINES[line]
    begin, finish = window_of(refs, day, shift)
    minutes = int((finish - begin).total_seconds() // 60)
    hours = minutes // 60

    # --- how the shift splits into runs (a PC mold change changes the product) -------------------
    two_runs = line == "PC" and rng.random() < 0.55
    products = rng.sample(cfg["products"], 2) if two_runs else [rng.choice(cfg["products"])]
    split = begin + datetime.timedelta(minutes=int(minutes * rng.uniform(0.4, 0.6))) if two_runs else None
    windows = [(begin, split), (split, finish)] if two_runs else [(begin, finish)]

    # --- stops, laid out one after another so they never overlap ---------------------------------
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
        # keep clear of the format change
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

    # --- runs -----------------------------------------------------------------------------------
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
        # --- the lot this run was packed into -------------------------------------------------
        lots[line] += 1
        lot = f"B{cfg['lot_start'] + lots[line]}SNL"
        runs[-1]["lot_number"] = lot
        packets = round(finished * 1000 / product["net_kg"] * rng.uniform(0.97, 0.995))
        cartons = round(packets / product["ppc"])
        packing.append(dict(
            of_id=runs[-1]["of_id"], run_index=index, equipment_id=refs.equipment[cfg["packing_machine"]], lot_number=lot,
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
        # --- production waste for this run ----------------------------------------------------
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


def team_for(day: datetime.date, shift: str) -> str:
    week = (day - datetime.date(2026, 8, 17)).days // 7
    return TEAMS[(["morning", "afternoon", "night"].index(shift) + week) % 3]


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


def apply_shift(conn, refs: Refs, line: str, day: datetime.date, shift: str, plan: dict, outcome: str, rng: random.Random) -> str:
    """Write the shift the way a team and a validator would. Returns the shift's id."""
    shifts, validator = ShiftReportService(conn), ShiftValidationService(conn)
    cfg = LINES[line]
    team = team_for(day, shift)
    crew = dict(CREWS[team])
    if rng.random() < 0.1:  # someone covers now and then
        crew["machiniste"] = rng.choice([c["machiniste"] for c in CREWS.values()])
    header = ok(shifts.open_shift(tenant_id=TENANT, actor_id=refs.actor, work_center_id=refs.wc[cfg["wc"]], report_date=day, shift=shift, team=team), "open")
    sid = header["id"]
    ok(shifts.update_header(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, fields=crew), "header")

    def save(key: str, payload: dict):
        ok(shifts.save_section(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_key=key, payload=payload), f"save {key}")

    def rows_of(key: str, part: str) -> list[dict]:
        section = next(s for s in ok(shifts.get_shift(tenant_id=TENANT, shift_report_id=sid), "read")["sections"] if s["key"] == key)
        return section["payload"][part]

    # runs and packing first: every other section points at their ids
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

    if outcome == "draft_runs":  # a shift still being filled: the run is typed in, nothing handed in
        return sid
    if outcome == "draft":  # a team that has only typed its stops so far
        save("stops", payloads["stops"])
        return sid
    if outcome == "partial":  # production handed in, the rest still to do
        hand_in("runs")
        save("stops", payloads["stops"])
        return sid

    for key in SECTION_KEYS:
        hand_in(key)

    if outcome.endswith("revised") or outcome == "validated+revised":
        lines = payloads["waste_production"]["waste_lines"]
        if lines:
            ids = [r["id"] for r in rows_of("waste_production", "waste_lines")]
            edited = [dict(line, id=ids[i]) for i, line in enumerate(lines)]
            edited[0]["quantity"] = float(edited[0]["quantity"]) + rng.randint(2, 8)
            ok(shifts.save_section(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_key="waste_production",
                                   payload={"waste_lines": edited, "mold_washes": plan["mold_washes"]}, reason="Correction de la quantité après pesée"),
               "revise")
    if outcome.startswith("returned:"):
        _, key, reason = outcome.split(":", 2)
        ok(validator.reject_sections(tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, section_keys=[key], reason=reason), "reject")
    if outcome.startswith("validated"):
        ok(validator.validate_shift(
            tenant_id=TENANT, actor_id=refs.actor, shift_report_id=sid, regrind_work_center_id=refs.wc[REGRIND_LINE_CODE],
            shortfall_comment="Stock initial incomplet, régularisé à la réception",
        ), "validate")
    return sid


def backdate(conn, sid: str, day: datetime.date, shift: str, refs: Refs, outcome: str, rng: random.Random) -> None:
    """Make the timestamps read like the shift really happened then, not when the seed ran."""
    _, finish = window_of(refs, day, shift)
    submitted = finish + datetime.timedelta(minutes=rng.randint(8, 45))
    validated = finish + datetime.timedelta(hours=rng.randint(3, 20), minutes=rng.randint(0, 59))
    started = window_of(refs, day, shift)[0]
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM production.shift_runs WHERE shift_report_id = %s UNION SELECT id FROM production.shift_packing_rows WHERE shift_report_id = %s",
        (sid, sid)).fetchall()]
    is_validated = outcome.startswith("validated")
    conn.execute("UPDATE production.shift_reports SET created_at = %s, updated_at = %s, submitted_at = CASE WHEN submitted_at IS NULL THEN NULL ELSE %s END, "
                 "validated_at = CASE WHEN validated_at IS NULL THEN NULL ELSE %s END WHERE id = %s", (started, submitted, submitted, validated, sid))
    conn.execute("UPDATE production.shift_report_sections SET updated_at = %s, submitted_at = CASE WHEN submitted_at IS NULL THEN NULL ELSE %s END WHERE shift_report_id = %s",
                 (submitted, submitted, sid))
    conn.execute("UPDATE production.shift_section_revisions SET created_at = %s WHERE shift_report_id = %s AND section_key <> '*'", (submitted, sid))
    conn.execute("UPDATE production.shift_section_revisions SET created_at = %s WHERE shift_report_id = %s AND section_key = '*'", (validated, sid))
    conn.execute("UPDATE core.audit_log SET occurred_at = %s WHERE entity_id = %s AND action <> 'shift_report.validated'", (submitted, sid))
    conn.execute("UPDATE core.audit_log SET occurred_at = %s WHERE entity_id = %s AND action = 'shift_report.validated'", (validated, sid))
    if ids and is_validated:
        conn.execute("UPDATE production.production_reports SET created_at = %s, updated_at = %s, submitted_at = %s, validated_at = %s WHERE id = ANY(%s)",
                     (started, validated, submitted, validated, ids))
        conn.execute("UPDATE warehouse.stock_moves SET created_at = %s WHERE source_id = ANY(%s)", (validated, ids))


def receive_stock(conn, refs: Refs) -> None:
    """The month's deliveries, dated just before it starts, so validation never runs the stores dry."""
    already = conn.execute("SELECT count(*) FROM warehouse.stock_moves WHERE reference = 'seed-month-receipt'").fetchone()[0]
    if already:
        print("stock already received for the seed; skipping")
        return
    stock = StockService(conn)
    deliveries = [
        ("semoule-ble-dur-salem", 3000), ("semoule-extra-fine-salem", 150), ("semoule-fine-salem", 150),
        ("carton-pl-500g-c", 150000), ("carton-pc-500g", 60000), ("film-pl-laize-230mm", 4000), ("film-pc-laize-390mm", 3000),
        ("scotch", 1500), ("ruban-tb200", 200),
    ]
    for sku, quantity in deliveries:
        ok(stock.receive_stock(
            tenant_id=TENANT, product_id=refs.products[sku], location_id=refs.raw_store, quantity=quantity,
            correlation_id=str(ULID()), reference="seed-month-receipt", actor_id=refs.actor,
        ), f"receive {sku}")
    conn.execute("UPDATE warehouse.stock_moves SET created_at = %s WHERE reference = 'seed-month-receipt'", (datetime.datetime(2026, 8, 19, 8, 0),))


class _Refused(Exception):
    pass


def close_finished_orders(conn, refs: Refs, orders: OrderBook) -> tuple[int, list[str]]:
    """Orders whose weeks are behind us are closed, as a plant would; anything that refuses stays open."""
    service = WorkOrderService(conn)
    closed, reasons = 0, []
    for order_id, started in orders.created:
        if started >= datetime.date(2026, 9, 7):
            continue
        try:
            with conn.transaction():
                result = service.close_work_order(
                    tenant_id=TENANT, actor_id=refs.actor, work_order_id=order_id, correlation_id=str(ULID()),
                    closed_at=datetime.datetime.combine(started + datetime.timedelta(days=7), datetime.time(18, 0)),
                )
                if isinstance(result, Err):
                    raise _Refused(result.message)
            closed += 1
        except _Refused as refusal:
            reasons.append(str(refusal))
    return closed, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="first", default=FIRST_DAY.isoformat())
    parser.add_argument("--to", dest="last", default=TODAY.isoformat())
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll it all back")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many shifts (for a dry run)")
    args = parser.parse_args()
    first, last = datetime.date.fromisoformat(args.first), datetime.date.fromisoformat(args.last)

    outcomes: Counter = Counter()
    failures: list[str] = []
    with get_connection() as conn:
        refs = Refs(conn)
        receive_stock(conn, refs)
        orders = OrderBook(conn, refs)
        lots: Counter = Counter()
        if not args.dry_run:
            conn.commit()
        tasks = []
        day = first
        while day <= last:
            for line in ("PL", "PC"):
                for shift in shifts_for(day, line):
                    tasks.append((day, line, shift))
            day += datetime.timedelta(days=1)
        done = 0
        for day, line, shift in tasks:
            exists = conn.execute(
                "SELECT 1 FROM production.shift_reports WHERE tenant_id = %s AND work_center_id = %s AND report_date = %s AND shift = %s",
                (TENANT, refs.wc[LINES[line]["wc"]], day, shift)).fetchone()
            if exists:
                outcomes["skipped (already there)"] += 1
                continue
            if args.limit and done >= args.limit:
                break
            rng = random.Random(f"{day.isoformat()}-{line}-{shift}")
            outcome = outcome_for(day, line, shift)
            checkpoint = orders.checkpoint()
            try:
                with conn.transaction():
                    plan = build_shift(rng, refs, orders, lots, line, day, shift)
                    sid = apply_shift(conn, refs, line, day, shift, plan, outcome, rng)
                    backdate(conn, sid, day, shift, refs, outcome, rng)
                outcomes[outcome.split(":")[0]] += 1
                done += 1
                if not args.dry_run:
                    conn.commit()
            except Exception as error:  # one bad shift must not stop the month
                orders.forget_after(checkpoint)
                failures.append(f"{day} {line} {shift} ({outcome}): {error}")
                print(f"  FAILED {day} {line} {shift}: {error}", file=sys.stderr)

        closed, refusals = 0, []
        if not args.limit:
            closed, refusals = close_finished_orders(conn, refs, orders)
        if args.dry_run:
            conn.rollback()
            print("DRY RUN: everything above was rolled back")
        else:
            conn.commit()

    print("\nshifts by outcome:", dict(outcomes))
    print(f"work orders created: {len(orders.created)}; closed: {closed}; left open: {len(orders.created) - closed}")
    if refusals:
        print("orders that refused to close:", dict(Counter(refusals)))
    if failures:
        print(f"\n{len(failures)} shift(s) failed:")
        for line in failures[:20]:
            print("  ", line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

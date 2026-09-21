"""Load a month of CRM work, through the real services: leads, opportunities and activities.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_crm_month.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_crm_month.py

Leads arrive through the month from the sources already in use and are qualified, disqualified or converted (which
makes the customer, its contact and a first opportunity) according to how long ago they came in. Opportunities,
those and new ones for the existing customers, move through the pipeline stage by stage and end won, lost or
still open. Amounts come from the same demo catalogue the sales seeder prices with; a won opportunity opens its
sales order the way the service does (a draft, here with priced lines). Activities (calls, tasks, meetings,
comments) hang off leads, opportunities and customers; the ones already past due are mostly done, some are overdue.

Test data, generated from a fixed seed. It skips itself once leads from the seed window exist.
The events the services queue are left unsent, like every other seeder's.
"""
from __future__ import annotations

import datetime
import random
import unicodedata
from collections import Counter

from ulid import ULID

from core.domain.result import Err
from modules.crm.api.activity_service import ActivityService
from modules.crm.api.lead_service import LeadService
from modules.crm.api.opportunity_service import OpportunityService
from modules.crm.domain.opportunity import WonLine
from scripts.seed_common import FIRST_DAY, TENANT, TODAY, actor_id, business_time, run, stamp_audit, stamp_events, working_days
from scripts.seed_sales_finance_month import CATALOGUE

NOW = datetime.datetime.combine(TODAY, datetime.time(15, 0))
HAND_MADE_FROM = datetime.date(2026, 9, 15)

PEOPLE = [
    ("Aminata Diarra", "diarra-distribution"), ("Oumar Sangaré", "sangare-import"), ("Fatoumata Coulibaly", "supermarche-coulibaly"),
    ("Seydou Maïga", "maiga-grossiste"), ("Mariam Traoré", "epicerie-traore"), ("Boubacar Sy", "sy-alimentation"),
    ("Kadiatou Keita", "keita-restauration"), ("Issa Konaté", "konate-negoce"), ("Awa Sidibé", "sidibe-boulangerie"),
    ("Modibo Dembélé", "dembele-logistique"), ("Nana Coulibaly", "nana-market"), ("Adama Diakité", "diakite-alimentaire"),
    ("Hawa Camara", "camara-cash-carry"), ("Lassana Bagayoko", "bagayoko-frais"), ("Salimata Doumbia", "doumbia-detail"),
    ("Yacouba Cissé", "cisse-import-export"), ("Rokia Samaké", "samake-traiteur"), ("Drissa Togola", "togola-magasin"),
    ("Bintou Fofana", "fofana-alimentation"), ("Mamadou Haïdara", "haidara-grossiste"), ("Kadidia Berthé", "berthe-distribution"),
    ("Cheick Ouattara", "ouattara-superette"), ("Aïssata Sow", "sow-epicerie"), ("Ibrahima Sanogo", "sanogo-negoce"),
]
SOURCES = ["website", "referral", "cold_call", "social_media", "trade_show"]
DISQUALIFY_REASONS = ["Budget too small for minimum order", "Pas de besoin actuel", "Hors zone de livraison", "Déjà fournisseur exclusif ailleurs"]
LOST_REASONS = ["Lost to a competitor", "Prix trop élevé", "Projet reporté"]
DEALS = ["Réassort trimestriel", "Programme promotionnel", "Commande d'ouverture", "Contrat annuel", "Nouveau format"]
STAGES = ["qualification", "proposal", "negotiation"]
NOTES = {
    "call": ["Appel de présentation de la gamme", "Relance sur le devis envoyé", "Point sur les délais de livraison"],
    "meeting": ["Visite du site client", "Dégustation et revue du contrat", "Réunion de cadrage du programme"],
    "task": ["Envoyer le catalogue et la grille tarifaire", "Préparer le devis", "Envoyer les échantillons"],
    "comment": ["Client sensible au prix, à suivre", "Demande de livraison groupée", "Contact clé : responsable des achats"],
}


def ascii_email(name: str, slug: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace(" ", ".")
    return f"{plain}@{slug}.example"


def at(moment: datetime.datetime) -> datetime.datetime:
    return min(moment, NOW)


def expect(result, what: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{what}: {result.code} {result.message}")
    return result.value


class Seeder:
    def __init__(self, conn) -> None:
        self.conn = conn
        self.actor = actor_id(conn)
        self.leads, self.opps, self.activities = LeadService(conn), OpportunityService(conn), ActivityService(conn)
        self.users = [r[0] for r in conn.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s AND email NOT LIKE 'audit-test%%' ORDER BY email", (TENANT,)).fetchall()]
        self.location = conn.execute("SELECT id FROM warehouse.locations WHERE tenant_id = %s AND code = 'produits-finis'", (TENANT,)).fetchone()[0]
        self.products = {sku: (pid, name) for sku, pid, name in conn.execute(
            "SELECT sku, id, name FROM core.products WHERE tenant_id = %s AND sku = ANY(%s)", (TENANT, list(CATALOGUE))).fetchall()}
        self.subjects: list[tuple[str, str, datetime.datetime]] = []  # what activities can hang off
        self.outcomes: Counter = Counter()

    def deal_lines(self, rng: random.Random) -> list[tuple[str, float]]:
        skus = rng.sample(sorted(CATALOGUE), k=rng.choice([1, 1, 2]))
        return [(sku, float(rng.choice(CATALOGUE[sku]["quantities"]) * rng.choice([1, 2, 3]))) for sku in skus]

    def deal_amount(self, lines) -> float:
        return round(sum(q * CATALOGUE[sku]["price"] for sku, q in lines), 2)

    def schedule(self, rng: random.Random, created: datetime.datetime) -> tuple[list[tuple[str, datetime.datetime]], str]:
        """The stage changes an opportunity went through, each dated, stopping where today runs out."""
        age = (TODAY - created.date()).days
        if age >= 14:
            end = rng.choices(["won", "lost", "open"], weights=[4, 3, 3])[0]
        elif age >= 6:
            end = rng.choices(["won", "lost", "open"], weights=[1, 1, 8])[0]
        else:
            end = "open"
        steps = STAGES + ["won"] if end == "won" else STAGES[: rng.randint(0, 3)] + ["lost"] if end == "lost" else STAGES[: rng.randint(0, 3)]
        dated, moment = [], created
        for stage in steps:
            moment = moment + datetime.timedelta(days=rng.randint(1, 5), hours=rng.randint(0, 6))
            if moment > NOW:
                break
            dated.append((stage, moment))
        return dated, end

    def advance(self, rng: random.Random, opp_id: str, dated: list[tuple[str, datetime.datetime]], lines) -> str:
        stage = "prospecting"
        for target, moment in dated:
            kwargs = {}
            if target == "lost":
                kwargs["lost_reason"] = rng.choice(LOST_REASONS)
            if target == "won":
                kwargs.update(won_lines=[WonLine(product_id=self.products[sku][0], quantity=q) for sku, q in lines], won_location_id=self.location,
                              requested_ship_date=moment.date() + datetime.timedelta(days=rng.randint(5, 12)))
            correlation = str(ULID())
            opportunity = expect(self.opps.transition_stage(tenant_id=TENANT, actor_id=self.actor, opportunity_id=opp_id, new_stage=target,
                                                             correlation_id=correlation, **kwargs), f"-> {target}")
            stamp_audit(self.conn, opp_id, moment)
            stamp_events(self.conn, correlation, moment)
            if target == "won":
                order_id = opportunity.sales_order_id
                stamp_audit(self.conn, order_id, moment)
                self.conn.execute("UPDATE sales.orders SET created_at = %s WHERE id = %s", (moment, order_id))
                for sku, _ in lines:
                    self.conn.execute("UPDATE sales.order_lines SET unit_price = %s WHERE order_id = %s AND product_id = %s",
                                      (CATALOGUE[sku]["price"], order_id, self.products[sku][0]))
            stage = target
        return stage

    def new_opportunity(self, rng: random.Random, partner_id: str, name: str, created: datetime.datetime, opp_id: str | None = None) -> str:
        lines = self.deal_lines(rng)
        dated, end = self.schedule(rng, created)
        closing = dated[-1][1].date() if end != "open" and dated and dated[-1][0] in ("won", "lost") else created.date() + datetime.timedelta(days=rng.randint(15, 45))
        owner, priority = rng.choice(self.users), rng.choices(["low", "medium", "high"], weights=[2, 5, 2])[0]
        if opp_id is None:
            opp_id = expect(self.opps.create_opportunity(tenant_id=TENANT, actor_id=self.actor, partner_id=partner_id, name=name, amount=self.deal_amount(lines),
                                                         expected_close_date=closing, owner_id=owner, priority=priority), "create opportunity").id
        else:  # the one a lead conversion opened, still at amount 0
            expect(self.opps.update_opportunity(tenant_id=TENANT, actor_id=self.actor, opportunity_id=opp_id, name=name, amount=self.deal_amount(lines),
                                                expected_close_date=closing, owner_id=owner, priority=priority), "update opportunity")
        stamp_audit(self.conn, opp_id, created)
        self.conn.execute("UPDATE crm.opportunities SET created_at = %s WHERE id = %s", (created, opp_id))
        stage = self.advance(rng, opp_id, dated, lines)
        self.outcomes[f"opportunity {stage}"] += 1
        self.subjects.append(("opportunity", opp_id, created))
        return opp_id

    def lead_fate(self, rng: random.Random, age: int) -> str:
        if age >= 12:
            return rng.choices(["converted", "disqualified", "qualified", "new"], weights=[35, 20, 25, 20])[0]
        if age >= 5:
            return rng.choices(["converted", "disqualified", "qualified", "new"], weights=[15, 15, 40, 30])[0]
        return rng.choices(["qualified", "new"], weights=[25, 75])[0]

    def lead(self, rng: random.Random, name: str, slug: str, created: datetime.datetime) -> None:
        conn = self.conn
        owner = rng.choice(self.users)
        lead = self.leads.create_lead(tenant_id=TENANT, actor_id=self.actor, contact_name=name, email=ascii_email(name, slug), source=rng.choice(SOURCES),
                                      owner_id=owner, priority=rng.choices(["low", "medium", "high"], weights=[3, 5, 2])[0])
        stamp_audit(conn, lead.id, created)
        conn.execute("UPDATE crm.leads SET created_at = %s WHERE id = %s", (created, lead.id))
        self.subjects.append(("lead", lead.id, created))
        fate = self.lead_fate(rng, (TODAY - created.date()).days)
        state = "new"
        if fate != "new":
            qualified_at = created + datetime.timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 5))
            if fate == "disqualified":
                disqualified_at = created + datetime.timedelta(days=rng.randint(1, 6), hours=rng.randint(0, 5))
                if disqualified_at <= NOW:
                    expect(self.leads.disqualify_lead(tenant_id=TENANT, actor_id=self.actor, lead_id=lead.id, reason=rng.choice(DISQUALIFY_REASONS),
                                                      correlation_id=str(ULID())), "disqualify")
                    stamp_audit(conn, lead.id, disqualified_at)
                    state = "disqualified"
            elif qualified_at <= NOW:
                expect(self.leads.qualify_lead(tenant_id=TENANT, actor_id=self.actor, lead_id=lead.id, correlation_id=str(ULID())), "qualify")
                stamp_audit(conn, lead.id, qualified_at)
                state = "qualified"
                converted_at = qualified_at + datetime.timedelta(days=rng.randint(1, 5), hours=rng.randint(0, 5))
                if fate == "converted" and converted_at <= NOW:
                    correlation = str(ULID())
                    done = expect(self.leads.convert_lead(tenant_id=TENANT, actor_id=self.actor, lead_id=lead.id, correlation_id=correlation), "convert")
                    partner, opportunity = done["partner"], done["opportunity"]
                    for entity in (lead.id, partner.id, opportunity.id):
                        stamp_audit(conn, entity, converted_at)
                    stamp_events(conn, correlation, converted_at)
                    conn.execute("UPDATE core.partners SET created_at = %s WHERE id = %s", (converted_at, partner.id))
                    conn.execute("UPDATE crm.contacts SET created_at = %s WHERE partner_id = %s", (converted_at, partner.id))
                    self.new_opportunity(rng, partner.id, f"Première commande {name}", converted_at, opp_id=opportunity.id)
                    state = "converted"
        self.outcomes[f"lead {state}"] += 1

    def activity(self, rng: random.Random, subject_type: str, subject_id: str, subject_created: datetime.datetime) -> None:
        kind = rng.choices(["call", "task", "meeting", "comment"], weights=[4, 3, 2, 2])[0]
        created = at(subject_created + datetime.timedelta(days=rng.randint(0, 12), hours=rng.randint(0, 8)))
        due = None if kind == "comment" else created + datetime.timedelta(days=rng.randint(1, 10), hours=rng.randint(0, 5))
        row = expect(self.activities.create_activity(tenant_id=TENANT, actor_id=self.actor, kind=kind, subject_type=subject_type, subject_id=subject_id,
                                                     note=rng.choice(NOTES[kind]), due_at=due), "activity")
        stamp_audit(self.conn, row.id, created)
        completed = None
        if due is not None and due <= NOW - datetime.timedelta(days=1) and rng.random() < 0.75:
            completed = at(due + datetime.timedelta(hours=rng.randint(0, 3)))
            expect(self.activities.complete_activity(tenant_id=TENANT, actor_id=self.actor, activity_id=row.id), "complete activity")
            stamp_audit(self.conn, row.id, completed)
        self.conn.execute("UPDATE crm.activities SET created_at = %s, completed_at = %s WHERE id = %s", (created, completed, row.id))
        state = "done" if completed else ("overdue" if due and due < NOW else "open")
        self.outcomes[f"activity {kind if kind == 'comment' else state}"] += 1


def work(conn, args) -> int:
    if conn.execute("SELECT 1 FROM crm.leads WHERE tenant_id = %s AND created_at >= %s AND created_at < %s AND email LIKE '%%.example'",
                    (TENANT, datetime.datetime.combine(FIRST_DAY, datetime.time()), datetime.datetime.combine(HAND_MADE_FROM, datetime.time()))).fetchone():
        print("leads from the seed window already exist; skipping")
        return 0
    seeder = Seeder(conn)
    rng = random.Random("crm-month")
    days = working_days(FIRST_DAY, TODAY)

    # The customers who exist before any lead converts; conversions add more, dated inside the month.
    customers = conn.execute("SELECT id, name FROM core.partners WHERE tenant_id = %s AND kind = 'customer' ORDER BY name", (TENANT,)).fetchall()

    # Leads, spread over the month, oldest first so conversions find their customers in order.
    lead_days = sorted(rng.choice(days) for _ in PEOPLE)
    for (name, slug), day in zip(PEOPLE, lead_days):
        lead_rng = random.Random(f"crm-lead-{name}")
        with conn.transaction():
            seeder.lead(lead_rng, name, slug, business_time(lead_rng, day, 8, 17))

    # New opportunities for the customers who were already there.
    for n in range(20):
        opp_rng = random.Random(f"crm-opp-{n}")
        partner_id, partner = customers[n % len(customers)]
        created = business_time(opp_rng, opp_rng.choice(days), 8, 17)
        with conn.transaction():
            seeder.new_opportunity(opp_rng, partner_id, f"{partner} — {opp_rng.choice(DEALS)}", created)

    seeder.subjects += [("partner", partner_id, datetime.datetime.combine(FIRST_DAY, datetime.time(9))) for partner_id, _ in customers]

    # Activities, on a share of the leads, opportunities and customers.
    for subject_type, subject_id, subject_created in sorted(seeder.subjects, key=lambda s: s[2]):
        act_rng = random.Random(f"crm-act-{subject_id}")
        for _ in range({"lead": act_rng.choice([0, 1, 1, 2]), "opportunity": act_rng.choice([1, 2, 2, 3]), "partner": act_rng.choice([1, 2])}[subject_type]):
            with conn.transaction():
                seeder.activity(act_rng, subject_type, subject_id, subject_created)

    print("\nby outcome:", dict(sorted(seeder.outcomes.items())))
    for label, sql in [
        ("leads", "SELECT status, count(*) FROM crm.leads GROUP BY 1"),
        ("opportunities", "SELECT stage, count(*) FROM crm.opportunities GROUP BY 1"),
        ("customers", "SELECT count(*) FROM core.partners WHERE kind = 'customer'"),
        ("activities", "SELECT count(*), count(completed_at) FROM crm.activities"),
        ("sales orders", "SELECT status, count(*) FROM sales.orders GROUP BY 1"),
    ]:
        print(f"{label} now:", conn.execute(sql).fetchall())
    return 0


if __name__ == "__main__":
    raise SystemExit(run(__doc__, work))

"""Seeds the HR employee core for the demo tenant: departments, positions, the pay grid and 60
employees of a Malian pasta plant with contracts, amendments, dependants, payment methods,
documents, two exits and the alert horizons; then a closed August 2026 presence month (phase 2) and
payroll on it (phase 3): the Mali DRAFT rule set, a demo bonus, advance and loan, and the August
regular run calculated but not approved. Dev-only; idempotent (codes, employee numbers, one ML
rule set, one regular run per month).

    .venv/Scripts/python -m scripts.seed_hr_payroll [--dry-run]

Every amount here (grid minimums, salaries, allowances) is DEMO data chosen for a realistic
spread, not the collective agreement: the client's HR and accountant replace them. The script
prints them under a TO CONFIRM banner. Phases 2 and 3 extend this file.
"""
from __future__ import annotations

import datetime
import random
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ulid import ULID

from core.auth import hash_password
from core.domain.result import Err, Ok
from core.permissions_registry import ensure_default_roles
from modules.hr.api.clock_import_service import ClockImportService, ClockProfileService
from modules.hr.api.contract_service import ContractService
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.document_service import DocumentService
from modules.hr.api.employee_service import EmployeeService
from modules.hr.api.leave_service import LeaveBalanceService, LeaveRequestService, LeaveTypeService
from modules.hr.api.organisation_service import DepartmentService, GradeService, PositionService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.presence_month_service import PresenceMonthService
from modules.hr.api.presence_service import PresenceService, employed_between
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.document import EmployeeDocument
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod
from modules.hr.domain.presence import ManualEntry
from modules.payroll.api.input_service import InputService
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_service import RunService
from modules.payroll.domain.earnings import period_end
from scripts.payroll_mali_rules import create_mali_rule_set
from scripts.payroll_mali_rules import print_to_confirm as print_mali_to_confirm
from scripts.seed_common import TENANT, actor_id, run

TODAY = datetime.date.today()
RNG_SEED = 20260925
GRID_FROM = datetime.date(2026, 1, 1)
RAISE_FROM = datetime.date(2026, 1, 1)
LAST_MONTH_END = TODAY.replace(day=1) - datetime.timedelta(days=1)
SELF_SERVICE_EMAIL = "employe.demo@sonalim-erp.local"
SELF_SERVICE_EMPLOYEE = "HRP-006"

# --- Phase 2: schedules, a month of presence, a clock import, leave (Task 14) -----------------
SCRIPT_DIR = Path(__file__).resolve().parent
PRESENCE_PERIOD = datetime.date(2026, 8, 1)
CLOCK_SAMPLE_PATH = SCRIPT_DIR / "data" / "hr_clock_sample_2026-08.csv"

# --- Phase 3: Mali draft rule set, monthly inputs, advances/loans, one calculated run ---------
PAYROLL_PERIOD = PRESENCE_PERIOD  # same month phase 2 closed presence for: calculation needs it closed
PAYROLL_COUNTRY = "ML"

DEPARTMENTS = [
    ("PROD", "Production"),
    ("CONDI", "Conditionnement"),
    ("MAINT", "Maintenance"),
    ("QUAL", "Qualité"),
    ("LOG", "Logistique et magasin"),
    ("ADM", "Administration et finance"),
    ("COM", "Commercial"),
]

# code, category, echelon, monthly minimum in F CFA (DEMO)
GRADES = [
    ("M1", "Manœuvre", "A", 45_000),
    ("M2", "Manœuvre", "B", 55_000),
    ("OS1", "Ouvrier spécialisé", "A", 70_000),
    ("OS2", "Ouvrier spécialisé", "B", 85_000),
    ("OQ1", "Ouvrier qualifié", "A", 110_000),
    ("AM1", "Agent de maîtrise", "A", 160_000),
    ("AM2", "Agent de maîtrise", "B", 210_000),
    ("CAD", "Cadre", "A", 380_000),
]

# code, title, department, grade, headcount budget, people seeded (sums to 60)
POSITIONS = [
    ("DIR-PROD", "Directeur de production", "PROD", "CAD", 1, 1),
    ("CHEF-EQ", "Chef d'équipe", "PROD", "AM1", 3, 3),
    ("OP-EXT", "Opérateur extrusion", "PROD", "OS2", 12, 12),
    ("OP-SECH", "Opérateur séchage", "PROD", "OS1", 4, 4),
    ("OP-COND", "Opérateur conditionnement", "CONDI", "OS1", 12, 11),
    ("CHEF-COND", "Chef de ligne conditionnement", "CONDI", "AM1", 1, 1),
    ("MANUT", "Manutentionnaire", "CONDI", "M2", 4, 2),
    ("MECA", "Mécanicien", "MAINT", "OQ1", 3, 3),
    ("ELEC", "Électricien", "MAINT", "OQ1", 2, 2),
    ("CHEF-MAINT", "Responsable maintenance", "MAINT", "AM2", 1, 1),
    ("LABO", "Technicien laboratoire", "QUAL", "OQ1", 3, 3),
    ("RESP-QUAL", "Responsable qualité", "QUAL", "AM2", 1, 1),
    ("MAG", "Magasinier", "LOG", "OS2", 2, 2),
    ("CARIST", "Cariste", "LOG", "OS1", 3, 3),
    ("CHAUF", "Chauffeur", "LOG", "OS1", 2, 2),
    ("COMPTA", "Comptable", "ADM", "AM2", 2, 2),
    ("ASS-RH", "Assistante RH", "ADM", "AM1", 1, 1),
    ("GARD", "Gardien", "ADM", "M1", 2, 2),
    ("COMM", "Commercial", "COM", "AM1", 3, 3),
    ("RESP-COM", "Responsable commercial", "COM", "CAD", 1, 1),
]

# Who gets which contract, by employee number (1-based, in POSITIONS order).
DAILY = {25, 30, 33, 34}             # two conditionnement operators and the two handlers
APPRENTICES = {37, 39}               # one mechanic, one electrician
INTERNS = {43, 53}                   # one lab technician, one accountant
CDD_ENDS_IN_DAYS = {7: 6, 12: 12, 19: 19, 23: 26, 28: 45, 46: 80, 49: 120, 57: 200}  # four inside a 30-day horizon
RECENT_HIRES_TRIAL_DAYS = {15: 4, 27: 11, 48: 25}                                       # two inside a 15-day horizon
RAISED = {2, 10, 18, 26, 36}         # CDI amended from RAISE_FROM with +10 000 F CFA
LEAVERS = {58: "resignation", 59: "dismissal"}

TRANSPORT = 15_000                   # DEMO allowance, every monthly contract
HOUSING = 50_000                     # DEMO allowance, grades below
HOUSING_GRADES = ("AM2", "CAD")

MALE = ["Moussa", "Mamadou", "Ibrahim", "Seydou", "Oumar", "Abdoulaye", "Boubacar", "Adama", "Souleymane", "Bakary",
        "Modibo", "Cheick", "Lassana", "Drissa", "Yacouba", "Sékou", "Amadou", "Issa", "Hamidou", "Siaka"]
FEMALE = ["Aminata", "Fatoumata", "Mariam", "Kadiatou", "Awa", "Oumou", "Hawa", "Assétou", "Djénéba", "Rokia",
          "Salimata", "Bintou", "Nana", "Korotoumou"]
LAST = ["Traoré", "Coulibaly", "Diarra", "Keïta", "Konaté", "Sangaré", "Diallo", "Touré", "Cissé", "Sidibé",
        "Dembélé", "Koné", "Sissoko", "Doumbia", "Maïga", "Kanté", "Camara", "Samaké", "Bagayoko", "Dicko"]
BANKS = ["BDM-SA", "BNDA", "Ecobank Mali", "Orabank Mali", "BOA Mali"]
PLACES = ["Bamako", "Ségou", "Sikasso", "Kayes", "Mopti", "Koulikoro", "Kati", "San"]


@dataclass(frozen=True)
class Plan:
    number: int
    employee_no: str
    badge_no: str
    first_name: str
    last_name: str
    gender: str
    birth_date: datetime.date
    birth_place: str
    married: bool
    children: tuple[datetime.date, ...]
    phone: str
    department: str
    position: str
    grade: str
    site: str
    contract_type: str
    pay_frequency: str
    hire_date: datetime.date
    contract_end: datetime.date | None
    trial_end: datetime.date | None
    base_salary: int
    payment: str  # bank / mobile / cash / split
    raise_from: datetime.date | None
    leaves_on: datetime.date | None


def _day(rng: random.Random, year: int) -> datetime.date:
    return datetime.date(year, rng.randint(1, 12), rng.randint(1, 28))


def _add_years(day: datetime.date, years: int) -> datetime.date:
    """`date.replace(year=...)` raises for a 29 Feb birth date landing on a non-leap year.
    Fall back to 28 Feb, same day as `_day()` already stays clear of (it never produces day 29-31)."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(month=2, day=28, year=day.year + years)


def plans(*, today: datetime.date | None = None) -> list[Plan]:
    """The same 60 people on every run (fixed random seed), for a given day. Every year bound is
    derived from `today` (defaulting to the real today) so the plan stays computable on any date,
    including years past the ones this file was written in."""
    today = today or TODAY
    rng = random.Random(RNG_SEED)
    result: list[Plan] = []
    number = 0
    for code, _title, department, grade, _budget, count in POSITIONS:
        minimum = next(m for g, _c, _e, m in GRADES if g == grade)
        for _ in range(count):
            number += 1
            female = rng.random() < (0.55 if department == "CONDI" else 0.2)
            age = rng.randint(22, 55)
            birth = _day(rng, today.year - age)
            married = age >= 28 and rng.random() < 0.7
            contract_type, frequency, end, trial = "cdi", "monthly", None, None
            hire = _day(rng, rng.randint(max(2012, birth.year + 19), max(birth.year + 19, today.year - 2)))
            salary = minimum + rng.randint(0, 8) * 5_000
            if number in DAILY:
                contract_type, frequency = "daily", "daily"
                hire = _day(rng, rng.randint(max(2024, birth.year + 19), max(birth.year + 19, today.year - 1)))
                salary = 3_000 + rng.randint(0, 6) * 250  # F CFA per day (DEMO)
            elif number in APPRENTICES:
                contract_type, hire = "apprentice", today - datetime.timedelta(days=200)
                end, salary = hire + datetime.timedelta(days=730), 50_000
            elif number in INTERNS:
                contract_type, hire = "intern", today - datetime.timedelta(days=40)
                end, salary = hire + datetime.timedelta(days=182), 40_000
            elif number in CDD_ENDS_IN_DAYS:
                contract_type = "cdd"
                hire = today - datetime.timedelta(days=rng.randint(200, 330))
                end = today + datetime.timedelta(days=CDD_ENDS_IN_DAYS[number])
            elif number in RECENT_HIRES_TRIAL_DAYS:
                hire = today - datetime.timedelta(days=45)
                trial = today + datetime.timedelta(days=RECENT_HIRES_TRIAL_DAYS[number])
            children = tuple(
                _day(rng, rng.randint(max(birth.year + 22, 2000), min(today.year - 1, birth.year + 45)))
                for _ in range(rng.choice([0, 1, 2, 2, 3, 3, 4]) if married else rng.choice([0, 0, 1]))
            ) if birth.year + 22 <= today.year - 1 else ()
            if number in DAILY:
                payment = "cash" if number % 2 == 0 else "mobile"
            elif number % 10 == 0:
                payment = "cash"
            elif number % 10 in (3, 7):
                payment = "mobile"
            elif number % 10 == 5:
                payment = "split"
            else:
                payment = "bank"
            result.append(
                Plan(
                    number=number,
                    employee_no=f"HRP-{number:03d}",
                    badge_no=f"B{number:04d}",
                    first_name=rng.choice(FEMALE if female else MALE),
                    last_name=rng.choice(LAST),
                    gender="female" if female else "male",
                    birth_date=birth,
                    birth_place=rng.choice(PLACES),
                    married=married,
                    children=children,
                    phone=f"{rng.choice(['76', '77', '78', '79', '66', '65', '90', '91'])} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
                    department=department,
                    position=code,
                    grade=grade,
                    site="Siège" if department in ("ADM", "COM") else "Usine",
                    contract_type=contract_type,
                    pay_frequency=frequency,
                    hire_date=hire,
                    contract_end=end,
                    trial_end=trial,
                    base_salary=salary,
                    payment=payment,
                    raise_from=RAISE_FROM if number in RAISED and hire < RAISE_FROM else None,
                    leaves_on=LAST_MONTH_END if number in LEAVERS and hire < LAST_MONTH_END else None,
                )
            )
    return result


def _ok(result):
    if isinstance(result, Err):
        raise RuntimeError(f"{result.code}: {result.message}")
    return result.value


def _fcfa(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " F CFA"


def _ensure_organisation(conn, actor: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    departments: dict[str, str] = {}
    for code, name in DEPARTMENTS:
        row = conn.execute("SELECT id FROM hr.departments WHERE tenant_id = %s AND code = %s", (TENANT, code)).fetchone()
        departments[code] = row[0] if row else _ok(DepartmentService(conn).create_department(tenant_id=TENANT, actor_id=actor, code=code, name=name))["id"]
    grades: dict[str, str] = {}
    for code, category, echelon, minimum in GRADES:
        row = conn.execute("SELECT id FROM hr.grades WHERE tenant_id = %s AND code = %s AND valid_from = %s", (TENANT, code, GRID_FROM)).fetchone()
        grades[code] = row[0] if row else _ok(
            GradeService(conn).create_grade(
                tenant_id=TENANT, actor_id=actor, code=code, category=category, echelon=echelon, base_salary=Decimal(minimum), valid_from=GRID_FROM
            )
        )["id"]
    positions: dict[str, str] = {}
    for code, title, department, _grade, budget, _count in POSITIONS:
        row = conn.execute("SELECT id FROM hr.positions WHERE tenant_id = %s AND code = %s", (TENANT, code)).fetchone()
        positions[code] = row[0] if row else _ok(
            PositionService(conn).create_position(
                tenant_id=TENANT, actor_id=actor, code=code, title=title, department_id=departments[department], headcount_budget=budget
            )
        )["id"]
    return departments, grades, positions


def _ensure_self_service_user(conn) -> str:
    conn.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (email) DO NOTHING",
        (str(ULID()), TENANT, SELF_SERVICE_EMAIL, hash_password("demo1234"), "Employé démo"),
    )
    user_id = conn.execute("SELECT id FROM core.users WHERE email = %s", (SELF_SERVICE_EMAIL,)).fetchone()[0]
    conn.execute(
        "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'hr.self_service') ON CONFLICT DO NOTHING", (user_id,)
    )
    return user_id


def _payment_methods(plan: Plan, rng: random.Random) -> list[PaymentMethod]:
    bank = PaymentMethod(
        method="bank", share_percent=Decimal("100"), is_primary=True, bank_name=rng.choice(BANKS),
        account_no=f"ML{rng.randint(10, 99)} {rng.randint(10000, 99999)} {rng.randint(10**11, 10**12 - 1)} {rng.randint(10, 99)}",
    )
    mobile = PaymentMethod(
        method="mobile_money", share_percent=Decimal("100"), is_primary=True,
        mobile_operator="orange_money" if plan.number % 3 else "moov_money", mobile_number=plan.phone,
    )
    if plan.payment == "cash":
        return [PaymentMethod(method="cash", share_percent=Decimal("100"), is_primary=True)]
    if plan.payment == "mobile":
        return [mobile]
    if plan.payment == "split":
        return [
            PaymentMethod(**{**bank.__dict__, "share_percent": Decimal("70")}),
            PaymentMethod(**{**mobile.__dict__, "share_percent": Decimal("30"), "is_primary": False}),
        ]
    return [bank]


def _create(conn, actor: str, plan: Plan, departments, grades, positions, self_service_user: str | None) -> None:
    rng = random.Random(f"{RNG_SEED}-{plan.employee_no}")
    employee = _ok(
        EmployeeService(conn).create_employee(
            tenant_id=TENANT,
            actor_id=actor,
            employee=EmployeeFile(
                employee_no=plan.employee_no, first_name=plan.first_name, last_name=plan.last_name, hire_date=plan.hire_date,
                phone=plan.phone, department_id=departments[plan.department], position_id=positions[plan.position],
                grade_id=grades[plan.grade], user_id=self_service_user, gender=plan.gender, birth_date=plan.birth_date,
                birth_place=plan.birth_place, nationality="Malienne", national_id=f"NINA-DEMO-{plan.number:04d}{rng.randint(1000, 9999)}",
                inps_no=f"INPS-DEMO-{rng.randint(100000, 999999)}", amo_no=f"AMO-DEMO-{rng.randint(100000, 999999)}",
                marital_status="married" if plan.married else "single", address=f"{plan.birth_place if plan.site == 'Siège' else 'Bamako'}",
                emergency_contact=f"{rng.choice(MALE + FEMALE)} {plan.last_name}", badge_no=plan.badge_no, site=plan.site,
            ),
        )
    )
    components: tuple[ContractComponent, ...] = ()
    if plan.pay_frequency == "monthly":
        components = (ContractComponent(component_code="TRANSPORT", amount=Decimal(TRANSPORT)),)
        if plan.grade in HOUSING_GRADES:
            components += (ContractComponent(component_code="HOUSING", amount=Decimal(HOUSING)),)
    contract = _ok(
        ContractService(conn).create_contract(
            tenant_id=TENANT,
            actor_id=actor,
            terms=ContractTerms(
                employee_id=employee["id"], contract_type=plan.contract_type, start_date=plan.hire_date,
                base_salary=Decimal(plan.base_salary), end_date=plan.contract_end, trial_end_date=plan.trial_end,
                pay_frequency=plan.pay_frequency, position_id=positions[plan.position], grade_id=grades[plan.grade],
                components=components,
            ),
        )
    )
    if plan.raise_from:
        _ok(
            ContractService(conn).amend_contract(
                tenant_id=TENANT, actor_id=actor, contract_id=contract["id"], effective_date=plan.raise_from,
                changes={"base_salary": Decimal(plan.base_salary + 10_000)},
            )
        )
    dependants = DependantService(conn)
    if plan.married:
        spouse_birth = plan.birth_date + datetime.timedelta(days=rng.randint(-1500, 1500))
        _ok(
            dependants.create_dependant(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                dependant=Dependant(
                    kind="spouse", name=f"{rng.choice(MALE if plan.gender == 'female' else FEMALE)} {rng.choice(LAST)}",
                    birth_date=spouse_birth, valid_from=_add_years(max(spouse_birth, plan.birth_date), 25),
                    dependent_for_tax=plan.gender == "male",
                ),
            )
        )
    for child_birth in plan.children:
        _ok(
            dependants.create_dependant(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                dependant=Dependant(
                    kind="child", name=f"{rng.choice(MALE + FEMALE)} {plan.last_name}", birth_date=child_birth, valid_from=child_birth,
                    dependent_for_tax=True, valid_to=child_birth.replace(year=child_birth.year + 21) - datetime.timedelta(days=1),
                ),
            )
        )
    _ok(
        PaymentMethodService(conn).replace_set(
            tenant_id=TENANT, actor_id=actor, employee_id=employee["id"], valid_from=plan.hire_date, methods=_payment_methods(plan, rng)
        )
    )
    documents = DocumentService(conn)
    issued = plan.hire_date - datetime.timedelta(days=30)
    _ok(
        documents.create_document(
            tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
            document=EmployeeDocument(kind="id_card", issued_on=issued, expires_on=issued + datetime.timedelta(days=3650),
                                      file_ref=f"\\\\srv-rh\\dossiers\\{plan.employee_no}\\nina.pdf"),
        )
    )
    if plan.department in ("PROD", "CONDI", "QUAL"):
        medical = TODAY - datetime.timedelta(days=rng.randint(20, 420))  # some expired, some expiring (DEMO)
        _ok(
            documents.create_document(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                document=EmployeeDocument(kind="medical_certificate", issued_on=medical, expires_on=medical + datetime.timedelta(days=365)),
            )
        )
    if plan.position in ("CHAUF", "CARIST"):
        _ok(
            documents.create_document(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                document=EmployeeDocument(kind="driving_licence", issued_on=datetime.date(2020, 6, 1),
                                          expires_on=TODAY + datetime.timedelta(days=rng.choice([10, 200, 400, 700]))),
            )
        )
    if plan.leaves_on:
        _ok(
            EmployeeService(conn).terminate_employee(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"], termination_date=plan.leaves_on,
                termination_reason=LEAVERS[plan.number],
            )
        )


def _print_to_confirm() -> None:
    print("\n=========== TO CONFIRM: demo values, not the collective agreement ===========")
    for code, category, echelon, minimum in GRADES:
        print(f"  grade {code:<4} {category} {echelon}: monthly minimum {_fcfa(minimum)} (from {GRID_FROM.isoformat()})")
    print(f"  allowance TRANSPORT: {_fcfa(TRANSPORT)} / month on every monthly contract")
    print(f"  allowance HOUSING:   {_fcfa(HOUSING)} / month for grades {', '.join(HOUSING_GRADES)}")
    print("  salaries: grade minimum + 0 to 40 000 F CFA; day labourers 3 000 to 4 500 F CFA / day;")
    print("            interns 40 000, apprentices 50 000; five raises of 10 000 from " + RAISE_FROM.isoformat())
    print("  alert horizons: contracts 30 days, trials 15 days (spec); documents 30 days (demo)")
    print("  NINA / INPS / AMO numbers, phones and bank accounts are fake.")
    print("  presence settings: night window 21:00-05:00; punch-attach 240 min; punch dedupe 60 s; late grace 5 min")
    print("  public holiday: \"Jour férié de démonstration\" on 2026-08-22 (ML, paid, unconfirmed)")
    print("  leave type ANNUEL: accrual 2.5 working days/month; no carry-over cap")
    print("=============================================================================")


def _seed_presence_and_leave(conn, actor: str) -> None:
    """A month of presence (August 2026), a clock-import sample and leave data for the
    demo tenant. Rerun-safe: skips outright if the month is already seeded. Draft settings,
    the Mali public holiday and the leave accrual rate are DEMO values, printed under a
    TO CONFIRM banner by `_print_to_confirm`."""
    already_seeded = conn.execute(
        "SELECT 1 FROM hr.presence_months WHERE tenant_id = %s AND period = %s", (TENANT, PRESENCE_PERIOD)
    ).fetchone()
    if already_seeded:
        print("Phase 2 presence/leave already seeded for 2026-08; skipping (rerun-safe).")
        return

    schedules = ScheduleService(conn)
    holidays = HolidayService(conn)
    settings = PresenceSettingsService(conn)
    presence = PresenceService(conn)
    months = PresenceMonthService(conn)
    leave_types = LeaveTypeService(conn)
    leave_requests = LeaveRequestService(conn)
    leave_balances = LeaveBalanceService(conn)

    # Draft settings: HR confirms the real night-work window and clock tolerances.
    settings.update(
        tenant_id=TENANT, actor_id=actor, night_start_minute=21 * 60, night_end_minute=5 * 60,
        punch_attach_minutes=240, punch_dedupe_seconds=60, late_grace_minutes=5,
    )
    day_shift = [{"weekday": w, "start_minute": 7 * 60, "end_minute": 15 * 60, "break_minutes": 0} for w in range(6)]
    evening_shift = [{"weekday": w, "start_minute": 15 * 60, "end_minute": 23 * 60, "break_minutes": 0} for w in range(6)]
    night_shift = [{"weekday": w, "start_minute": 23 * 60, "end_minute": 7 * 60, "break_minutes": 0} for w in range(6)]
    day_result = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="JOUR", name="Jour 07-15", is_night=False, days=day_shift)
    evening_result = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="SOIR", name="Soir 15-23", is_night=False, days=evening_shift)
    night_result = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="NUIT", name="Nuit 23-07", is_night=True, days=night_shift)

    def schedule_id(result, code: str) -> str:
        if isinstance(result, Ok):
            return result.value["id"]
        existing = next(s for s in schedules.list_schedules(tenant_id=TENANT) if s["code"] == code)
        return existing["id"]

    day_id = schedule_id(day_result, "JOUR")
    evening_id = schedule_id(evening_result, "SOIR")
    night_id = schedule_id(night_result, "NUIT")

    # Mali public holidays, draft: the accountant confirms the exact dates each year.
    for holiday_date, name in [(datetime.date(2026, 8, 22), "Jour férié de démonstration")]:
        holidays.create_holiday(tenant_id=TENANT, actor_id=actor, country_code="ML", holiday_date=holiday_date, name=name, paid=True, confirmed=False)

    # Assign every tenant employee employed at some point in August to a schedule (month close
    # scans the whole tenant, so anyone left unassigned - including employees of other dev/test
    # runs on this shared demo tenant, not just this script's own HRP-* cohort - would show up
    # as a "no_schedule" gap and block the close below). Filtered by hire/termination dates
    # (`employed_between`), not by today's `status` field: a leaver terminated on 2026-08-31 or
    # in September was still employed throughout August even though `status` now reads
    # "terminated". The seed's own HRP-001/002/003 (deterministic by employee_no, not by this
    # list's name ordering) carry the three shifts and the clock sample's badges; HRP-004/005
    # get the leave requests; everyone else stays on JOUR. A pre-existing schedule assignment
    # left by earlier manual/integration testing on this shared tenant can make the open-ended
    # (Jan 2026 to open) assignment overlap and get refused (ASSIGNMENT_OVERLAP); retrying it
    # bounded to just August is enough for this seed and doesn't touch that other assignment.
    _period_first, _period_last = datetime.date(2026, 8, 1), datetime.date(2026, 8, 31)
    all_employees = employed_between(conn, tenant_id=TENANT, date_from=_period_first, date_to=_period_last)
    seeded_employees = sorted((e for e in all_employees if e["employee_no"].startswith("HRP-")), key=lambda e: e["employee_no"])
    clock_employees = seeded_employees[:3]
    clock_ids = {employee["id"] for employee in clock_employees}

    def _assign(employee_id: str, target_schedule_id: str) -> None:
        result = schedules.create_assignment(tenant_id=TENANT, actor_id=actor, employee_id=employee_id, valid_from=datetime.date(2026, 1, 1), schedule_id=target_schedule_id)
        if isinstance(result, Err):
            bounded = schedules.create_assignment(
                tenant_id=TENANT, actor_id=actor, employee_id=employee_id, valid_from=_period_first, valid_to=_period_last, schedule_id=target_schedule_id
            )
            if isinstance(bounded, Err):
                print(f"WARNING: could not assign a schedule to employee {employee_id}: {result}")

    for employee in all_employees:
        if employee["id"] in clock_ids:
            continue
        _assign(employee["id"], day_id)
    for index, employee in enumerate(clock_employees):
        target = [day_id, evening_id, night_id][index]
        _assign(employee["id"], target)
        conn.execute("UPDATE hr.employees SET badge_no = %s WHERE id = %s", (f"B-{index + 1:04d}", employee["id"]))

    # Leave: one draft paid annual-leave type (Mali statutory rate to be confirmed), an
    # opening balance, and one approved + one pending request so both screens show data. This
    # runs BEFORE the bulk "present" fill below: `LeaveRequestService.approve` refuses a day
    # already marked worked (LEAVE_OVERLAPS_WORK), so HRP-004's Aug 17-18 leave must be written
    # first; the bulk fill then skips it via `day["record"] is None`, exactly like the clock
    # employees' remaining-days fill already does.
    annual = leave_types.create_type(
        tenant_id=TENANT, actor_id=actor, code="ANNUEL", name_en="Annual leave", name_fr="Congé annuel",
        paid=True, accrual_days_per_month=Decimal("2.5"), max_carry_over=None, counts_days="working",
        requires_document=False, presence_status="leave", confirmed=False,
    )
    annual_id = annual.value["id"] if isinstance(annual, Ok) else next(t["id"] for t in leave_types.list_types(tenant_id=TENANT) if t["code"] == "ANNUEL")
    if len(seeded_employees) > 3:
        leave_balances.adjust(
            tenant_id=TENANT, actor_id=actor, employee_id=seeded_employees[3]["id"], leave_type_id=annual_id,
            year=2026, delta=Decimal("5"), reason="solde d'ouverture (démo)",
        )
        approved = leave_requests.create_request(
            tenant_id=TENANT, actor_id=actor, employee_id=seeded_employees[3]["id"], leave_type_id=annual_id,
            start_date=datetime.date(2026, 8, 17), end_date=datetime.date(2026, 8, 18), half_day=False, reason="Congé démo",
        )
        if isinstance(approved, Ok):
            decided = leave_requests.approve(tenant_id=TENANT, actor_id=actor, request_id=approved.value["id"])
            if isinstance(decided, Err):
                print(f"WARNING: approving the demo leave request failed: {decided}")
    if len(seeded_employees) > 4:
        leave_requests.create_request(
            tenant_id=TENANT, actor_id=actor, employee_id=seeded_employees[4]["id"], leave_type_id=annual_id,
            start_date=datetime.date(2026, 9, 7), end_date=datetime.date(2026, 9, 8), half_day=False, reason="Demande démo en attente",
        )

    # A full month of "present" on every working day for everyone but the first three
    # (whose days come from the clock import below). `day["employed"]` is required here: some
    # of the 60 demo employees are hired mid-August or leave on its last day, and their
    # pre-hire/post-termination days still resolve a schedule (default_status "present") even
    # though they are not employed yet/anymore - `save_days` validates its whole batch
    # atomically, so a single NOT_EMPLOYED day would otherwise silently discard every entry.
    # `day["record"] is None` skips HRP-004's Aug 17-18 leave days written just above.
    entries = []
    for employee in all_employees:
        if employee["id"] in clock_ids:
            continue
        month = presence.employee_month(tenant_id=TENANT, employee_id=employee["id"], period=PRESENCE_PERIOD)
        if isinstance(month, Ok):
            entries += [
                ManualEntry(employee_id=employee["id"], work_date=datetime.date.fromisoformat(day["work_date"]), status="present")
                for day in month.value["days"]
                if day["default_status"] == "present" and day["employed"] and day["record"] is None
            ]
    if entries:
        saved = presence.save_days(tenant_id=TENANT, actor_id=actor, entries=entries)
        if isinstance(saved, Err):
            print(f"WARNING: bulk presence save failed: {saved}")

    # The clock sample: stage and commit it for the three badge-carrying employees.
    profile = ClockProfileService(conn).create_profile(
        tenant_id=TENANT, actor_id=actor, code="ZK-DEMO", name="Pointeuse démo", delimiter=";", has_header=True,
        badge_column="Badge", timestamp_column="DateHeure", timestamp_format="%d/%m/%Y %H:%M",
        direction_column="Etat", in_values=["Entrée"], out_values=["Sortie"],
    )
    clock_content = CLOCK_SAMPLE_PATH.read_text(encoding="utf-8")
    imports = ClockImportService(conn)
    staged = imports.stage(
        tenant_id=TENANT, actor_id=actor, profile_id=profile.value["id"], file_name="hr_clock_sample_2026-08.csv",
        content=clock_content, date_from=datetime.date(2026, 8, 3), date_to=datetime.date(2026, 8, 4),
    )
    if isinstance(staged, Ok):
        committed = imports.commit(tenant_id=TENANT, actor_id=actor, import_id=staged.value["id"])
        print(f"Clock sample committed: {committed.value if isinstance(committed, Ok) else committed}")

    # The three clock employees' remaining August days (the ones the clock did not cover).
    remaining_entries = []
    for employee in seeded_employees[:3]:
        month = presence.employee_month(tenant_id=TENANT, employee_id=employee["id"], period=PRESENCE_PERIOD)
        if isinstance(month, Ok):
            remaining_entries += [
                ManualEntry(employee_id=employee["id"], work_date=datetime.date.fromisoformat(day["work_date"]), status="present")
                for day in month.value["days"]
                if day["default_status"] == "present" and day["employed"] and day["record"] is None
            ]
    if remaining_entries:
        saved = presence.save_days(tenant_id=TENANT, actor_id=actor, entries=remaining_entries)
        if isinstance(saved, Err):
            print(f"WARNING: remaining presence save failed: {saved}")

    closed = months.close(tenant_id=TENANT, actor_id=actor, period=PRESENCE_PERIOD)
    print(f"August 2026 presence close: {closed.value if isinstance(closed, Ok) else closed}")
    print("Presence settings, holidays and leave accrual rate are DRAFT seed values - confirm with HR/payroll before go-live.")


def _seed_payroll(conn, actor: str) -> None:
    """The Mali DRAFT rule set (`scripts.payroll_mali_rules`), one demo bonus, one approved advance
    and one loan, and the August 2026 regular run calculated on them -- left CALCULATED, never
    approved (approval needs a confirmed rule set and a second person). Rerun-safe: the rule set
    is skipped once an ML set exists; the bonus, advance and loan once the month's regular run
    exists. A run still in draft (its calculation failed, or a later edit sent it back) is
    calculated again, so rerunning after fixing the cause finishes the job."""
    rules = RuleSetService(conn)
    if rules.get_settings(tenant_id=TENANT) is None:
        _ok(rules.save_settings(tenant_id=TENANT, actor_id=actor, country=PAYROLL_COUNTRY))
    if conn.execute("SELECT 1 FROM payroll.rule_sets WHERE tenant_id = %s AND country = %s", (TENANT, PAYROLL_COUNTRY)).fetchone():
        print("Payroll: Mali rule set already seeded; skipping (rerun-safe).")
    else:
        rule_set = create_mali_rule_set(rules, tenant_id=TENANT, actor_id=actor)
        print(f"Payroll: Mali rule set seeded as DRAFT ({rule_set['id']}), valid from {rule_set['valid_from']}.")
        print_mali_to_confirm()

    runs = RunService(conn)
    existing = conn.execute(
        "SELECT id, status FROM payroll.runs WHERE tenant_id = %s AND period = %s AND run_type = 'regular'", (TENANT, PAYROLL_PERIOD)
    ).fetchone()
    if existing and existing[1] != "draft":
        print(f"Payroll: August 2026 run already seeded ({existing[1]}); skipping (rerun-safe).")
        return
    if existing:
        run_id = existing[0]
        print("Payroll: August 2026 run found in draft; calculating it again.")
    else:
        run_id = _ok(runs.create_run(tenant_id=TENANT, actor_id=actor, period=PAYROLL_PERIOD, run_type="regular"))["id"]
        # One demo bonus, one approved advance and one loan so the Inputs screens show data. Same
        # HRP-* cohort phase 2 works on (employed in August, by employee number).
        employed = employed_between(conn, tenant_id=TENANT, date_from=PAYROLL_PERIOD, date_to=period_end(PAYROLL_PERIOD))
        seeded_employees = sorted((e for e in employed if e["employee_no"].startswith("HRP-")), key=lambda e: e["employee_no"])
        inputs = InputService(conn)
        bonus_target = seeded_employees[5] if len(seeded_employees) > 5 else seeded_employees[0]
        _ok(inputs.add_run_input(
            tenant_id=TENANT, actor_id=actor, run_id=run_id, employee_id=bonus_target["id"],
            component_code="BONUS", amount=Decimal(25_000), note="Prime démo",
        ))
        advance_target = seeded_employees[6] if len(seeded_employees) > 6 else seeded_employees[0]
        advance = _ok(inputs.create_advance(
            tenant_id=TENANT, actor_id=actor, employee_id=advance_target["id"], amount=Decimal(30_000),
            requested_on=PAYROLL_PERIOD, deduct_period=PAYROLL_PERIOD, note="Avance démo",
        ))
        _ok(inputs.approve_advance(tenant_id=TENANT, actor_id=actor, advance_id=advance["id"]))
        loan_target = seeded_employees[7] if len(seeded_employees) > 7 else seeded_employees[0]
        _ok(inputs.create_loan(
            tenant_id=TENANT, actor_id=actor, employee_id=loan_target["id"], principal=Decimal(150_000),
            instalment_count=6, first_period=PAYROLL_PERIOD, note="Prêt démo",
        ))
        print(f"Payroll: demo bonus {_fcfa(25_000)} ({bonus_target['employee_no']}), approved advance {_fcfa(30_000)} "
              f"({advance_target['employee_no']}), loan {_fcfa(150_000)} in 6 instalments ({loan_target['employee_no']}).")

    calculated = runs.calculate(tenant_id=TENANT, actor_id=actor, run_id=run_id)
    if isinstance(calculated, Err):
        # PRESENCE_NOT_CLOSED here means phase 2's month close did not succeed in this pass. The run
        # stays in draft with its inputs; the next pass calculates it again (see above).
        print(f"Payroll: could not calculate the August 2026 run ({calculated.code}: {calculated.message}); "
              "fix that, then run scripts.seed_hr_payroll again.")
        return
    totals = calculated.value
    print(f"Payroll: August 2026 run calculated ({totals['payslip_count']} payslips, gross {_fcfa(totals['gross'])}, "
          f"net {_fcfa(totals['net'])}); left as CALCULATED, not approved.")
    print("Payroll rule set, inputs, advances/loans and the run are DEMO seed data -- see the TO CONFIRM banner.")


def seed(conn, _args) -> int:
    actor = actor_id(conn)
    ensure_default_roles(conn, TENANT)  # the administrateur role picks up the new hr.* codes
    departments, grades, positions = _ensure_organisation(conn, actor)
    settings = HrSettingsService(conn)
    if all(value is None for value in settings.get(TENANT).values()):
        _ok(settings.save(tenant_id=TENANT, actor_id=actor, contract_expiry_horizon_days=30, trial_end_horizon_days=15, document_expiry_horizon_days=30))
    self_service_user = _ensure_self_service_user(conn)
    created = skipped = 0
    for plan in plans():
        if conn.execute("SELECT 1 FROM hr.employees WHERE tenant_id = %s AND employee_no = %s", (TENANT, plan.employee_no)).fetchone():
            skipped += 1
            continue
        linked = self_service_user if plan.employee_no == SELF_SERVICE_EMPLOYEE else None
        _create(conn, actor, plan, departments, grades, positions, linked)
        created += 1
    print(f"hr seed: {created} employee(s) created, {skipped} already there; {len(DEPARTMENTS)} departments, {len(POSITIONS)} positions, {len(GRADES)} grades")
    print(f"self-service login: {SELF_SERVICE_EMAIL} / demo1234 -> {SELF_SERVICE_EMPLOYEE}")
    _seed_presence_and_leave(conn, actor)
    _seed_payroll(conn, actor)
    _print_to_confirm()
    return 0


if __name__ == "__main__":
    raise SystemExit(run(__doc__, seed))

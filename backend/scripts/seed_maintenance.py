"""Seeds the maintenance workflow for a browser walkthrough: a team, two equipment with
photo maps and checkpoints, two recurring programs (swept once so they materialise their
due jobs), one job per lifecycle state (planned / assigned / in_progress / submitted /
rework / closed), and one pending spare-parts request. Grants the demo user every
maintenance permission so the whole feature is reachable from one login. Dev-only.

    .venv/Scripts/python -m scripts.seed_maintenance

Idempotent: skips everything (prints "already seeded") when a team named
"Équipe maintenance" already exists for the demo tenant. The script only adds maintenance
rows (+ permission grants on the demo user) -- it never touches another module's data, and
the dev DB is shared with other sessions.

Placeholder equipment-view photos are generated in-script (no Pillow in this venv): a small
hand-built PNG (zlib + struct), flat background with a grid and a labelled silhouette block,
well under the 10 MB upload limit.
"""
from __future__ import annotations

import datetime
import struct
import zlib
from decimal import Decimal

from ulid import ULID

from core.db import get_connection
from core.domain.result import Err
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.map_service import MapService
from modules.maintenance.api.parts_service import PartsService
from modules.maintenance.api.people import active_employees
from modules.maintenance.api.program_service import ProgramService
from modules.maintenance.api.team_service import TeamService

TENANT = "demo"
DEMO_EMAIL = "demo@sonalim-erp.local"
TEAM_NAME = "Équipe maintenance"
SYSTEM_ACTOR = "system:maintenance-sweep"

PERMISSIONS = [
    "maintenance.view_jobs",
    "maintenance.plan_jobs",
    "maintenance.execute_jobs",
    "maintenance.manage_checkpoints",
    "maintenance.manage_teams",
]

TODAY = datetime.date.today()
UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# Placeholder PNG generation (no Pillow in this venv)
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_placeholder_png(width: int, height: int, bg: tuple[int, int, int], fg: tuple[int, int, int]) -> bytes:
    """A flat-colour PNG with a grid and a centred silhouette block, built by hand
    (struct + zlib, no imaging library) -- a stand-in for a real machine photo."""
    block_w, block_h = width // 2, height // 2
    block_x0, block_y0 = (width - block_w) // 2, (height - block_h) // 2

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # no filter
        for x in range(width):
            on_grid = x % 40 == 0 or y % 40 == 0
            in_block = block_x0 <= x < block_x0 + block_w and block_y0 <= y < block_y0 + block_h
            if in_block:
                r, g, b = fg
            elif on_grid:
                r, g, b = tuple(max(0, c - 20) for c in bg)
            else:
                r, g, b = bg
            rows += bytes((r, g, b))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit depth, colour type 2 (RGB)
    body = b"\x89PNG\r\n\x1a\n"
    body += _png_chunk(b"IHDR", header)
    body += _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
    body += _png_chunk(b"IEND", b"")
    return body


def _check(result, context: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{context}: {result.code} — {result.message}")
    return result.value


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def seed() -> None:
    with get_connection() as connection:
        already = connection.execute(
            "SELECT 1 FROM maintenance.teams WHERE tenant_id = %s AND name = %s", (TENANT, TEAM_NAME)
        ).fetchone()
        if already is not None:
            print("already seeded")
            return

        demo_user = connection.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s AND email = %s", (TENANT, DEMO_EMAIL)
        ).fetchone()
        if demo_user is None:
            raise RuntimeError(f"demo user {DEMO_EMAIL} not found — run scripts.seed_dev first")
        demo_user_id = demo_user[0]

        for permission in PERMISSIONS:
            connection.execute(
                "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (demo_user_id, permission),
            )
        print(f"granted {len(PERMISSIONS)} maintenance permissions to {DEMO_EMAIL}")

        # ---- equipment ------------------------------------------------------
        equipment_rows = connection.execute(
            "SELECT id, code, name, work_center_id FROM maintenance.equipment "
            "WHERE tenant_id = %s AND archived_at IS NULL ORDER BY created_at DESC LIMIT 2",
            (TENANT,),
        ).fetchall()
        if len(equipment_rows) < 2:
            work_center_id = connection.execute(
                "SELECT id FROM production.work_centers WHERE tenant_id = %s LIMIT 1", (TENANT,)
            ).fetchone()
            work_center_id = work_center_id[0] if work_center_id else str(ULID())
            created = []
            for i in range(1, 3):
                equipment_id = str(ULID())
                connection.execute(
                    """
                    INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, status)
                    VALUES (%s, %s, %s, %s, %s, 'operational')
                    ON CONFLICT DO NOTHING
                    """,
                    (equipment_id, TENANT, work_center_id, f"MAINT-DEMO-{i}", f"Machine démo {i}"),
                )
                created.append((equipment_id, f"MAINT-DEMO-{i}", f"Machine démo {i}", work_center_id))
            equipment_rows = created
        equipment_a = equipment_rows[0]  # (id, code, name, work_center_id)
        equipment_b = equipment_rows[1]
        print(f"equipment: {equipment_a[1]} ({equipment_a[0]}), {equipment_b[1]} ({equipment_b[0]})")

        map_service = MapService(connection)

        def make_views(equipment_id: str, equipment_name: str) -> list[dict]:
            views = []
            for label, bg, fg in [
                ("Vue avant", (235, 240, 245), (90, 110, 140)),
                ("Vue latérale", (240, 235, 230), (140, 100, 70)),
            ]:
                png = make_placeholder_png(640, 480, bg, fg)
                view = _check(
                    map_service.create_view(
                        tenant_id=TENANT, actor_id=demo_user_id, equipment_id=equipment_id, label=label, image=png, mime="image/png"
                    ),
                    f"create_view {equipment_name}/{label}",
                )
                views.append(view)
            return views

        views_a = make_views(equipment_a[0], equipment_a[1])
        views_b = make_views(equipment_b[0], equipment_b[1])
        print(f"views: {len(views_a) + len(views_b)} (image/png, < 200 KB each)")

        # Checkpoints: mix of actions across the two machines' first views; one
        # "measure" (°C) and one "requires_photo" so the wizard exercises both.
        checkpoint_specs = [
            (views_a[0]["id"], 20.0, 30.0, "Température moteur", "measure", "°C", False, "Relever la température au thermomètre IR"),
            (views_a[0]["id"], 55.0, 40.0, "Courroie d'entraînement", "inspect", None, True, "Vérifier l'usure et l'alignement, photo requise"),
            (views_a[0]["id"], 75.0, 65.0, "Graissage palier", "lubricate", None, False, None),
            (views_a[1]["id"], 30.0, 50.0, "Serrage fixations", "tighten", None, False, None),
            (views_b[0]["id"], 40.0, 35.0, "Nettoyage trémie", "clean", None, False, None),
            (views_b[0]["id"], 60.0, 70.0, "État général", "inspect", None, False, "Contrôle visuel rapide"),
        ]
        checkpoints: list[dict] = []
        for view_id, x_pct, y_pct, label, action, measure_unit, requires_photo, instructions in checkpoint_specs:
            checkpoints.append(
                _check(
                    map_service.add_checkpoint(
                        tenant_id=TENANT,
                        actor_id=demo_user_id,
                        view_id=view_id,
                        x_pct=x_pct,
                        y_pct=y_pct,
                        label=label,
                        action=action,
                        instructions=instructions,
                        measure_unit=measure_unit,
                        requires_photo=requires_photo,
                    ),
                    f"add_checkpoint {label}",
                )
            )
        measure_checkpoint = checkpoints[0]
        photo_checkpoint = checkpoints[1]
        print(f"checkpoints: {len(checkpoints)} (1 measure °C, 1 requires_photo)")

        # ---- team -------------------------------------------------------
        candidates = active_employees(connection, TENANT)
        member_ids = [c["id"] for c in candidates[:3]]
        if len(member_ids) < 3:
            print(f"WARNING: only {len(member_ids)} active HR employee(s) found — team created with fewer members")

        team = _check(
            TeamService(connection).create_team(
                tenant_id=TENANT, actor_id=demo_user_id, name=TEAM_NAME, chef_user_id=demo_user_id
            ),
            "create_team",
        )
        if member_ids:
            team = _check(
                TeamService(connection).set_members(
                    tenant_id=TENANT, actor_id=demo_user_id, team_id=team["id"], employee_ids=member_ids
                ),
                "set_members",
            )
        print(f"team: {TEAM_NAME} ({team['id']}), chef=demo, members={len(member_ids)}")

        if not member_ids:
            raise RuntimeError(
                "no active HR employees found — maintenance jobs need at least one active employee as performer; "
                "run scripts.seed_hr_payroll (or seed_dev) first"
            )
        performer_id = member_ids[0]

        # ---- programs -----------------------------------------------------
        program_start = TODAY - datetime.timedelta(weeks=3)
        program_service = ProgramService(connection)
        weekly_program = _check(
            program_service.create_program(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_a[0],
                name="Graissage hebdomadaire",
                description="Graissage des paliers et vérification courroie",
                interval_value=1,
                interval_unit="week",
                start_date=program_start,
                lead_days=2,
                estimated_minutes=30,
                default_team_id=team["id"],
                stops_machine=False,
                checkpoint_ids=[c["id"] for c in checkpoints if c["view_id"] == views_a[0]["id"]],
            ),
            "create_program weekly",
        )
        monthly_program = _check(
            program_service.create_program(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_b[0],
                name="Serrage mensuel",
                description="Contrôle et resserrage des fixations",
                interval_value=1,
                interval_unit="month",
                start_date=program_start,
                lead_days=3,
                estimated_minutes=45,
                default_team_id=team["id"],
                stops_machine=False,
                checkpoint_ids=[c["id"] for c in checkpoints if c["view_id"] == views_b[0]["id"]],
            ),
            "create_program monthly",
        )
        print(f"programs: {weekly_program['name']} ({weekly_program['id']}), {monthly_program['name']} ({monthly_program['id']})")

        swept = program_service.run_due(tenant_id=TENANT, today=TODAY)
        print(f"program sweep: created={swept['created']}, overdue_notified={swept['overdue_notified']}")

        # ---- jobs: one per lifecycle state ---------------------------------
        job_service = JobService(connection)
        all_checkpoint_ids = [c["id"] for c in checkpoints]
        job_ids: dict[str, str] = {}
        job_numbers: dict[str, str] = {}

        def job_number(job_id: str) -> str:
            return connection.execute("SELECT number FROM maintenance.jobs WHERE id = %s", (job_id,)).fetchone()[0]

        def backdate_job(job_id: str, *, created_at: datetime.datetime | None = None, due_date: datetime.date | None = None) -> None:
            if created_at is not None:
                connection.execute("UPDATE maintenance.jobs SET created_at = %s WHERE id = %s", (created_at, job_id))
                connection.execute("UPDATE maintenance.job_events SET at = %s WHERE job_id = %s AND kind = 'created'", (created_at, job_id))
            if due_date is not None:
                connection.execute("UPDATE maintenance.jobs SET due_date = %s WHERE id = %s", (due_date, job_id))

        # 1) planned — no chef yet, due later this week (shows in the calendar's current window)
        planned_id = _check(
            job_service.create_job(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_a[0],
                title="Vérification courroie avant redémarrage ligne",
                description="Demande du chef d'équipe après un bruit anormal signalé en poste.",
                kind="corrective",
                priority="normal",
                due_date=TODAY + datetime.timedelta(days=2),
                stops_machine=False,
                checkpoint_ids=[photo_checkpoint["id"]],
                tasks=[],
            ),
            "create_job planned",
        )
        job_ids["planned"] = planned_id
        job_numbers["planned"] = job_number(planned_id)

        # 2) assigned — created with a chef/team directly (create_job assigns automatically)
        assigned_id = _check(
            job_service.create_job(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_b[0],
                title="Contrôle fixations avant lancement OF",
                description=None,
                kind="corrective",
                priority="normal",
                due_date=TODAY + datetime.timedelta(days=5),
                stops_machine=False,
                checkpoint_ids=[c["id"] for c in checkpoints if c["view_id"] == views_b[0]["id"]],
                tasks=[{"label": "Vérifier le niveau d'huile", "action": "inspect", "instructions": None}],
                team_id=team["id"],
                chef_user_id=demo_user_id,
            ),
            "create_job assigned",
        )
        job_ids["assigned"] = assigned_id
        job_numbers["assigned"] = job_number(assigned_id)

        # 3) in_progress — urgent, started, 2 entries recorded (one measure, one photo-required),
        #    at least one check left pending so it cannot be submitted yet.
        in_progress_id = _check(
            job_service.create_job(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_a[0],
                title="Surchauffe moteur signalée",
                description="Arrêt immédiat demandé par le chef de ligne.",
                kind="corrective",
                priority="urgent",
                due_date=TODAY,
                stops_machine=True,
                checkpoint_ids=all_checkpoint_ids[:3],  # measure_checkpoint, photo_checkpoint, one more
                tasks=[],
                team_id=team["id"],
                chef_user_id=demo_user_id,
            ),
            "create_job in_progress",
        )
        job_ids["in_progress"] = in_progress_id
        job_numbers["in_progress"] = job_number(in_progress_id)

        in_progress_checks = connection.execute(
            "SELECT id, checkpoint_id FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order",
            (in_progress_id,),
        ).fetchall()
        check_by_checkpoint = {row[1]: row[0] for row in in_progress_checks}

        now = datetime.datetime.now(UTC)
        started = now - datetime.timedelta(hours=1)
        finished = now - datetime.timedelta(minutes=40)
        _check(
            job_service.record_entry(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                job_id=in_progress_id,
                check_id=check_by_checkpoint[measure_checkpoint["id"]],
                performer_employee_id=performer_id,
                outcome="ok",
                note="Relevé stabilisé après arrêt",
                measured_value=78.5,
                started_at=started,
                finished_at=finished,
                manual_minutes=None,
                photo=None,
                actor_can_plan=True,
                now=now,
            ),
            "record_entry measure",
        )
        png_entry_photo = make_placeholder_png(320, 240, (230, 230, 230), (120, 60, 60))
        started2 = now - datetime.timedelta(minutes=35)
        finished2 = now - datetime.timedelta(minutes=20)
        _check(
            job_service.record_entry(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                job_id=in_progress_id,
                check_id=check_by_checkpoint[photo_checkpoint["id"]],
                performer_employee_id=performer_id,
                outcome="issue",
                note="Usure visible, à surveiller",
                measured_value=None,
                started_at=started2,
                finished_at=finished2,
                manual_minutes=None,
                photo=(png_entry_photo, "image/png"),
                actor_can_plan=True,
                now=now,
            ),
            "record_entry photo",
        )
        print(f"in_progress job {job_numbers['in_progress']}: 2 entries recorded (measure + photo), 1 check left pending")

        # 4) submitted — every check entered, awaiting review
        submitted_id = _check(
            job_service.create_job(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_b[0],
                title="Nettoyage trémie fin de semaine",
                description=None,
                kind="corrective",
                priority="normal",
                due_date=TODAY - datetime.timedelta(days=1),
                stops_machine=False,
                checkpoint_ids=[c["id"] for c in checkpoints if c["view_id"] == views_b[0]["id"]],
                tasks=[],
                team_id=team["id"],
                chef_user_id=demo_user_id,
            ),
            "create_job submitted",
        )
        job_ids["submitted"] = submitted_id
        job_numbers["submitted"] = job_number(submitted_id)
        for row in connection.execute(
            "SELECT id FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order", (submitted_id,)
        ).fetchall():
            _check(
                job_service.record_entry(
                    tenant_id=TENANT,
                    actor_id=demo_user_id,
                    job_id=submitted_id,
                    check_id=row[0],
                    performer_employee_id=performer_id,
                    outcome="ok",
                    note=None,
                    measured_value=None,
                    started_at=None,
                    finished_at=None,
                    manual_minutes=10,
                    photo=None,
                    actor_can_plan=True,
                    now=now,
                ),
                "record_entry submitted-job",
            )
        _check(job_service.submit(tenant_id=TENANT, actor_id=demo_user_id, job_id=submitted_id, actor_can_plan=True), "submit")
        print(f"submitted job {job_numbers['submitted']}: all checks entered, awaiting review")

        # 5) rework — submitted, then reviewed with one rejection
        rework_id = _check(
            job_service.create_job(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_a[0],
                title="Graissage hebdomadaire — contrôle qualité",
                description=None,
                kind="preventive",
                priority="normal",
                due_date=TODAY - datetime.timedelta(days=2),
                stops_machine=False,
                checkpoint_ids=[c["id"] for c in checkpoints if c["view_id"] == views_a[0]["id"]],
                tasks=[],
                team_id=team["id"],
                chef_user_id=demo_user_id,
            ),
            "create_job rework",
        )
        job_ids["rework"] = rework_id
        job_numbers["rework"] = job_number(rework_id)
        rework_checks = connection.execute(
            "SELECT id, action, requires_photo FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order", (rework_id,)
        ).fetchall()
        rework_photo = make_placeholder_png(320, 240, (230, 230, 230), (90, 90, 60))
        for check_id, action, requires_photo in rework_checks:
            _check(
                job_service.record_entry(
                    tenant_id=TENANT,
                    actor_id=demo_user_id,
                    job_id=rework_id,
                    check_id=check_id,
                    performer_employee_id=performer_id,
                    outcome="ok",
                    note=None,
                    measured_value=80.0 if action == "measure" else None,
                    started_at=None,
                    finished_at=None,
                    manual_minutes=8,
                    photo=(rework_photo, "image/png") if requires_photo else None,
                    actor_can_plan=True,
                    now=now,
                ),
                "record_entry rework-job attempt1",
            )
        _check(job_service.submit(tenant_id=TENANT, actor_id=demo_user_id, job_id=rework_id, actor_can_plan=True), "submit rework-job")
        rework_check_ids = [row[0] for row in rework_checks]
        verdicts = [(rework_check_ids[0], "rejected", "Mesure incohérente, à reprendre")]
        verdicts += [(check_id, "accepted", None) for check_id in rework_check_ids[1:]]
        _check(job_service.review(tenant_id=TENANT, actor_id=demo_user_id, job_id=rework_id, verdicts=verdicts), "review rework-job")
        print(f"rework job {job_numbers['rework']}: 1 check rejected and reopened, {len(rework_checks) - 1} accepted")

        # 6) closed — full history, dated last week so it shows in the calendar's past
        closed_id = _check(
            job_service.create_job(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                equipment_id=equipment_b[0],
                title="Serrage mensuel — intervention clôturée",
                description="Intervention de référence pour la démonstration de l'historique complet.",
                kind="preventive",
                priority="normal",
                due_date=TODAY - datetime.timedelta(days=7),
                stops_machine=False,
                checkpoint_ids=[c["id"] for c in checkpoints if c["view_id"] == views_b[0]["id"]],
                tasks=[],
                team_id=team["id"],
                chef_user_id=demo_user_id,
            ),
            "create_job closed",
        )
        job_ids["closed"] = closed_id
        job_numbers["closed"] = job_number(closed_id)
        closed_checks = connection.execute(
            "SELECT id FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order", (closed_id,)
        ).fetchall()
        last_week_start = now - datetime.timedelta(days=7)
        for i, row in enumerate(closed_checks):
            _check(
                job_service.record_entry(
                    tenant_id=TENANT,
                    actor_id=demo_user_id,
                    job_id=closed_id,
                    check_id=row[0],
                    performer_employee_id=performer_id,
                    outcome="ok",
                    note="Effectué en atelier",
                    measured_value=None,
                    started_at=last_week_start + datetime.timedelta(minutes=10 * i),
                    finished_at=last_week_start + datetime.timedelta(minutes=10 * i + 8),
                    manual_minutes=None,
                    photo=None,
                    actor_can_plan=True,
                    now=now,
                ),
                "record_entry closed-job",
            )
        _check(job_service.submit(tenant_id=TENANT, actor_id=demo_user_id, job_id=closed_id, actor_can_plan=True), "submit closed-job")
        _check(
            job_service.review(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                job_id=closed_id,
                verdicts=[(row[0], "accepted", None) for row in closed_checks],
            ),
            "review closed-job",
        )
        _check(job_service.close(tenant_id=TENANT, actor_id=demo_user_id, job_id=closed_id), "close closed-job")
        # Backdate the whole trail to last week so the calendar's "past" shows a closed job,
        # not one closed seconds ago. Direct UPDATEs on maintenance.* rows only, dev-seed only.
        connection.execute(
            "UPDATE maintenance.jobs SET created_at = %s, assigned_at = %s, started_at = %s, submitted_at = %s, closed_at = %s "
            "WHERE id = %s",
            (
                last_week_start,
                last_week_start,
                last_week_start,
                last_week_start + datetime.timedelta(hours=1),
                last_week_start + datetime.timedelta(hours=2),
                closed_id,
            ),
        )
        connection.execute(
            "UPDATE maintenance.job_events SET at = %s WHERE job_id = %s AND kind = 'created'", (last_week_start, closed_id)
        )
        connection.execute(
            "UPDATE maintenance.check_entries SET created_at = %s WHERE check_id = ANY(%s)",
            (last_week_start, [row[0] for row in closed_checks]),
        )
        print(f"closed job {job_numbers['closed']}: full history, backdated to last week")

        # ---- parts request --------------------------------------------------
        part_product = connection.execute(
            "SELECT p.id, p.uom_id FROM core.products p WHERE p.tenant_id = %s AND p.sku = %s", (TENANT, "CARTON-STD")
        ).fetchone()
        if part_product is None:
            part_product = connection.execute(
                "SELECT id, uom_id FROM core.products WHERE tenant_id = %s ORDER BY sku LIMIT 1", (TENANT,)
            ).fetchone()
        product_id, uom_id = part_product

        parts_service = PartsService(connection)
        request_id = _check(
            parts_service.create_request(
                tenant_id=TENANT,
                actor_id=demo_user_id,
                job_id=in_progress_id,
                lines=[{"product_id": product_id, "uom_id": uom_id, "quantity": 5}],
                note="Pièce de rechange nécessaire pour terminer l'intervention",
                actor_can_plan=True,
            ),
            "create_request",
        )
        print(f"parts request: {request_id} (pending, job {job_numbers['in_progress']})")

        connection.commit()

        print("\nSeed summary:")
        print(f"  team: {TEAM_NAME} ({team['id']})")
        print(f"  equipment: {equipment_a[1]}, {equipment_b[1]}")
        print(f"  programs: {weekly_program['name']}, {monthly_program['name']} (swept: created={swept['created']})")
        for state, jid in job_ids.items():
            print(f"  job [{state}]: {job_numbers[state]} ({jid})")
        print(f"  parts request: {request_id} (pending)")
        print(f"\nSeeded maintenance demo data. Login with {DEMO_EMAIL} / demo1234")


if __name__ == "__main__":
    seed()

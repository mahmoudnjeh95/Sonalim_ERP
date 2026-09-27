"""Seeds a demo tenant so the API can be exercised right after `docker compose up`. Dev-only."""

from __future__ import annotations

import datetime

from ulid import ULID

from core.auth import hash_password
from core.db import get_connection
from core.permissions_registry import ADMINISTRATOR_ROLE_CODE, ensure_default_roles
from modules.crm.domain.opportunity import DEFAULT_PROBABILITY_BY_STAGE

DEMO_TENANT_ID = "demo"


def seed() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO core.users (id, tenant_id, email, password_hash)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            """,
            (str(ULID()), DEMO_TENANT_ID, "demo@sonalim-erp.local", hash_password("demo1234")),
        )
        user_id = connection.execute(
            "SELECT id FROM core.users WHERE email = %s",
            ("demo@sonalim-erp.local",),
        ).fetchone()[0]

        role_ids = ensure_default_roles(connection, DEMO_TENANT_ID)
        connection.execute(
            """
            INSERT INTO core.user_roles (user_id, role_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, role_id) DO NOTHING
            """,
            (user_id, role_ids[ADMINISTRATOR_ROLE_CODE]),
        )

        connection.execute(
            """
            INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base, is_integer_only)
            VALUES (%s, %s, 'ea', 'Pièce', 'unit', 1, TRUE)
            ON CONFLICT (tenant_id, code) DO UPDATE SET name = EXCLUDED.name
            """,
            (str(ULID()), DEMO_TENANT_ID),
        )

        # HR demo data is keyed by stable business identifiers so this seed can be rerun safely.
        department_ids: dict[str, str] = {}
        for code, name in [("SALES", "Sales"), ("OPS", "Operations"), ("FIN", "Finance")]:
            connection.execute(
                """
                INSERT INTO hr.departments (id, tenant_id, code, name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (str(ULID()), DEMO_TENANT_ID, code, name),
            )
            department_ids[code] = connection.execute(
                "SELECT id FROM hr.departments WHERE tenant_id = %s AND code = %s",
                (DEMO_TENANT_ID, code),
            ).fetchone()[0]

        employee_ids: dict[str, str] = {}
        demo_employees = [
            ("EMP-001", "Amina", "Diallo", "amina.diallo@sonalim.local", "Sales Manager", "SALES", "2023-02-06", "active", 1800),
            ("EMP-002", "Moussa", "Traore", "moussa.traore@sonalim.local", "Production Supervisor", "OPS", "2022-09-12", "active", 1650),
            ("EMP-003", "Fatou", "Coulibaly", "fatou.coulibaly@sonalim.local", "Accountant", "FIN", "2024-01-15", "on_leave", 1500),
            ("EMP-004", "Ibrahim", "Keita", "ibrahim.keita@sonalim.local", "Sales Representative", "SALES", "2024-05-20", "active", 1200),
        ]
        for employee_no, first_name, last_name, email, title, department, hire_date, employee_status, salary in demo_employees:
            connection.execute(
                """
                INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, email, job_title, department_id, hire_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, employee_no) DO NOTHING
                """,
                (str(ULID()), DEMO_TENANT_ID, employee_no, first_name, last_name, email, title, department_ids[department], hire_date, employee_status),
            )
            employee_id = connection.execute(
                "SELECT id FROM hr.employees WHERE tenant_id = %s AND employee_no = %s",
                (DEMO_TENANT_ID, employee_no),
            ).fetchone()[0]
            employee_ids[employee_no] = employee_id
            connection.execute(
                """
                INSERT INTO hr.contracts (id, tenant_id, employee_id, contract_type, start_date, salary, currency, status)
                SELECT %s, %s, %s, 'permanent', %s, %s, 'USD', 'active'
                WHERE NOT EXISTS (SELECT 1 FROM hr.contracts WHERE tenant_id = %s AND employee_id = %s)
                """,
                (str(ULID()), DEMO_TENANT_ID, employee_id, hire_date, salary, DEMO_TENANT_ID, employee_id),
            )

        attendance_date = datetime.date.today() - datetime.timedelta(days=1)
        for employee_no, attendance_status, hours in [("EMP-001", "present", 8), ("EMP-002", "late", 7), ("EMP-003", "leave", 0), ("EMP-004", "remote", 8)]:
            connection.execute(
                """
                INSERT INTO hr.attendance_records (id, tenant_id, employee_id, attendance_date, status, hours_worked)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, employee_id, attendance_date) DO UPDATE SET status = EXCLUDED.status, hours_worked = EXCLUDED.hours_worked
                """,
                (str(ULID()), DEMO_TENANT_ID, employee_ids[employee_no], attendance_date, attendance_status, hours),
            )

        leave_start = datetime.date.today() + datetime.timedelta(days=7)
        connection.execute(
            """
            INSERT INTO hr.leave_requests (id, tenant_id, employee_id, leave_type, start_date, end_date, reason, status)
            SELECT %s, %s, %s, 'annual', %s, %s, 'Family vacation', 'pending'
            WHERE NOT EXISTS (SELECT 1 FROM hr.leave_requests WHERE tenant_id = %s AND employee_id = %s AND start_date = %s)
            """,
            (str(ULID()), DEMO_TENANT_ID, employee_ids["EMP-001"], leave_start, leave_start + datetime.timedelta(days=4), DEMO_TENANT_ID, employee_ids["EMP-001"], leave_start),
        )

        payroll_month = datetime.date.today().replace(day=1)
        payroll_run_id = connection.execute(
            "SELECT id FROM hr.payroll_runs WHERE tenant_id = %s AND period_month = %s",
            (DEMO_TENANT_ID, payroll_month),
        ).fetchone()
        if payroll_run_id is None:
            payroll_run_id = str(ULID())
            connection.execute(
                "INSERT INTO hr.payroll_runs (id, tenant_id, period_month, status) VALUES (%s, %s, %s, 'calculated')",
                (payroll_run_id, DEMO_TENANT_ID, payroll_month),
            )
        else:
            payroll_run_id = payroll_run_id[0]
        for employee_no, salary in [("EMP-001", 1800), ("EMP-002", 1650), ("EMP-003", 1500), ("EMP-004", 1200)]:
            bonuses, deductions, taxes = (150, 50, 180) if employee_no == "EMP-001" else (0, 25, 120)
            connection.execute(
                """
                INSERT INTO hr.payroll_items (id, tenant_id, payroll_run_id, employee_id, base_salary, bonuses, deductions, taxes, net_salary, currency)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'USD')
                ON CONFLICT (payroll_run_id, employee_id) DO UPDATE SET base_salary = EXCLUDED.base_salary, bonuses = EXCLUDED.bonuses, deductions = EXCLUDED.deductions, taxes = EXCLUDED.taxes, net_salary = EXCLUDED.net_salary
                """,
                (str(ULID()), DEMO_TENANT_ID, payroll_run_id, employee_ids[employee_no], salary, bonuses, deductions, taxes, salary + bonuses - deductions - taxes),
            )
        uom_id = connection.execute(
            "SELECT id FROM core.uoms WHERE tenant_id = %s AND code = 'ea'",
            (DEMO_TENANT_ID,),
        ).fetchone()[0]

        connection.execute(
            """
            INSERT INTO core.products (id, tenant_id, sku, name, uom_id)
            VALUES (%s, %s, 'WIDGET-1', 'Demo Widget', %s)
            ON CONFLICT (tenant_id, sku) DO NOTHING
            """,
            (str(ULID()), DEMO_TENANT_ID, uom_id),
        )
        connection.execute(
            """
            INSERT INTO core.partners (id, tenant_id, name, kind, email)
            VALUES (%s, %s, 'Acme Corp', 'customer', 'buyer@acme.example')
            ON CONFLICT (tenant_id, name) DO NOTHING
            """,
            (str(ULID()), DEMO_TENANT_ID),
        )

        # Matches the id the 0012 migration's backfill would assign, so seeding
        # stays consistent whether it runs on a fresh DB or one migrated from
        # pre-multi-site data.
        demo_site_id = "default-site-" + DEMO_TENANT_ID
        connection.execute(
            """
            INSERT INTO warehouse.sites (id, tenant_id, code, name)
            VALUES (%s, %s, 'main', 'Site principal')
            ON CONFLICT (tenant_id, code) DO NOTHING
            """,
            (demo_site_id, DEMO_TENANT_ID),
        )
        for code, name in [("raw-materials", "Matières premières"), ("spare-parts", "Pièces de rechange")]:
            connection.execute(
                """
                INSERT INTO warehouse.locations (id, tenant_id, code, name, site_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (str(ULID()), DEMO_TENANT_ID, code, name, demo_site_id),
            )

        # --- CRM demo data -----------------------------------------------
        # Reuses the HR demo employees above as CRM owners so "assigned to"
        # feels like a real person, not a placeholder id.
        owner_id_by_name: dict[str, str] = {}
        for full_name, email in [("Amina Diallo", "amina.diallo@sonalim.local"), ("Ibrahim Keita", "ibrahim.keita@sonalim.local")]:
            connection.execute(
                """
                INSERT INTO core.users (id, tenant_id, email, password_hash, full_name)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET full_name = EXCLUDED.full_name
                """,
                (str(ULID()), DEMO_TENANT_ID, email, hash_password("demo1234"), full_name),
            )
            owner_user_id = connection.execute("SELECT id FROM core.users WHERE email = %s", (email,)).fetchone()[0]
            owner_id_by_name[full_name] = owner_user_id
            connection.execute(
                "INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s) ON CONFLICT (user_id, role_id) DO NOTHING",
                (owner_user_id, role_ids["crm"]),
            )
        amina_id = owner_id_by_name["Amina Diallo"]
        ibrahim_id = owner_id_by_name["Ibrahim Keita"]

        new_accounts = [
            ("Global Foods Distribution", "customer", "purchasing@globalfoods.example"),
            ("Mediterra Retail Group", "customer", "orders@mediterra.example"),
        ]
        for name, kind, email in new_accounts:
            connection.execute(
                """
                INSERT INTO core.partners (id, tenant_id, name, kind, email)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, name) DO NOTHING
                """,
                (str(ULID()), DEMO_TENANT_ID, name, kind, email),
            )
        partner_id_by_name = {
            name: connection.execute(
                "SELECT id FROM core.partners WHERE tenant_id = %s AND name = %s", (DEMO_TENANT_ID, name)
            ).fetchone()[0]
            for name in ["Acme Corp", "Global Foods Distribution", "Mediterra Retail Group"]
        }

        demo_contacts = [
            ("Global Foods Distribution", "Nadia", "Haddad", "Purchasing Manager", "nadia.haddad@globalfoods.example", True),
            ("Global Foods Distribution", "Karim", "Belhadj", "Buyer", "karim.belhadj@globalfoods.example", False),
            ("Mediterra Retail Group", "Sophie", "Laurent", "Category Manager", "sophie.laurent@mediterra.example", True),
            ("Mediterra Retail Group", "Youssef", "Amrani", "Store Operations", "youssef.amrani@mediterra.example", False),
        ]
        for account_name, first_name, last_name, job_title, email, is_primary in demo_contacts:
            partner_id = partner_id_by_name[account_name]
            connection.execute(
                """
                INSERT INTO crm.contacts (id, tenant_id, partner_id, first_name, last_name, job_title, email, is_primary)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (SELECT 1 FROM crm.contacts WHERE tenant_id = %s AND partner_id = %s AND email = %s)
                """,
                (str(ULID()), DEMO_TENANT_ID, partner_id, first_name, last_name, job_title, email, is_primary,
                 DEMO_TENANT_ID, partner_id, email),
            )

        demo_leads = [
            ("Rania Ben Salah", "rania.bensalah@newbakery.example", "new", "website", amina_id, "medium", None),
            ("Tarek Fassi", "tarek.fassi@freshmart.example", "new", "trade_show", ibrahim_id, "high", None),
            ("Leila Mansour", "leila.mansour@cornerstore.example", "qualified", "referral", amina_id, "medium", None),
            ("Hamid Ouali", "hamid.ouali@quickstop.example", "converted", "cold_call", ibrahim_id, "low", None),
            ("Sami Trabelsi", "sami.trabelsi@budgetgoods.example", "disqualified", "social_media", amina_id, "low", "Budget too small for minimum order"),
        ]
        for contact_name, email, lead_status, source, owner_id, priority, disqualify_reason in demo_leads:
            connection.execute(
                """
                INSERT INTO crm.leads (id, tenant_id, contact_name, email, status, source, owner_id, priority, disqualify_reason)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (SELECT 1 FROM crm.leads WHERE tenant_id = %s AND email = %s)
                """,
                (str(ULID()), DEMO_TENANT_ID, contact_name, email, lead_status, source, owner_id, priority, disqualify_reason,
                 DEMO_TENANT_ID, email),
            )

        today = datetime.date.today()
        demo_opportunities = [
            ("Acme Corp", "Acme Q4 pasta restock", "won", 8500, amina_id, "medium", today - datetime.timedelta(days=10), None),
            ("Acme Corp", "Acme new product line", "negotiation", 4200, amina_id, "high", today + datetime.timedelta(days=3), None),
            ("Global Foods Distribution", "Global Foods bulk semoule contract", "proposal", 15000, ibrahim_id, "high", today + datetime.timedelta(days=20), None),
            ("Global Foods Distribution", "Global Foods trial order", "qualification", 2500, ibrahim_id, "medium", today - datetime.timedelta(days=2), None),
            ("Mediterra Retail Group", "Mediterra shelf program", "prospecting", 6000, amina_id, "low", today + datetime.timedelta(days=45), None),
            ("Mediterra Retail Group", "Mediterra Q1 promo", "lost", 3000, ibrahim_id, "medium", today - datetime.timedelta(days=15), "Lost to a competitor"),
        ]
        for account_name, name, stage, amount, owner_id, priority, close_date, lost_reason in demo_opportunities:
            partner_id = partner_id_by_name[account_name]
            connection.execute(
                """
                INSERT INTO crm.opportunities
                    (id, tenant_id, partner_id, name, stage, amount, expected_close_date, probability, owner_id, priority, lost_reason)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (SELECT 1 FROM crm.opportunities WHERE tenant_id = %s AND partner_id = %s AND name = %s)
                """,
                (str(ULID()), DEMO_TENANT_ID, partner_id, name, stage, amount, close_date,
                 DEFAULT_PROBABILITY_BY_STAGE[stage], owner_id, priority, lost_reason,
                 DEMO_TENANT_ID, partner_id, name),
            )
        opportunity_id_by_name = {
            name: connection.execute(
                "SELECT id FROM crm.opportunities WHERE tenant_id = %s AND name = %s", (DEMO_TENANT_ID, name)
            ).fetchone()[0]
            for _, name, *_ in demo_opportunities
        }
        lead_id_by_email = {
            email: connection.execute(
                "SELECT id FROM crm.leads WHERE tenant_id = %s AND email = %s", (DEMO_TENANT_ID, email)
            ).fetchone()[0]
            for _, email, *_ in demo_leads
        }

        now = datetime.datetime.now(datetime.timezone.utc)
        demo_activities = [
            ("call", "lead", lead_id_by_email["rania.bensalah@newbakery.example"],
             "Introductory call, interested in retail packs", now - datetime.timedelta(days=2), True),
            ("task", "lead", lead_id_by_email["tarek.fassi@freshmart.example"],
             "Send product catalog and price list", now + datetime.timedelta(days=1), False),
            ("meeting", "opportunity", opportunity_id_by_name["Global Foods bulk semoule contract"],
             "On-site tasting and contract review", now + datetime.timedelta(days=5), False),
            ("call", "opportunity", opportunity_id_by_name["Acme new product line"],
             "Negotiated pricing for new SKU", now - datetime.timedelta(days=1), True),
            ("comment", "partner", partner_id_by_name["Acme Corp"],
             "Long-standing customer, prioritize support tickets", now - datetime.timedelta(days=20), True),
            ("task", "opportunity", opportunity_id_by_name["Global Foods trial order"],
             "Follow up on trial order feedback", now - datetime.timedelta(days=3), False),
            ("meeting", "partner", partner_id_by_name["Mediterra Retail Group"],
             "Quarterly business review", now + datetime.timedelta(days=10), False),
            ("comment", "lead", lead_id_by_email["leila.mansour@cornerstore.example"],
             "Requested samples before qualifying further", now - datetime.timedelta(days=1), False),
        ]
        for kind, subject_type, subject_id, note, due_at, completed in demo_activities:
            connection.execute(
                """
                INSERT INTO crm.activities (id, tenant_id, kind, subject_type, subject_id, note, due_at, completed_at)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM crm.activities WHERE tenant_id = %s AND subject_type = %s AND subject_id = %s AND note = %s
                )
                """,
                (str(ULID()), DEMO_TENANT_ID, kind, subject_type, subject_id, note, due_at, now if completed else None,
                 DEMO_TENANT_ID, subject_type, subject_id, note),
            )

        connection.commit()

    print("Seeded demo tenant. Login with demo@sonalim-erp.local / demo1234")


if __name__ == "__main__":
    seed()

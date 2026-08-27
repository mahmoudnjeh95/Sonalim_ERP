"""Seeds a demo tenant so the API can be exercised right after `docker compose up`. Dev-only."""

from __future__ import annotations

import datetime

from ulid import ULID

from core.auth import hash_password
from core.db import get_connection

DEMO_TENANT_ID = "demo"
DEMO_PERMISSIONS = [
    "crm.view_leads",
    "crm.manage_leads",
    "crm.view_opportunities",
    "crm.manage_opportunities",
    "crm.view_activities",
    "crm.manage_activities",
    "crm.view_contacts",
    "crm.manage_contacts",
    "crm.view_dashboard",
    "hr.view_attendance",
    "hr.manage_attendance",
    "hr.view_payroll",
    "hr.manage_payroll",
    "core.manage_permissions",
    "core.view_partners",
    "core.manage_partners",
    "core.view_exchange_rates",
    "core.manage_exchange_rates",
    "core.view_products",
    "core.view_audit_log",
    "warehouse.view_moves",
    "warehouse.manage_stock",
    "warehouse.adjust_stock",
    "warehouse.view_material_receipts",
    "warehouse.manage_material_receipts",
    "warehouse.admin_material_receipts",
]


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

        for permission in DEMO_PERMISSIONS:
            connection.execute(
                """
                INSERT INTO core.user_permissions (user_id, permission)
                VALUES (%s, %s)
                ON CONFLICT (user_id, permission) DO NOTHING
                """,
                (user_id, permission),
            )

        connection.execute(
            """
            INSERT INTO core.uoms (id, tenant_id, code, name, category, ratio_to_base)
            VALUES (%s, %s, 'ea', 'Pièce', 'unit', 1)
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

        for code, name in [("raw-materials", "Matières premières"), ("spare-parts", "Pièces de rechange")]:
            connection.execute(
                """
                INSERT INTO warehouse.locations (id, tenant_id, code, name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (str(ULID()), DEMO_TENANT_ID, code, name),
            )
        connection.commit()

    print("Seeded demo tenant. Login with demo@sonalim-erp.local / demo1234")


if __name__ == "__main__":
    seed()

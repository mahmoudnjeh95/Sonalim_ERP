"""The employer block printed on payslips, cash sheets and declarations."""
from __future__ import annotations

from typing import Any

import psycopg

from modules.payroll.api.rule_set_service import RuleSetService


def company_header(connection: psycopg.Connection, tenant_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT name FROM core.companies WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (tenant_id,)).fetchone()
    settings = RuleSetService(connection).get_settings(tenant_id=tenant_id) or {}
    return {"name": row[0] if row else None, "address": settings.get("company_address"),
            "employer_inps_no": settings.get("employer_inps_no"), "employer_tax_id": settings.get("employer_tax_id")}

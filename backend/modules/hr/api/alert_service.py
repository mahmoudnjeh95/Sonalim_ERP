"""What falls due inside the horizons HR set: contracts ending, trial periods ending, documents
to renew. People who left raise nothing; a contract already renewed and a paper already replaced
by a newer one of the same kind raise nothing either."""
from __future__ import annotations

import datetime

import psycopg

from modules.hr.api.settings_service import HrSettingsService
from modules.hr.domain.alerts import expiry_state, window_end

# A renewal is a signed contract of the same person starting after this one ends.
_NOT_RENEWED = """
    AND NOT EXISTS (
        SELECT 1 FROM hr.contracts n
        WHERE n.tenant_id = c.tenant_id AND n.employee_id = c.employee_id AND n.status <> 'draft' AND n.start_date > c.end_date
    )
"""


class HrAlertService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def expiry_alerts(self, *, tenant_id: str, today: datetime.date) -> dict:
        settings = HrSettingsService(self.connection).get(tenant_id)
        return {
            "as_of": today.isoformat(),
            **settings,
            "contracts_ending": self._contracts(tenant_id, "end_date", today, window_end(today, settings["contract_expiry_horizon_days"])),
            "trials_ending": self._contracts(tenant_id, "trial_end_date", today, window_end(today, settings["trial_end_horizon_days"])),
            "documents_expiring": self._documents(tenant_id, today, settings["document_expiry_horizon_days"]),
        }

    def _contracts(self, tenant_id: str, column: str, today: datetime.date, until: datetime.date | None) -> list[dict]:
        # `column` is one of the two literals above, never user input.
        if until is None:
            return []
        renewal = _NOT_RENEWED if column == "end_date" else ""
        rows = self.connection.execute(
            f"""
            SELECT c.id, c.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, c.contract_type, c.{column}
            FROM hr.contracts c
            JOIN hr.employees e ON e.id = c.employee_id
            WHERE c.tenant_id = %s AND c.status = 'active' AND e.status <> 'terminated'
              AND c.{column} BETWEEN %s AND %s {renewal}
            ORDER BY c.{column}, e.employee_no
            """,
            (tenant_id, today, until),
        ).fetchall()
        return [
            {"contract_id": r[0], "employee_id": r[1], "employee_no": r[2], "employee_name": r[3], "contract_type": r[4], "date": r[5].isoformat()}
            for r in rows
        ]

    def _documents(self, tenant_id: str, today: datetime.date, days: int | None) -> list[dict]:
        until = window_end(today, days)
        if until is None:
            return []
        rows = self.connection.execute(
            """
            SELECT d.id, d.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, d.kind, d.title, d.expires_on
            FROM hr.employee_documents d
            JOIN hr.employees e ON e.id = d.employee_id
            WHERE d.tenant_id = %s AND e.status <> 'terminated' AND d.expires_on IS NOT NULL AND d.expires_on <= %s
              AND (d.kind = 'other' OR NOT EXISTS (
                    SELECT 1 FROM hr.employee_documents n
                    WHERE n.tenant_id = d.tenant_id AND n.employee_id = d.employee_id AND n.kind = d.kind AND n.id <> d.id
                      AND (n.expires_on IS NULL OR n.expires_on > d.expires_on)))
            ORDER BY d.expires_on, e.employee_no
            """,
            (tenant_id, until),
        ).fetchall()
        return [
            {
                "document_id": r[0],
                "employee_id": r[1],
                "employee_no": r[2],
                "employee_name": r[3],
                "kind": r[4],
                "title": r[5],
                "expires_on": r[6].isoformat(),
                "state": expiry_state(r[6], today, days),
            }
            for r in rows
        ]

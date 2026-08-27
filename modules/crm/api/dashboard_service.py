from __future__ import annotations

import datetime
from collections import Counter

import psycopg

from core.api.service import CoreService


class CrmDashboardService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_dashboard(self, *, tenant_id: str) -> dict:
        today = datetime.date.today()
        current_year = today.year
        previous_year = current_year - 1
        week_end = today + datetime.timedelta(days=7)
        seven_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)

        won_amount = self._connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM crm.opportunities WHERE tenant_id = %s AND stage = 'won'",
            (tenant_id,),
        ).fetchone()[0]

        stage_rows = self._connection.execute(
            "SELECT stage, COUNT(*), COALESCE(SUM(amount), 0) FROM crm.opportunities WHERE tenant_id = %s GROUP BY stage",
            (tenant_id,),
        ).fetchall()
        pipeline_by_stage = {row[0]: {"count": row[1], "amount": float(row[2])} for row in stage_rows}

        forecast = self._connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM crm.opportunities
            WHERE tenant_id = %s AND stage NOT IN ('won', 'lost')
            """,
            (tenant_id,),
        ).fetchone()

        due_this_week = self._connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM crm.opportunities
            WHERE tenant_id = %s AND stage NOT IN ('won', 'lost')
              AND expected_close_date BETWEEN %s AND %s
            """,
            (tenant_id, today, week_end),
        ).fetchone()

        overdue = self._connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM crm.opportunities
            WHERE tenant_id = %s AND stage NOT IN ('won', 'lost')
              AND expected_close_date < %s
            """,
            (tenant_id, today),
        ).fetchone()

        month_rows = self._connection.execute(
            """
            SELECT EXTRACT(YEAR FROM created_at)::int AS y, EXTRACT(MONTH FROM created_at)::int AS m, COUNT(*)
            FROM crm.opportunities
            WHERE tenant_id = %s AND created_at >= %s
            GROUP BY 1, 2
            """,
            (tenant_id, datetime.date(previous_year, 1, 1)),
        ).fetchall()
        by_year_month: dict[int, dict[int, int]] = {}
        for year, month, count in month_rows:
            by_year_month.setdefault(int(year), {})[int(month)] = count
        opportunities_by_month = {
            "current_year": current_year,
            "previous_year": previous_year,
            "current": [by_year_month.get(current_year, {}).get(m, 0) for m in range(1, 13)],
            "previous": [by_year_month.get(previous_year, {}).get(m, 0) for m in range(1, 13)],
        }

        activity_rows = self._connection.execute(
            """
            SELECT kind, COUNT(*) FROM crm.activities
            WHERE tenant_id = %s AND created_at >= %s
            GROUP BY kind
            """,
            (tenant_id, seven_days_ago),
        ).fetchall()
        activities_by_kind = {row[0]: row[1] for row in activity_rows}

        recent_rows = self._connection.execute(
            """
            SELECT id, kind, subject_type, subject_id, note, due_at, completed_at, created_at
            FROM crm.activities WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 8
            """,
            (tenant_id,),
        ).fetchall()
        recent_activities = [
            {
                "id": r[0],
                "kind": r[1],
                "subject_type": r[2],
                "subject_id": r[3],
                "note": r[4],
                "due_at": r[5].isoformat() if r[5] else None,
                "completed_at": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat(),
            }
            for r in recent_rows
        ]

        lead_rows = self._connection.execute(
            "SELECT status, COUNT(*) FROM crm.leads WHERE tenant_id = %s GROUP BY status", (tenant_id,)
        ).fetchall()
        leads_by_status = {row[0]: row[1] for row in lead_rows}

        all_partners = CoreService(self._connection).list_partners(tenant_id=tenant_id)
        customer_partners = [p for p in all_partners if p.kind in ("customer", "both")]
        partners_by_status = dict(Counter(partner.status for partner in customer_partners))

        return {
            "won_amount": float(won_amount),
            "pipeline_by_stage": pipeline_by_stage,
            "forecast": {"count": forecast[0], "amount": float(forecast[1])},
            "due_this_week": {"count": due_this_week[0], "amount": float(due_this_week[1])},
            "overdue": {"count": overdue[0], "amount": float(overdue[1])},
            "opportunities_by_month": opportunities_by_month,
            "activities_by_kind": activities_by_kind,
            "recent_activities": recent_activities,
            "leads_by_status": leads_by_status,
            "partners_by_status": partners_by_status,
        }

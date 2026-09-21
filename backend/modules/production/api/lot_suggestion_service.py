from __future__ import annotations

import datetime

import psycopg

from modules.production.domain.lot_number import suggest_lot_number

# How far back to look for a lot that is a counter. Nearly always the first row
# is one; the window only matters if a run of free-text lots comes right before.
_LOOKBACK = 50


class LotSuggestionService:
    """The lot number a new packing report is most likely to carry.

    Read from what the same line already filed, never from the warehouse's lots: a lot
    exists there only once its report is validated, and the number is wanted while the
    day's first report is still being typed. Drafts and submitted reports therefore
    count -- a rejected one does not, since its figures were sent back as wrong.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def suggest(self, *, tenant_id: str, work_center_id: str, report_date: datetime.date) -> dict:
        rows = self._connection.execute(
            """
            SELECT c.lot_number, r.report_date
            FROM production.conditionnement_reports c
            JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
            WHERE c.tenant_id = %s AND r.work_center_id = %s AND r.report_date <= %s
              AND r.status <> 'rejected' AND btrim(coalesce(c.lot_number, '')) <> ''
            ORDER BY r.report_date DESC, r.created_at DESC
            LIMIT %s
            """,
            (tenant_id, work_center_id, report_date, _LOOKBACK),
        ).fetchall()
        for last_lot, last_date in rows:
            suggestion = suggest_lot_number(last_lot=last_lot, last_date=last_date, report_date=report_date)
            if suggestion is not None:
                return {
                    "lot_number": suggestion,
                    "based_on": {"lot_number": last_lot.strip(), "report_date": last_date.isoformat()},
                }
        return {"lot_number": None, "based_on": None}

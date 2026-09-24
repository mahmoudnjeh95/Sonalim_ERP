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
            SELECT p.lot_number, s.report_date
            FROM production.shift_packing_rows p
            JOIN production.shift_reports s ON s.id = p.shift_report_id AND s.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND s.work_center_id = %s AND s.report_date <= %s
              AND s.status <> 'returned' AND btrim(coalesce(p.lot_number, '')) <> ''
            ORDER BY s.report_date DESC, p.created_at DESC
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

"""Fiscal years (calendar years, SYSCOHADA) and their monthly periods, open or closed.

Nothing is posted into a closed period; `ensure_open` is the one check every posting goes through."""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result

PERIOD_KEYS = ("period", "year", "status", "closed_by", "closed_at")


def period_missing(period: datetime.date) -> Err:
    return Err(
        "PERIOD_MISSING",
        f"no accounting period for {period:%Y-%m}; open fiscal year {period.year} first",
        f"aucune période comptable pour {period:%m/%Y} ; ouvrez d'abord l'exercice {period.year}",
    )


class PeriodService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def open_fiscal_year(self, *, tenant_id: str, actor_id: str, year: int) -> Result[dict]:
        if not 2000 <= year <= 2100:
            return Err(
                "INVALID_PERIOD",
                f"{year} is not a fiscal year this ledger accepts (2000 to 2100)",
                f"{year} n'est pas un exercice accepté (2000 à 2100)",
            )
        exists = self._connection.execute(
            "SELECT 1 FROM finance.fiscal_years WHERE tenant_id = %s AND year = %s", (tenant_id, year)
        ).fetchone()
        if exists:
            return Err("FISCAL_YEAR_EXISTS", f"fiscal year {year} is already open", f"l'exercice {year} est déjà ouvert")
        fiscal_year_id = str(ULID())
        start, end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
        self._connection.execute(
            """
            INSERT INTO finance.fiscal_years (id, tenant_id, year, start_date, end_date, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (fiscal_year_id, tenant_id, year, start, end, actor_id),
        )
        for month in range(1, 13):
            self._connection.execute(
                "INSERT INTO finance.periods (tenant_id, period, fiscal_year_id) VALUES (%s, %s, %s)",
                (tenant_id, datetime.date(year, month, 1), fiscal_year_id),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="fiscal_year.opened",
            entity_type="fiscal_year",
            entity_id=fiscal_year_id,
            payload={"year": year},
        )
        return Ok({"id": fiscal_year_id, "year": year, "start_date": start, "end_date": end})

    def list_periods(self, *, tenant_id: str, year: int | None = None) -> list[dict]:
        sql = """
            SELECT p.period, f.year, p.status, p.closed_by, p.closed_at
            FROM finance.periods p
            JOIN finance.fiscal_years f ON f.id = p.fiscal_year_id
            WHERE p.tenant_id = %s
        """
        params: list[object] = [tenant_id]
        if year is not None:
            sql += " AND f.year = %s"
            params.append(year)
        rows = self._connection.execute(sql + " ORDER BY p.period", params).fetchall()
        return [dict(zip(PERIOD_KEYS, row)) for row in rows]

    def ensure_open(self, *, tenant_id: str, day: datetime.date) -> Result[datetime.date]:
        """The period `day` falls in, if it exists and is open."""
        period = day.replace(day=1)
        row = self._connection.execute(
            "SELECT status FROM finance.periods WHERE tenant_id = %s AND period = %s", (tenant_id, period)
        ).fetchone()
        if row is None:
            return period_missing(period)
        if row[0] == "closed":
            return Err(
                "PERIOD_CLOSED",
                f"period {period:%Y-%m} is closed; nothing can be posted into it",
                f"la période {period:%m/%Y} est clôturée ; aucune écriture ne peut y être passée",
            )
        return Ok(period)

    def close_period(self, *, tenant_id: str, actor_id: str, period: datetime.date) -> Result[dict]:
        return self._set_status(tenant_id=tenant_id, actor_id=actor_id, period=period, status="closed")

    def reopen_period(self, *, tenant_id: str, actor_id: str, period: datetime.date) -> Result[dict]:
        return self._set_status(tenant_id=tenant_id, actor_id=actor_id, period=period, status="open")

    def _set_status(self, *, tenant_id: str, actor_id: str, period: datetime.date, status: str) -> Result[dict]:
        if period.day != 1:
            return Err(
                "INVALID_PERIOD",
                "a period is named by the first day of its month",
                "une période est désignée par le premier jour de son mois",
            )
        row = self._connection.execute(
            "SELECT status FROM finance.periods WHERE tenant_id = %s AND period = %s FOR UPDATE", (tenant_id, period)
        ).fetchone()
        if row is None:
            return period_missing(period)
        if row[0] == status:
            word_en, word_fr = ("closed", "clôturée") if status == "closed" else ("open", "ouverte")
            return Err(
                "INVALID_TRANSITION",
                f"period {period:%Y-%m} is already {word_en}",
                f"la période {period:%m/%Y} est déjà {word_fr}",
            )
        if status == "closed":
            self._connection.execute(
                """
                UPDATE finance.periods SET status = 'closed', closed_by = %s, closed_at = NOW()
                WHERE tenant_id = %s AND period = %s
                """,
                (actor_id, tenant_id, period),
            )
        else:
            self._connection.execute(
                """
                UPDATE finance.periods SET status = 'open', closed_by = NULL, closed_at = NULL
                WHERE tenant_id = %s AND period = %s
                """,
                (tenant_id, period),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="period.closed" if status == "closed" else "period.reopened",
            entity_type="period",
            entity_id=period.isoformat(),
            payload={"period": period.isoformat(), "from_status": row[0], "to_status": status},
        )
        return Ok(next(p for p in self.list_periods(tenant_id=tenant_id, year=period.year) if p["period"] == period))

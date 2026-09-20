from __future__ import annotations

import datetime

import psycopg

from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.domain.dashboard import direction, previous_period

GRANULARITIES = ("shift", "day", "week", "month")

# Same rule as every other aggregate in this module: a draft or rejected report
# is a team's working notes, and a submitted one is still waiting for a
# supervisor. Only validated reports are results.
_VALIDATED = "r.tenant_id = %s AND r.status = 'validated' AND r.report_date BETWEEN %s AND %s"


def _pct(finished: float, material: float) -> float | None:
    return finished / material * 100 if material > 0 else None


def _bucket(day: datetime.date, granularity: str) -> datetime.date:
    if granularity == "week":
        return day - datetime.timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def _next_bucket(day: datetime.date, granularity: str) -> datetime.date:
    if granularity == "week":
        return day + datetime.timedelta(days=7)
    if granularity == "month":
        return (day.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return day + datetime.timedelta(days=1)


def _bucket_keys(date_from: datetime.date, date_to: datetime.date, granularity: str) -> list[datetime.date]:
    keys, cursor = [], _bucket(date_from, granularity)
    while cursor <= date_to:
        keys.append(cursor)
        cursor = _next_bucket(cursor, granularity)
    return keys


class DashboardDayService:
    """What a period produced, read from validated reports only.

    Every figure is computed per report first and only then added up, so one
    OF, one shift, one team and one line can each be cut out of the same facts
    without re-deriving the unit handling. The handling itself is the one
    TeamPerformanceService and WorkOrderYieldService already use: rebroyat
    poured back in may be recorded in a different unit than the semoule (kg
    against tonnes), so it is restated into the report's own semoule unit
    before the two are added -- adding the raw figures inflated material input
    up to 1000x.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # -- facts ---------------------------------------------------------------

    def _report_facts(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
        rows = self._connection.execute(
            f"""
            WITH sem AS (
                SELECT sl.report_id, SUM(sl.quantity) AS quantity,
                       CASE WHEN COUNT(DISTINCT u.ratio_to_base) = 1 THEN MIN(u.ratio_to_base) END AS ratio
                FROM production.report_semolina_lines sl
                LEFT JOIN core.products p ON p.id = sl.product_id AND p.tenant_id = sl.tenant_id
                LEFT JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
                WHERE sl.tenant_id = %s
                GROUP BY sl.report_id
            )
            SELECT r.of_id, r.report_date, r.team, r.shift, r.work_center_id,
                   COALESCE(sem.quantity, 0),
                   COALESCE(d.regrind_input_quantity
                            * COALESCE(riu.ratio_to_base, COALESCE(sem.ratio, 1))
                            / COALESCE(sem.ratio, 1), 0),
                   COALESCE(d.finished_product_quantity, 0),
                   COALESCE(d.production_minutes, 0)
            FROM production.production_reports r
            JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            LEFT JOIN sem ON sem.report_id = r.id
            LEFT JOIN core.products rip ON rip.id = d.regrind_input_product_id AND rip.tenant_id = r.tenant_id
            LEFT JOIN core.uoms riu ON riu.id = rip.uom_id AND riu.tenant_id = rip.tenant_id
            WHERE {_VALIDATED} AND r.report_type = 'daily'
            """,
            (tenant_id, tenant_id, date_from, date_to),
        ).fetchall()
        return [
            {
                "of_id": of_id, "date": report_date, "team": team, "shift": shift, "work_center_id": work_center_id,
                "semolina": float(semolina), "regrind": float(regrind), "finished": float(finished),
                "production_minutes": int(minutes),
            }
            for of_id, report_date, team, shift, work_center_id, semolina, regrind, finished, minutes in rows
        ]

    def _stop_rows(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
        """Minutes lost, one row per arrêt. A daily report lists its arrêts; a
        conditionnement report still carries exactly one reason and duration."""
        rows = self._connection.execute(
            f"""
            SELECT r.of_id, r.work_center_id, r.team, dl.motif, dl.minutes
            FROM production.report_downtime_lines dl
            JOIN production.production_reports r ON r.id = dl.report_id AND r.tenant_id = dl.tenant_id
            WHERE {_VALIDATED} AND dl.minutes > 0
            UNION ALL
            SELECT r.of_id, r.work_center_id, r.team, c.downtime_reason, c.downtime_minutes
            FROM production.conditionnement_reports c
            JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
            WHERE {_VALIDATED} AND c.downtime_minutes > 0
            """,
            (tenant_id, date_from, date_to, tenant_id, date_from, date_to),
        ).fetchall()
        return [
            {"of_id": of_id, "work_center_id": wc, "team": team, "motif": motif, "minutes": int(minutes)}
            for of_id, wc, team, motif, minutes in rows
        ]

    def _waste_rows(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
        """Semoule-side déchet by stage, in the raw kilos the daily form records.
        A packing report's product/packaging waste is in each item's own unit,
        so it is never mixed in here."""
        rows = self._connection.execute(
            f"""
            SELECT r.of_id, r.work_center_id, r.team, w.category, SUM(w.quantity)
            FROM production.report_waste_lines w
            JOIN production.production_reports r ON r.id = w.report_id AND r.tenant_id = w.tenant_id
            WHERE {_VALIDATED} AND r.report_type = 'daily'
            GROUP BY r.of_id, r.work_center_id, r.team, w.category
            """,
            (tenant_id, date_from, date_to),
        ).fetchall()
        return [
            {"of_id": of_id, "work_center_id": wc, "team": team, "category": category, "quantity": float(quantity)}
            for of_id, wc, team, category, quantity in rows
        ]

    def _semolina_by_product(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, list[dict]]:
        rows = self._connection.execute(
            f"""
            SELECT r.of_id, sl.product_id, p.name, u.code, SUM(sl.quantity)
            FROM production.report_semolina_lines sl
            JOIN production.production_reports r ON r.id = sl.report_id AND r.tenant_id = sl.tenant_id
            LEFT JOIN core.products p ON p.id = sl.product_id AND p.tenant_id = sl.tenant_id
            LEFT JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE {_VALIDATED} AND r.report_type = 'daily'
            GROUP BY r.of_id, sl.product_id, p.name, u.code
            ORDER BY r.of_id, SUM(sl.quantity) DESC
            """,
            (tenant_id, date_from, date_to),
        ).fetchall()
        by_of: dict[str, list[dict]] = {}
        for of_id, product_id, name, unit, quantity in rows:
            by_of.setdefault(of_id, []).append(
                {"product_id": product_id, "name": name, "unit": unit, "quantity": float(quantity)}
            )
        return by_of

    def _packets_by_of(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, float]:
        rows = self._connection.execute(
            f"""
            SELECT r.of_id, SUM(c.packets_counted)
            FROM production.conditionnement_reports c
            JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
            WHERE {_VALIDATED}
            GROUP BY r.of_id
            """,
            (tenant_id, date_from, date_to),
        ).fetchall()
        return {of_id: float(total) for of_id, total in rows}

    def _semolina_unit(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> str | None:
        row = self._connection.execute(
            f"""
            SELECT u.code
            FROM production.report_semolina_lines sl
            JOIN production.production_reports r ON r.id = sl.report_id AND r.tenant_id = sl.tenant_id
            JOIN core.products p ON p.id = sl.product_id AND p.tenant_id = sl.tenant_id
            JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE {_VALIDATED} AND r.report_type = 'daily'
            GROUP BY u.code
            ORDER BY COUNT(*) DESC
            LIMIT 1
            """,
            (tenant_id, date_from, date_to),
        ).fetchone()
        return row[0] if row else None

    def _awaiting_validation(self, tenant_id: str, day: datetime.date) -> int:
        return self._connection.execute(
            "SELECT count(*) FROM production.production_reports "
            "WHERE tenant_id = %s AND status = 'submitted' AND report_date = %s",
            (tenant_id, day),
        ).fetchone()[0]

    def _of_details(self, tenant_id: str, of_ids: list[str]) -> dict[str, dict]:
        if not of_ids:
            return {}
        rows = self._connection.execute(
            "SELECT id, reference, product_type, work_center_id FROM production.work_orders "
            "WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, of_ids),
        ).fetchall()
        return {i: {"reference": ref, "product_type": pt, "work_center_id": wc} for i, ref, pt, wc in rows}

    # -- the day -------------------------------------------------------------

    @staticmethod
    def _totals(facts: list[dict], stops: list[dict]) -> dict:
        semolina_poured = sum(f["semolina"] + f["regrind"] for f in facts)
        finished = sum(f["finished"] for f in facts)
        return {
            "semolina_poured": semolina_poured,
            "finished_product": finished,
            "yield_pct": _pct(finished, semolina_poured),
            "downtime_minutes": sum(s["minutes"] for s in stops),
            "report_count": len(facts),
        }

    def get_day(self, *, tenant_id: str, date: datetime.date) -> dict:
        facts = self._report_facts(tenant_id, date, date)
        stops = self._stop_rows(tenant_id, date, date)
        waste = self._waste_rows(tenant_id, date, date)
        semolina_by_product = self._semolina_by_product(tenant_id, date, date)
        packets = self._packets_by_of(tenant_id, date, date)

        previous_from, previous_to = previous_period(date, date)
        previous_facts = self._report_facts(tenant_id, previous_from, previous_to)
        previous_totals = (
            self._totals(previous_facts, self._stop_rows(tenant_id, previous_from, previous_to))
            if previous_facts
            else None
        )
        totals = self._totals(facts, stops)
        directions = {
            key: direction(totals[key], previous_totals[key] if previous_totals else None, decimals=decimals)
            if totals[key] is not None
            else None
            for key, decimals in (("semolina_poured", 1), ("finished_product", 1), ("yield_pct", 1), ("downtime_minutes", 0))
        }

        of_ids = sorted({f["of_id"] for f in facts} | {s["of_id"] for s in stops} | {w["of_id"] for w in waste} | set(packets))
        details = self._of_details(tenant_id, of_ids)
        ofs = []
        for of_id in of_ids:
            of_facts = [f for f in facts if f["of_id"] == of_id]
            of_stops = [s for s in stops if s["of_id"] == of_id]
            poured = sum(f["semolina"] + f["regrind"] for f in of_facts)
            finished = sum(f["finished"] for f in of_facts)
            output: dict[tuple, float] = {}
            for f in of_facts:
                output[(f["shift"], f["team"])] = output.get((f["shift"], f["team"]), 0.0) + f["finished"]
            stop_by_key: dict[tuple, int] = {}
            for s in of_stops:
                stop_by_key[(s["motif"], s["team"])] = stop_by_key.get((s["motif"], s["team"]), 0) + s["minutes"]
            ofs.append(
                {
                    "of_id": of_id,
                    **details.get(of_id, {"reference": None, "product_type": None, "work_center_id": None}),
                    "semolina_poured": poured,
                    "regrind_input": sum(f["regrind"] for f in of_facts),
                    "finished_product": finished,
                    "yield_pct": _pct(finished, poured),
                    "production_minutes": sum(f["production_minutes"] for f in of_facts),
                    "downtime_minutes": sum(s["minutes"] for s in of_stops),
                    "waste_kg": sum(w["quantity"] for w in waste if w["of_id"] == of_id),
                    "packets_counted": packets.get(of_id),
                    "output_by_shift": [
                        {"shift": shift, "team": team, "finished_product": qty}
                        for (shift, team), qty in sorted(output.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
                    ],
                    "semolina_by_product": semolina_by_product.get(of_id, []),
                    "stops": [
                        {"motif": motif, "team": team, "minutes": minutes}
                        for (motif, team), minutes in sorted(stop_by_key.items(), key=lambda kv: -kv[1])
                    ],
                }
            )

        def collapse(rows: list[dict], name: str, value: str) -> list[dict]:
            """Drop the OF from the rows: the rankings cut by stage/motif, team and line."""
            merged: dict[tuple, float] = {}
            for row in rows:
                key = (row[name], row["team"], row["work_center_id"])
                merged[key] = merged.get(key, 0) + row[value]
            return [{name: k[0], "team": k[1], "work_center_id": k[2], "value": v} for k, v in merged.items()]

        return {
            "date": date.isoformat(),
            "previous_date": previous_from.isoformat(),
            "unit": self._semolina_unit(tenant_id, date, date),
            "awaiting_validation": self._awaiting_validation(tenant_id, date),
            "totals": totals,
            "previous_totals": previous_totals,
            "directions": directions,
            "ofs": ofs,
            "waste": collapse(waste, "category", "quantity"),
            "stops": collapse(stops, "motif", "minutes"),
        }

    # -- the trend -----------------------------------------------------------

    def get_trend(
        self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date, granularity: str
    ) -> dict:
        previous_from, previous_to = previous_period(date_from, date_to)
        configured = DashboardSettingsService(self._connection).list_shift_windows(tenant_id=tenant_id)
        windows = {w.shift.lower(): w for w in configured}

        def series(start: datetime.date, end: datetime.date) -> dict:
            facts = self._report_facts(tenant_id, start, end)
            totals: dict = {}
            for f in facts:
                key = f["shift"] if granularity == "shift" else _bucket(f["date"], granularity)
                bucket = totals.setdefault(key, {"semolina_poured": 0.0, "finished_product": 0.0})
                bucket["semolina_poured"] += f["semolina"] + f["regrind"]
                bucket["finished_product"] += f["finished"]
            return {"facts": facts, "totals": totals}

        current = series(date_from, date_to)
        previous = series(previous_from, previous_to)

        if granularity == "shift":
            seen = {k for k in (*current["totals"], *previous["totals"]) if k is not None}
            keys: list = sorted(seen, key=lambda s: (windows[s.lower()].start if s.lower() in windows else datetime.time.max, s))
            labels = list(keys)
            previous_keys, previous_labels = keys, labels
        else:
            keys = _bucket_keys(date_from, date_to, granularity)
            previous_keys = _bucket_keys(previous_from, previous_to, granularity)
            labels = [k.isoformat() for k in keys]
            previous_labels = [k.isoformat() for k in previous_keys]

        def points(source: dict, bucket_keys: list, bucket_labels: list) -> list[dict]:
            # A bucket nobody reported on is None, not 0: a missing day is not a
            # day that produced nothing, and drawing it as zero would fake a drop.
            return [
                {
                    "key": label,
                    "semolina_poured": source["totals"].get(key, {}).get("semolina_poured"),
                    "finished_product": source["totals"].get(key, {}).get("finished_product"),
                }
                for key, label in zip(bucket_keys, bucket_labels)
            ]

        return {
            "granularity": granularity,
            "unit": self._semolina_unit(tenant_id, min(date_from, previous_from), date_to),
            "current": {"from": date_from.isoformat(), "to": date_to.isoformat(), "points": points(current, keys, labels)},
            "previous": {
                "from": previous_from.isoformat(),
                "to": previous_to.isoformat(),
                "points": points(previous, previous_keys, previous_labels),
            },
        }

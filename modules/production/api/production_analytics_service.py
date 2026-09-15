from __future__ import annotations

import datetime

from modules.production.api.daily_recap_export import (
    fetch_period_rows,
    fill_unpriced_packaging_from_landed_cost,
    resolve_period,
    totals_from_rows,
)
from modules.procurement.api.service import PurchaseOrderService

# How many consecutive periods the trend charts cover, keyed by granularity --
# 30 days, 12 ISO weeks or 12 calendar months, always ending at the requested
# `date`'s own period. Chosen so a day-mode trend still reads as "this month
# so far and a bit," while week/month trends cover a full year-ish view.
_TREND_LENGTH = {"day": 30, "week": 12, "month": 12}

_PACKAGING_CATEGORIES = ("film", "carton", "scotch", "ruban")


def _has_unpriced_rows(rows: list[dict]) -> bool:
    """True when at least one row exists but couldn't be priced -- as opposed to no
    rows at all, which legitimately means zero cost for that component, not unknown
    cost. totals_from_rows collapses both cases to the same None, which is right for
    the export's "—" cell but not enough to decide whether variable_cost below is a
    real number or a fabricated one."""
    return any(not r["priced"] for r in rows)


def _trend_windows(period: str, anchor_date: str, count: int) -> list[tuple[str, str]]:
    """`count` consecutive (date_from, date_to) windows of the given
    granularity, oldest first, ending with the period that contains
    `anchor_date`. Steps backward one day past each window's start and
    re-resolves from there -- correct for day/week/month without separate
    calendar arithmetic for each."""
    windows: list[tuple[str, str]] = []
    cursor = anchor_date
    for _ in range(count):
        date_from, date_to, _, _ = resolve_period(period, cursor)
        windows.append((date_from, date_to))
        cursor = (datetime.date.fromisoformat(date_from) - datetime.timedelta(days=1)).isoformat()
    windows.reverse()
    return windows


def _trend_label(period: str, date_from: str) -> str:
    return date_from[:7] if period == "month" else date_from


def _cost_breakdown(mp_rows: list[dict], packaging_rows: list[dict]) -> list[dict]:
    """Cost of production's two components, split into the bar/pie chart's
    categories -- MP as one line, then each priced packaging category that
    actually has cost this period. Mirrors _totals_from_rows' own
    "film/carton/scotch/ruban count as emballage" grouping."""
    breakdown = []
    mp_cost = sum(r["cost"] for r in mp_rows if r["priced"])
    if mp_cost:
        breakdown.append({"category": "MP", "cost": mp_cost})
    for category in _PACKAGING_CATEGORIES:
        cost = sum(r["cost"] for r in packaging_rows if r["category"] == category and r["priced"])
        if cost:
            breakdown.append({"category": category.capitalize(), "cost": cost})
    return breakdown


def _period_point(connection, *, tenant_id: str, date_from: str, date_to: str, label: str, receipt_lines: list[dict]) -> dict:
    mp_rows, packaging_rows, finished_goods_rows = fetch_period_rows(
        connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to, receipt_lines=receipt_lines
    )
    packaging_rows = fill_unpriced_packaging_from_landed_cost(packaging_rows, receipt_lines)
    mp_cost, packaging_cost, tonnage, cartons, packets = totals_from_rows(mp_rows, packaging_rows, finished_goods_rows)
    # mp_cost/packaging_cost are None both when there's simply nothing of that kind this
    # period (a real zero) and when something exists but isn't priced yet (unknown, not
    # zero) -- totals_from_rows can't tell those apart. Re-check the rows directly so an
    # unpriced row makes variable_cost/cost_per_tonne None too, instead of silently
    # dropping that component to 0 and understating the total -- the same gap the export
    # shows as "—" (see totals_from_rows).
    packaging_costed = [r for r in packaging_rows if r["category"] in _PACKAGING_CATEGORIES]
    incomplete = _has_unpriced_rows(mp_rows) or _has_unpriced_rows(packaging_costed)
    variable_cost = None if incomplete else (mp_cost or 0.0) + (packaging_cost or 0.0)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "label": label,
        "tonnage": tonnage,
        "mp_cost": mp_cost,
        "packaging_cost": packaging_cost,
        "variable_cost": variable_cost,
        "cost_per_tonne": (variable_cost / tonnage) if (variable_cost is not None and tonnage) else None,
        "cartons": cartons,
        "packets": packets,
        "cost_breakdown": _cost_breakdown(mp_rows, packaging_rows),
    }


def build_analytics_payload(connection, *, tenant_id: str, period: str, date: str) -> dict:
    """Everything the always-on Production recap dashboard renders: the
    selected period's own numbers (`current`), a trailing trend of the same
    shape for the combo/histogram/scatter charts, and the purchase-cost
    anomalies worth flagging. Unlike build_daily_recap_workbook, this never
    includes fixed charges (Salaire, Amortissement, Impôts, ...) -- those
    stay hand-entered in the exported .xlsx only, since nothing in the
    database holds them yet (see build_charge_sheet). "variable_cost" /
    "cost_per_tonne" here means MP + emballage only; the export's "Coût de
    production" sheet is the one place the full, charges-included figure
    exists."""
    if period not in ("day", "week", "month"):
        raise ValueError(f"period must be one of 'day', 'week', 'month', got {period!r}")

    date_from, date_to, period_phrase, _period_days = resolve_period(period, date)
    receipt_lines = PurchaseOrderService(connection).list_confirmed_receipt_line_details(tenant_id=tenant_id)

    # _trend_windows' last window always ends on the requested date's own period (same
    # resolve_period call as date_from/date_to above), so `current` is always trend[-1] --
    # no separate fetch needed for it.
    windows = _trend_windows(period, date, _TREND_LENGTH[period])
    trend = [
        _period_point(
            connection, tenant_id=tenant_id, date_from=w_from, date_to=w_to,
            label=_trend_label(period, w_from), receipt_lines=receipt_lines,
        )
        for w_from, w_to in windows
    ]
    current = trend[-1]

    period_anomalies = [r for r in receipt_lines if r["is_cost_anomaly"] and date_from <= (r["invoice_date"] or "") <= date_to]
    anomalies = period_anomalies or [r for r in receipt_lines if r["is_cost_anomaly"]]
    anomalies = sorted(anomalies, key=lambda r: -(r["cost_deviation_pct"] or 0))[:20]

    return {
        "period": period,
        "period_phrase": period_phrase,
        "date_from": date_from,
        "date_to": date_to,
        "current": current,
        "trend": trend,
        "anomalies": anomalies,
    }

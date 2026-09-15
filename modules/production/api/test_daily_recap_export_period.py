"""Unit tests for week/month period resolution and the per-day breakdown
shape in the daily recap workbook -- no DB needed, these are pure functions
of their inputs. See test_daily_recap_export_integration.py for the
real-data, single-day path these build on.
"""
from __future__ import annotations

import io

import openpyxl
import pytest

from modules.production.api.daily_recap_export import build_daily_recap_workbook, resolve_period


def test_day_period_is_just_the_one_date():
    assert resolve_period("day", "2026-09-10") == ("2026-09-10", "2026-09-10", "la journée du 10 septembre 2026", 1)


def test_week_period_is_the_iso_week_monday_to_sunday():
    # 2026-09-10 is a Thursday.
    date_from, date_to, phrase, days = resolve_period("week", "2026-09-10")
    assert (date_from, date_to, days) == ("2026-09-07", "2026-09-13", 7)
    assert phrase == "la semaine du 7 au 13 septembre 2026"


def test_week_period_crossing_a_month_boundary_names_both_months():
    date_from, date_to, phrase, days = resolve_period("week", "2026-09-01")
    assert (date_from, date_to, days) == ("2026-08-31", "2026-09-06", 7)
    assert phrase == "la semaine du 31 août au 6 septembre 2026"


def test_month_period_is_the_full_calendar_month():
    date_from, date_to, phrase, days = resolve_period("month", "2026-09-10")
    assert (date_from, date_to, days) == ("2026-09-01", "2026-09-30", 30)
    assert phrase == "le mois de septembre 2026"

    # February in a non-leap year (2026) has 28 days.
    date_from, date_to, phrase, days = resolve_period("month", "2026-02-15")
    assert (date_from, date_to, days) == ("2026-02-01", "2026-02-28", 28)


def test_invalid_period_is_rejected():
    with pytest.raises(ValueError):
        resolve_period("fortnight", "2026-09-10")


def _empty_recap_kwargs(**overrides) -> dict:
    base = dict(
        period_phrase="le mois de septembre 2026", period_days=30,
        mp_rows=[], packaging_rows=[], finished_goods_rows=[], receipt_lines=[],
        mp_product_ids=set(), film_product_ids=set(), carton_product_ids=set(),
        product_names={}, supplier_names={},
    )
    base.update(overrides)
    return base


def test_month_workbook_gets_one_sheet_per_day_with_data_plus_a_scaled_period_total():
    daily_breakdowns = [
        {"date": "2026-09-04", "mp_rows": [], "packaging_rows": [], "finished_goods_rows": []},
        {"date": "2026-09-10", "mp_rows": [], "packaging_rows": [], "finished_goods_rows": []},
    ]
    content = build_daily_recap_workbook(**_empty_recap_kwargs(daily_breakdowns=daily_breakdowns))
    wb = openpyxl.load_workbook(io.BytesIO(content))

    assert "CP 2026-09-04" in wb.sheetnames
    assert "CP 2026-09-10" in wb.sheetnames

    # The period-total sheet scales the always-daily "Charge production"
    # quote-part by period_days (30) -- summing what each day's own sheet
    # would show, per "the recap contains the sum."
    period_total = wb["Coût de production"]
    assert period_total["B5"].value == "='Charge production'!C17*30"

    # Each day's own sheet references the same daily quote-part unscaled.
    day_sheet = wb["CP 2026-09-10"]
    assert day_sheet["B5"].value == "='Charge production'!C17"


def test_day_mode_still_has_no_multiplier_and_no_extra_sheets():
    content = build_daily_recap_workbook(**_empty_recap_kwargs(period_phrase="la journée du 10 septembre 2026", period_days=1))
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert not [name for name in wb.sheetnames if name.startswith("CP ")]
    assert wb["Coût de production"]["B5"].value == "='Charge production'!C17"

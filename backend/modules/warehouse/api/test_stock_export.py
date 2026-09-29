"""The stock workbook, built from plain rows -- no database."""
from __future__ import annotations

import datetime
import io

from openpyxl import load_workbook

from modules.warehouse.api.stock_export import ProductValue, StockExportLine, build_stock_workbook

AS_OF = datetime.datetime(2026, 9, 29, 8, 30)


def _line(location_code, *, on_hand, reserved=0.0, blocked=False, sku="SPAG", product="Spaghetti"):
    return StockExportLine(
        site="Main", location_code=location_code, location=location_code, blocked=blocked, sku=sku, product=product,
        unit="ctn", on_hand=on_hand, reserved=reserved, in_production=0.0,
    )


def _sheets(content: bytes):
    wb = load_workbook(io.BytesIO(content))
    return wb["Stock par emplacement"], wb["Stock par produit"]


def test_quarantined_stock_is_never_available():
    content = build_stock_workbook(
        [_line("A1", on_hand=10, reserved=4), _line("Q1", on_hand=5, blocked=True)],
        as_of=AS_OF, site_label="Main", values_by_sku=None,
    )
    by_location, by_product = _sheets(content)
    assert [by_location.cell(row=r, column=10).value for r in (3, 4)] == [6, 0]
    # Per product: 15 on hand, of which 5 quarantined, 6 available.
    assert [by_product.cell(row=3, column=c).value for c in (4, 5, 7)] == [15, 5, 6]


def test_value_columns_only_appear_with_valuation_access():
    lines = [_line("A1", on_hand=10)]
    _, without = _sheets(build_stock_workbook(lines, as_of=AS_OF, site_label="Main", values_by_sku=None))
    assert without.max_column == 8
    _, with_value = _sheets(
        build_stock_workbook(
            lines, as_of=AS_OF, site_label="Main",
            values_by_sku={"SPAG": ProductValue(value=12000, unvalued_quantity=0, average_unit_cost=1200)},
        )
    )
    assert with_value.cell(row=3, column=10).value == 12000
    assert with_value.cell(row=4, column=10).value == 12000  # grand total

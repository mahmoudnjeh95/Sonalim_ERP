"""The stock table as an .xlsx workbook -- for the monthly count and the
auditor, who want the figures in a spreadsheet rather than on a screen.

Two sheets: stock per location (every bucket), then per product across the
plant. The second one carries FIFO value columns only when the caller may see
valuation -- stock value is financial information, and the export must not
become a side door around warehouse.view_valuation.
"""
from __future__ import annotations

import datetime
import io
from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Same house style as the production report workbooks, kept local so the
# warehouse module doesn't import another module's internal helpers.
_TITLE_FILL = PatternFill("solid", fgColor="A6A6A6")
_HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
_BOLD = Font(bold=True)
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_QUANTITY_FORMAT = "#,##0.###"
_MONEY_FORMAT = "#,##0"


@dataclass(frozen=True)
class StockExportLine:
    site: str
    location_code: str
    location: str
    blocked: bool
    sku: str
    product: str
    unit: str
    on_hand: float
    reserved: float
    in_production: float

    @property
    def available(self) -> float:
        # Same rule as StockService.get_available_quantity: quarantine promises nothing.
        return 0.0 if self.blocked else self.on_hand - self.reserved


@dataclass(frozen=True)
class ProductValue:
    value: float
    unvalued_quantity: float
    average_unit_cost: float | None


def _title(ws, span: int, text: str) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    cell = ws.cell(row=1, column=1, value=text)
    cell.font = Font(bold=True, size=12)
    cell.alignment = _CENTER
    for col in range(1, span + 1):
        ws.cell(row=1, column=col).fill = _TITLE_FILL


def _header(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = _BOLD
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = _CENTER


def _row(ws, row: int, values: list, *, quantity_cols: set[int], money_cols: set[int] = frozenset(), bold: bool = False) -> None:
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.border = _BORDER
        if bold:
            cell.font = _BOLD
            cell.fill = _HEADER_FILL
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if col in money_cols:
                cell.number_format = _MONEY_FORMAT
            elif col in quantity_cols:
                cell.number_format = _QUANTITY_FORMAT


def _widths(ws, widths: list[int]) -> None:
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width


def build_stock_workbook(
    lines: list[StockExportLine],
    *,
    as_of: datetime.datetime,
    site_label: str,
    values_by_sku: dict[str, ProductValue] | None,
) -> bytes:
    wb = Workbook()
    stamp = as_of.strftime("%d/%m/%Y %H:%M")

    by_location = wb.active
    by_location.title = "Stock par emplacement"
    headers = ["Site", "Code empl.", "Emplacement", "Quarantaine", "SKU", "Produit", "Unité",
               "En stock", "Réservé", "Disponible", "En production"]
    _title(by_location, len(headers), f"Stock par emplacement — {site_label} — {stamp}")
    _header(by_location, 2, headers)
    quantity_cols = {8, 9, 10, 11}
    ordered = sorted(lines, key=lambda l: (l.site, l.location_code, l.product))
    for index, line in enumerate(ordered, start=3):
        _row(
            by_location, index,
            [line.site, line.location_code, line.location, "Oui" if line.blocked else "", line.sku, line.product, line.unit,
             line.on_hand, line.reserved, line.available, line.in_production],
            quantity_cols=quantity_cols,
        )
    by_location.freeze_panes = "A3"
    _widths(by_location, [16, 14, 24, 12, 16, 32, 8, 12, 12, 12, 14])

    by_product = wb.create_sheet("Stock par produit")
    product_headers = ["SKU", "Produit", "Unité", "En stock", "dont quarantaine", "Réservé", "Disponible", "En production"]
    if values_by_sku is not None:
        product_headers += ["Coût moyen PEPS (F CFA)", "Valeur PEPS (F CFA)", "Qté non valorisée"]
    _title(by_product, len(product_headers), f"Stock par produit — {site_label} — {stamp}")
    _header(by_product, 2, product_headers)

    totals: dict[str, dict] = {}
    for line in lines:
        entry = totals.setdefault(line.sku, {"product": line.product, "unit": line.unit, "on_hand": 0.0, "blocked": 0.0,
                                             "reserved": 0.0, "available": 0.0, "in_production": 0.0})
        entry["on_hand"] += line.on_hand
        entry["blocked"] += line.on_hand if line.blocked else 0.0
        entry["reserved"] += line.reserved
        entry["available"] += line.available
        entry["in_production"] += line.in_production

    grand_value = 0.0
    row = 3
    for sku in sorted(totals, key=lambda s: totals[s]["product"]):
        entry = totals[sku]
        values = [sku, entry["product"], entry["unit"], entry["on_hand"], entry["blocked"], entry["reserved"],
                  entry["available"], entry["in_production"]]
        if values_by_sku is not None:
            product_value = values_by_sku.get(sku)
            values += [
                product_value.average_unit_cost if product_value else None,
                product_value.value if product_value else 0,
                product_value.unvalued_quantity if product_value else 0,
            ]
            grand_value += product_value.value if product_value else 0
        _row(by_product, row, values, quantity_cols={4, 5, 6, 7, 8, 11}, money_cols={9, 10})
        row += 1
    if values_by_sku is not None:
        total = ["Total", "", "", None, None, None, None, None, None, grand_value, None]
        _row(by_product, row, total, quantity_cols=set(), money_cols={10}, bold=True)
    by_product.freeze_panes = "A3"
    _widths(by_product, [16, 32, 8, 12, 14, 12, 12, 14, 18, 18, 16])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

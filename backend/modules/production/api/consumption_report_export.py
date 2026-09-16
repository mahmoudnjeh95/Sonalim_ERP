from __future__ import annotations

import datetime
import io

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from modules.production.api.xlsx_report_style import (
    autofit as _autofit,
    data_row as _data_row,
    header_row as _header_row,
    total_row as _total_row,
    HEADER_FILL as _HEADER_FILL,
    BOLD as _BOLD,
    CENTER as _CENTER,
    BORDER as _BORDER,
)
from modules.production.api.xlsx_report_style import title_row as _title_row

# Visual shape matches the plant's hand-built monthly sheets (Consommation
# Carton/Film/Rub&Scotch/Gasoil/Fuel): a merged gray title bar, a bold header
# row, data rows, a gray subtotal row per group and a grand total at the foot.
# One honest gap from the original: the plant's Carton/Film sheets subtotal by
# pasta shape ("SPAGETTI", "MACARONI") as well as PC/PL -- that grouping isn't
# data we have (conditionnement reports carry PC/PL via the OF's product_type,
# not a shape family), so subtotals here are by PC/PL only.
_MONTHS_FR = (
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
)


def _month_label(month_iso: str) -> str:
    d = datetime.date.fromisoformat(month_iso)
    return f"{_MONTHS_FR[d.month - 1]} {d.year}"


def _period_label(rows: list[dict]) -> str:
    """A phrase for the sheet titles below: 'le mois de X' (or 'les mois de X
    à Y' for a range spanning more than one). Combined with the fixed 'pour
    {phrase}' template each sheet builder uses -- see build_daily_recap_export.py
    for the day-scoped equivalent of this same phrase."""
    months = sorted({row["month"] for row in rows})
    if not months:
        return "le mois de —"
    if len(months) == 1:
        return f"le mois de {_month_label(months[0])}"
    return f"les mois de {_month_label(months[0])} à {_month_label(months[-1])}"


def _designation(row: dict, product_names: dict[str, str]) -> str:
    return product_names.get(row["product_id"], "—") if row["product_id"] else "—"


def _supplier(row: dict, supplier_names: dict[str, str]) -> str:
    return supplier_names.get(row["supplier_id"], "—") if row["supplier_id"] else "—"


def _cost_cell(row: dict) -> object:
    return row["cost"] if row["priced"] else "—"


def _unit_price_cell(row: dict) -> object:
    return row["unit_price"] if row["priced"] else "—"


def build_packaging_sheet(
    wb: Workbook, sheet_title: str, category_rows: list[dict], *, period_phrase: str,
    product_names: dict[str, str], supplier_names: dict[str, str],
) -> None:
    """A Carton/Film-shaped consumption sheet, grouped and subtotaled by PC/PL.
    `period_phrase` is the pre-formatted French phrase completing "... pour
    {period_phrase}" -- e.g. "le mois de Juillet 2026" or "la journée du 10
    septembre 2026" -- so this builder stays period-agnostic; see
    consumption_report_export._period_label for the monthly phrase and
    daily_recap_export for the day-scoped one."""
    ws = wb.create_sheet(sheet_title)
    headers = ["Fournisseur", "Désignation", "PC/PL", "Qté utilisée", "Coût en CFA"]
    _title_row(ws, 1, len(headers), f"Consommation {sheet_title} pour {period_phrase}")
    row = 3
    _header_row(ws, row, headers)
    row += 1

    groups: dict[str, list[dict]] = {}
    for item in category_rows:
        groups.setdefault(item["pc_pl"] or "—", []).append(item)

    grand_qty = 0.0
    grand_cost = 0.0
    grand_priced = True
    for pc_pl in sorted(groups):
        group_rows = sorted(groups[pc_pl], key=lambda r: (_designation(r, product_names), _supplier(r, supplier_names)))
        subtotal_qty = 0.0
        subtotal_cost = 0.0
        subtotal_priced = True
        for item in group_rows:
            _data_row(
                ws, row,
                [_supplier(item, supplier_names), _designation(item, product_names), pc_pl, item["quantity"], _cost_cell(item)],
                money_cols={4, 5},
            )
            row += 1
            subtotal_qty += item["quantity"]
            if item["priced"]:
                subtotal_cost += item["cost"]
            else:
                subtotal_priced = False
        _total_row(
            ws, row, len(headers), f"Total {pc_pl}", 3,
            [subtotal_qty, subtotal_cost if subtotal_priced else "—"], money_cols={4, 5},
        )
        row += 1
        grand_qty += subtotal_qty
        grand_cost += subtotal_cost
        grand_priced = grand_priced and subtotal_priced

    _total_row(ws, row, len(headers), "Total", 3, [grand_qty, grand_cost if grand_priced else "—"], money_cols={4, 5})
    _autofit(ws, [22, 32, 8, 14, 16])


def build_rub_scotch_sheet(
    wb: Workbook, rows: list[dict], *, period_phrase: str,
    product_names: dict[str, str], supplier_names: dict[str, str],
) -> None:
    ws = wb.create_sheet("Rub&Scotch")
    headers = ["Fournisseur", "Qté (Pièce)", "Prix unitaire (CFA)", "Prix total (CFA)"]
    _title_row(ws, 1, len(headers), f"Consommation Rub&Scotch pour {period_phrase}")
    row = 3

    scotch_rows = [r for r in rows if r["category"] == "scotch"]
    ruban_by_product: dict[str, list[dict]] = {}
    for item in (r for r in rows if r["category"] == "ruban"):
        ruban_by_product.setdefault(_designation(item, product_names), []).append(item)

    sub_tables = [("SCOTCH", scotch_rows)] + [
        (f"RUBAN IMPRIMANTE {name.upper()}", items) for name, items in sorted(ruban_by_product.items())
    ]

    for label, items in sub_tables:
        ws.cell(row=row, column=1, value=label).font = _BOLD
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(headers))
        ws.cell(row=row, column=1).alignment = _CENTER
        ws.cell(row=row, column=1).fill = _HEADER_FILL
        for col in range(1, len(headers) + 1):
            ws.cell(row=row, column=col).fill = _HEADER_FILL
        row += 1
        _header_row(ws, row, headers)
        row += 1
        total_qty = 0.0
        total_cost = 0.0
        priced = True
        for item in sorted(items, key=lambda r: _supplier(r, supplier_names)):
            _data_row(
                ws, row,
                [_supplier(item, supplier_names), item["quantity"], _unit_price_cell(item), _cost_cell(item)],
                money_cols={2, 3, 4},
            )
            row += 1
            total_qty += item["quantity"]
            if item["priced"]:
                total_cost += item["cost"]
            else:
                priced = False
        _total_row(ws, row, len(headers), "TOTAL", 1, [total_qty, "", total_cost if priced else "—"], money_cols={2, 4})
        row += 2

    _autofit(ws, [26, 14, 18, 16])


def build_fuel_sheet(
    wb: Workbook, sheet_title: str, rows: list[dict], *, category: str, period_phrase: str, supplier_names: dict[str, str],
) -> None:
    ws = wb.create_sheet(sheet_title)
    headers = ["Fourniseur", "Qté (L)", "Prix unitaire (CFA)", "Prix total (CFA)"]
    _title_row(ws, 1, len(headers), f"Consommation {sheet_title.upper()} pour {period_phrase}")
    row = 3
    _header_row(ws, row, headers)
    row += 1

    items = [r for r in rows if r["category"] == category]
    total_qty = 0.0
    total_cost = 0.0
    priced = True
    for item in sorted(items, key=lambda r: _supplier(r, supplier_names)):
        _data_row(
            ws, row,
            [_supplier(item, supplier_names), item["quantity"], _unit_price_cell(item), _cost_cell(item)],
            money_cols={2, 3, 4},
        )
        row += 1
        total_qty += item["quantity"]
        if item["priced"]:
            total_cost += item["cost"]
        else:
            priced = False

    _total_row(ws, row, len(headers), "TOTAL", 1, [total_qty, "", total_cost if priced else "—"], money_cols={2, 4})
    _autofit(ws, [22, 12, 18, 16])


def build_consumption_workbook(rows: list[dict], *, product_names: dict[str, str], supplier_names: dict[str, str]) -> bytes:
    """One workbook, one sheet per consumable, laid out like the spreadsheets
    this report replaces. `rows` is exactly what
    ConsumptionReportService.list_monthly_consumption_by_supplier returns;
    `product_names`/`supplier_names` resolve the ids it carries into the
    names a spreadsheet reader actually needs (see the no-raw-ids-in-UI rule
    this project applies to screens -- an exported file is no different)."""
    wb = Workbook()
    wb.remove(wb.active)
    period_phrase = _period_label(rows)

    build_packaging_sheet(
        wb, "Carton", [r for r in rows if r["category"] == "carton"],
        period_phrase=period_phrase, product_names=product_names, supplier_names=supplier_names,
    )
    build_packaging_sheet(
        wb, "Film", [r for r in rows if r["category"] == "film"],
        period_phrase=period_phrase, product_names=product_names, supplier_names=supplier_names,
    )
    build_rub_scotch_sheet(wb, rows, period_phrase=period_phrase, product_names=product_names, supplier_names=supplier_names)
    build_fuel_sheet(wb, "Gasoil", rows, category="gasoil", period_phrase=period_phrase, supplier_names=supplier_names)
    build_fuel_sheet(wb, "Fuel", rows, category="fuel", period_phrase=period_phrase, supplier_names=supplier_names)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

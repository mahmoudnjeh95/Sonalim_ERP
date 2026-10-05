from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# Shared house style for every generated report workbook: a merged gray title
# bar, a bold header row, data rows, a gray subtotal row per group and a grand
# total at the foot. Originally built for consumption_report_export.py's
# monthly sheets (matching the plant's hand-built Consommation Carton/Film/
# Rub&Scotch/Gasoil/Fuel spreadsheets); factored out here once the daily recap
# export needed the same visual language for its own sheets.
TITLE_FILL = PatternFill("solid", fgColor="A6A6A6")
SUBTOTAL_FILL = PatternFill("solid", fgColor="D9D9D9")
HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
TITLE_FONT = Font(bold=True, size=12)
HEADER_FONT = Font(bold=True)
BOLD = Font(bold=True)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")


# Excel and LibreOffice read a cell whose text starts with one of these as a formula, so an
# exported product name, motif or note typed as "=1+1" -- or something far worse -- would run
# on whoever opens the file. Guarded here, once, for every report built on these helpers.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value):
    """A cell's value, with text a user typed kept as text. The leading apostrophe is the
    spreadsheet's own "this is literal" marker: it is not shown in the cell and is dropped
    on copy. Numbers, dates and None are returned untouched."""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return f"'{value}"
    return value


def title_row(ws: Worksheet, row: int, span: int, text: str) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=safe_text(text))
    cell.font = TITLE_FONT
    cell.fill = TITLE_FILL
    cell.alignment = CENTER
    for col in range(1, span + 1):
        ws.cell(row=row, column=col).fill = TITLE_FILL


def header_row(ws: Worksheet, row: int, headers: list[str]) -> None:
    for col, label in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=safe_text(label))
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = BORDER
        cell.alignment = CENTER


def data_row(ws: Worksheet, row: int, values: list, *, money_cols: set[int] = frozenset()) -> None:
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=safe_text(value))
        cell.border = BORDER
        if col in money_cols and isinstance(value, (int, float)):
            cell.number_format = "#,##0"


def total_row(ws: Worksheet, row: int, span: int, label: str, label_span: int, values: list, *, money_cols: set[int]) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=label_span)
    label_cell = ws.cell(row=row, column=1, value=safe_text(label))
    label_cell.font = BOLD
    label_cell.fill = SUBTOTAL_FILL
    label_cell.alignment = CENTER
    for col in range(1, label_span + 1):
        ws.cell(row=row, column=col).fill = SUBTOTAL_FILL
        ws.cell(row=row, column=col).border = BORDER
    for offset, value in enumerate(values):
        col = label_span + 1 + offset
        cell = ws.cell(row=row, column=col, value=safe_text(value))
        cell.font = BOLD
        cell.fill = SUBTOTAL_FILL
        cell.border = BORDER
        if col in money_cols and isinstance(value, (int, float)):
            cell.number_format = "#,##0"
    for col in range(label_span + 1 + len(values), span + 1):
        ws.cell(row=row, column=col).fill = SUBTOTAL_FILL
        ws.cell(row=row, column=col).border = BORDER


def autofit(ws: Worksheet, widths: list[int]) -> None:
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

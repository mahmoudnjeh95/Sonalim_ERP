"""Every generated workbook writes text a user typed -- a product name, a motif, a note.

Excel and LibreOffice treat a cell whose text starts with = + - @ as a formula, so an
export is a way to run something on whoever opens the file. The shared row helpers are
where that is stopped, once, for every report built on them.
"""
from __future__ import annotations

import pytest
from openpyxl import Workbook

from modules.production.api.xlsx_report_style import data_row, header_row, title_row, total_row

DANGEROUS = ["=1+1", "+34", "-7", "@SUM(A1)", '=HYPERLINK("http://x","clic")']


@pytest.mark.parametrize("text", DANGEROUS)
def test_a_data_cell_keeps_dangerous_text_as_text(text):
    ws = Workbook().active

    data_row(ws, 1, [text, 42])

    assert ws.cell(row=1, column=1).value == f"'{text}"
    assert ws.cell(row=1, column=1).data_type == "s"
    # Numbers are ours, not the user's: they stay numbers.
    assert ws.cell(row=1, column=2).value == 42


@pytest.mark.parametrize("text", DANGEROUS)
def test_titles_headers_and_totals_are_guarded_too(text):
    ws = Workbook().active

    title_row(ws, 1, 3, text)
    header_row(ws, 2, [text, "Quantité"])
    total_row(ws, 3, 3, text, 1, [7], money_cols=set())

    assert ws.cell(row=1, column=1).value == f"'{text}"
    assert ws.cell(row=2, column=1).value == f"'{text}"
    assert ws.cell(row=3, column=1).value == f"'{text}"
    assert ws.cell(row=2, column=2).value == "Quantité"


def test_ordinary_text_numbers_and_blanks_are_untouched():
    ws = Workbook().active

    data_row(ws, 1, ["Semoule fine", 12.5, None, "Ligne 1 - PL"])

    assert [ws.cell(row=1, column=c).value for c in range(1, 5)] == ["Semoule fine", 12.5, None, "Ligne 1 - PL"]


def test_a_dash_inside_the_text_is_not_the_problem():
    """Only a leading = + - @ makes a formula; "Ligne 1 - PL" is ordinary text."""
    ws = Workbook().active

    data_row(ws, 1, ["Rupture - manque de cartons"])

    assert ws.cell(row=1, column=1).value == "Rupture - manque de cartons"

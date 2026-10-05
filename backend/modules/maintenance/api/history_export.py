"""The maintenance journal as an Excel workbook, in the house style of the production recaps."""
from __future__ import annotations

import datetime
import io

from openpyxl import Workbook

from modules.production.api.xlsx_report_style import autofit, data_row, header_row, title_row, total_row

_TEXT = {
    "fr": {
        "sheet": "Journal",
        "title": "Journal des interventions de maintenance — {from_} → {to}",
        "headers": ["N°", "Clôturée le", "Machine", "Type", "Intervention", "Techniciens", "Temps (min)",
                    "OK", "Anomalies", "Non faits", "Pièces sorties (lignes)", "Pièces commandées (lignes)"],
        "cost": "Coût (XOF)",
        "kind": {"preventive": "Préventive", "corrective": "Corrective"},
        "total": "Total",
    },
    "en": {
        "sheet": "Journal",
        "title": "Maintenance journal — {from_} → {to}",
        "headers": ["No.", "Closed on", "Machine", "Type", "Intervention", "Technicians", "Time (min)",
                    "OK", "Issues", "Not done", "Parts issued (lines)", "Parts ordered (lines)"],
        "cost": "Cost (XOF)",
        "kind": {"preventive": "Preventive", "corrective": "Corrective"},
        "total": "Total",
    },
}


def journal_workbook(journal: dict, *, lang: str) -> bytes:
    text = _TEXT.get(lang, _TEXT["fr"])
    headers = list(text["headers"]) + ([text["cost"]] if journal["costs_visible"] else [])
    span = len(headers)
    money_cols = {span} if journal["costs_visible"] else set()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = text["sheet"]
    title_row(sheet, 1, span, text["title"].format(from_=journal["from"], to=journal["to"]))
    header_row(sheet, 2, headers)
    row_number = 3
    total_minutes = 0
    total_cost = 0.0
    for row in journal["rows"]:
        minutes = (row["technician_seconds"] + 30) // 60
        total_minutes += minutes
        values = [
            row["number"],
            datetime.date.fromisoformat(row["date"][:10]) if row["date"] else None,
            f"{row['equipment_code']} — {row['equipment_name']}",
            text["kind"][row["kind"]],
            row["title"],
            ", ".join(person["name"] for person in row["performers"]),
            minutes,
            row["outcomes"]["ok"],
            row["outcomes"]["issue"],
            row["outcomes"]["not_done"],
            row["parts"]["issued_lines"],
            row["parts"]["purchase_lines"],
        ]
        if journal["costs_visible"]:
            values.append(row["parts_cost"] or 0)
            total_cost += row["parts_cost"] or 0
        data_row(sheet, row_number, values, money_cols=money_cols)
        sheet.cell(row=row_number, column=2).number_format = "dd/mm/yyyy"
        row_number += 1
    totals: list = [total_minutes, None, None, None, None, None]
    if journal["costs_visible"]:
        totals.append(total_cost)
    total_row(sheet, row_number, span, text["total"], 6, totals, money_cols=money_cols)
    autofit(sheet, [14, 12, 28, 12, 34, 30, 11, 6, 10, 10, 14, 16, 14][:span])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from fastapi import Response
from openpyxl import Workbook


def tabular_response(headers: list[str], rows: list[list[Any]], fmt: str, filename: str) -> Response:
    """CSV or XLSX download of a flat report. Decimals are written as numbers, not text; the CSV
    carries a BOM so Excel opens accented French labels correctly."""
    if fmt == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append([float(c) if isinstance(c, Decimal) else c for c in row])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return Response(
            buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )

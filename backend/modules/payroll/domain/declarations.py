"""Monthly declarations from payslip lines, and the annual recap.

A declaration code comes from the rule set: a contribution's declaration_code (e.g. INPS, AMO), a
tax code (e.g. ITS), or EMPLOYER_TAXES for every employer charge. The payslips of one employee in
the month (regular + off-cycle) add up into one row.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

EMPLOYER_TAXES = "EMPLOYER_TAXES"
_CONTRIBUTIONS = ("employee_contribution", "employer_contribution")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Declaration:
    code: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    totals: dict[str, Decimal]


def available_codes(payslips: Sequence[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()
    for payslip in payslips:
        for line in payslip["lines"]:
            if line["section"] in _CONTRIBUTIONS and line["declaration_code"]:
                codes.add(line["declaration_code"])
            elif line["section"] == "tax":
                codes.add(line["code"])
            elif line["section"] == "employer_charge":
                codes.add(EMPLOYER_TAXES)
    return sorted(codes)


def _by_employee(payslips: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for payslip in payslips:
        grouped.setdefault(payslip["employee_id"], []).append(payslip)
    return sorted(grouped.values(), key=lambda group: group[0]["employee_no"])


def _start(group: list[dict[str, Any]]) -> dict[str, Any]:
    return {"employee_no": group[0]["employee_no"], "full_name": group[0]["full_name"]}


def _totals(columns: tuple[str, ...], rows: list[dict[str, Any]], first_numeric: int) -> dict[str, Decimal]:
    return {column: sum((row[column] for row in rows), ZERO) for column in columns[first_numeric:]}


def _sum(lines: list[dict[str, Any]], **match: Any) -> Decimal:
    return sum((line["amount"] for line in lines if all(line[key] == value for key, value in match.items())), ZERO)


def _contribution(code: str, payslips: Sequence[dict[str, Any]]) -> Declaration:
    def matching(payslip: dict[str, Any]) -> list[dict[str, Any]]:
        return [line for line in payslip["lines"] if line["section"] in _CONTRIBUTIONS and line["declaration_code"] == code]

    codes = sorted({line["code"] for payslip in payslips for line in matching(payslip)})
    columns = ("employee_no", "full_name", "identifier", "base",
               *[f"{item}_employee" for item in codes], *[f"{item}_employer" for item in codes], "total")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        chunks = [matching(payslip) for payslip in group]
        lines = [line for chunk in chunks for line in chunk]
        if not lines:
            continue
        identifiers = group[0].get("identifiers") or {}
        # the contributable salary before ceilings: the highest base of the group, per payslip
        row = {**_start(group), "identifier": identifiers.get(f"{code.lower()}_no") or "",
               "base": sum((max(line["base"] or ZERO for line in chunk) for chunk in chunks if chunk), ZERO)}
        for item in codes:
            row[f"{item}_employee"] = _sum(lines, code=item, section="employee_contribution")
            row[f"{item}_employer"] = _sum(lines, code=item, section="employer_contribution")
        row["total"] = sum((line["amount"] for line in lines), ZERO)
        rows.append(row)
    return Declaration(code=code, columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 3))


def _tax(code: str, payslips: Sequence[dict[str, Any]]) -> Declaration:
    columns = ("employee_no", "full_name", "taxable", "amount")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        lines = [line for payslip in group for line in payslip["lines"] if line["section"] == "tax" and line["code"] == code]
        if lines:
            rows.append({**_start(group), "taxable": sum((line["base"] or ZERO for line in lines), ZERO),
                         "amount": sum((line["amount"] for line in lines), ZERO)})
    return Declaration(code=code, columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 2))


def _employer_taxes(payslips: Sequence[dict[str, Any]]) -> Declaration:
    codes = sorted({line["code"] for payslip in payslips for line in payslip["lines"] if line["section"] == "employer_charge"})
    columns = ("employee_no", "full_name", "gross", *codes, "total")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        lines = [line for payslip in group for line in payslip["lines"] if line["section"] == "employer_charge"]
        if not lines:
            continue
        row = {**_start(group), "gross": sum((payslip["gross"] for payslip in group), ZERO)}
        for item in codes:
            row[item] = _sum(lines, code=item)
        row["total"] = sum((line["amount"] for line in lines), ZERO)
        rows.append(row)
    return Declaration(code=EMPLOYER_TAXES, columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 2))


def build_declaration(code: str, payslips: Sequence[dict[str, Any]]) -> Declaration | None:
    if code not in available_codes(payslips):
        return None
    if code == EMPLOYER_TAXES:
        return _employer_taxes(payslips)
    is_tax = any(line["section"] == "tax" and line["code"] == code for payslip in payslips for line in payslip["lines"])
    return _tax(code, payslips) if is_tax else _contribution(code, payslips)


def annual_recap(payslips: Sequence[dict[str, Any]]) -> Declaration:
    columns = ("employee_no", "full_name", "months", "gross", "employee_contrib", "employer_contrib", "its", "net")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        row = {**_start(group), "months": len({payslip["period"] for payslip in group})}
        for column in columns[3:]:
            row[column] = sum((payslip[column] for payslip in group), ZERO)
        rows.append(row)
    return Declaration(code="ANNUAL", columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 3))


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(int(value)) if value == value.to_integral_value() else str(value)
    return str(value)


def to_csv(declaration: Declaration) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(declaration.columns)
    for row in declaration.rows:
        writer.writerow([_cell(row[column]) for column in declaration.columns])
    writer.writerow(["TOTAL" if index == 0 else _cell(declaration.totals.get(column, "")) if column in declaration.totals else ""
                     for index, column in enumerate(declaration.columns)])
    return buffer.getvalue()

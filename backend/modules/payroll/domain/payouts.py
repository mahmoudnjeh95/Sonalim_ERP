"""Paying the net: split by payment method, cash note-and-coin count, bank and mobile-money files."""
from __future__ import annotations

import csv
import datetime
import io
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from core.domain.result import Err, Ok, Result

# Notes and coins the BCEAO issues for the franc CFA (XOF) — a fact of the currency, not a payroll
# rule. 500 exists as a note and as a coin and is counted once.
XOF_DENOMINATIONS = (10000, 5000, 2000, 1000, 500, 250, 200, 100, 50, 25, 10, 5, 1)
METHODS = ("bank", "mobile_money", "cash")
BANK_TEMPLATE_FIELDS = ("employee_no", "full_name", "bank_name", "account_no", "amount", "period", "reference")
DELIMITERS = (";", ",", "\t", "|")
MOBILE_HEADER = ("operator", "number", "name", "amount")
_DETAIL_KEYS = ("bank_name", "account_no", "mobile_operator", "mobile_number")


@dataclass(frozen=True)
class PayoutShare:
    method: str
    group_key: str
    amount: Decimal
    details: dict[str, Any]


def _split_error(english: str, french: str) -> Err:
    return Err("PAYOUT_SPLIT_INVALID", english, french)


def validate_methods(methods: list[dict[str, Any]]) -> Result[list[dict[str, Any]]]:
    if not methods:
        return _split_error("no payment method", "aucun moyen de paiement")
    clean: list[dict[str, Any]] = []
    total = Decimal(0)
    for raw in methods:
        method = raw.get("method")
        if method not in METHODS:
            return _split_error(f"unknown payment method {method}", f"moyen de paiement inconnu {method}")
        share = Decimal(str(raw.get("share_percent") or 0))
        if share <= 0:
            return _split_error("each share is above 0 %", "chaque part est supérieure à 0 %")
        if method == "bank" and not (raw.get("bank_name") and raw.get("account_no")):
            return _split_error("a bank payment needs the bank and the account number",
                                "un virement demande la banque et le numéro de compte")
        if method == "mobile_money" and not (raw.get("mobile_operator") and raw.get("mobile_number")):
            return _split_error("a mobile-money payment needs the operator and the number",
                                "un paiement mobile demande l'opérateur et le numéro")
        total += share
        clean.append({"method": method, **{key: raw.get(key) for key in _DETAIL_KEYS},
                      "share_percent": share, "is_primary": bool(raw.get("is_primary"))})
    if total != 100:
        return _split_error(f"shares add up to {total} %, not 100 %", f"les parts totalisent {total} %, pas 100 %")
    return Ok(clean)


def group_key(method: dict[str, Any]) -> str:
    if method["method"] == "bank":
        return str(method["bank_name"]).strip().upper()
    if method["method"] == "mobile_money":
        return str(method["mobile_operator"]).strip().upper()
    return "CASH"


def split_net(net: Decimal, methods: list[dict[str, Any]]) -> Result[list[PayoutShare]]:
    checked = validate_methods(methods)
    if isinstance(checked, Err):
        return checked
    ordered = sorted(checked.value, key=lambda method: method["is_primary"])  # the primary (else the last) goes last
    shares: list[PayoutShare] = []
    paid = Decimal(0)
    for index, method in enumerate(ordered):
        if index == len(ordered) - 1:
            amount = net - paid
        else:
            amount = (net * method["share_percent"] / 100).to_integral_value(rounding=ROUND_DOWN)
            paid += amount
        if amount > 0:
            shares.append(PayoutShare(method=method["method"], group_key=group_key(method), amount=amount,
                                      details={key: method[key] for key in _DETAIL_KEYS}))
    return Ok(shares)


def billetage(amount: Decimal, denominations: tuple[int, ...] = XOF_DENOMINATIONS) -> tuple[dict[int, int], Decimal]:
    left = amount
    counts: dict[int, int] = {}
    for value in denominations:
        count = int(left // value)
        counts[value] = count
        left -= count * value
    return counts, left


def _writer(delimiter: str) -> tuple[io.StringIO, Any]:
    buffer = io.StringIO()
    return buffer, csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")


def render_bank_csv(template: dict[str, Any], lines: list[dict[str, Any]], period: datetime.date) -> str:
    buffer, writer = _writer(template["delimiter"])
    if template["include_header"]:
        writer.writerow([column["header"] for column in template["columns"]])
    for line in lines:
        details = line.get("details") or {}
        values = {
            "employee_no": line["employee_no"], "full_name": line["full_name"],
            "bank_name": details.get("bank_name") or "", "account_no": details.get("account_no") or "",
            "amount": str(int(line["amount"])), "period": f"{period:%Y-%m}",
            "reference": f"PAIE {period:%Y-%m} {line['employee_no']}",
        }
        writer.writerow([values[column["field"]] for column in template["columns"]])
    return buffer.getvalue()


def render_mobile_csv(lines: list[dict[str, Any]]) -> str:
    buffer, writer = _writer(";")
    writer.writerow(MOBILE_HEADER)
    for line in lines:
        details = line.get("details") or {}
        writer.writerow([details.get("mobile_operator") or "", details.get("mobile_number") or "",
                         line["full_name"], str(int(line["amount"]))])
    return buffer.getvalue()


def _template_error(english: str, french: str) -> Err:
    return Err("TEMPLATE_INVALID", english, french)


def validate_bank_template(values: dict[str, Any]) -> Result[dict[str, Any]]:
    bank_name = str(values.get("bank_name") or "").strip().upper()
    if not bank_name:
        return _template_error("the bank name is required", "le nom de la banque est obligatoire")
    delimiter = values.get("delimiter") or ";"
    if delimiter not in DELIMITERS:
        return _template_error("the delimiter is ; , tab or |", "le séparateur est ; , tabulation ou |")
    include_header = values.get("include_header", True)
    if not isinstance(include_header, bool):
        return _template_error("include_header is true or false", "include_header vaut vrai ou faux")
    columns = values.get("columns")
    if not isinstance(columns, list) or not columns:
        return _template_error("a template needs at least one column", "un modèle demande au moins une colonne")
    clean: list[dict[str, str]] = []
    allowed = ", ".join(BANK_TEMPLATE_FIELDS)
    for column in columns:
        column = column if isinstance(column, dict) else {}
        header = str(column.get("header") or "").strip()
        field = column.get("field")
        if not header or field not in BANK_TEMPLATE_FIELDS:
            return _template_error(f"each column has a header and one of: {allowed}", f"chaque colonne a un en-tête et l'un de : {allowed}")
        clean.append({"header": header, "field": field})
    return Ok({"bank_name": bank_name, "delimiter": delimiter, "include_header": include_header, "columns": clean})

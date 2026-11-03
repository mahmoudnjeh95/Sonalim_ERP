from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# The manual's layout: DATE, LIBELLE, DEBIT, CREDIT, SOLDE with a header row. Banks differ, so the
# column names and formats are a profile that can be replaced per bank, not hard-coded parsing.
DEFAULT_PROFILE: dict[str, Any] = {
    "columns": {"date": "DATE", "label": "LIBELLE", "debit": "DEBIT", "credit": "CREDIT", "balance": "SOLDE"},
    "date_formats": ["%d-%b-%y", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"],
    "decimal_sep": ",",
    "has_header": True,
    "skip_rows": 0,
}

MONTHS_FR = {"janv": "Jan", "févr": "Feb", "fevr": "Feb", "mars": "Mar", "avr": "Apr", "mai": "May", "juin": "Jun",
             "juil": "Jul", "août": "Aug", "aout": "Aug", "sept": "Sep", "oct": "Oct", "nov": "Nov", "déc": "Dec", "dec": "Dec"}


@dataclass(frozen=True)
class StatementLine:
    row: int
    line_date: datetime.date
    label: str
    debit: Decimal
    credit: Decimal
    balance: Decimal | None


@dataclass
class ParseResult:
    lines: list[StatementLine] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def parse_amount(value: Any, decimal_sep: str = ",") -> Decimal:
    """Blank is zero. Accepts numbers from a spreadsheet and text such as '1 250,50' or '1,250.50'."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if decimal_sep == ",":
        text = text.replace(".", "") if text.count(",") == 1 and "." in text else text
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def parse_date(value: Any, formats: list[str]) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    lowered = text.lower()
    for fr, en in MONTHS_FR.items():
        if fr in lowered:
            lowered = lowered.replace(fr + ".", en).replace(fr, en)
            text = lowered.title()
            break
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {value!r}")


def parse_rows(rows: list[list[Any]], profile: dict[str, Any] | None = None) -> ParseResult:
    """Turn raw spreadsheet/CSV rows into statement lines. Row numbers in errors are 1-based file
    rows. A line with both debit and credit, or neither, is a format error, not a guess."""
    profile = {**DEFAULT_PROFILE, **(profile or {})}
    result = ParseResult()
    skip = int(profile.get("skip_rows", 0))
    body = rows[skip:]
    index_of: dict[str, int] = {}
    start = skip + 1
    if profile["has_header"]:
        if not body:
            result.errors.append({"row": skip + 1, "message": "empty file", "message_fr": "fichier vide"})
            return result
        header = [str(c).strip().upper() if c is not None else "" for c in body[0]]
        for key, name in profile["columns"].items():
            if name.upper() in header:
                index_of[key] = header.index(name.upper())
        body = body[1:]
        start += 1
        missing = [profile["columns"][k] for k in ("date", "label", "debit", "credit") if k not in index_of]
        if missing:
            result.errors.append({"row": skip + 1, "message": f"missing columns: {', '.join(missing)}",
                                  "message_fr": f"colonnes manquantes : {', '.join(missing)}"})
            return result
    else:
        index_of = {"date": 0, "label": 1, "debit": 2, "credit": 3, "balance": 4}

    for offset, raw in enumerate(body):
        row_number = start + offset
        if all(c is None or str(c).strip() == "" for c in raw):
            continue
        try:
            cell = lambda key: raw[index_of[key]] if key in index_of and index_of[key] < len(raw) else None  # noqa: E731
            line_date = parse_date(cell("date"), profile["date_formats"])
            debit = parse_amount(cell("debit"), profile["decimal_sep"])
            credit = parse_amount(cell("credit"), profile["decimal_sep"])
            balance_raw = cell("balance")
            balance = parse_amount(balance_raw, profile["decimal_sep"]) if balance_raw not in (None, "") else None
        except ValueError as exc:
            result.errors.append({"row": row_number, "message": str(exc), "message_fr": f"valeur invalide : {exc}"})
            continue
        if debit < 0 or credit < 0:
            result.errors.append({"row": row_number, "message": "amounts must not be negative",
                                  "message_fr": "les montants ne doivent pas être négatifs"})
            continue
        if any(value != value.to_integral_value() for value in (debit, credit, balance) if value is not None):
            result.errors.append({"row": row_number, "message": "amounts must be whole F CFA",
                                  "message_fr": "les montants doivent être des nombres entiers en F CFA"})
            continue
        if (debit > 0) == (credit > 0):
            result.errors.append({"row": row_number, "message": "a line needs exactly one of debit or credit",
                                  "message_fr": "une ligne doit avoir un débit ou un crédit, pas les deux ni aucun"})
            continue
        label = str(cell("label") or "").strip()
        result.lines.append(StatementLine(row_number, line_date, label, debit, credit, balance))

    previous: StatementLine | None = None
    for line in result.lines:
        if previous is not None and previous.balance is not None and line.balance is not None:
            # Debit is money in (customer), credit is money out (supplier), as in the manual.
            expected = previous.balance + line.debit - line.credit
            if expected != line.balance:
                result.warnings.append({
                    "row": line.row,
                    "message": f"balance {line.balance} does not follow the previous line (expected {expected})",
                    "message_fr": f"le solde {line.balance} ne suit pas la ligne précédente (attendu {expected})",
                })
        previous = line
    return result


def dedupe_key(line: StatementLine) -> tuple:
    return (line.line_date, line.label, line.debit, line.credit, line.balance)


def suggest_matches(lines: list[dict[str, Any]], payments: list[dict[str, Any]], window_days: int = 5) -> dict[str, str]:
    """line id -> payment id. A payment matches a line when the amount is equal and in the same
    direction and the dates are within the window; each payment is used at most once, nearest date first."""
    suggestions: dict[str, str] = {}
    used: set[str] = set()
    for line in sorted(lines, key=lambda l: l["line_date"]):
        direction = "in" if line["debit"] > 0 else "out"
        amount = line["debit"] if direction == "in" else line["credit"]
        candidates = [
            p for p in payments
            if p["id"] not in used and p["direction"] == direction and p["amount"] == amount
            and abs((p["date"] - line["line_date"]).days) <= window_days
        ]
        if candidates:
            best = min(candidates, key=lambda p: abs((p["date"] - line["line_date"]).days))
            suggestions[line["id"]] = best["id"]
            used.add(best["id"])
    return suggestions

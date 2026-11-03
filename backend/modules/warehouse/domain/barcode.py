from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from core.domain.result import Err, Ok, Result

BARCODE_TYPES = frozenset({"gtin", "internal"})
GTIN_LENGTHS = frozenset({8, 12, 13, 14})
GROUP_SEPARATOR = "\x1d"  # FNC1 as most scanners transmit it inside a GS1-128 read


@dataclass(frozen=True)
class ProductBarcode:
    id: str
    tenant_id: str
    product_id: str
    barcode: str
    barcode_type: str
    units_per_scan: float
    label: str | None
    created_by: str
    created_at: datetime.datetime


@dataclass(frozen=True)
class Gs1Data:
    """The application identifiers a warehouse actually uses off a GS1-128 label."""

    gtin: str | None = None
    sscc: str | None = None
    lot_number: str | None = None
    expiry_date: datetime.date | None = None
    count: int | None = None
    serial: str | None = None
    unknown: dict[str, str] = field(default_factory=dict)


def gtin_check_digit(body: str) -> int:
    """GS1 mod-10: weights 3,1,3,1... from the rightmost digit of the body."""
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def is_valid_gtin(code: str) -> bool:
    return code.isdigit() and len(code) in GTIN_LENGTHS and gtin_check_digit(code[:-1]) == int(code[-1])


def normalize_gtin(code: str) -> str:
    """Every GTIN length compares as GTIN-14, which is how a GS1-128 label
    carries it and how product_barcodes stores it."""
    return code.zfill(14)


def validate_barcode(*, barcode: str, barcode_type: str, units_per_scan: float) -> Result[str]:
    """Returns the value to store: a GTIN normalised to 14 digits, an internal
    code trimmed. A GTIN with a wrong check digit is refused outright -- it is
    almost always a typo, and a typo stored here would silently never match
    a real scan."""
    if barcode_type not in BARCODE_TYPES:
        return Err("INVALID_BARCODE_TYPE", f"unknown barcode type {barcode_type}", f"type de code-barres inconnu {barcode_type}")
    if units_per_scan <= 0:
        return Err("INVALID_QUANTITY", "units per scan must be positive", "les unités par scan doivent être positives")
    value = barcode.strip()
    if not value:
        return Err("INVALID_BARCODE", "barcode cannot be empty", "le code-barres ne peut pas être vide")
    if barcode_type == "gtin":
        if not is_valid_gtin(value):
            return Err(
                "INVALID_GTIN",
                f"{value} is not a valid GTIN-8/12/13/14 (length or check digit)",
                f"{value} n'est pas un GTIN-8/12/13/14 valide (longueur ou clé de contrôle)",
            )
        return Ok(normalize_gtin(value))
    return Ok(value)


# Fixed-length AIs this parser understands; everything else is variable
# length and ends at a group separator or the end of the read.
_FIXED_LENGTH_AIS = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
_VARIABLE_AIS = {"10", "21", "37"}
_PARENTHESISED = re.compile(r"\((\d{2,4})\)([^(]*)")


def _parse_yymmdd(value: str) -> datetime.date | None:
    """GS1 dates: YYMMDD, DD=00 meaning the last day of the month. The century
    is taken as 20YY -- GS1's sliding -49/+50 year window only matters for
    dates decades away, and a pasta best-before is months out."""
    if len(value) != 6 or not value.isdigit():
        return None
    year, month, day = 2000 + int(value[:2]), int(value[2:4]), int(value[4:6])
    if not 1 <= month <= 12:
        return None
    if day == 0:
        next_month = datetime.date(year + (month // 12), month % 12 + 1, 1)
        return next_month - datetime.timedelta(days=1)
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _pairs_from_raw(raw: str) -> list[tuple[str, str]] | None:
    pairs: list[tuple[str, str]] = []
    position = 0
    while position < len(raw):
        if raw[position] == GROUP_SEPARATOR:
            position += 1
            continue
        ai = raw[position:position + 2]
        if ai in _FIXED_LENGTH_AIS:
            length = _FIXED_LENGTH_AIS[ai]
            value = raw[position + 2:position + 2 + length]
            if len(value) != length:
                return None
            pairs.append((ai, value))
            position += 2 + length
        elif ai in _VARIABLE_AIS:
            end = raw.find(GROUP_SEPARATOR, position + 2)
            end = len(raw) if end == -1 else end
            pairs.append((ai, raw[position + 2:end]))
            position = end
        else:
            return None  # an AI this parser can't delimit -- not safe to guess
    return pairs


def looks_like_gs1(code: str) -> bool:
    return code.startswith(("(", "]C1", "]d2", "]Q3")) or GROUP_SEPARATOR in code


def parse_gs1(code: str) -> Gs1Data | None:
    """Parses the human-readable "(01)...(10)..." form or the raw scanner
    form (symbology prefix, FNC1 as GS). Returns None for anything that isn't
    well-formed GS1 -- the caller then treats the read as a plain code."""
    text = code.strip()
    for prefix in ("]C1", "]d2", "]Q3"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.startswith("("):
        pairs = [(ai, value) for ai, value in _PARENTHESISED.findall(text)]
        if not pairs or "".join(f"({ai}){value}" for ai, value in pairs) != text:
            return None
    else:
        parsed = _pairs_from_raw(text)
        if not parsed:
            return None
        pairs = parsed

    data: dict = {"unknown": {}}
    for ai, value in pairs:
        if ai in ("01", "02"):
            if not is_valid_gtin(value):
                return None
            data["gtin"] = value
        elif ai == "00":
            data["sscc"] = value
        elif ai == "10":
            data["lot_number"] = value
        elif ai == "17":
            data["expiry_date"] = _parse_yymmdd(value)
        elif ai == "37":
            if not value.isdigit():
                return None
            data["count"] = int(value)
        elif ai == "21":
            data["serial"] = value
        else:
            data["unknown"][ai] = value
    return Gs1Data(**data)

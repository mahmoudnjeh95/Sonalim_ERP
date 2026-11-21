"""Tax codes: a named VAT rate a tenant applies to sales and purchase lines. Pure rules, no database."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from core.domain.result import Err, Ok, Result

APPLIES_TO = ("sales", "purchase", "both")
SIDES = ("sales", "purchase")


@dataclass(frozen=True)
class TaxCodeInput:
    code: str
    name_fr: str
    name_en: str
    rate: Decimal
    applies_to: str
    exempt: bool


# The catalogue every tenant starts with: (code, French name, English name, rate, applies_to, exempt).
# TVA18 is Mali's standard rate; the first code is the default for both sides.
DEFAULT_CODES: tuple[tuple[str, str, str, Decimal, str, bool], ...] = (
    ("TVA18", "TVA 18 %", "VAT 18 %", Decimal("18"), "both", False),
    ("EXO", "Exonéré", "Exempt", Decimal("0"), "both", True),
)


def applies_to_side(applies_to: str, side: str) -> bool:
    return applies_to == "both" or applies_to == side


def validate(code: str, name_fr: str, name_en: str, rate: object, applies_to: str, exempt: bool) -> Result[TaxCodeInput]:
    code, name_fr = (code or "").strip().upper(), (name_fr or "").strip()
    name_en = (name_en or "").strip() or name_fr
    if not code or not name_fr:
        return Err("INVALID_TAX_CODE", "a tax code needs a code and a name", "un code de taxe a un code et un nom")
    try:
        value = Decimal(str(rate))
    except (InvalidOperation, ValueError):
        return Err("INVALID_TAX_RATE", "the rate must be a number", "le taux doit être un nombre")
    if not value.is_finite() or value < 0 or value > 100:
        return Err("INVALID_TAX_RATE", "the rate must be between 0 and 100", "le taux doit être compris entre 0 et 100")
    if applies_to not in APPLIES_TO:
        return Err("INVALID_TAX_CODE", "applies_to is sales, purchase or both", "applicable à : ventes, achats ou les deux")
    if exempt and value != 0:
        return Err("INVALID_TAX_CODE", "an exempt code has a rate of 0", "un code exonéré a un taux de 0")
    return Ok(TaxCodeInput(code, name_fr, name_en, value.quantize(Decimal("0.01")), applies_to, bool(exempt)))

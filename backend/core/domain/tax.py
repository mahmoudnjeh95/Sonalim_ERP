"""Tax codes: which VAT a line bears, and how a document's VAT splits across codes. Pure rules, no database.

A tax code is a tenant's name for a rate (TVA18 = 18 %) or an exemption (EXO = 0 %, with the legal mention
the invoice must carry). Lines keep both the code and the rate they were given, as snapshots: changing a
code later never changes a document already written.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from core.domain.result import Err, Ok, Result

ZERO = Decimal("0")
HUNDRED = Decimal("100")
SIDES = ("sales", "purchases")
SCOPES = ("sales", "purchases", "both")
CODE_MAX_LENGTH = 20

# The catalog every tenant starts with (Mali): (code, French name, English name, rate, exempt, legal mention).
# WP-3.4 moves this into per-country packs.
DEFAULT_TAX_CODES: tuple[tuple[str, str, str, Decimal, bool, str | None], ...] = (
    ("TVA18", "TVA 18 %", "VAT 18%", Decimal("18"), False, None),
    ("EXO", "Exonéré de TVA", "VAT exempt", Decimal("0"), True, "Exonération de TVA"),
)


@dataclass(frozen=True)
class TaxCode:
    id: str
    code: str
    rate: Decimal
    scope: str = "both"
    exempt: bool = False
    active: bool = True

    def applies_to(self, side: str) -> bool:
        return self.scope == "both" or self.scope == side


def normalize_code(raw: str | None) -> str:
    return (raw or "").strip().upper()


def check_tax_code(*, code: str, name_fr: str, rate: object, scope: str, exempt: bool) -> Result[Decimal]:
    """The checked rate of a code about to be saved."""
    if not code or not name_fr.strip():
        return Err("INVALID_TAX_CODE", "a tax code needs a code and a name", "un code de taxe a un code et un nom")
    if len(code) > CODE_MAX_LENGTH or not all(ch.isalnum() or ch in "-_." for ch in code):
        return Err(
            "INVALID_TAX_CODE",
            f"a tax code is up to {CODE_MAX_LENGTH} letters, digits, '-', '_' or '.'",
            f"un code de taxe compte au plus {CODE_MAX_LENGTH} lettres, chiffres, « - », « _ » ou « . »",
        )
    if scope not in SCOPES:
        return Err("INVALID_TAX_CODE", f"scope is one of {', '.join(SCOPES)}", f"la portée est l'une de {', '.join(SCOPES)}")
    checked = check_rate(rate)
    if isinstance(checked, Err):
        return checked
    if exempt and checked.value != ZERO:
        return Err("INVALID_TAX_CODE", "an exempt code has a 0 % rate", "un code d'exonération a un taux de 0 %")
    return checked


def check_rate(rate: object) -> Result[Decimal]:
    try:
        value = Decimal(str(rate))
    except (InvalidOperation, ValueError):
        return Err("INVALID_VAT_RATE", "a VAT rate is between 0 and 100 %", "un taux de TVA est compris entre 0 et 100 %")
    if not value.is_finite() or value < ZERO or value > HUNDRED or value != value.quantize(Decimal("0.01")):
        return Err("INVALID_VAT_RATE", "a VAT rate is between 0 and 100 %, with at most two decimals",
                   "un taux de TVA est compris entre 0 et 100 %, avec au plus deux décimales")
    return Ok(value)


@dataclass(frozen=True)
class ResolvedTax:
    tax_code: str | None
    rate: Decimal


def resolve_line_tax(
    *,
    side: str,
    codes: Sequence[TaxCode],
    explicit_code: str | None = None,
    explicit_rate: object = None,
    partner_code_id: str | None = None,
    product_code_id: str | None = None,
    default_rate: Decimal = ZERO,
) -> Result[ResolvedTax]:
    """The code and rate of one line.

    - An explicit code wins and gives the rate; a different explicit rate is refused.
    - An explicit rate alone keeps the rate and takes a code of that rate: the partner's, then the product's,
      then the first active, non-exempt code of this side with that rate; none if no code has it.
    - Neither: the partner's code (an exemption), then the product's, then the default rate with its code.
    """
    by_id = {code.id: code for code in codes}
    by_code = {code.code: code for code in codes}

    if normalize_code(explicit_code):
        wanted = normalize_code(explicit_code)
        code = by_code.get(wanted)
        if code is None:
            return Err("TAX_CODE_NOT_FOUND", f"tax code {wanted} does not exist", f"le code de taxe {wanted} n'existe pas")
        if not code.active:
            return Err("TAX_CODE_INACTIVE", f"tax code {wanted} is no longer in use", f"le code de taxe {wanted} n'est plus utilisé")
        if not code.applies_to(side):
            return Err("TAX_CODE_WRONG_SCOPE", f"tax code {wanted} is not for {side}",
                       f"le code de taxe {wanted} ne s'applique pas aux {'ventes' if side == 'sales' else 'achats'}")
        if explicit_rate is not None:
            rate = check_rate(explicit_rate)
            if isinstance(rate, Err):
                return rate
            if rate.value != code.rate:
                return Err("TAX_RATE_MISMATCH", f"tax code {wanted} is {code.rate} %, not {rate.value} %",
                           f"le code de taxe {wanted} est à {code.rate} %, pas à {rate.value} %")
        return Ok(ResolvedTax(code.code, code.rate))

    usable = [code for code in codes if code.active and code.applies_to(side)]
    preferred = [by_id[i] for i in (partner_code_id, product_code_id) if i and i in by_id and by_id[i].active and by_id[i].applies_to(side)]

    def code_for(rate: Decimal) -> str | None:
        for code in preferred:
            if code.rate == rate:
                return code.code
        # An exemption is a legal status someone chose (on the partner or product), never read from a 0 % rate.
        for code in sorted((c for c in usable if not c.exempt), key=lambda c: c.code):
            if code.rate == rate:
                return code.code
        return None

    if explicit_rate is not None:
        rate = check_rate(explicit_rate)
        if isinstance(rate, Err):
            return rate
        return Ok(ResolvedTax(code_for(rate.value), rate.value))
    if preferred:
        return Ok(ResolvedTax(preferred[0].code, preferred[0].rate))
    rate = check_rate(default_rate)
    if isinstance(rate, Err):
        return rate
    return Ok(ResolvedTax(code_for(rate.value), rate.value))


@dataclass(frozen=True)
class BreakdownPart:
    tax_code: str | None
    rate: Decimal
    base: Decimal
    vat: Decimal

    def as_payload(self) -> dict[str, Any]:
        return {"tax_code": self.tax_code, "rate": str(self.rate), "base": str(self.base), "vat": str(self.vat)}


def vat_breakdown(lines: Iterable[tuple[str | None, object, object]]) -> list[BreakdownPart]:
    """Per (code, rate), the base excluding tax and its VAT, from (code, rate, net) lines; exact values,
    two decimals, to be rounded by whoever posts them against a document total."""
    bases: dict[tuple[str | None, Decimal], Decimal] = defaultdict(lambda: ZERO)
    for code, rate, net in lines:
        bases[(code or None, Decimal(str(rate)))] += Decimal(str(net))
    cent = Decimal("0.01")
    return [
        BreakdownPart(code, rate, base.quantize(cent, rounding=ROUND_HALF_UP), (base * rate / HUNDRED).quantize(cent, rounding=ROUND_HALF_UP))
        for (code, rate), base in sorted(bases.items(), key=lambda item: (item[0][0] or "", item[0][1]))
    ]


def breakdown_payload(parts: Iterable[BreakdownPart]) -> list[dict[str, Any]]:
    return [part.as_payload() for part in parts]


def parse_breakdown(raw: object) -> list[BreakdownPart]:
    """An event's `vat_breakdown`; anything malformed reads as no breakdown (the event posts as before)."""
    if not isinstance(raw, list):
        return []
    parts = []
    try:
        for item in raw:
            parts.append(BreakdownPart(
                item.get("tax_code") or None, Decimal(str(item.get("rate", "0"))),
                Decimal(str(item.get("base", "0"))), Decimal(str(item.get("vat", "0"))),
            ))
    except (InvalidOperation, ValueError, AttributeError, TypeError):
        return []
    return parts


def split_whole(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """`total` (whole francs) shared in proportion to `weights`, each part whole, summing exactly to `total`:
    the rounding gap goes on the largest part. All-zero weights put everything on the first part."""
    if not weights:
        return []
    weight_sum = sum(weights, ZERO)
    if weight_sum == ZERO:
        return [total] + [ZERO] * (len(weights) - 1)
    parts = [(total * weight / weight_sum).quantize(Decimal("1"), rounding=ROUND_HALF_UP) for weight in weights]
    gap = total - sum(parts, ZERO)
    if gap:
        largest = max(range(len(parts)), key=lambda i: abs(weights[i]))
        parts[largest] += gap
    return parts


def allocate_breakdown(parts: Sequence[BreakdownPart], *, base_total: Decimal, vat_total: Decimal) -> list[BreakdownPart]:
    """The breakdown in whole francs that sums exactly to the document's posted base and VAT."""
    bases = split_whole(base_total, [part.base for part in parts])
    vats = split_whole(vat_total, [part.vat for part in parts]) if any(part.vat for part in parts) else [ZERO] * len(parts)
    if vat_total and not any(part.vat for part in parts):
        # VAT on the document but none in the breakdown (inconsistent event): keep it on the base shares.
        vats = split_whole(vat_total, [part.base for part in parts])
    return [BreakdownPart(part.tax_code, part.rate, base, vat) for part, base, vat in zip(parts, bases, vats)]


def codes_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[TaxCode]:
    return [TaxCode(id=r["id"], code=r["code"], rate=Decimal(str(r["rate"])), scope=r["scope"], exempt=r["exempt"], active=r["active"])
            for r in rows]

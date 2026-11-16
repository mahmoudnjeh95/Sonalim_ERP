"""Prices, discounts, VAT and quotes -- pure rules, no database.

A line's price comes from the customer's price list (or the default list), the best quantity break the
quantity reaches, else the product's catalog price. Discounts stack: the line discount, then the
document's discount; the customer's standing discount is the document discount's starting value.
VAT is computed on the net of each line. XOF has no cents, so only totals are rounded, half up."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from core.domain.result import Err, Ok, Result

ZERO = Decimal("0")
HUNDRED = Decimal("100")

QUOTE_TRANSITIONS = {
    "draft": {"sent", "accepted", "refused", "expired", "superseded"},
    "sent": {"accepted", "refused", "expired", "superseded"},
    "accepted": set(),
    "refused": set(),
    "expired": set(),
    "superseded": set(),
}
# A quote that can still change hands: what expiry and revision apply to.
OPEN_QUOTE_STATUSES = ("draft", "sent")


def whole_francs(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PricedLine:
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal = ZERO
    vat_rate: Decimal = ZERO

    @property
    def gross(self) -> Decimal:
        return self.quantity * self.unit_price

    def net(self, document_discount: Decimal = ZERO) -> Decimal:
        """Excluding tax, after the line discount then the document discount; exact, rounded only in the totals."""
        return self.gross * (HUNDRED - self.discount_rate) / HUNDRED * (HUNDRED - document_discount) / HUNDRED

    def net_unit_price(self, document_discount: Decimal = ZERO) -> Decimal:
        return self.unit_price * (HUNDRED - self.discount_rate) / HUNDRED * (HUNDRED - document_discount) / HUNDRED


@dataclass(frozen=True)
class Totals:
    gross: Decimal        # before discounts, excluding tax
    discount: Decimal
    excl_tax: Decimal     # after discounts
    vat: Decimal
    incl_tax: Decimal     # excl_tax + vat, whole francs

    def as_dict(self) -> dict[str, Decimal]:
        return {"gross": self.gross, "discount": self.discount, "excl_tax": self.excl_tax, "vat": self.vat, "incl_tax": self.incl_tax}


def compute_totals(lines: Iterable[PricedLine], document_discount: Decimal = ZERO) -> Totals:
    lines = list(lines)
    gross = whole_francs(sum((line.gross for line in lines), ZERO))
    excl = whole_francs(sum((line.net(document_discount) for line in lines), ZERO))
    vat = whole_francs(sum((line.net(document_discount) * line.vat_rate / HUNDRED for line in lines), ZERO))
    return Totals(gross=gross, discount=gross - excl, excl_tax=excl, vat=vat, incl_tax=excl + vat)


def effective_discount(line_discount: Decimal, document_discount: Decimal) -> Decimal:
    """The combined discount of a line, in %: 10 % then 5 % is 14.5 %, not 15 %."""
    kept = (HUNDRED - line_discount) / HUNDRED * (HUNDRED - document_discount) / HUNDRED
    return HUNDRED - kept * HUNDRED


def check_rate(value: Decimal, *, what: str) -> Result[None]:
    if not ZERO <= value <= HUNDRED:
        if what == "vat":
            return Err("INVALID_VAT_RATE", "a VAT rate is between 0 and 100 %", "un taux de TVA est compris entre 0 et 100 %")
        return Err("INVALID_DISCOUNT", "a discount is between 0 and 100 %", "une remise est comprise entre 0 et 100 %")
    return Ok(None)


def check_line(*, quantity: Decimal, unit_price: Decimal, discount_rate: Decimal, vat_rate: Decimal) -> Result[None]:
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "a line's quantity must be positive", "la quantité d'une ligne doit être positive")
    if unit_price < 0:
        return Err("INVALID_PRICE", "a price can't be negative", "un prix ne peut pas être négatif")
    checked = check_rate(discount_rate, what="discount")
    if isinstance(checked, Err):
        return checked
    return check_rate(vat_rate, what="vat")


def check_discount_limit(line_discounts: Iterable[Decimal], document_discount: Decimal, *, limit: Decimal,
                         may_exceed: bool) -> Result[None]:
    """A seller gives at most `limit` %, line and document discounts combined, on any line. Above it the
    user needs sales.admin_discounts."""
    if may_exceed:
        return Ok(None)
    worst = max((effective_discount(rate, document_discount) for rate in line_discounts), default=document_discount)
    worst = max(worst, document_discount)
    if worst > limit + Decimal("0.005"):
        shown = worst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP).normalize()
        limit_shown = limit.normalize()
        return Err(
            "DISCOUNT_ABOVE_LIMIT",
            f"a discount of {shown} % is above the {limit_shown} % you may give; ask someone allowed to grant larger discounts",
            f"une remise de {shown} % dépasse les {limit_shown} % que vous pouvez accorder ; demandez à une personne habilitée",
        )
    return Ok(None)


# ---- price lists -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PriceBreak:
    price_list_id: str
    min_quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class ListWindow:
    id: str
    name: str
    valid_from: datetime.date | None
    valid_to: datetime.date | None
    active: bool = True

    def covers(self, on: datetime.date) -> bool:
        return self.active and (self.valid_from is None or self.valid_from <= on) and (self.valid_to is None or on <= self.valid_to)


@dataclass(frozen=True)
class ResolvedPrice:
    unit_price: Decimal
    source: str                    # "price_list" | "catalog"
    price_list_id: str | None
    price_list_name: str | None
    min_quantity: Decimal | None   # the break that applied
    discount_rate: Decimal         # the customer's standing discount

    def as_dict(self) -> dict[str, object]:
        return {"unit_price": self.unit_price, "source": self.source, "price_list_id": self.price_list_id,
                "price_list_name": self.price_list_name, "min_quantity": self.min_quantity, "discount_rate": self.discount_rate}


def best_break(breaks: Iterable[PriceBreak], quantity: Decimal) -> PriceBreak | None:
    """The highest break the quantity reaches."""
    reached = [b for b in breaks if b.min_quantity <= quantity]
    return max(reached, key=lambda b: b.min_quantity) if reached else None


def resolve(*, quantity: Decimal, on: datetime.date, customer_list: ListWindow | None, default_list: ListWindow | None,
            breaks: Iterable[PriceBreak], catalog_price: Decimal, customer_discount: Decimal = ZERO) -> ResolvedPrice:
    """The customer's list when it is valid that day and prices the product, else the default list, else the
    catalog price."""
    breaks = list(breaks)
    for window in (customer_list, default_list):
        if window is None or not window.covers(on):
            continue
        found = best_break([b for b in breaks if b.price_list_id == window.id], quantity)
        if found is not None:
            return ResolvedPrice(found.unit_price, "price_list", window.id, window.name, found.min_quantity, customer_discount)
    return ResolvedPrice(catalog_price, "catalog", None, None, None, customer_discount)


def check_price_list(*, name: str, valid_from: datetime.date | None, valid_to: datetime.date | None) -> Result[None]:
    if not name.strip():
        return Err("INVALID_PRICE_LIST", "a price list needs a name", "une liste de prix doit avoir un nom")
    if valid_from and valid_to and valid_to < valid_from:
        return Err("INVALID_PRICE_LIST", "a price list can't end before it starts",
                   "une liste de prix ne peut pas se terminer avant de commencer")
    return Ok(None)


# ---- quotes ----------------------------------------------------------------------------------

def check_quote_transition(current: str, target: str) -> Result[None]:
    if target not in QUOTE_TRANSITIONS.get(current, set()):
        return Err("INVALID_TRANSITION", f"a quote can't go from {current} to {target}",
                   f"un devis ne peut pas passer de {current} à {target}")
    return Ok(None)


def is_expired(status: str, valid_until: datetime.date, today: datetime.date) -> bool:
    return status in OPEN_QUOTE_STATUSES and valid_until < today


def display_number(number: str, revision: int) -> str:
    return number if revision == 1 else f"{number}-{revision}"


def conversion_rate(statuses: Iterable[str]) -> Decimal | None:
    """Accepted quotes out of those that reached a decision (accepted, refused or expired), in %.
    Revisions replaced by a later one don't count."""
    decided = [s for s in statuses if s in ("accepted", "refused", "expired")]
    if not decided:
        return None
    return (Decimal(sum(1 for s in decided if s == "accepted")) * HUNDRED / Decimal(len(decided))).quantize(Decimal("0.1"))

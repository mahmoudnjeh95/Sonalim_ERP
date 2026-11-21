from __future__ import annotations

import datetime
from dataclasses import dataclass, replace
from decimal import Decimal

from core.domain.money import to_decimal
from core.domain.result import Err, Ok, Result
from modules.sales.domain.pricing import PricedLine, Totals, compute_totals

VALID_TRANSITIONS = {
    "draft": {"confirmed"},
    # Set by warehouse.shipment.shipped or by issue vouchers covering every line,
    # never by a user action: an order is shipped when the goods have physically
    # left, which only warehouse knows.
    "confirmed": {"shipped"},
    "shipped": set(),
}


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    quantity: Decimal
    unit_price: Decimal
    # 0 for orders created before discounts and VAT existed, so they total what they always did
    discount_rate: Decimal = Decimal("0")
    vat_rate: Decimal = Decimal("0")
    price_list_id: str | None = None
    # core.tax_codes.code the rate came from; None on lines written before tax codes
    tax_code: str | None = None

    def __post_init__(self) -> None:
        # Callers outside sales (CRM, seed scripts) may still pass floats.
        for name in ("quantity", "unit_price", "discount_rate", "vat_rate"):
            object.__setattr__(self, name, to_decimal(getattr(self, name)))

    def priced(self) -> PricedLine:
        return PricedLine(self.quantity, self.unit_price, self.discount_rate, self.vat_rate)


@dataclass(frozen=True)
class SalesOrder:
    id: str
    partner_id: str
    location_id: str
    status: str
    lines: tuple[OrderLine, ...]
    requested_ship_date: datetime.date | None = None
    opportunity_id: str | None = None
    discount_rate: Decimal = Decimal("0")
    quote_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "discount_rate", to_decimal(self.discount_rate))

    @property
    def totals(self) -> Totals:
        return compute_totals((line.priced() for line in self.lines), self.discount_rate)

    @property
    def total_amount(self) -> Decimal:
        """What the customer pays, VAT included, in whole francs."""
        return self.totals.incl_tax

    def net_unit_price(self, line: OrderLine) -> Decimal:
        """The price one unit of the line is invoiced at, excluding tax, after both discounts."""
        return line.priced().net_unit_price(self.discount_rate)


def confirm(order: SalesOrder) -> Result[SalesOrder]:
    if "confirmed" not in VALID_TRANSITIONS.get(order.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot confirm order in status {order.status}",
            f"impossible de confirmer une commande au statut {order.status}",
        )
    return Ok(replace(order, status="confirmed"))


def covers_all_lines(lines: tuple[OrderLine, ...], issued_to_date: dict[str, Decimal | float]) -> bool:
    """Whether what left the warehouse covers everything ordered. Lines of one product count together."""
    ordered: dict[str, Decimal] = {}
    for line in lines:
        ordered[line.product_id] = ordered.get(line.product_id, Decimal("0")) + line.quantity
    return all(to_decimal(issued_to_date.get(product_id, 0)) >= quantity for product_id, quantity in ordered.items())


def mark_shipped(order_status: str) -> Result[str]:
    if "shipped" not in VALID_TRANSITIONS.get(order_status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot mark an order in status {order_status} as shipped",
            f"impossible de marquer comme expédiée une commande au statut {order_status}",
        )
    return Ok("shipped")

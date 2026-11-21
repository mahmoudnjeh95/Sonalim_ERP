"""Sales invoices from deliveries, and credit notes from returns -- pure rules, no database.

An invoice bills what a delivery carried, at the order's prices, never more of a product than the order
holds once earlier invoices are counted. A credit note takes back, at the price it was invoiced, what a
return brought back, never more than those invoices still carry once earlier credit notes are counted."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping

ZERO = Decimal("0")


@dataclass(frozen=True)
class BilledLine:
    product_id: str
    quantity: Decimal
    # excluding tax, after the order's discounts
    unit_price: Decimal
    vat_rate: Decimal = ZERO
    # core.tax_codes.code the rate came from (None before tax codes)
    tax_code: str | None = None

    @property
    def amount(self) -> Decimal:
        """Excluding tax."""
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def order_prices(lines: Iterable[tuple[str, Decimal, Decimal]]) -> dict[str, tuple[Decimal, Decimal]]:
    """Per product, what the order holds and its price. A product on several lines is priced at their
    weighted average, so billing it in any order gives the same total."""
    quantities: dict[str, Decimal] = {}
    values: dict[str, Decimal] = {}
    for product_id, quantity, unit_price in lines:
        quantities[product_id] = quantities.get(product_id, ZERO) + quantity
        values[product_id] = values.get(product_id, ZERO) + quantity * unit_price
    return {
        product_id: (quantity, (values[product_id] / quantity) if quantity else ZERO)
        for product_id, quantity in quantities.items()
    }


def lines_to_invoice(
    delivered: Mapping[str, Decimal],
    ordered: Mapping[str, tuple[Decimal, Decimal]],
    already_invoiced: Mapping[str, Decimal],
    vat_rates: Mapping[str, Decimal] | None = None,
    tax_codes: Mapping[str, str | None] | None = None,
) -> list[BilledLine]:
    """What a delivery bills. A product the order doesn't hold is not billed; past what the order holds
    nothing more is billed, so a second delivery of the same goods can't bill them twice."""
    lines = []
    for product_id, quantity in delivered.items():
        if product_id not in ordered or quantity <= 0:
            continue
        on_order, price = ordered[product_id]
        left = on_order - already_invoiced.get(product_id, ZERO)
        billed = min(quantity, left)
        if billed > 0:
            lines.append(BilledLine(product_id, billed, price, (vat_rates or {}).get(product_id, ZERO), (tax_codes or {}).get(product_id)))
    return lines


def whole_francs(lines: Iterable[BilledLine]) -> Decimal:
    """The total excluding tax. XOF has no cents, so the total is rounded half up to the franc."""
    return sum((line.quantity * line.unit_price for line in lines), ZERO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def vat_total(lines: Iterable[BilledLine]) -> Decimal:
    """The VAT of the lines, computed on each net line and rounded once on the total."""
    return sum((line.quantity * line.unit_price * line.vat_rate / Decimal("100") for line in lines), ZERO).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)


def document_totals(lines: Iterable[BilledLine]) -> tuple[Decimal, Decimal, Decimal]:
    """(excluding tax, VAT, including tax) in whole francs; including tax is what the customer owes."""
    lines = list(lines)
    excl, vat = whole_francs(lines), vat_total(lines)
    return excl, vat, excl + vat


def order_vat_rates(lines: Iterable[tuple[str, Decimal, Decimal]]) -> dict[str, Decimal]:
    """Per product, the VAT rate of its order lines: (product, net value, rate). A product on lines at different
    rates (unusual) takes the rate of the larger value."""
    return {product_id: rate for product_id, (rate, _) in order_taxes((p, v, r, None) for p, v, r in lines).items()}


def order_taxes(lines: Iterable[tuple[str, Decimal, Decimal, str | None]]) -> dict[str, tuple[Decimal, str | None]]:
    """Per product, the (VAT rate, tax code) of its order lines: (product, net value, rate, code). A product on lines
    taxed differently (unusual) takes the tax of the larger value."""
    best: dict[str, tuple[Decimal, Decimal, str | None]] = {}
    for product_id, value, rate, code in lines:
        if product_id not in best or value > best[product_id][0]:
            best[product_id] = (value, rate, code)
    return {product_id: (rate, code) for product_id, (_, rate, code) in best.items()}


@dataclass(frozen=True)
class CreditableInvoice:
    invoice_id: str
    # product -> (quantity invoiced, unit price invoiced)
    lines: Mapping[str, tuple[Decimal, Decimal]]
    # product -> quantity already credited
    credited: Mapping[str, Decimal]
    # product -> VAT rate invoiced
    vat_rates: Mapping[str, Decimal] = field(default_factory=dict)
    # product -> tax code invoiced
    tax_codes: Mapping[str, str | None] = field(default_factory=dict)


def lines_to_credit(returned: Mapping[str, Decimal], invoices: Iterable[CreditableInvoice]) -> dict[str, list[BilledLine]]:
    """Per invoice, what a return credits. Invoices are taken in the order given (the caller passes the
    latest delivery first, the one the goods most likely came from). A returned quantity no invoice still
    carries is not credited: it was never billed."""
    left = {product_id: quantity for product_id, quantity in returned.items() if quantity > 0}
    result: dict[str, list[BilledLine]] = {}
    for invoice in invoices:
        for product_id, (invoiced, price) in invoice.lines.items():
            wanted = left.get(product_id, ZERO)
            if wanted <= 0:
                continue
            room = invoiced - invoice.credited.get(product_id, ZERO)
            take = min(wanted, room)
            if take > 0:
                result.setdefault(invoice.invoice_id, []).append(
                    BilledLine(product_id, take, price, invoice.vat_rates.get(product_id, ZERO), invoice.tax_codes.get(product_id)))
                left[product_id] = wanted - take
    return result


def amount_due(amount: Decimal, credited: Decimal) -> Decimal:
    return max(amount - credited, ZERO)


def customer_credit(due: Decimal, paid: Decimal) -> Decimal:
    """What the company owes back once a credit note brings what is due below what was already paid."""
    return max(paid - due, ZERO)

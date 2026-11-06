"""Sales invoices from deliveries, and credit notes from returns -- pure rules, no database.

An invoice bills what a delivery carried, at the order's prices, never more of a product than the order
holds once earlier invoices are counted. A credit note takes back, at the price it was invoiced, what a
return brought back, never more than those invoices still carry once earlier credit notes are counted."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping

ZERO = Decimal("0")


@dataclass(frozen=True)
class BilledLine:
    product_id: str
    quantity: Decimal
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
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
            lines.append(BilledLine(product_id, billed, price))
    return lines


def whole_francs(lines: Iterable[BilledLine]) -> Decimal:
    """The invoice total. XOF has no cents, so the total is rounded half up to the franc."""
    return sum((line.quantity * line.unit_price for line in lines), ZERO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CreditableInvoice:
    invoice_id: str
    # product -> (quantity invoiced, unit price invoiced)
    lines: Mapping[str, tuple[Decimal, Decimal]]
    # product -> quantity already credited
    credited: Mapping[str, Decimal]


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
                result.setdefault(invoice.invoice_id, []).append(BilledLine(product_id, take, price))
                left[product_id] = wanted - take
    return result


def amount_due(amount: Decimal, credited: Decimal) -> Decimal:
    return max(amount - credited, ZERO)


def customer_credit(due: Decimal, paid: Decimal) -> Decimal:
    """What the company owes back once a credit note brings what is due below what was already paid."""
    return max(paid - due, ZERO)

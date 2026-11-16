from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping

from core.domain.result import Err, Ok, Result

# Payment-driven states (partially_paid, paid) are never requested directly: they are
# derived from amount_paid by `status_for_payment`, so the only manual transitions are these.
MANUAL_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"validated", "cancelled"},
    "validated": {"cancelled"},
    "partially_paid": set(),
    "paid": set(),
    "cancelled": set(),
}

PAYABLE_STATUSES = {"validated", "partially_paid"}
LINES_TOLERANCE = Decimal("0.01")
# Mali's standard VAT rate; a tenant can change its default (procurement.invoice_settings).
DEFAULT_VAT_RATE = Decimal("18.00")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def check_new_invoice_currency(currency: str) -> Result[None]:
    """Purchase invoices are in XOF (F CFA); treasury cannot settle anything else."""
    if currency != "XOF":
        return Err("INVOICE_CURRENCY_NOT_XOF", f"purchase invoices are in XOF (F CFA), not {currency}",
                   f"les factures d'achat sont en XOF (F CFA), pas en {currency}")
    return Ok(None)


def check_transition(current: str, target: str) -> Result[None]:
    if target not in MANUAL_TRANSITIONS.get(current, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move purchase invoice from {current} to {target}",
            f"impossible de faire passer la facture d'achat de {current} à {target}",
        )
    return Ok(None)


def remaining(amount: Decimal, amount_paid: Decimal) -> Decimal:
    """Under one franc is settled (see status_for_payment), so it is not shown as still due."""
    gap = amount - amount_paid
    return gap if gap >= 1 else ZERO


def supplier_credit(amount: Decimal, amount_paid: Decimal) -> Decimal:
    """What the supplier owes back when a credit note brought the amount due below what was already paid."""
    return max(amount_paid - amount, ZERO)


def status_for_payment(amount: Decimal, amount_paid: Decimal) -> str:
    """The status a validated invoice has once `amount_paid` has been applied. `amount` is what is due
    after credit notes. Treasury pays in whole francs, so what is left under one franc of an amount with
    cents can never be paid: settled. An invoice credited down to nothing is settled too."""
    if amount < 1:
        return "paid"
    if amount_paid <= 0:
        return "validated"
    if amount - amount_paid < 1:
        return "paid"
    return "partially_paid"


def check_payment_delta(amount: Decimal, amount_paid: Decimal, delta: Decimal) -> Result[Decimal]:
    """A payment can't take the paid amount below zero or above what is due. Taking one back is always
    allowed while something stays paid: after a credit note the invoice may hold more than is now due."""
    new_paid = amount_paid + delta
    if new_paid < 0 or (delta > 0 and new_paid > amount):
        return Err(
            "OVER_ALLOCATION",
            f"payment of {new_paid} is outside 0..{amount} for this invoice",
            f"un paiement de {new_paid} sort de la plage 0..{amount} pour cette facture",
        )
    return Ok(new_paid)


def check_lines_total(amount: Decimal, lines: list[tuple[Decimal, Decimal]]) -> Result[None]:
    """`lines` are (quantity, unit_price). No lines is valid: the header total stands alone."""
    if not lines:
        return Ok(None)
    total = sum((quantity * unit_price for quantity, unit_price in lines), ZERO)
    if abs(total - amount) > LINES_TOLERANCE:
        return Err(
            "TOTAL_MISMATCH",
            f"lines total {total} differs from invoice amount {amount}",
            f"le total des lignes {total} diffère du montant de la facture {amount}",
        )
    return Ok(None)


# ---- lines and totals ------------------------------------------------------------------------------

def whole_francs(value: Decimal) -> Decimal:
    """F CFA has no cents: totals are rounded half up to the franc."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Line:
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal = ZERO
    vat_rate: Decimal = ZERO

    @property
    def gross(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def net(self) -> Decimal:
        """Excluding tax, after the line discount; exact, rounded only in the totals."""
        return self.gross * (HUNDRED - self.discount_rate) / HUNDRED

    @property
    def vat(self) -> Decimal:
        return self.net * self.vat_rate / HUNDRED


@dataclass(frozen=True)
class Totals:
    gross: Decimal       # before discounts, excluding tax
    discount: Decimal
    excl_tax: Decimal    # after discounts
    vat: Decimal
    incl_tax: Decimal    # what the supplier is owed: excl_tax + vat, whole francs


def compute_totals(lines: Iterable[Line]) -> Totals:
    lines = list(lines)
    gross = whole_francs(sum((line.gross for line in lines), ZERO))
    excl = whole_francs(sum((line.net for line in lines), ZERO))
    vat = whole_francs(sum((line.vat for line in lines), ZERO))
    return Totals(gross=gross, discount=gross - excl, excl_tax=excl, vat=vat, incl_tax=excl + vat)


def check_line(*, description: str | None, product_id: str | None, quantity: Decimal, unit_price: Decimal,
               discount_rate: Decimal, vat_rate: Decimal) -> Result[None]:
    if not (description or "").strip() and not product_id:
        return Err("LINE_DESCRIPTION_REQUIRED", "a line needs a product or a description",
                   "une ligne doit avoir un produit ou un libellé")
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "a line's quantity must be greater than zero",
                   "la quantité d'une ligne doit être supérieure à zéro")
    if unit_price < 0:
        return Err("INVALID_UNIT_PRICE", "a unit price cannot be negative", "un prix unitaire ne peut pas être négatif")
    if not ZERO <= discount_rate <= HUNDRED:
        return Err("INVALID_DISCOUNT", "a discount is between 0 and 100 %", "une remise est comprise entre 0 et 100 %")
    if not ZERO <= vat_rate <= HUNDRED:
        return Err("INVALID_VAT_RATE", "a VAT rate is between 0 and 100 %", "un taux de TVA est compris entre 0 et 100 %")
    return Ok(None)


def check_has_amount(totals: Totals) -> Result[None]:
    if totals.incl_tax <= 0:
        return Err("INVOICE_AMOUNT_ZERO", "the invoice total must be greater than zero",
                   "le total de la facture doit être supérieur à zéro")
    return Ok(None)


# ---- three-way match --------------------------------------------------------------------------------

# A price within half a percent of the reference is not worth a warning (rounding on the supplier's side).
PRICE_TOLERANCE = Decimal("0.005")


@dataclass(frozen=True)
class OrderLineFacts:
    """What procurement knows about one purchase-order line when an invoice line refers to it."""
    received: Decimal                 # on confirmed goods receipts
    invoiced_elsewhere: Decimal       # on other invoices not cancelled, net of their credit notes
    # The goods price per unit the receipts recorded (their goods value, freight and customs excluded);
    # None when it isn't known in F CFA.
    order_unit_price: Decimal | None


def price_differs(price: Decimal, reference: Decimal) -> bool:
    return abs(price - reference) > max(reference * PRICE_TOLERANCE, Decimal("0.01"))


def match_warnings(lines: Iterable[tuple[str, str | None, Decimal, Decimal]],
                   facts: Mapping[str, OrderLineFacts]) -> list[dict[str, object]]:
    """`lines` are (line key, purchase-order line id, quantity, unit price). A line invoicing more than was
    received and not yet invoiced, or at a price other than the order's, gets a warning."""
    quantities: dict[str, Decimal] = {}
    for _key, po_line, quantity, _price in lines:
        if po_line:
            quantities[po_line] = quantities.get(po_line, ZERO) + quantity
    warnings: list[dict[str, object]] = []
    over_reported: set[str] = set()
    for key, po_line, _quantity, price in lines:
        if not po_line or po_line not in facts:
            continue
        fact = facts[po_line]
        open_quantity = fact.received - fact.invoiced_elsewhere
        if quantities[po_line] > open_quantity and po_line not in over_reported:
            over_reported.add(po_line)
            warnings.append({"code": "QUANTITY_OVER_RECEIVED", "line": key, "purchase_order_line_id": po_line,
                             "invoiced": quantities[po_line], "receivable": max(open_quantity, ZERO)})
        if fact.order_unit_price is not None and price_differs(price, fact.order_unit_price):
            warnings.append({"code": "PRICE_DIFFERS_FROM_ORDER", "line": key, "purchase_order_line_id": po_line,
                             "unit_price": price, "order_unit_price": fact.order_unit_price})
    return warnings


def check_not_over_received(warnings: list[dict[str, object]], *, may_override: bool) -> Result[None]:
    if may_override or not any(w["code"] == "QUANTITY_OVER_RECEIVED" for w in warnings):
        return Ok(None)
    return Err("INVOICED_MORE_THAN_RECEIVED",
               "this invoice bills more than was received and not yet invoiced; a dedicated permission is needed to validate it",
               "cette facture facture plus que la quantité reçue et non encore facturée ; une permission dédiée est nécessaire pour la valider")


# ---- credit notes -----------------------------------------------------------------------------------

def check_credit_lines(invoice_lines: Mapping[str, Decimal], already_credited: Mapping[str, Decimal],
                       new_lines: Iterable[tuple[str, Decimal]]) -> Result[None]:
    """`invoice_lines` maps each invoice line to its value excluding tax; `already_credited` what earlier
    validated credit notes took off it; `new_lines` are (invoice line id, value excluding tax). A credit
    note can only refer to the invoice's own lines and never credit a line beyond what it was invoiced."""
    asked: dict[str, Decimal] = {}
    for line_id, value in new_lines:
        if line_id not in invoice_lines:
            return Err("CREDIT_LINE_NOT_ON_INVOICE", "a credit note line must refer to a line of its invoice",
                       "une ligne d'avoir doit se rapporter à une ligne de sa facture")
        asked[line_id] = asked.get(line_id, ZERO) + value
    for line_id, value in asked.items():
        left = invoice_lines[line_id] - already_credited.get(line_id, ZERO)
        if value > left + LINES_TOLERANCE:
            return Err("CREDIT_EXCEEDS_INVOICE",
                       f"a credit note can take at most {whole_francs(max(left, ZERO))} excl. tax off this line",
                       f"un avoir peut retirer au plus {whole_francs(max(left, ZERO))} HT de cette ligne")
    return Ok(None)

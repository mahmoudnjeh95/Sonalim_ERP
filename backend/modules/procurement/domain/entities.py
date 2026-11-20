from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.domain.money import to_decimal
from core.domain.result import Err, Ok, Result


def _as_decimals(obj, *names: str) -> None:
    """Money and the quantities it is computed from are Decimal (NUMERIC columns); a frozen
    dataclass built from floats or ints still holds Decimals."""
    for name in names:
        object.__setattr__(obj, name, to_decimal(getattr(obj, name)))

# Manual, caller-initiated transitions only. "partially_received" and "fully_received" are
# deliberately unreachable here — they can only be reached through receive_against_order,
# which derives them from actual line receipts. This stops a caller from marking an order
# partially/fully received without a goods receipt ever being recorded.
PURCHASE_ORDER_MANUAL_TRANSITIONS = {
    "draft": {"validated", "canceled"},
    "validated": {"approved", "refused", "canceled"},
    "approved": {"ordered", "canceled"},
    "ordered": {"canceled"},
    "partially_received": {"canceled"},
    "fully_received": set(),
    "canceled": set(),
    "refused": set(),
}

RECEIVING_ELIGIBLE_STATUSES = {"ordered", "partially_received"}


@dataclass(frozen=True)
class PurchaseOrder:
    id: str
    tenant_id: str
    supplier_id: str | None
    status: str
    order_date: str | None
    expected_date: str | None
    currency_code: str | None
    notes: str | None
    is_import: bool = False


def validate_new_purchase_order(*, currency_code: str | None = None) -> Result[None]:
    """currency_code is optional at order creation -- it's decided at receiving instead
    (see PurchaseOrderService.create_receipt), once an explicitly-passed blank string is
    still rejected rather than silently treated as "not set"."""
    if currency_code is not None and not currency_code.strip():
        return Err("INVALID_CURRENCY", "currency_code cannot be blank", "currency_code ne peut pas être vide")
    return Ok(None)


def transition_purchase_order(order: PurchaseOrder, new_status: str) -> Result[PurchaseOrder]:
    if new_status not in PURCHASE_ORDER_MANUAL_TRANSITIONS.get(order.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move purchase order from {order.status} to {new_status}",
            f"impossible de faire passer la commande d'achat de {order.status} à {new_status}",
        )
    return Ok(_with_status(order, new_status))


def receive_against_order(order: PurchaseOrder, line_statuses: list[str]) -> Result[PurchaseOrder]:
    """Recomputes the order's receiving status from its lines' statuses after a goods
    receipt is confirmed. Only legal once the order has actually been placed — this is the
    only path to 'partially_received' / 'fully_received'."""
    if order.status not in RECEIVING_ELIGIBLE_STATUSES:
        return Err(
            "INVALID_TRANSITION",
            f"cannot record a receipt against a purchase order in status {order.status}",
            f"impossible d'enregistrer une réception sur une commande d'achat au statut {order.status}",
        )
    return Ok(_with_status(order, derive_order_status(line_statuses)))


def _with_status(order: PurchaseOrder, new_status: str) -> PurchaseOrder:
    return PurchaseOrder(
        id=order.id,
        tenant_id=order.tenant_id,
        supplier_id=order.supplier_id,
        status=new_status,
        order_date=order.order_date,
        expected_date=order.expected_date,
        currency_code=order.currency_code,
        notes=order.notes,
        is_import=order.is_import,
    )


def derive_order_status(line_statuses: list[str]) -> str:
    """Order-level receiving status, derived from its lines' statuses. Only ever returns a
    value in {ordered, partially_received, fully_received} — the pre-order (draft/
    validated/approved) and terminal (canceled/refused) statuses are explicit transitions
    the caller applies directly via transition_purchase_order, never derived here."""
    if not line_statuses:
        return "ordered"
    if all(status == "fully_received" for status in line_statuses):
        return "fully_received"
    if any(status != "pending" for status in line_statuses):
        return "partially_received"
    return "ordered"


@dataclass(frozen=True)
class PurchaseOrderLine:
    id: str
    tenant_id: str
    purchase_order_id: str
    product_id: str
    uom_id: str
    quantity_ordered: Decimal
    quantity_received: Decimal
    status: str
    unit_price: Decimal
    unit_price_currency: str

    def __post_init__(self) -> None:
        _as_decimals(self, "quantity_ordered", "quantity_received", "unit_price")


def validate_new_purchase_order_line(*, quantity_ordered: Decimal, unit_price: Decimal = Decimal("0")) -> Result[None]:
    if quantity_ordered <= 0:
        return Err("INVALID_QUANTITY", "quantity_ordered must be positive", "quantity_ordered doit être positive")
    if unit_price < 0:
        return Err("INVALID_PRICE", "unit_price cannot be negative", "unit_price ne peut pas être négatif")
    return Ok(None)


def apply_receipt_to_line(line: PurchaseOrderLine, quantity: Decimal) -> Result[PurchaseOrderLine]:
    """Records that `quantity` more of this line's product has physically arrived in one
    goods receipt. Example: a line ordered for 10t, already at 0 received, gets a 5t
    delivery -> quantity_received becomes 5, status becomes 'partially_received'; a later
    5t delivery brings it to 10/10 -> 'fully_received'."""
    quantity = to_decimal(quantity)
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "received quantity must be positive", "la quantité reçue doit être positive")
    new_received = line.quantity_received + quantity
    if new_received > line.quantity_ordered:
        return Err(
            "OVER_RECEIPT",
            f"cannot receive {quantity}, only {line.quantity_ordered - line.quantity_received} still outstanding on this line",
            f"impossible de recevoir {quantity}, il ne reste que {line.quantity_ordered - line.quantity_received} en attente sur cette ligne",
        )
    return Ok(
        PurchaseOrderLine(
            id=line.id,
            tenant_id=line.tenant_id,
            purchase_order_id=line.purchase_order_id,
            product_id=line.product_id,
            uom_id=line.uom_id,
            quantity_ordered=line.quantity_ordered,
            quantity_received=new_received,
            status=_line_status(line.quantity_ordered, new_received),
            unit_price=line.unit_price,
            unit_price_currency=line.unit_price_currency,
        )
    )


def _line_status(quantity_ordered: Decimal, quantity_received: Decimal) -> str:
    if quantity_received <= 0:
        return "pending"
    if quantity_received >= quantity_ordered:
        return "fully_received"
    return "partially_received"


# The cost fields a goods receipt carries, summed into its landed cost.
RECEIPT_FEES = ("base_cost", "license_fee", "insurance_fee", "transit_fee", "transport_fee", "customs_duty", "handling_fee")


@dataclass(frozen=True)
class PurchaseOrderReceipt:
    id: str
    tenant_id: str
    purchase_order_id: str
    location_id: str
    status: str
    currency_code: str
    invoice_number: str | None
    invoice_date: str | None
    origin_country: str | None
    carrier: str | None
    transport_company_name: str | None
    driver_name: str | None
    base_cost: Decimal
    license_fee: Decimal
    insurance_fee: Decimal
    transit_fee: Decimal
    transport_fee: Decimal
    customs_duty: Decimal
    handling_fee: Decimal
    total_cost: Decimal
    confirmed_at: str | None

    def __post_init__(self) -> None:
        _as_decimals(self, *RECEIPT_FEES, "total_cost")


def confirm_purchase_order_receipt(status: str) -> Result[str]:
    if status != "draft":
        return Err(
            "INVALID_TRANSITION",
            f"cannot confirm a goods receipt already in status {status}",
            f"impossible de confirmer une réception déjà au statut {status}",
        )
    return Ok("confirmed")


@dataclass(frozen=True)
class PurchaseOrderReceiptLine:
    id: str
    tenant_id: str
    purchase_order_receipt_id: str
    purchase_order_line_id: str
    quantity: Decimal
    lot_number: str | None
    cost_per_unit: Decimal

    def __post_init__(self) -> None:
        _as_decimals(self, "quantity", "cost_per_unit")


def compute_landed_cost(
    *,
    base_cost: Decimal,
    license_fee: Decimal,
    insurance_fee: Decimal,
    transit_fee: Decimal,
    transport_fee: Decimal,
    customs_duty: Decimal,
    quantity: Decimal,
    handling_fee: Decimal = Decimal("0"),
) -> Result[tuple[Decimal, Decimal]]:
    """(total cost, cost per unit). The per-unit cost is exact to Decimal's 28 digits; the column
    stores it at its own scale."""
    quantity = to_decimal(quantity)
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "quantity must be positive", "la quantité doit être positive")
    total_cost = sum((to_decimal(fee) for fee in (base_cost, license_fee, insurance_fee, transit_fee, transport_fee,
                                                  customs_duty, handling_fee)), Decimal("0"))
    return Ok((total_cost, total_cost / quantity))


COST_ANOMALY_THRESHOLD_PCT = 15.0


def compute_cost_anomaly(*, cost_per_unit: float, baseline_avg_cost_per_unit: float | None) -> tuple[float | None, bool]:
    """Flags a receipt line whose cost/unit lands materially above what this material has
    typically cost -- mirrors the "Majoration" warning triangle in the BD MP tracking sheet
    this feature is modeled on. baseline_avg_cost_per_unit is that product's (weighted)
    average cost/unit across every *other* confirmed receipt for it -- None when this is the
    first receipt for that product/unit, since there's nothing yet to compare against, so
    nothing is flagged. Only flags overspend (not unusually cheap receipts): "Majoration"
    means a markup, not a generic anomaly."""
    if baseline_avg_cost_per_unit is None or baseline_avg_cost_per_unit <= 0:
        return None, False
    deviation_pct = (cost_per_unit - baseline_avg_cost_per_unit) / baseline_avg_cost_per_unit * 100
    return deviation_pct, deviation_pct > COST_ANOMALY_THRESHOLD_PCT


# license/insurance/transit/customs only make sense once goods cross a border -- handling
# and transport are incurred on local deliveries too, so they're not gated here. This is
# what lets a buyer flip "importation" off at order creation (point 1 of the MP cost plan)
# and trust that nobody can then sneak a customs line onto a local CFA purchase.
IMPORT_ONLY_FEES = ("license_fee", "insurance_fee", "transit_fee", "customs_duty")


def validate_receipt_fees(
    *,
    is_import: bool,
    license_fee: Decimal,
    insurance_fee: Decimal,
    transit_fee: Decimal,
    customs_duty: Decimal,
) -> Result[None]:
    if is_import:
        return Ok(None)
    fees = {"license_fee": license_fee, "insurance_fee": insurance_fee, "transit_fee": transit_fee, "customs_duty": customs_duty}
    offending = [name for name, value in fees.items() if value > 0]
    if offending:
        return Err(
            "IMPORT_FEE_ON_LOCAL_ORDER",
            f"cannot set {', '.join(offending)} on a receipt for a non-import purchase order",
            f"impossible de définir {', '.join(offending)} sur une réception pour une commande d'achat non-import",
        )
    return Ok(None)


@dataclass(frozen=True)
class LastPrice:
    """The most recent unit price a supplier was ordered at for a product, derived from
    purchase order line history. Not a standalone price catalog -- see the "priced" chip
    tradeoff in the vendor-suggestion feature: no vendor SKU/ref, no quote before a first
    real order."""

    product_id: str
    unit_price: float
    unit_price_currency: str
    order_date: str | None

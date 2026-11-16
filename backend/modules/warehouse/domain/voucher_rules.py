from __future__ import annotations

from decimal import Decimal

from core.domain.result import Err, Ok, Result

VOUCHER_TYPES = ("receipt", "issue", "return", "transfer")
PREFIX = {"receipt": "BE", "issue": "BS", "return": "BR", "transfer": "TR", "delivery": "BL"}


def check_issue_available(available: Decimal, quantity: Decimal) -> Result[None]:
    if quantity > available:
        return Err("STOCK_INSUFFICIENT", f"only {available} available, {quantity} requested",
                   f"seulement {available} disponible, {quantity} demandé")
    return Ok(None)


def check_order_cumulative(ordered: Decimal, already_issued: Decimal, quantity: Decimal) -> Result[None]:
    """Across every issue voucher of one order, the total taken must not pass what was ordered."""
    if already_issued + quantity > ordered:
        return Err("ORDER_QTY_EXCEEDED", f"{already_issued + quantity} would exceed the {ordered} ordered",
                   f"{already_issued + quantity} dépasserait les {ordered} commandés")
    return Ok(None)


def check_return(issued: Decimal, already_returned: Decimal, quantity: Decimal) -> Result[None]:
    if already_returned + quantity > issued:
        return Err("RETURN_QTY_EXCEEDED", f"{already_returned + quantity} would exceed the {issued} issued",
                   f"{already_returned + quantity} dépasserait les {issued} sortis")
    return Ok(None)


def check_delivery(source: Decimal, already_delivered: Decimal, quantity: Decimal) -> Result[None]:
    """A delivery note can't deliver more than the document it comes from carries."""
    if already_delivered + quantity > source:
        return Err("DELIVERY_QTY_EXCEEDED", f"{already_delivered + quantity} would exceed the {source} on the source document",
                   f"{already_delivered + quantity} dépasserait les {source} du document d'origine")
    return Ok(None)


def check_transfer(source_id: str | None, dest_id: str | None, available: Decimal, quantity: Decimal) -> Result[None]:
    if not source_id or not dest_id or source_id == dest_id:
        return Err("INVALID_TRANSFER", "source and destination locations must differ",
                   "l'emplacement source et l'emplacement de destination doivent être différents")
    return check_issue_available(available, quantity)


def below_minimum(on_hand_after: Decimal, minimum: Decimal | None) -> bool:
    """A warning, never a refusal: the manual alerts when a safety quantity is crossed."""
    return minimum is not None and minimum > 0 and on_hand_after < minimum


def require_cost(voucher_type: str, lines: list[dict]) -> Result[None]:
    """A receipt without a unit cost would leave the weighted average undefined."""
    if voucher_type == "receipt" and any(line.get("unit_cost") is None for line in lines):
        return Err("COST_REQUIRED", "every receipt line needs a unit cost", "chaque ligne de réception exige un coût unitaire")
    return Ok(None)


def check_lines(voucher_type: str, lines: list[dict]) -> Result[None]:
    if not lines:
        return Err("NO_LINES", "a voucher needs at least one line", "un bon doit comporter au moins une ligne")
    if any(Decimal(str(line["quantity"])) <= 0 for line in lines):
        return Err("INVALID_QUANTITY", "line quantities must be positive", "les quantités doivent être positives")
    return require_cost(voucher_type, lines)

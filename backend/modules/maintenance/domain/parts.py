from __future__ import annotations

from core.domain.result import Err, Ok, Result


def split_line(*, quantity: float, issue_quantity: float, available: float) -> Result[tuple[float, float]]:
    """Split a requested line between what is issued from stock now and what is
    left to purchase. `issue_quantity` must fit both the requested quantity and
    what is actually available at the chosen location.
    """
    if issue_quantity < 0 or issue_quantity > quantity:
        return Err(
            "INVALID_QUANTITY",
            "issue_quantity must be between 0 and the requested quantity",
            "la quantité à sortir doit être comprise entre 0 et la quantité demandée",
        )
    if issue_quantity > available:
        return Err(
            "INSUFFICIENT_STOCK",
            "issue_quantity exceeds what is available at this location",
            "la quantité à sortir dépasse le disponible à cet emplacement",
        )
    return Ok((issue_quantity, quantity - issue_quantity))


def fulfilment(issued: float | None, purchase: float | None) -> str | None:
    """How a part request line was decided, derived for display -- never stored."""
    if issued is None and purchase is None:
        return None
    has_issued = bool(issued)
    has_purchase = bool(purchase)
    if has_issued and has_purchase:
        return "split"
    if has_purchase:
        return "purchase"
    return "stock"

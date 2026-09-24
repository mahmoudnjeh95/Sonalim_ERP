"""Rules for the figures a packing row is derived from instead of typed."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

_FORMAT_NAME = {"packet": "Sachet", "carton": "Carton", "sac": "Sac"}


def packing_type_label(*, packaging_format: str | None, net_weight_grams: float | None) -> str | None:
    """'Sachet 500 g': the product's packaging format and net weight, as the paper fiche writes it."""
    name = _FORMAT_NAME.get(packaging_format or "")
    weight = None
    if net_weight_grams and net_weight_grams > 0:
        grams = float(net_weight_grams)
        weight = f"{int(grams)} g" if grams == int(grams) else f"{grams:g} g"
    return " ".join(part for part in (name, weight) if part) or None


def resolve_packing_order(
    *,
    given_of_id: str | None,
    run_of_id: str | None,
    shift_orders: Mapping[str, str | None],
    product_id: str | None,
) -> tuple[str | None, str | None]:
    """The work order a packing row belongs to: `(of_id, None)`, or `(None, why_not)`.

    A run the row names decides it (an old row); then an order the row already holds; then the
    shift's own production: its only order, else the one order whose product is the row's.
    `shift_orders` maps each distinct order of the shift's runs to that order's own product.
    """
    if run_of_id:
        return run_of_id, None
    if given_of_id:
        return given_of_id, None
    if not shift_orders:
        return None, "PRODUCTION_FIRST"
    if len(shift_orders) == 1:
        return next(iter(shift_orders)), None
    matching = [of_id for of_id, of_product in shift_orders.items() if product_id and of_product == product_id]
    if len(matching) == 1:
        return matching[0], None
    return None, "OF_AMBIGUOUS"


def pick_packaging_location(locations: Iterable[str | None]) -> tuple[str | None, bool]:
    """The one store all of a row's packaging comes from: `(location, conflict)`.

    Stock posting draws every packaging item of a row from a single store, so items with
    different default stores cannot be posted as one row: that is a conflict, not a guess.
    """
    found = {location for location in locations if location}
    if len(found) == 1:
        return next(iter(found)), False
    return None, len(found) > 1

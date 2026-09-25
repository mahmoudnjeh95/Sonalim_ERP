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


def carton_waste_owners(
    packing_rows: Iterable[tuple[str, str | None]], waste_lines: Iterable[tuple[str, str | None, str | None]]
) -> dict[str, str]:
    """Which packing row each lost-carton line belongs to: `{line id: packing row id}`.

    `packing_rows` are `(id, carton_product_id)` in the shift's order; `waste_lines` are
    `(id, product_id, packing_row_id)` packaging-waste lines. A line naming a carton belongs to
    the row it names when that row packs with that carton, else to the first row that does.
    A line whose item no row packs with belongs to none: it stays a plain packaging loss.
    """
    carton_of = {}
    first_with: dict[str, str] = {}
    for row_id, carton in packing_rows:
        carton_of[row_id] = carton
        if carton and carton not in first_with:
            first_with[carton] = row_id
    owners: dict[str, str] = {}
    for line_id, product_id, packing_row_id in waste_lines:
        if not product_id:
            continue
        if packing_row_id and carton_of.get(packing_row_id) == product_id:
            owners[line_id] = packing_row_id
        elif product_id in first_with:
            owners[line_id] = first_with[product_id]
    return owners

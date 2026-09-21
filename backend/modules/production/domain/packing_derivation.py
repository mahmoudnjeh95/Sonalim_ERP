"""Rules for the figures a packing row is derived from instead of typed."""
from __future__ import annotations

from collections.abc import Iterable

_FORMAT_NAME = {"packet": "Sachet", "carton": "Carton", "sac": "Sac"}


def packing_type_label(*, packaging_format: str | None, net_weight_grams: float | None) -> str | None:
    """'Sachet 500 g': the product's packaging format and net weight, as the paper fiche writes it."""
    name = _FORMAT_NAME.get(packaging_format or "")
    weight = None
    if net_weight_grams and net_weight_grams > 0:
        grams = float(net_weight_grams)
        weight = f"{int(grams)} g" if grams == int(grams) else f"{grams:g} g"
    return " ".join(part for part in (name, weight) if part) or None


def pick_packaging_location(locations: Iterable[str | None]) -> tuple[str | None, bool]:
    """The one store all of a row's packaging comes from: `(location, conflict)`.

    Stock posting draws every packaging item of a row from a single store, so items with
    different default stores cannot be posted as one row: that is a conflict, not a guess.
    """
    found = {location for location in locations if location}
    if len(found) == 1:
        return next(iter(found)), False
    return None, len(found) > 1

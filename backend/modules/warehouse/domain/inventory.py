from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CountResult:
    """Outcome of a line's counts. `final_qty` is None until the counts settle."""

    final_qty: Decimal | None
    variance: Decimal | None
    needs_third: bool
    observation_required: bool


def resolve_count(theoretical: Decimal, count_1: Decimal | None, count_2: Decimal | None, count_3: Decimal | None) -> CountResult:
    """Two equal counts settle the line; two different ones need a third, which then decides.

    One sign convention throughout: variance = final − theoretical (positive means more was found
    than the books say). An observation is mandatory whenever the variance is not zero."""
    if count_1 is None or count_2 is None:
        return CountResult(None, None, False, False)
    if count_1 == count_2:
        final = count_1
    elif count_3 is None:
        return CountResult(None, None, True, False)
    else:
        final = count_3
    variance = final - theoretical
    return CountResult(final, variance, False, variance != 0)

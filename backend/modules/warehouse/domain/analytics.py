"""Pure warehouse KPI rules -- no database, no clock.

Everything here is a calculation on figures the service layer has already
fetched, so the rules a manager reads a stock KPI by (how many days of cover
is "critical", when a shelf counts as dormant, which movements consume stock)
are testable on their own and shared by every screen that shows them.
"""
from __future__ import annotations

from dataclasses import dataclass

# Movements that take stock *out of the plant's usable inventory*. A transfer
# between two shelves and a reservation are not consumption -- the goods are
# still here -- so they are deliberately excluded when measuring how fast a
# product is used up. A customer shipment is: it is exactly how finished goods
# get used up.
CONSUMPTION_MOVE_TYPES = frozenset({"issue", "production_consumption", "send_to_production", "shipment"})

# Movements that bring stock in from outside the plant or out of production.
# `production_consumption_reversal` is material a reversed production report put
# back: it arrives, but it is not consumption going negative -- it is its own type
# so the unsigned row is never misread as one more consumption.
INBOUND_MOVE_TYPES = frozenset({"receipt", "production", "production_consumption_reversal"})

# Movements that leave the location they are recorded on. `transfer_out` is
# included here (and not above): it does leave *this* location, it just does
# not leave the plant. `production_reversal` is finished goods (or a regrind
# receipt) a reversal took back out.
OUTBOUND_MOVE_TYPES = CONSUMPTION_MOVE_TYPES | frozenset({"transfer_out", "production_reversal"})

# Movements a human keyed in to make the books match the shelf. Their volume
# is the inventory-accuracy signal: a warehouse that needs many corrections
# has a recording problem somewhere upstream.
CORRECTION_MOVE_TYPES = frozenset({"adjustment", "admin_correction"})

# Days-of-cover thresholds. Below `CRITICAL` the next shortage is this week's
# problem; below `WARNING` a purchase order should already be on its way.
COVERAGE_CRITICAL_DAYS = 7.0
COVERAGE_WARNING_DAYS = 21.0


@dataclass(frozen=True)
class Coverage:
    on_hand: float
    avg_daily_consumption: float
    # None means "no consumption in the window": the stock is not being used up,
    # so a number of days would be meaningless (infinite), not zero.
    days_of_cover: float | None
    status: str  # "out" | "critical" | "warning" | "ok" | "idle"


def signed_quantity(move_type: str, quantity: float) -> float:
    """A move row stores an unsigned quantity and encodes direction in its
    type; corrections already carry their own sign. Same rule as the
    frontend's `signedMoveQuantity` so a chart and a KPI never disagree."""
    if move_type in CORRECTION_MOVE_TYPES:
        return quantity
    if move_type in OUTBOUND_MOVE_TYPES:
        return -abs(quantity)
    if move_type in INBOUND_MOVE_TYPES or move_type == "transfer_in":
        return abs(quantity)
    # reservation / reservation_released / reservation_expired never touch on-hand.
    return 0.0


def average_daily_consumption(consumed_quantity: float, window_days: int) -> float:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    return max(consumed_quantity, 0.0) / window_days


def coverage(on_hand: float, consumed_quantity: float, window_days: int) -> Coverage:
    """How long the shelf lasts at the recent rate of use.

    `consumed_quantity` is the total taken out over the last `window_days`.
    A product nobody has used in the window is `idle`, not `ok`: it may be
    obsolete stock rather than a healthy one, and the screen should say so.
    """
    daily = average_daily_consumption(consumed_quantity, window_days)
    if on_hand <= 0:
        return Coverage(on_hand=on_hand, avg_daily_consumption=daily, days_of_cover=0.0, status="out")
    if daily <= 0:
        return Coverage(on_hand=on_hand, avg_daily_consumption=0.0, days_of_cover=None, status="idle")
    days = on_hand / daily
    if days < COVERAGE_CRITICAL_DAYS:
        status = "critical"
    elif days < COVERAGE_WARNING_DAYS:
        status = "warning"
    else:
        status = "ok"
    return Coverage(on_hand=on_hand, avg_daily_consumption=daily, days_of_cover=days, status=status)


def is_dormant(on_hand: float, idle_days: float | None, dormant_after_days: int) -> bool:
    """Stock that sits without moving. A product that has never moved at all
    (`idle_days` None) but has stock on hand is dormant too -- an opening
    balance nobody touched is exactly the case to surface."""
    if on_hand <= 0:
        return False
    if idle_days is None:
        return True
    return idle_days >= dormant_after_days


def stock_value(on_hand: float, unit_cost: float | None) -> float | None:
    """Value at the product's standard (purchase) cost. None when the catalog
    has no cost for it -- a 0 would silently understate the total."""
    if unit_cost is None or unit_cost <= 0:
        return None
    return on_hand * unit_cost

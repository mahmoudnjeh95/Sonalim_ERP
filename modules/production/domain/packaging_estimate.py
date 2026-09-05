"""Turning a tonnage into an expected packet and carton count, and comparing it
to what the line actually tallied.

Phase 9, decisions 17-22. This module is pure arithmetic on purpose: both ecarts
-- the one shown at the validation desk and the quality-adjusted one shown on the
OF -- come through here, so there is exactly one place where a packet count is
derived from a weight, and exactly one sign convention.

**The sign convention.** A variance is `actual - expected`. Negative means the
line has fewer good packets than the weight it reported says it should: product
is unaccounted for. Positive means more packets than the tonnage supports, which
is usually a mis-weigh rather than a windfall.

**Why cartons are never quality-adjusted.** Quality pulls packets out of cartons
after the fact; it does not un-build the carton. The number of cartons the line
made is what it is, so the carton comparison is always tonnage-as-packed against
cartons-as-packed. Only the packet side takes the subtraction of decision 21.
"""

from __future__ import annotations

from dataclasses import dataclass

GRAMS_PER_TONNE = 1_000_000

# Decision 22. Colours a number; no validation path consults it.
DEFAULT_TOLERANCE_PERCENT = 2.0


@dataclass(frozen=True)
class PackagingEstimate:
    """What a tonnage should have produced, given the product's packaging."""

    packets: float | None
    cartons: float | None
    # Why a figure is None, so a screen can say "no net weight recorded" instead
    # of showing an empty cell that looks like a bug.
    missing: tuple[str, ...] = ()


def estimate_packaging(
    *,
    tonnage: float,
    net_weight_grams: float | None,
    packets_per_carton: float | None,
) -> PackagingEstimate:
    """Expected packets and cartons for a tonnage.

    Both figures are deliberately fallible. Without a net weight there is no way
    to turn a weight into a count, and inventing one would produce an ecart that
    looks authoritative and means nothing. A missing `packets_per_carton` is not
    an omission at all for products like the 4.54 kg sac, which is its own selling
    unit -- there is simply no carton line.
    """
    missing: list[str] = []

    if net_weight_grams is None or net_weight_grams <= 0:
        missing.append("net_weight_grams")
        return PackagingEstimate(packets=None, cartons=None, missing=tuple(missing))

    packets = tonnage * GRAMS_PER_TONNE / net_weight_grams

    if packets_per_carton is None or packets_per_carton <= 0:
        missing.append("packets_per_carton")
        return PackagingEstimate(packets=packets, cartons=None, missing=tuple(missing))

    return PackagingEstimate(packets=packets, cartons=packets / packets_per_carton)


@dataclass(frozen=True)
class PackagingVariance:
    """One ecart, with every term it was computed from kept alongside it.

    The inputs travel with the answer because an ecart nobody can decompose is an
    ecart nobody will trust: a supervisor looking at "-412 packets" needs to see
    which net weight produced it before deciding whether the line lost product or
    someone typed the wrong tonnage.
    """

    tonnage: float
    net_weight_grams: float | None
    packets_per_carton: float | None

    expected_packets: float | None
    expected_cartons: float | None

    counted_packets: float
    counted_cartons: float

    # Decision 21. `rejected` is what quality has taken out of sellable stock and
    # not given back; `undecided` is the part of it still awaiting a disposition,
    # reported separately so an open case does not read as a permanent loss.
    rejected_packets: float
    undecided_packets: float
    good_packets: float

    packet_variance: float | None
    packet_variance_ratio: float | None
    carton_variance: float | None
    carton_variance_ratio: float | None

    tolerance_percent: float
    within_tolerance: bool | None
    missing: tuple[str, ...]


def _ratio(variance: float | None, expected: float | None) -> float | None:
    if variance is None or expected is None or expected == 0:
        return None
    return variance / expected


def compute_variance(
    *,
    tonnage: float,
    net_weight_grams: float | None,
    packets_per_carton: float | None,
    counted_packets: float,
    counted_cartons: float,
    rejected_packets: float = 0.0,
    undecided_packets: float = 0.0,
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT,
) -> PackagingVariance:
    """Compare a tonnage's expected packaging against what was counted.

    Leaving `rejected_packets` at zero gives the ecart de conditionnement -- the
    scale against the counter, complete the moment a report is validated. Passing
    quality's subtraction gives the ecart net. Same arithmetic either way, which
    is why they can never drift apart.
    """
    estimate = estimate_packaging(
        tonnage=tonnage,
        net_weight_grams=net_weight_grams,
        packets_per_carton=packets_per_carton,
    )

    good_packets = counted_packets - rejected_packets

    packet_variance = None if estimate.packets is None else good_packets - estimate.packets
    carton_variance = None if estimate.cartons is None else counted_cartons - estimate.cartons
    packet_ratio = _ratio(packet_variance, estimate.packets)

    # Tolerance is judged on the packet side alone: cartons are a rounded-down
    # consequence of packets, so a part-full carton would trip a tolerance that
    # the packets themselves pass.
    within = None if packet_ratio is None else abs(packet_ratio) <= tolerance_percent / 100

    return PackagingVariance(
        tonnage=tonnage,
        net_weight_grams=net_weight_grams,
        packets_per_carton=packets_per_carton,
        expected_packets=estimate.packets,
        expected_cartons=estimate.cartons,
        counted_packets=counted_packets,
        counted_cartons=counted_cartons,
        rejected_packets=rejected_packets,
        undecided_packets=undecided_packets,
        good_packets=good_packets,
        packet_variance=packet_variance,
        packet_variance_ratio=packet_ratio,
        carton_variance=carton_variance,
        carton_variance_ratio=_ratio(carton_variance, estimate.cartons),
        tolerance_percent=tolerance_percent,
        within_tolerance=within,
        missing=estimate.missing,
    )


def variance_to_json(variance: PackagingVariance) -> dict:
    """Wire shape. Kept beside the dataclass so the two cannot drift."""
    return {
        "tonnage": variance.tonnage,
        "net_weight_grams": variance.net_weight_grams,
        "packets_per_carton": variance.packets_per_carton,
        "expected_packets": variance.expected_packets,
        "expected_cartons": variance.expected_cartons,
        "counted_packets": variance.counted_packets,
        "counted_cartons": variance.counted_cartons,
        "rejected_packets": variance.rejected_packets,
        "undecided_packets": variance.undecided_packets,
        "good_packets": variance.good_packets,
        "packet_variance": variance.packet_variance,
        "packet_variance_ratio": variance.packet_variance_ratio,
        "carton_variance": variance.carton_variance,
        "carton_variance_ratio": variance.carton_variance_ratio,
        "tolerance_percent": variance.tolerance_percent,
        "within_tolerance": variance.within_tolerance,
        "missing": list(variance.missing),
    }

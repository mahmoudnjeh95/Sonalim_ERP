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

**Decision 23 — the machine/carton ecart.** The two figures above both compare
the line against the weighed tonnage. Neither compares the line against itself:
the packet count is an electronic tally off the packaging machine's HMI, the
carton count is what the floor physically counted, and the two can disagree
even when the scale is right — a sensor miscount, a carton closed short, a
packet that never made it into a box. `machine_carton_variance` is that third
comparison: `counted_packets - (counted_cartons * packets_per_carton)`. It only
exists for products that have a carton tier at all; a sac counted directly has
nothing to compare its packet tally against.

**Decision 25 — tonnage is no longer typed on the packing report.** It used to
be re-entered here (decision 17), but the plant already weighs it once, on the
daily report the line files before packaging -- re-typing it on the packing
report was a second, independent chance to mistype the same number, not a
second measurement. `tonnage` is `None` wherever the caller has no daily-report
figure to attribute (a single packing report has no natural share of an OF's
daily tonnage), and a `None` tonnage is treated exactly like a missing net
weight: the weight-based figures go absent rather than wrong, and
`machine_carton_variance` -- which needs no tonnage at all -- still stands on
its own.

**`waste_cartons` -- cartons the line counted that never held sellable product.**
A damaged or short-filled carton still gets swept into the floor's physical
carton tally (`counted_cartons`) the same as a good one, but it has no packets
to compare against and no business posting as finished goods. Left at the
default of zero, nothing here changes. Passed a figure, `good_cartons =
counted_cartons - waste_cartons` is what the carton-side arithmetic actually
uses -- `carton_variance` against the tonnage estimate, and the carton side of
`machine_carton_variance` -- so a shift that already told the report "8 of
these were empty" does not also have that same 8 read back as unaccounted
product. This is deliberately distinct from quality's `rejected_packets`: a
rejected packet was real product in a real carton the line still built (the
carton count is right, only the fate of what was inside it is not), while a
waste carton was never real product at all.
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
    tonnage: float | None,
    net_weight_grams: float | None,
    packets_per_carton: float | None,
) -> PackagingEstimate:
    """Expected packets and cartons for a tonnage.

    Both figures are deliberately fallible. Without a tonnage to attribute
    (decision 25) or a net weight there is no way to turn a weight into a count,
    and inventing one would produce an ecart that looks authoritative and means
    nothing. A missing `packets_per_carton` is not an omission at all for
    products like the 4.54 kg sac, which is its own selling unit -- there is
    simply no carton line.
    """
    missing: list[str] = []
    if tonnage is None:
        missing.append("tonnage")
    if net_weight_grams is None or net_weight_grams <= 0:
        missing.append("net_weight_grams")
    if tonnage is None or net_weight_grams is None or net_weight_grams <= 0:
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

    tonnage: float | None
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

    # Cartons the line counted that never held product -- empty or damaged,
    # swept into `counted_cartons` the same as a good one. `good_cartons` is
    # what the carton-side arithmetic below is actually judged against.
    waste_cartons: float
    good_cartons: float

    packet_variance: float | None
    packet_variance_ratio: float | None
    carton_variance: float | None
    carton_variance_ratio: float | None

    # Decision 23. The machine's tally against what the floor actually boxed --
    # independent of the weighed tonnage, and of quality's later subtraction.
    machine_carton_variance: float | None
    machine_carton_variance_ratio: float | None

    tolerance_percent: float
    within_tolerance: bool | None
    missing: tuple[str, ...]


def _ratio(variance: float | None, expected: float | None) -> float | None:
    if variance is None or expected is None or expected == 0:
        return None
    return variance / expected


def compute_variance(
    *,
    tonnage: float | None,
    net_weight_grams: float | None,
    packets_per_carton: float | None,
    counted_packets: float,
    counted_cartons: float,
    rejected_packets: float = 0.0,
    undecided_packets: float = 0.0,
    waste_cartons: float = 0.0,
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT,
) -> PackagingVariance:
    """Compare a tonnage's expected packaging against what was counted.

    Leaving `rejected_packets` at zero gives the ecart de conditionnement -- the
    scale against the counter, complete the moment a report is validated. Passing
    quality's subtraction gives the ecart net. Same arithmetic either way, which
    is why they can never drift apart.

    `waste_cartons` nets out of the carton side the same way `rejected_packets`
    nets out of the packet side -- both scopes (report and OF) pass it the same
    way, so `carton_variance` and `machine_carton_variance` are never inflated by
    a carton the line itself already said was empty.
    """
    estimate = estimate_packaging(
        tonnage=tonnage,
        net_weight_grams=net_weight_grams,
        packets_per_carton=packets_per_carton,
    )

    good_packets = counted_packets - rejected_packets
    good_cartons = counted_cartons - waste_cartons

    packet_variance = None if estimate.packets is None else good_packets - estimate.packets
    carton_variance = None if estimate.cartons is None else good_cartons - estimate.cartons
    packet_ratio = _ratio(packet_variance, estimate.packets)

    # Decision 23. Only meaningful for a product with a carton tier -- a sac has
    # nothing to compare its tally against. `good_cartons` here too: an empty
    # carton has no packets to reconcile the machine's tally against either.
    carton_equivalent_packets = (
        None if packets_per_carton is None or packets_per_carton <= 0 else good_cartons * packets_per_carton
    )
    machine_carton_variance = (
        None if carton_equivalent_packets is None else counted_packets - carton_equivalent_packets
    )

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
        waste_cartons=waste_cartons,
        good_cartons=good_cartons,
        packet_variance=packet_variance,
        packet_variance_ratio=packet_ratio,
        carton_variance=carton_variance,
        carton_variance_ratio=_ratio(carton_variance, estimate.cartons),
        machine_carton_variance=machine_carton_variance,
        machine_carton_variance_ratio=_ratio(machine_carton_variance, carton_equivalent_packets),
        tolerance_percent=tolerance_percent,
        within_tolerance=within,
        missing=estimate.missing,
    )


def finished_quantity_from_count(
    *,
    packets_per_carton: float | None,
    carton_quantity: float,
    packets_counted: float,
    waste_carton_quantity: float = 0.0,
) -> float:
    """What a carton/sac count says actually became finished goods.

    Decision 24, pulled out of `report_stock_service.post_conditionnement_report`
    so the stock quantity and the tonnage below are always the same count read
    two ways rather than two rules that could drift apart. A carton tier makes
    the carton count the source of truth -- only a closed carton is finished
    goods ready to move. `packets_counted` is the fallback for a sac (no carton
    tier) or a report nobody has boxed yet.

    `waste_carton_quantity` is the part of `carton_quantity` the line itself
    says never held sellable product -- empty or damaged cartons swept into the
    same physical tally as a good one. Without subtracting it here, a report
    with waste cartons would post more finished goods than the line actually
    packed; see `packaging_estimate`'s module docstring.
    """
    if packets_per_carton and packets_per_carton > 0 and carton_quantity > 0:
        return max(carton_quantity - waste_carton_quantity, 0.0) * packets_per_carton
    return packets_counted


def tonnage_from_count(
    *,
    net_weight_grams: float | None,
    packets_per_carton: float | None,
    carton_quantity: float,
    packets_counted: float,
    waste_carton_quantity: float = 0.0,
) -> float:
    """The weight a carton/sac count represents, in tonnes.

    The inverse of `estimate_packaging`: instead of turning a weighed tonnage
    into an expected count, this turns the count the line actually reported
    into a weight, via `finished_quantity_from_count`'s same decision-24 rule
    (and its waste-carton subtraction). Zero when the product has no net weight
    configured yet, matching `ConditionnementReportDetail.finished_product_
    quantity`'s own default -- there is nothing to compute from, and a
    validated report cannot carry a missing figure the way an estimate can.
    """
    if net_weight_grams is None or net_weight_grams <= 0:
        return 0.0
    units = finished_quantity_from_count(
        packets_per_carton=packets_per_carton,
        carton_quantity=carton_quantity,
        packets_counted=packets_counted,
        waste_carton_quantity=waste_carton_quantity,
    )
    return units * net_weight_grams / GRAMS_PER_TONNE


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
        "waste_cartons": variance.waste_cartons,
        "good_cartons": variance.good_cartons,
        "packet_variance": variance.packet_variance,
        "packet_variance_ratio": variance.packet_variance_ratio,
        "carton_variance": variance.carton_variance,
        "carton_variance_ratio": variance.carton_variance_ratio,
        "machine_carton_variance": variance.machine_carton_variance,
        "machine_carton_variance_ratio": variance.machine_carton_variance_ratio,
        "tolerance_percent": variance.tolerance_percent,
        "within_tolerance": variance.within_tolerance,
        "missing": list(variance.missing),
    }

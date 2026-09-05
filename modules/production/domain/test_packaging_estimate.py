from modules.production.domain.packaging_estimate import (
    DEFAULT_TOLERANCE_PERCENT,
    compute_variance,
    estimate_packaging,
)


# ---- the estimate itself ------------------------------------------------


def test_a_tonne_of_500g_packets_is_two_thousand_packets():
    estimate = estimate_packaging(tonnage=1, net_weight_grams=500, packets_per_carton=20)
    assert estimate.packets == 2000
    assert estimate.cartons == 100
    assert estimate.missing == ()


def test_the_real_doman_pl_500g_figures():
    # 12.5 t of the SKU that is actually in the catalogue, 20 packets to a carton.
    estimate = estimate_packaging(tonnage=12.5, net_weight_grams=500, packets_per_carton=20)
    assert estimate.packets == 25_000
    assert estimate.cartons == 1250


def test_a_sac_that_is_its_own_selling_unit_has_no_carton_line():
    # doman-pc-4540g-sac: a 4.54 kg sac with no carton. The packet figure still
    # works; the carton figure is absent rather than invented.
    estimate = estimate_packaging(tonnage=4.54, net_weight_grams=4540, packets_per_carton=None)
    assert estimate.packets == 1000
    assert estimate.cartons is None
    assert estimate.missing == ("packets_per_carton",)


def test_without_a_net_weight_nothing_can_be_estimated():
    estimate = estimate_packaging(tonnage=10, net_weight_grams=None, packets_per_carton=20)
    assert estimate.packets is None
    assert estimate.cartons is None
    assert estimate.missing == ("net_weight_grams",)


def test_a_zero_net_weight_is_treated_as_missing_not_as_a_division():
    estimate = estimate_packaging(tonnage=10, net_weight_grams=0, packets_per_carton=20)
    assert estimate.packets is None
    assert estimate.missing == ("net_weight_grams",)


# ---- the ecart ----------------------------------------------------------


def test_a_perfectly_packed_shift_has_no_variance():
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=2000, counted_cartons=100
    )
    assert variance.packet_variance == 0
    assert variance.carton_variance == 0
    assert variance.within_tolerance is True


def test_counting_fewer_packets_than_the_weight_supports_is_negative():
    # The sign convention: actual - expected, so short reads negative.
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=1900, counted_cartons=95
    )
    assert variance.packet_variance == -100
    assert variance.packet_variance_ratio == -0.05
    assert variance.within_tolerance is False


def test_counting_more_packets_than_the_weight_supports_is_positive():
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=2100, counted_cartons=105
    )
    assert variance.packet_variance == 100
    assert variance.within_tolerance is False


def test_quality_rejects_are_subtracted_from_the_counted_side():
    # 2000 packed, 100 rejected by quality, so 1900 good against 2000 expected.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=100,
        rejected_packets=100,
        undecided_packets=40,
    )
    assert variance.good_packets == 1900
    assert variance.packet_variance == -100
    assert variance.undecided_packets == 40


def test_the_same_shift_with_no_quality_subtraction_is_the_ecart_de_conditionnement():
    # Decision 22: the gross ecart is the same arithmetic with rejected at zero,
    # which is why the two ecarts can never drift apart.
    gross = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=2000, counted_cartons=100
    )
    assert gross.packet_variance == 0
    assert gross.rejected_packets == 0


def test_cartons_are_never_quality_adjusted():
    # Quality pulls packets out of cartons; it does not un-build the carton.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=100,
        rejected_packets=500,
    )
    assert variance.packet_variance == -500
    assert variance.carton_variance == 0


def test_a_variance_within_two_percent_passes_the_default_tolerance():
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=1970, counted_cartons=99
    )
    assert variance.tolerance_percent == DEFAULT_TOLERANCE_PERCENT
    assert variance.packet_variance_ratio == -0.015
    assert variance.within_tolerance is True


def test_tolerance_is_judged_on_packets_not_on_the_rounded_carton_count():
    # 99 cartons against an expected 98.5 is a 0.5% carton variance that would
    # otherwise trip a tolerance the packets themselves pass.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=99,
        tolerance_percent=0.1,
    )
    assert variance.packet_variance == 0
    assert variance.within_tolerance is True
    assert variance.carton_variance == -1


def test_a_missing_net_weight_leaves_the_variance_unknown_rather_than_zero():
    variance = compute_variance(
        tonnage=1, net_weight_grams=None, packets_per_carton=20, counted_packets=2000, counted_cartons=100
    )
    assert variance.packet_variance is None
    assert variance.within_tolerance is None
    assert variance.missing == ("net_weight_grams",)
    # The counted side is still reported: it is a fact even when the estimate is not.
    assert variance.counted_packets == 2000


def test_a_shift_that_packed_nothing_has_no_ratio_to_report():
    variance = compute_variance(
        tonnage=0, net_weight_grams=500, packets_per_carton=20, counted_packets=0, counted_cartons=0
    )
    assert variance.expected_packets == 0
    assert variance.packet_variance == 0
    # Dividing by a zero expectation would be a percentage of nothing.
    assert variance.packet_variance_ratio is None
    assert variance.within_tolerance is None

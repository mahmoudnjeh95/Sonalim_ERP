import pytest

from modules.production.domain.packaging_estimate import (
    compute_variance,
    estimate_packaging,
    finished_quantity_from_count,
    tonnage_from_count,
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
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=100,
        tolerance_percent=2.0,
    )
    assert variance.packet_variance == 0
    assert variance.carton_variance == 0
    assert variance.within_tolerance is True


def test_counting_fewer_packets_than_the_weight_supports_is_negative():
    # The sign convention: actual - expected, so short reads negative.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=1900,
        counted_cartons=95,
        tolerance_percent=2.0,
    )
    assert variance.packet_variance == -100
    assert variance.packet_variance_ratio == -0.05
    assert variance.within_tolerance is False


def test_counting_more_packets_than_the_weight_supports_is_positive():
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2100,
        counted_cartons=105,
        tolerance_percent=2.0,
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


def test_a_variance_within_the_configured_tolerance_passes():
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=1970,
        counted_cartons=99,
        tolerance_percent=2.0,
    )
    assert variance.tolerance_percent == 2.0
    assert variance.packet_variance_ratio == -0.015
    assert variance.within_tolerance is True


def test_without_a_configured_tolerance_the_ecart_is_shown_but_not_judged():
    # Nobody chose a tolerance, so there is no verdict to give: the figures stand
    # on their own rather than being coloured against an invented default.
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=1900, counted_cartons=95
    )
    assert variance.packet_variance == -100
    assert variance.packet_variance_ratio == -0.05
    assert variance.tolerance_percent is None
    assert variance.within_tolerance is None


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


# ---- decision 23: machine vs. carton --------------------------------------


def test_a_perfectly_boxed_shift_has_no_machine_carton_variance():
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=2000, counted_cartons=100
    )
    assert variance.machine_carton_variance == 0
    assert variance.machine_carton_variance_ratio == 0


def test_the_machine_overcounts_against_what_was_actually_boxed():
    # The HMI tallied 2000, but only 95 cartons of 20 were actually closed --
    # 1900 packets' worth. 100 packets are unaccounted for on the floor even
    # though the weight-based ecart never sees it here.
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=2000, counted_cartons=95
    )
    assert variance.machine_carton_variance == 100
    assert variance.machine_carton_variance_ratio == pytest.approx(100 / 1900)


def test_a_sac_with_no_carton_tier_has_no_machine_carton_variance():
    variance = compute_variance(
        tonnage=4.54, net_weight_grams=4540, packets_per_carton=None, counted_packets=1000, counted_cartons=0
    )
    assert variance.machine_carton_variance is None
    assert variance.machine_carton_variance_ratio is None


def test_machine_carton_variance_is_not_quality_adjusted():
    # Same reasoning as the carton side: it compares the machine against the
    # floor's own carton count, not against the estimate quality later corrects.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=100,
        rejected_packets=500,
    )
    assert variance.machine_carton_variance == 0


# ---- waste cartons: counted but never held product ------------------------


def test_waste_cartons_are_subtracted_from_the_carton_side():
    # 100 cartons counted, 8 of them empty/damaged. The carton variance is
    # judged against the 92 that actually could have held product.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=100,
        waste_cartons=8,
    )
    assert variance.good_cartons == 92
    assert variance.carton_variance == -8


def test_waste_cartons_are_excluded_from_the_machine_carton_comparison_too():
    # The Doman PL 500gr example: 15532 cartons counted, 20 of quality's rejects
    # plus 8 waste cartons (28 total) never went through the machine's counter,
    # so its 310080-packet tally is short by exactly 28 cartons' worth -- but
    # only the 8 waste cartons are cartons with nothing inside them at all.
    variance = compute_variance(
        tonnage=None,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=310_080,
        counted_cartons=15_532,
        waste_cartons=8,
    )
    # good_cartons = 15524, so the equivalent is 310480 packets against a
    # 310080 machine tally -- the remaining -400 is the 20 rejected packets'
    # worth of real cartons the machine still never scanned, which is not
    # this field's job to explain (see the packet-side rejected_packets).
    assert variance.good_cartons == 15_524
    assert variance.machine_carton_variance == -400


def test_waste_cartons_default_to_zero_so_existing_callers_are_unaffected():
    variance = compute_variance(
        tonnage=1, net_weight_grams=500, packets_per_carton=20, counted_packets=2000, counted_cartons=100
    )
    assert variance.waste_cartons == 0
    assert variance.good_cartons == variance.counted_cartons


def test_waste_cartons_are_distinct_from_quality_rejected_packets():
    # A rejected packet was real product in a real carton the line still
    # built -- the carton count is right, only what was inside it is not.
    # A waste carton was never real product at all. The two subtract from
    # opposite sides and never touch each other's arithmetic.
    variance = compute_variance(
        tonnage=1,
        net_weight_grams=500,
        packets_per_carton=20,
        counted_packets=2000,
        counted_cartons=100,
        rejected_packets=20,
        waste_cartons=8,
    )
    assert variance.good_packets == 1980
    assert variance.good_cartons == 92
    assert variance.carton_variance == -8
    assert variance.packet_variance == -20


# ---- turning a count back into a tonnage ----------------------------------


def test_a_carton_of_500g_packets_weighs_ten_kilos():
    # 20 packets to a carton, 500g each: one carton is 10kg, i.e. 0.01 tonnes.
    assert finished_quantity_from_count(packets_per_carton=20, carton_quantity=1, packets_counted=0) == 20
    assert tonnage_from_count(
        net_weight_grams=500, packets_per_carton=20, carton_quantity=1, packets_counted=0
    ) == pytest.approx(0.01)


def test_a_carton_of_200g_packets_weighs_eight_kilos():
    # 40 packets to a carton, 200g each: one carton is 8kg, i.e. 0.008 tonnes.
    assert tonnage_from_count(
        net_weight_grams=200, packets_per_carton=40, carton_quantity=1, packets_counted=0
    ) == pytest.approx(0.008)


def test_a_sac_has_no_carton_tier_so_the_tally_leads():
    # doman-pc-4540g-sac: no carton line at all, so packets_counted (the sac
    # tally) is what both the stock quantity and the tonnage are read from.
    assert finished_quantity_from_count(packets_per_carton=None, carton_quantity=0, packets_counted=1000) == 1000
    assert tonnage_from_count(
        net_weight_grams=4540, packets_per_carton=None, carton_quantity=0, packets_counted=1000
    ) == pytest.approx(4.54)


def test_waste_cartons_do_not_become_finished_goods():
    # 100 cartons counted, 8 empty/damaged: only 92 are real finished goods,
    # 1840 packets' worth -- not 2000. Posting the raw count would overstate
    # what actually moved into stock.
    assert (
        finished_quantity_from_count(
            packets_per_carton=20, carton_quantity=100, packets_counted=0, waste_carton_quantity=8
        )
        == 1840
    )
    assert tonnage_from_count(
        net_weight_grams=500,
        packets_per_carton=20,
        carton_quantity=100,
        packets_counted=0,
        waste_carton_quantity=8,
    ) == pytest.approx(0.92)


def test_waste_carton_quantity_cannot_drive_the_finished_count_negative():
    # Defensive only -- validate_conditionnement_detail already refuses a
    # waste_carton_quantity greater than carton_quantity before this is
    # reached, but the arithmetic itself must not produce a negative count.
    assert (
        finished_quantity_from_count(
            packets_per_carton=20, carton_quantity=5, packets_counted=0, waste_carton_quantity=8
        )
        == 0
    )


def test_an_uncounted_carton_falls_back_to_the_machine_tally():
    # Same decision-24 fallback as a sac: zero cartons counted means there is no
    # carton figure to lead with, so the packet tally is used instead.
    assert finished_quantity_from_count(packets_per_carton=20, carton_quantity=0, packets_counted=150) == 150


def test_tonnage_from_count_is_zero_without_a_net_weight():
    # Matches finished_product_quantity's own default -- there is nothing to
    # compute from, and unlike the estimate this field cannot carry a "missing".
    assert tonnage_from_count(
        net_weight_grams=None, packets_per_carton=20, carton_quantity=10, packets_counted=0
    ) == 0.0
    assert tonnage_from_count(
        net_weight_grams=0, packets_per_carton=20, carton_quantity=10, packets_counted=0
    ) == 0.0

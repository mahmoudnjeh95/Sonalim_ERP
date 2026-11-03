from decimal import Decimal

from modules.warehouse.domain.inventory import resolve_count

D = Decimal


def test_matching_counts_equal_to_theory_need_no_observation():
    result = resolve_count(D("10"), D("10"), D("10"), None)
    assert (result.final_qty, result.variance, result.observation_required) == (D("10"), D("0"), False)


def test_matching_counts_that_differ_from_theory_need_an_observation():
    result = resolve_count(D("10"), D("8"), D("8"), None)
    assert (result.final_qty, result.variance, result.observation_required) == (D("8"), D("-2"), True)


def test_differing_counts_need_a_third():
    result = resolve_count(D("10"), D("8"), D("9"), None)
    assert result.needs_third and result.final_qty is None


def test_third_count_decides():
    result = resolve_count(D("10"), D("8"), D("9"), D("10"))
    assert (result.final_qty, result.variance, result.observation_required) == (D("10"), D("0"), False)
    found_more = resolve_count(D("10"), D("8"), D("9"), D("12"))
    assert found_more.variance == D("2") and found_more.observation_required


def test_unfinished_counts_are_unresolved():
    assert resolve_count(D("10"), None, None, None).final_qty is None
    assert resolve_count(D("10"), D("10"), None, None).needs_third is False

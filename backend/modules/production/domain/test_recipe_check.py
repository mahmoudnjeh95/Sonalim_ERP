"""Domain tests for the recipe limit check. No database.

Every case here is about what the supervisor is told. The one thing none of them
assert is a refusal, because the check never refuses anything — that is the whole
design, and it is worth the file being explicit about it.
"""
from __future__ import annotations

from modules.production.domain.recipe_check import (
    PouredComponent,
    RecipeLimit,
    check_recipe_limits,
)

SEMOULE = "product-semoule"
REBROYAT = "product-rebroyat"
ADDITIVE = "product-additive"


def _limits(*specs) -> list[RecipeLimit]:
    return [
        RecipeLimit(
            component_product_id=product_id,
            min_percentage=minimum,
            max_percentage=maximum,
            is_hard_limit=hard,
        )
        for product_id, minimum, maximum, hard in specs
    ]


# --- the ordinary case ------------------------------------------------------


def test_a_mix_inside_its_limits_says_nothing():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 900), PouredComponent(REBROYAT, 100)],
        _limits((SEMOULE, 85, 95, True), (REBROYAT, 5, 15, False)),
    )
    assert findings == []


def test_the_share_is_of_the_mix_not_of_the_plan():
    """90 kg of semoule in a 100 kg mix is 90%, whatever the OF planned to make."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 90), PouredComponent(REBROYAT, 10)],
        _limits((SEMOULE, 89.9, 90.1, True), (REBROYAT, 0, 100, False)),
    )
    assert findings == []


# --- out of range -----------------------------------------------------------


def test_a_component_below_its_minimum_is_reported():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 700), PouredComponent(REBROYAT, 300)],
        _limits((SEMOULE, 85, 95, True), (REBROYAT, 5, 15, False)),
    )
    codes = {(f.code, f.component_product_id) for f in findings}
    assert ("BELOW_MINIMUM", SEMOULE) in codes


def test_a_component_above_its_maximum_is_reported():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 700), PouredComponent(REBROYAT, 300)],
        _limits((SEMOULE, 85, 95, True), (REBROYAT, 5, 15, False)),
    )
    above = [f for f in findings if f.code == "ABOVE_MAXIMUM"]
    assert [f.component_product_id for f in above] == [REBROYAT]
    assert above[0].actual_percentage == 30


def test_the_finding_carries_the_limits_it_broke():
    """The screen shows "12% (limit 5–10%)", so the numbers travel with it."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 880), PouredComponent(REBROYAT, 120)],
        _limits((REBROYAT, 5, 10, False)),
    )
    finding = next(f for f in findings if f.component_product_id == REBROYAT)
    assert finding.actual_percentage == 12
    assert finding.min_percentage == 5
    assert finding.max_percentage == 10


def test_a_hard_limit_is_marked_hard_and_a_soft_one_soft():
    """The severity says how far outside the formula the plant is. It does not
    mean the hard one is blocked — nothing here blocks."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 500), PouredComponent(REBROYAT, 500)],
        _limits((SEMOULE, 85, 95, True), (REBROYAT, 5, 15, False)),
    )
    by_product = {f.component_product_id: f for f in findings}
    assert by_product[SEMOULE].severity == "hard"
    assert by_product[REBROYAT].severity == "soft"


# --- the recipe's own limits, and nothing added to them ---------------------


def test_exactly_on_the_limit_is_within_it():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 90), PouredComponent(REBROYAT, 10)],
        _limits((SEMOULE, 90, 95, True), (REBROYAT, 0, 100, False)),
    )
    assert findings == []


def test_any_share_outside_the_recipe_limit_reports_even_a_hair_outside():
    # No allowance is invented on top of the recipe's own min/max.
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 89.98), PouredComponent(REBROYAT, 10.02)],
        _limits((SEMOULE, 90, 95, True), (REBROYAT, 0, 100, False)),
    )
    assert [f.code for f in findings if f.component_product_id == SEMOULE] == ["BELOW_MINIMUM"]


def test_a_real_drift_still_reports():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 88), PouredComponent(REBROYAT, 12)],
        _limits((SEMOULE, 90, 95, True)),
    )
    assert [f.code for f in findings if f.component_product_id == SEMOULE] == ["BELOW_MINIMUM"]


# --- components missing and unexpected --------------------------------------


def test_a_component_the_recipe_names_but_nobody_poured_is_reported():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 1000)],
        _limits((SEMOULE, 85, 95, True), (ADDITIVE, 1, 3, False)),
    )
    missing = [f for f in findings if f.code == "COMPONENT_NOT_POURED"]
    assert [f.component_product_id for f in missing] == [ADDITIVE]
    assert missing[0].actual_percentage == 0


def test_a_missing_component_is_not_also_reported_as_below_minimum():
    """One finding per problem. "Not poured" already says everything "0% is below
    1%" would, and saying both twice as loudly is how a panel gets ignored."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 1000)],
        _limits((SEMOULE, 85, 100, True), (ADDITIVE, 1, 3, False)),
    )
    assert [f.code for f in findings] == ["COMPONENT_NOT_POURED"]


def test_a_product_the_recipe_does_not_name_is_reported():
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 900), PouredComponent(ADDITIVE, 100)],
        _limits((SEMOULE, 85, 95, True)),
    )
    unexpected = [f for f in findings if f.code == "NOT_IN_RECIPE"]
    assert [f.component_product_id for f in unexpected] == [ADDITIVE]
    assert unexpected[0].actual_percentage == 10


def test_an_unexpected_product_is_never_marked_hard():
    """There is no limit to break: the recipe says nothing about it at all."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 900), PouredComponent(ADDITIVE, 100)],
        _limits((SEMOULE, 0, 100, True)),
    )
    assert [f.severity for f in findings if f.code == "NOT_IN_RECIPE"] == ["soft"]


# --- degenerate input -------------------------------------------------------


def test_an_empty_mix_produces_no_findings():
    """An OF whose first shift has not reported yet has broken nothing."""
    assert check_recipe_limits([], _limits((SEMOULE, 85, 95, True))) == []


def test_a_mix_of_zeroes_produces_no_findings():
    assert (
        check_recipe_limits([PouredComponent(SEMOULE, 0)], _limits((SEMOULE, 85, 95, True))) == []
    )


def test_no_recipe_means_only_the_mix_is_described():
    """An OF with no recipe cannot violate one. Every poured product is simply
    unnamed by a formula that does not exist."""
    findings = check_recipe_limits([PouredComponent(SEMOULE, 1000)], [])
    assert [f.code for f in findings] == ["NOT_IN_RECIPE"]


def test_the_same_product_poured_twice_is_one_component():
    """Two shifts each pouring semoule is 1000 kg of semoule, not two components
    of 500 measured against the limit separately."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 500), PouredComponent(SEMOULE, 500)],
        _limits((SEMOULE, 99, 100, True)),
    )
    assert findings == []


def test_a_negative_total_is_reported_instead_of_percentages():
    """A component reversed more than it was poured leaves no honest denominator:
    counting it shrinks the mix, dropping it inflates everything else. Report the
    anomaly and say nothing about shares, rather than invent a confident number."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 900), PouredComponent(REBROYAT, -100)],
        _limits((SEMOULE, 85, 95, True)),
    )
    assert [f.code for f in findings] == ["NEGATIVE_QUANTITY"]
    assert findings[0].component_product_id == REBROYAT
    assert findings[0].actual_percentage is None


def test_a_component_reversed_exactly_to_zero_is_not_an_anomaly():
    """Zero is a component that was poured and fully reversed. That is ordinary,
    and the recipe still has something to say about it being absent."""
    findings = check_recipe_limits(
        [PouredComponent(SEMOULE, 900), PouredComponent(REBROYAT, 100), PouredComponent(REBROYAT, -100)],
        _limits((SEMOULE, 0, 100, True), (REBROYAT, 5, 15, False)),
    )
    assert [f.code for f in findings] == ["COMPONENT_NOT_POURED"]

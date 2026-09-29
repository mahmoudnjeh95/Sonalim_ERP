from dataclasses import replace
from decimal import Decimal

import pytest

from modules.payroll.domain.rules import BASE, RuleSetIncomplete
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal


def test_require_names_the_missing_component_in_both_languages():
    rules = synthetic_rule_set()
    assert rules.require(BASE).kind == "earning"
    with pytest.raises(RuleSetIncomplete) as missing:
        rules.require("NOPE")
    assert (missing.value.what_en, missing.value.what_fr) == ("component NOPE", "rubrique NOPE")


def test_overtime_multiplier_by_band():
    rules = synthetic_rule_set()
    assert rules.overtime_multiplier("day") == D("1.5")
    assert rules.overtime_multiplier("night") == D(2)


def test_a_band_without_rate_makes_the_rule_set_incomplete():
    rules = replace(synthetic_rule_set(), overtime_rates=())
    with pytest.raises(RuleSetIncomplete):
        rules.overtime_multiplier("day")


def test_brackets_come_back_sorted_per_tax_code():
    rules = synthetic_rule_set()
    assert rules.tax_codes() == ("TAX",)
    assert [bracket.lower for bracket in rules.brackets_for("TAX")] == [0, 100000, 300000]


def test_the_annualised_variant_uses_yearly_bounds():
    brackets = synthetic_rule_set(annualised=True).brackets_for("TAX")
    assert [(b.lower, b.upper) for b in brackets] == [(0, 1200000), (1200000, 3600000), (3600000, None)]
    assert all(b.annualised for b in brackets)


def test_lines_and_tax_round_with_their_own_settings():
    rules = synthetic_rule_set()
    assert rules.round(D("10687.5")) == 10688
    assert rules.round_tax(D("37345.7")) == 37340


def test_employer_charges_are_the_employer_charge_components():
    assert [component.code for component in synthetic_rule_set().employer_charges()] == ["EMP_TAX"]


def test_reliefs_are_found_by_tax_code():
    rules = synthetic_rule_set()
    assert rules.family_relief("TAX").mode == "percent_of_tax"
    assert rules.professional_relief("TAX").cap_monthly == D(20000)
    assert rules.family_relief("OTHER") is None
